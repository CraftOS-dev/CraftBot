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
//! Asset URLs are resolved from GitHub release metadata, including the final
//! Python 3.10 release when the newest release no longer carries that version.
//! This mirrors app/provision/runtimes.py and its dependency-lock constraint.

use crate::download;
use crate::logger;
use crate::paths;
use std::path::PathBuf;

/// Same as `TARGET_PYTHON` in runtimes.py — the version the dependency locks
/// are generated for, not a minimum.
pub const TARGET: (u32, u32) = (3, 10);

const PBS_API: &str =
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest";
const PBS_310_API: &str =
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases/tags/20261009";
const PBS_310_ARCHIVE: &str = "https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.10.22%2B20261009";

fn archived_url(triple: &str) -> Option<String> {
    if TARGET == (3, 10)
        && matches!(
            triple,
            "x86_64-pc-windows-msvc"
                | "x86_64-unknown-linux-gnu"
                | "aarch64-unknown-linux-gnu"
                | "x86_64-apple-darwin"
                | "aarch64-apple-darwin"
        )
    {
        Some(format!("{PBS_310_ARCHIVE}-{triple}-install_only.tar.gz"))
    } else {
        None
    }
}

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
        // A wrong or broken sidecar is removed wholesale; a partial tree is
        // worse than none.
        let _ = std::fs::remove_dir_all(paths::python_runtime_dir().join("python"));
    }

    let triple = triple().ok_or_else(|| {
        format!(
            "no portable Python {}.{} is published for this machine",
            TARGET.0, TARGET.1
        )
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
    } else {
        "x86_64"
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

fn resolve_url(triple: &str) -> Result<String, String> {
    resolve_url_with(triple, download::get_json)
}

fn resolve_url_with(
    triple: &str,
    mut fetch: impl FnMut(&str) -> Result<serde_json::Value, String>,
) -> Result<String, String> {
    let prefix = format!("cpython-{}.{}.", TARGET.0, TARGET.1);
    let suffix = format!("-{triple}-install_only.tar.gz");
    let mut indexes = vec![PBS_API];
    if TARGET == (3, 10) {
        indexes.push(PBS_310_API);
    }
    for index in indexes {
        let data = match fetch(index) {
            Ok(data) => data,
            Err(error) => {
                // GitHub API quotas are shared by public egress IP. Assets
                // use a separate endpoint, so metadata throttling must not
                // strand a fresh install whose compatible build is known.
                if let Some(url) = archived_url(triple) {
                    logger::log(&format!(
                        "Python index unavailable ({error}); using archived 3.10.22 download"
                    ));
                    return Ok(url);
                }
                return Err(format!(
                    "could not reach the Python download index: {error}"
                ));
            }
        };
        if let Some(assets) = data.get("assets").and_then(|a| a.as_array()) {
            for asset in assets {
                let name = asset.get("name").and_then(|n| n.as_str()).unwrap_or("");
                if name.starts_with(&prefix) && name.ends_with(&suffix) {
                    if let Some(url) = asset.get("browser_download_url").and_then(|u| u.as_str()) {
                        if !url.is_empty() {
                            return Ok(url.to_string());
                        }
                    }
                }
            }
        }
    }
    Err(format!(
        "no {prefix}*{suffix} in the checked python-build-standalone releases"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn api_rate_limit_does_not_block_known_python_downloads() {
        for triple in [
            "x86_64-pc-windows-msvc",
            "x86_64-unknown-linux-gnu",
            "aarch64-unknown-linux-gnu",
            "x86_64-apple-darwin",
            "aarch64-apple-darwin",
        ] {
            let url =
                resolve_url_with(triple, |_| Err("HTTP 403 rate limit exceeded".into())).unwrap();
            assert_eq!(
                url,
                format!("{PBS_310_ARCHIVE}-{triple}-install_only.tar.gz")
            );
        }
        assert!(resolve_url_with("unsupported-target", |_| Err("HTTP 403".into())).is_err());
    }

    #[test]
    fn resolves_retired_python_from_last_supported_release() {
        for triple in [
            "x86_64-pc-windows-msvc",
            "x86_64-unknown-linux-gnu",
            "x86_64-apple-darwin",
            "aarch64-apple-darwin",
        ] {
            let mut requests = Vec::new();
            let url = resolve_url_with(triple, |index| {
                requests.push(index.to_string());
                Ok(if index == PBS_API {
                    json!({"assets": []})
                } else {
                    json!({"assets": [{
                        "name": format!("cpython-3.10.22+20261009-{triple}-install_only.tar.gz"),
                        "browser_download_url": "https://example.test/compatible-python.tar.gz"
                    }]})
                })
            })
            .unwrap();
            assert_eq!(requests, [PBS_API, PBS_310_API]);
            assert_eq!(url, "https://example.test/compatible-python.tar.gz");
        }
    }

    #[test]
    fn does_not_substitute_a_different_python_version() {
        let result = resolve_url_with("x86_64-unknown-linux-gnu", |_| {
            Ok(json!({"assets": [{
                "name": "cpython-3.11.0+20261110-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "browser_download_url": "https://example.test/wrong-python.tar.gz"
            }]}))
        });
        assert!(result.is_err());
    }
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
