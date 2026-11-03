//! The Python sidecar.
//!
//! install.py and run.py are the source of truth for what an install is,
//! and both are Python — so before the launcher can run either it needs an
//! interpreter, and it must not depend on one being on the machine. It
//! downloads python-build-standalone (a relocatable CPython with pip), the
//! same build `app/provision/runtimes.py` uses, into the same place that
//! module puts it. When install.py later runs its own `python` stage it
//! finds this one already there and accepts it; nothing is downloaded twice.
//!
//! Download pins are shared with Python provisioning and embedded at build
//! time: the launcher needs them before the source payload or Python exists.

use crate::download;
use crate::logger;
use crate::paths;
use std::path::PathBuf;

/// Same as `TARGET_PYTHON` in runtimes.py — the version the dependency locks
/// are generated for, not a minimum.
pub const TARGET: (u32, u32) = (3, 10);

const RUNTIMES: &str = include_str!("../../app/runtime-manifest.json");

#[derive(serde::Deserialize)]
struct Asset {
    url: String,
    sha256: String,
}

/// The interpreter to run CraftBot with, downloading it if needed.
pub fn ensure(
    say: &mut dyn FnMut(&str),
    progress: &mut dyn FnMut(u64, Option<u64>),
) -> Result<PathBuf, String> {
    ensure_in(&paths::python_runtime_dir(), say, progress)
}

fn ensure_in(
    dest_dir: &std::path::Path,
    say: &mut dyn FnMut(&str),
    progress: &mut dyn FnMut(u64, Option<u64>),
) -> Result<PathBuf, String> {
    let exe = paths::python_exe_in(dest_dir);
    if exe.is_file() {
        if let Some(v) = probe(&exe) {
            if v == TARGET {
                say(&format!("Python {}.{} ready", v.0, v.1));
                return Ok(exe);
            }
            logger::log(&format!(
                "sidecar at {} is {}.{}, replacing",
                exe.display(),
                v.0,
                v.1
            ));
        } else {
            logger::log(&format!(
                "sidecar at {} does not run, replacing",
                exe.display()
            ));
        }
    }

    let triple = triple().ok_or_else(|| {
        format!(
            "no portable Python {}.{} is published for this machine",
            TARGET.0, TARGET.1
        )
    })?;
    say(&format!("Downloading Python {}.{}…", TARGET.0, TARGET.1));
    let asset = resolve_asset(&triple)?;
    logger::log(&format!("python: {}", asset.url));

    std::fs::create_dir_all(dest_dir)
        .map_err(|e| format!("cannot create {}: {e}", dest_dir.display()))?;
    let stage = tempfile::tempdir_in(dest_dir).map_err(|e| e.to_string())?;
    let archive = stage.path().join("_download.tar.gz");
    download::verified_to_file(&asset.url, &archive, &asset.sha256, progress)?;

    say("Unpacking Python…");
    let result = extract_tar_gz(&archive, stage.path());
    let _ = std::fs::remove_file(&archive);
    result?;

    let candidate = paths::python_exe_in(stage.path());
    if !candidate.is_file() {
        return Err(format!(
            "Python unpacked, but {} is missing",
            candidate.display()
        ));
    }
    match probe(&candidate) {
        Some(v) if v == TARGET => {
            let installed = dest_dir.join("python");
            let backup = dest_dir.join(".python-previous");
            if backup.exists() {
                std::fs::remove_dir_all(&backup).map_err(|e| e.to_string())?;
            }
            if installed.exists() {
                std::fs::rename(&installed, &backup).map_err(|e| e.to_string())?;
            }
            if let Err(e) = std::fs::rename(stage.path().join("python"), &installed) {
                if backup.exists() {
                    let _ = std::fs::rename(&backup, &installed);
                }
                return Err(format!("cannot finish Python installation: {e}"));
            }
            if backup.exists() {
                let _ = std::fs::remove_dir_all(&backup);
            }
            say(&format!("Python {}.{} ready", v.0, v.1));
            Ok(exe)
        }
        Some(v) => Err(format!(
            "downloaded Python reports {}.{}, expected {}.{}",
            v.0, v.1, TARGET.0, TARGET.1
        )),
        None => Err("downloaded Python will not run on this machine".to_string()),
    }
}

/// Run the interpreter and read back its (major, minor).
pub fn probe(exe: &std::path::Path) -> Option<(u32, u32)> {
    let out = crate::craftbot::quiet_command(exe)
        .args([
            "-c",
            "import sys; print(sys.version_info[0], sys.version_info[1])",
        ])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let mut parts = text.split_whitespace();
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    Some((major, minor))
}

/// python-build-standalone's platform triple for this machine. Same table
/// as `_pbs_triple()` in runtimes.py, including "arm64 Windows runs the x64
/// build under emulation" because no win-arm64 build is published.
fn triple() -> Option<String> {
    let arch = if cfg!(target_arch = "aarch64") {
        "aarch64"
    } else if cfg!(target_arch = "x86_64") {
        "x86_64"
    } else {
        return None;
    };
    if cfg!(target_os = "windows") {
        Some("x86_64-pc-windows-msvc".to_string())
    } else if cfg!(target_os = "macos") {
        Some(format!("{arch}-apple-darwin"))
    } else if cfg!(target_os = "linux") {
        Some(format!("{arch}-unknown-linux-gnu"))
    } else {
        None
    }
}

fn resolve_asset(triple: &str) -> Result<Asset, String> {
    let data: serde_json::Value = serde_json::from_str(RUNTIMES).map_err(|e| e.to_string())?;
    let asset: Asset = serde_json::from_value(data["python"]["assets"][triple].clone())
        .map_err(|_| format!("No approved Python download for {triple}"))?;
    if !asset.url.starts_with("https://")
        || asset.sha256.len() != 64
        || !asset.sha256.bytes().all(|c| c.is_ascii_hexdigit())
    {
        return Err("Invalid Python runtime download manifest".into());
    }
    Ok(asset)
}

/// Extract a .tar.gz, preserving permissions — the executable bit on
/// bin/python3 is the whole point on macOS and Linux.
fn extract_tar_gz(archive: &std::path::Path, dest: &std::path::Path) -> Result<(), String> {
    let file = std::fs::File::open(archive)
        .map_err(|e| format!("cannot open {}: {e}", archive.display()))?;
    let gz = flate2::read::GzDecoder::new(std::io::BufReader::new(file));
    let mut tar = tar::Archive::new(gz);
    tar.set_preserve_permissions(true);
    tar.set_overwrite(true);
    tar.unpack(dest)
        .map_err(|e| format!("cannot unpack Python: {e}"))
}

/// Free space available at (the nearest existing ancestor of) `path`.
pub fn free_space(path: &std::path::Path) -> Option<u64> {
    let mut probe = path.to_path_buf();
    while !probe.exists() {
        probe = probe.parent()?.to_path_buf();
    }
    fs4::available_space(&probe).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "downloads and executes the release-pinned Python"]
    fn live_python_bootstrap() {
        let temp = tempfile::tempdir().unwrap();
        let dest = temp.path().join("User Name & caf\u{e9}");
        let executable = ensure_in(&dest, &mut |_| {}, &mut |_, _| {}).unwrap();
        assert_eq!(probe(&executable), Some(TARGET));
        assert_eq!(
            ensure_in(&dest, &mut |_| {}, &mut |_, _| panic!(
                "ready runtime must be reused"
            ))
            .unwrap(),
            executable
        );
    }

    #[test]
    fn manifest_resolves_all_platforms_without_network() {
        for target in [
            "x86_64-pc-windows-msvc",
            "x86_64-apple-darwin",
            "aarch64-apple-darwin",
            "x86_64-unknown-linux-gnu",
            "aarch64-unknown-linux-gnu",
        ] {
            let asset = resolve_asset(target).unwrap();
            assert!(asset.url.contains("/20261009/cpython-3.10.22%2B"));
            assert_eq!(asset.sha256.len(), 64);
        }
        assert!(resolve_asset("unsupported").is_err());
    }

    #[test]
    fn manifest_matches_dependency_lock_python() {
        let data: serde_json::Value = serde_json::from_str(RUNTIMES).unwrap();
        assert!(data["python"]["version"]
            .as_str()
            .unwrap()
            .starts_with(&format!("{}.{}.", TARGET.0, TARGET.1)));
    }
}
