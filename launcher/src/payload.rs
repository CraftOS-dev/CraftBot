//! The source payload: `CraftBot-src.zip`, one asset for every platform.
//!
//! The launcher is pinned to the CraftBot version it was built for (see
//! build.rs), so it downloads that release's asset; a dev build ("latest")
//! takes the newest release. Every download is checked against the
//! `CraftBot-src.zip.sha256` asset published beside it by release.yml.
//!
//! A zip staged beside the launcher or in `./dist/` is used instead of
//! downloading only when the VERSION inside it is the version being
//! installed; a leftover zip from an older release is ignored, not
//! installed. `CRAFTBOT_SRC_ZIP` names a zip explicitly (the developer loop)
//! and is always used.

use crate::download;
use crate::logger;
use crate::paths;
use std::cmp::Ordering;
use std::io::Read;
use std::path::{Path, PathBuf};

pub const GITHUB_OWNER: &str = "CraftOS-dev";
pub const GITHUB_REPO: &str = "CraftBot";
pub const ASSET: &str = "CraftBot-src.zip";

/// The CraftBot version this launcher installs. Baked in by build.rs.
pub const VERSION: &str = env!("CRAFTBOT_VERSION");

pub fn download_url() -> String {
    if VERSION == "latest" {
        format!("https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download/{ASSET}")
    } else {
        format!(
            "https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/v{VERSION}/{ASSET}"
        )
    }
}

/// The published digest: `sha256sum` output for the zip.
pub fn checksum_url() -> String {
    format!("{}.sha256", download_url())
}

/// A locally staged payload this launcher may install, if any.
fn local_zip() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("CRAFTBOT_SRC_ZIP").map(PathBuf::from) {
        if p.is_file() {
            logger::log(&format!(
                "payload: CRAFTBOT_SRC_ZIP={} (version {})",
                p.display(),
                zip_version(&p).unwrap_or_else(|| "unknown".into())
            ));
            return Some(p);
        }
        logger::log(&format!(
            "payload: CRAFTBOT_SRC_ZIP={} is not a file; ignoring it",
            p.display()
        ));
    }
    for candidate in paths::beside_app_dirs().into_iter().map(|d| d.join(ASSET)) {
        if !candidate.is_file() {
            continue;
        }
        match zip_version(&candidate) {
            Some(v) if same_version(&v, VERSION) => return Some(candidate),
            found => logger::log(&format!(
                "payload: ignoring {} (version {}, installing {VERSION})",
                candidate.display(),
                found.unwrap_or_else(|| "unreadable".into())
            )),
        }
    }
    None
}

/// The VERSION file inside a payload, at its root or under one wrapper
/// directory. A zip without one is a development build: "latest".
pub fn zip_version(zip_path: &Path) -> Option<String> {
    let file = std::fs::File::open(zip_path).ok()?;
    let mut archive = zip::ZipArchive::new(std::io::BufReader::new(file)).ok()?;
    let name = archive
        .file_names()
        .filter(|n| *n == "VERSION" || (n.ends_with("/VERSION") && n.matches('/').count() == 1))
        .min_by_key(|n| n.len())
        .map(str::to_string);
    let Some(name) = name else {
        return Some("latest".into());
    };
    let mut text = String::new();
    archive
        .by_name(&name)
        .ok()?
        .take(64)
        .read_to_string(&mut text)
        .ok()?;
    Some(normalize(&text))
}

fn normalize(v: &str) -> String {
    v.trim().trim_start_matches('v').to_string()
}

fn same_version(a: &str, b: &str) -> bool {
    normalize(a) == normalize(b)
}

/// `1.4.0` → [1, 4, 0]. None for "latest", "dev" and anything else that is
/// not a release number, so no comparison is ever made against those.
fn release_number(v: &str) -> Option<Vec<u64>> {
    let core = normalize(v);
    let core = core.split(['-', '+']).next()?;
    let parts: Option<Vec<u64>> = core.split('.').map(|p| p.parse().ok()).collect();
    parts.filter(|p| !p.is_empty())
}

/// How this launcher's version compares with an installed one, when both
/// are release numbers.
pub fn compare_with_installed(installed: &str) -> Option<Ordering> {
    let (mine, theirs) = (release_number(VERSION)?, release_number(installed)?);
    let len = mine.len().max(theirs.len());
    let pad = |v: &[u64]| {
        let mut v = v.to_vec();
        v.resize(len, 0);
        v
    };
    Some(pad(&mine).cmp(&pad(&theirs)))
}

/// Where a downloaded payload is kept until it has been extracted.
fn temp_zip() -> PathBuf {
    paths::user_data_root().join("downloads").join(ASSET)
}

/// Obtain the payload. Returns the zip path and whether the launcher owns it
/// (downloaded, so delete after extraction) or not (staged locally, so leave
/// it alone).
pub fn obtain(
    say: &mut dyn FnMut(&str),
    progress: &mut dyn FnMut(u64, Option<u64>),
) -> Result<(PathBuf, bool), String> {
    if let Some(local) = local_zip() {
        logger::log(&format!("payload: using local {}", local.display()));
        say("Using the CraftBot package found beside the installer");
        return Ok((local, false));
    }
    let url = download_url();
    logger::log(&format!("payload: {url}"));
    say(&if VERSION == "latest" {
        "Downloading CraftBot…".to_string()
    } else {
        format!("Downloading CraftBot {VERSION}…")
    });
    let missing = |e: String| {
        if e.contains("HTTP 404") {
            let release = if VERSION == "latest" {
                "The latest CraftBot release".to_string()
            } else {
                format!("The CraftBot {VERSION} release")
            };
            format!("{release} has no {ASSET} download yet.\n{e}")
        } else {
            e
        }
    };
    let digest = parse_checksum(&download::fetch_text(&checksum_url()).map_err(missing)?)
        .ok_or_else(|| format!("{} is not a SHA-256 checksum", checksum_url()))?;
    let dest = temp_zip();
    download::verified_to_file(&url, &dest, &digest, progress).map_err(missing)?;
    Ok((dest, true))
}

/// The digest from a `sha256sum`-style line: `<64 hex>  CraftBot-src.zip`.
fn parse_checksum(text: &str) -> Option<String> {
    let token = text.split_whitespace().next()?.to_ascii_lowercase();
    let token = token.strip_prefix("sha256:").unwrap_or(&token).to_string();
    (token.len() == 64 && token.bytes().all(|c| c.is_ascii_hexdigit())).then_some(token)
}

/// Extract the payload into `target` and return the directory holding
/// run.py. Tolerates both shapes a zip can have: files at the root, or
/// everything under one wrapper directory (what `git archive` and GitHub's
/// own zips produce). Getting this wrong yields an install that looks fine
/// until nothing can find run.py.
pub fn extract(zip_path: &Path, target: &Path) -> Result<PathBuf, String> {
    std::fs::create_dir_all(target)
        .map_err(|e| format!("cannot create {}: {e}", target.display()))?;
    let file = std::fs::File::open(zip_path)
        .map_err(|e| format!("cannot open {}: {e}", zip_path.display()))?;
    let mut archive = zip::ZipArchive::new(std::io::BufReader::new(file))
        .map_err(|e| format!("{} is not a valid zip: {e}", zip_path.display()))?;

    for i in 0..archive.len() {
        let mut entry = archive
            .by_index(i)
            .map_err(|e| format!("zip entry {i}: {e}"))?;
        // enclosed_name() refuses "../" and absolute paths: a payload must not
        // be able to write outside the install directory.
        let Some(rel) = entry.enclosed_name() else {
            logger::log(&format!(
                "payload: skipping unsafe entry {:?}",
                entry.name()
            ));
            continue;
        };
        let out = target.join(rel);
        if entry.is_dir() {
            std::fs::create_dir_all(&out)
                .map_err(|e| format!("cannot create {}: {e}", out.display()))?;
            continue;
        }
        if let Some(parent) = out.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
        }
        let mut data = Vec::with_capacity(entry.size() as usize);
        entry
            .read_to_end(&mut data)
            .map_err(|e| format!("cannot read {}: {e}", entry.name()))?;
        std::fs::write(&out, &data).map_err(|e| format!("cannot write {}: {e}", out.display()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Some(mode) = entry.unix_mode() {
                let _ = std::fs::set_permissions(&out, std::fs::Permissions::from_mode(mode));
            }
        }
    }

    if target.join("run.py").is_file() {
        return Ok(target.to_path_buf());
    }
    let mut dirs: Vec<PathBuf> = std::fs::read_dir(target)
        .map_err(|e| e.to_string())?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.is_dir())
        .collect();
    dirs.sort();
    for candidate in dirs {
        if candidate.join("run.py").is_file() {
            return Ok(candidate);
        }
    }
    Err(format!(
        "run.py not found after extracting to {}. The source payload is not shaped as expected.",
        target.display()
    ))
}

/// Stamp an install root as managed: `app.paths.mark_managed_install()`.
/// Must happen before anything in that tree imports `app.paths`, because
/// the marker decides where the user's data goes: without it, the installed
/// copy looks exactly like a developer checkout and would put databases and
/// logs inside the install directory, which the next upgrade replaces.
pub fn mark_managed(root: &Path) -> Result<(), String> {
    const TEXT: &str = "This file marks a managed CraftBot install.\n\n\
It tells app/paths.py to keep user data (agent_file_system, databases, logs,\n\
the vector store) in the per-user data directory rather than in this folder,\n\
which an upgrade replaces wholesale.\n\n\
Delete it only if you are converting this directory into a dev checkout.\n";
    let path = root.join(paths::MANAGED_MARKER);
    std::fs::write(&path, TEXT).map_err(|e| format!("cannot write {}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn zip_with(entries: &[(&str, &str)]) -> (tempfile::TempDir, PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(ASSET);
        let mut w = zip::ZipWriter::new(std::fs::File::create(&path).unwrap());
        for (name, body) in entries {
            w.start_file(*name, zip::write::SimpleFileOptions::default())
                .unwrap();
            std::io::Write::write_all(&mut w, body.as_bytes()).unwrap();
        }
        w.finish().unwrap();
        (dir, path)
    }

    #[test]
    fn version_is_read_from_the_root_or_one_wrapper() {
        let (_d, root) = zip_with(&[("VERSION", "v1.5.0\n"), ("run.py", "")]);
        assert_eq!(zip_version(&root).as_deref(), Some("1.5.0"));
        let (_d, wrapped) = zip_with(&[("CraftBot-1.5.1/VERSION", "1.5.1"), ("x/y/VERSION", "9")]);
        assert_eq!(zip_version(&wrapped).as_deref(), Some("1.5.1"));
        let (_d, dev) = zip_with(&[("run.py", "")]);
        assert_eq!(zip_version(&dev).as_deref(), Some("latest"));
    }

    #[test]
    fn only_the_matching_version_counts() {
        assert!(same_version("v1.4.0", "1.4.0"));
        assert!(!same_version("1.3.9", "1.4.0"));
        assert!(same_version("latest", "latest"));
    }

    #[test]
    fn release_numbers_compare_numerically() {
        assert_eq!(release_number("v1.10.2"), Some(vec![1, 10, 2]));
        assert_eq!(release_number("1.4.0-rc1"), Some(vec![1, 4, 0]));
        assert_eq!(release_number("latest"), None);
        assert_eq!(release_number(""), None);
    }

    #[test]
    fn checksum_file_formats() {
        let hex = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        assert_eq!(
            parse_checksum(&format!("{hex}  CraftBot-src.zip\n")).as_deref(),
            Some(hex)
        );
        assert_eq!(
            parse_checksum(&format!("sha256:{}", hex.to_uppercase())).as_deref(),
            Some(hex)
        );
        assert_eq!(parse_checksum("<html>Not Found</html>"), None);
        assert_eq!(parse_checksum(""), None);
    }

    #[test]
    fn checksum_sits_beside_the_payload() {
        assert_eq!(checksum_url(), format!("{}.sha256", download_url()));
    }
}
