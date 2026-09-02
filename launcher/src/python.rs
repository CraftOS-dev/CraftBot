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
//! The release tag, patch version and platform triple are resolved from the
//! GitHub API rather than hardcoded, for the reason recorded in runtimes.py:
//! a hardcoded asset name went stale and produced a silent 404.

use crate::download;
use crate::logger;
use crate::paths;
use std::path::PathBuf;

/// Same as `TARGET_PYTHON` in runtimes.py — the version the dependency locks
/// are generated for, not a minimum.
pub const TARGET: (u32, u32) = (3, 10);

const PBS_API: &str =
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest";

/// The interpreter to run CraftBot with, downloading it if needed.
pub fn ensure(
    say: &mut dyn FnMut(&str),
    progress: &mut dyn FnMut(u64, Option<u64>),
) -> Result<PathBuf, String> {
    let exe = paths::python_exe();
    if exe.is_file() {
        if let Some(v) = probe(&exe) {
            if v == TARGET {
                say(&format!("Python {}.{} ready", v.0, v.1));
                return Ok(exe);
            }
            logger::log(&format!("sidecar at {} is {}.{}, replacing", exe.display(), v.0, v.1));
        } else {
            logger::log(&format!("sidecar at {} does not run, replacing", exe.display()));
        }
        // A wrong or broken sidecar is removed wholesale; a partial tree is
        // worse than none.
        let _ = std::fs::remove_dir_all(paths::python_runtime_dir().join("python"));
    }

    let triple = triple().ok_or_else(|| {
        format!("no portable Python {}.{} is published for this machine", TARGET.0, TARGET.1)
    })?;
    say(&format!("Downloading Python {}.{}…", TARGET.0, TARGET.1));
    let url = resolve_url(&triple)?;
    logger::log(&format!("python: {url}"));

    let dest_dir = paths::python_runtime_dir();
    std::fs::create_dir_all(&dest_dir)
        .map_err(|e| format!("cannot create {}: {e}", dest_dir.display()))?;
    let archive = dest_dir.join("_download.tar.gz");
    download::to_file(&url, &archive, progress)?;

    say("Unpacking Python…");
    let result = extract_tar_gz(&archive, &dest_dir);
    let _ = std::fs::remove_file(&archive);
    result?;

    if !exe.is_file() {
        return Err(format!("Python unpacked, but {} is missing", exe.display()));
    }
    match probe(&exe) {
        Some(v) if v == TARGET => {
            say(&format!("Python {}.{} ready", v.0, v.1));
            Ok(exe)
        }
        Some(v) => Err(format!("downloaded Python reports {}.{}, expected {}.{}", v.0, v.1, TARGET.0, TARGET.1)),
        None => Err("downloaded Python will not run on this machine".to_string()),
    }
}

/// Run the interpreter and read back its (major, minor).
pub fn probe(exe: &std::path::Path) -> Option<(u32, u32)> {
    let out = crate::craftbot::quiet_command(exe)
        .args(["-c", "import sys; print(sys.version_info[0], sys.version_info[1])"])
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
    let arch = if cfg!(target_arch = "aarch64") { "aarch64" } else { "x86_64" };
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

fn resolve_url(triple: &str) -> Result<String, String> {
    let data = download::get_json(PBS_API)
        .map_err(|e| format!("could not reach the Python download index: {e}"))?;
    let prefix = format!("cpython-{}.{}.", TARGET.0, TARGET.1);
    let suffix = format!("-{triple}-install_only.tar.gz");
    let assets = data.get("assets").and_then(|a| a.as_array()).cloned().unwrap_or_default();
    for asset in &assets {
        let name = asset.get("name").and_then(|n| n.as_str()).unwrap_or("");
        if name.starts_with(&prefix) && name.ends_with(&suffix) {
            if let Some(url) = asset.get("browser_download_url").and_then(|u| u.as_str()) {
                return Ok(url.to_string());
            }
        }
    }
    let tag = data.get("tag_name").and_then(|t| t.as_str()).unwrap_or("?");
    Err(format!("no {prefix}*{suffix} in python-build-standalone release {tag}"))
}

/// Extract a .tar.gz, preserving permissions — the executable bit on
/// bin/python3 is the whole point on macOS and Linux.
fn extract_tar_gz(archive: &std::path::Path, dest: &std::path::Path) -> Result<(), String> {
    let file = std::fs::File::open(archive).map_err(|e| format!("cannot open {}: {e}", archive.display()))?;
    let gz = flate2::read::GzDecoder::new(std::io::BufReader::new(file));
    let mut tar = tar::Archive::new(gz);
    tar.set_preserve_permissions(true);
    tar.set_overwrite(true);
    tar.unpack(dest).map_err(|e| format!("cannot unpack Python: {e}"))
}

/// Free space available at (the nearest existing ancestor of) `path`.
pub fn free_space(path: &std::path::Path) -> Option<u64> {
    let mut probe = path.to_path_buf();
    while !probe.exists() {
        probe = probe.parent()?.to_path_buf();
    }
    fs4::available_space(&probe).ok()
}
