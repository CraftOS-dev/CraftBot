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
//! The archive comes from the release python_downloads.json pins, checked
//! against the SHA-256 it pins for this platform before it is unpacked, as
//! app/provision/runtimes.py does. No release listing is asked for, so a
//! GitHub API rate limit cannot stop an install.

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
    download_base: String,
    repository: String,
    fallback_release: String,
    fallback_version: String,
    fallback_platforms: Vec<String>,
    sha256: std::collections::HashMap<String, String>,
}

impl DownloadConfig {
    fn bundled() -> Result<Self, String> {
        serde_json::from_str(include_str!("../../app/provision/python_downloads.json"))
            .map_err(|error| format!("invalid Python download configuration: {error}"))
    }

    /// The pinned archive for `triple` and the SHA-256 it must have.
    fn pinned(&self, triple: &str) -> Result<(String, String), String> {
        if !self
            .fallback_version
            .starts_with(&format!("{}.{}.", TARGET.0, TARGET.1))
        {
            return Err(format!(
                "the pinned Python {} is not {}.{}",
                self.fallback_version, TARGET.0, TARGET.1
            ));
        }
        let digest = self
            .sha256
            .get(triple)
            .filter(|_| self.fallback_platforms.iter().any(|p| p == triple))
            .filter(|d| d.len() == 64 && d.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')))
            .ok_or_else(|| {
                format!(
                    "no pinned Python {} build for {triple}",
                    self.fallback_version
                )
            })?;
        let url = format!(
            "{}/{}/releases/download/{}/cpython-{}%2B{}-{triple}-install_only.tar.gz",
            self.download_base.trim_end_matches('/'),
            self.repository,
            self.fallback_release,
            self.fallback_version,
            self.fallback_release
        );
        Ok((url, digest.clone()))
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
    let (url, sha256) = DownloadConfig::bundled()?.pinned(&triple)?;
    logger::log(&format!("python: {url}"));

    let dest_dir = paths::python_runtime_dir();
    std::fs::create_dir_all(&dest_dir)
        .map_err(|e| format!("cannot create {}: {e}", dest_dir.display()))?;
    let archive = dest_dir.join("_download.tar.gz");
    download::verified_to_file(&url, &archive, &sha256, progress)?;

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
    fn every_platform_resolves_its_pinned_archive_and_digest() {
        let config = DownloadConfig::bundled().unwrap();
        for triple in &config.fallback_platforms {
            let (url, sha256) = config.pinned(triple).unwrap();
            assert_eq!(
                url,
                format!(
                    "https://github.com/astral-sh/python-build-standalone/releases/download/{0}/cpython-{1}%2B{0}-{triple}-install_only.tar.gz",
                    config.fallback_release, config.fallback_version
                )
            );
            assert_eq!(&sha256, &config.sha256[triple]);
            assert_eq!(sha256.len(), 64);
        }
        assert!(config.pinned("unsupported-target").is_err());
    }

    #[test]
    fn a_platform_without_a_pinned_digest_is_refused() {
        let config: DownloadConfig = serde_json::from_value(json!({
            "download_base": "https://downloads.example.test/",
            "repository": "maintainer/python",
            "fallback_release": "20990101",
            "fallback_version": "3.10.99",
            "fallback_platforms": ["pinned", "unpinned", "malformed"],
            "sha256": {"pinned": "a".repeat(64), "malformed": "A".repeat(64), "unlisted": "b".repeat(64)}
        }))
        .unwrap();
        assert_eq!(
            config.pinned("pinned").unwrap(),
            (
                "https://downloads.example.test/maintainer/python/releases/download/20990101/cpython-3.10.99%2B20990101-pinned-install_only.tar.gz".to_string(),
                "a".repeat(64)
            )
        );
        for triple in ["unpinned", "malformed", "unlisted"] {
            assert!(config.pinned(triple).is_err(), "{triple}");
        }
    }

    #[test]
    fn configuration_cannot_supply_a_different_python_version() {
        let mut config = DownloadConfig::bundled().unwrap();
        config.fallback_version = "3.11.0".into();
        assert!(config.pinned("x86_64-unknown-linux-gnu").is_err());
    }
}
