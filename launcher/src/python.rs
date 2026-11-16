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

// Embedded so a standalone installer can bootstrap Python before downloading
// the source payload. The CLI reads the same file from that payload.
#[derive(serde::Deserialize)]
struct DownloadConfig {
    api_base: String,
    download_base: String,
    repository: String,
    fallback_release: String,
    fallback_version: String,
    fallback_platforms: Vec<String>,
}

impl DownloadConfig {
    fn bundled() -> Result<Self, String> {
        serde_json::from_str(include_str!("../../app/provision/python_downloads.json"))
            .map_err(|error| format!("invalid Python download configuration: {error}"))
    }

    fn compatible_fallback(&self) -> bool {
        self.fallback_version
            .starts_with(&format!("{}.{}.", TARGET.0, TARGET.1))
    }

    fn indexes(&self) -> Vec<String> {
        let api = format!(
            "{}/repos/{}/releases",
            self.api_base.trim_end_matches('/'),
            self.repository
        );
        let mut indexes = vec![format!("{api}/latest")];
        if self.compatible_fallback() {
            indexes.push(format!("{api}/tags/{}", self.fallback_release));
        }
        indexes
    }

    fn archived_url(&self, triple: &str) -> Option<String> {
        if self.compatible_fallback() && self.fallback_platforms.iter().any(|p| p == triple) {
            Some(format!(
                "{}/{}/releases/download/{}/cpython-{}%2B{}-{triple}-install_only.tar.gz",
                self.download_base.trim_end_matches('/'),
                self.repository,
                self.fallback_release,
                self.fallback_version,
                self.fallback_release
            ))
        } else {
            None
        }
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
    let out = crate::craftbot::child_command(exe)
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
    fetch: impl FnMut(&str) -> Result<serde_json::Value, String>,
) -> Result<String, String> {
    resolve_url_with_config(triple, &DownloadConfig::bundled()?, fetch)
}

fn resolve_url_with_config(
    triple: &str,
    config: &DownloadConfig,
    mut fetch: impl FnMut(&str) -> Result<serde_json::Value, String>,
) -> Result<String, String> {
    let prefix = format!("cpython-{}.{}.", TARGET.0, TARGET.1);
    let suffix = format!("-{triple}-install_only.tar.gz");
    for index in config.indexes() {
        let data = match fetch(&index) {
            Ok(data) => data,
            Err(error) => {
                // GitHub API quotas are shared by public egress IP. Assets
                // use a separate endpoint, so metadata throttling must not
                // strand a fresh install whose compatible build is known.
                if let Some(url) = config.archived_url(triple) {
                    logger::log(&format!(
                        "Python index unavailable ({error}); using archived {} download",
                        config.fallback_version
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
    use serde_json::json;

    #[test]
    fn api_rate_limit_does_not_block_known_python_downloads() {
        let config = DownloadConfig::bundled().unwrap();
        for triple in &config.fallback_platforms {
            let url =
                resolve_url_with(triple, |_| Err("HTTP 403 rate limit exceeded".into())).unwrap();
            assert_eq!(url, config.archived_url(triple).unwrap());
        }
        assert!(resolve_url_with("unsupported-target", |_| Err("HTTP 403".into())).is_err());
    }

    #[test]
    fn resolves_retired_python_from_last_supported_release() {
        let config = DownloadConfig::bundled().unwrap();
        for triple in &config.fallback_platforms {
            let mut requests = Vec::new();
            let url = resolve_url_with(triple, |index| {
                requests.push(index.to_string());
                Ok(if index == config.indexes()[0] {
                    json!({"assets": []})
                } else {
                    json!({"assets": [{
                        "name": format!("cpython-{}+{}-{triple}-install_only.tar.gz", config.fallback_version, config.fallback_release),
                        "browser_download_url": "https://example.test/compatible-python.tar.gz"
                    }]})
                })
            })
            .unwrap();
            assert_eq!(requests, config.indexes());
            assert_eq!(url, "https://example.test/compatible-python.tar.gz");
        }
    }

    #[test]
    fn latest_matching_asset_takes_priority() {
        let mut requests = Vec::new();
        let url = resolve_url_with("x86_64-unknown-linux-gnu", |index| {
            requests.push(index.to_string());
            Ok(json!({"assets": [{
                "name": "cpython-3.10.99+test-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "browser_download_url": "https://example.test/newer-python.tar.gz"
            }]}))
        })
        .unwrap();
        assert_eq!(url, "https://example.test/newer-python.tar.gz");
        assert_eq!(requests.len(), 1);
    }

    #[test]
    fn configuration_controls_indexes_and_archive() {
        let config: DownloadConfig = serde_json::from_value(json!({
            "api_base": "https://api.example.test/",
            "download_base": "https://downloads.example.test/",
            "repository": "maintainer/python",
            "fallback_release": "20990101",
            "fallback_version": "3.10.99",
            "fallback_platforms": ["test-platform"]
        }))
        .unwrap();
        for fail_on in [1, 2] {
            let mut requests = Vec::new();
            let url = resolve_url_with_config("test-platform", &config, |index| {
                requests.push(index.to_string());
                if requests.len() == fail_on {
                    Err("index unavailable".into())
                } else {
                    Ok(json!({"assets": []}))
                }
            })
            .unwrap();
            assert_eq!(url, "https://downloads.example.test/maintainer/python/releases/download/20990101/cpython-3.10.99%2B20990101-test-platform-install_only.tar.gz");
            assert_eq!(
                requests,
                [
                    "https://api.example.test/repos/maintainer/python/releases/latest",
                    "https://api.example.test/repos/maintainer/python/releases/tags/20990101"
                ][..fail_on]
            );
        }
    }

    #[test]
    fn configuration_cannot_supply_a_different_python_version() {
        let mut config = DownloadConfig::bundled().unwrap();
        config.fallback_version = "3.11.0".into();
        assert!(
            resolve_url_with_config("x86_64-pc-windows-msvc", &config, |_| Err("offline".into()))
                .is_err()
        );
        assert_eq!(config.indexes().len(), 1);
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
