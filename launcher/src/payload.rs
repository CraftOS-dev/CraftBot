//! The source payload: `CraftBot-src.zip`, one asset for every platform.
//!
//! Mirrors `installer/payload.py`. The launcher is pinned to the CraftBot
//! version it was built for (see build.rs), so it downloads that release's
//! asset; a dev build ("latest") takes the newest release. A zip staged
//! beside the launcher, in `./dist/`, or named by `CRAFTBOT_SRC_ZIP` is used
//! instead of downloading — that is the developer loop.

use crate::download;
use crate::logger;
use crate::paths;
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

/// A locally staged payload, if any. Explicit override first, then beside
/// the app, then the local build output.
pub fn local_zip() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("CRAFTBOT_SRC_ZIP").map(PathBuf::from) {
        if p.is_file() {
            return Some(p);
        }
    }
    paths::beside_app_dirs()
        .into_iter()
        .map(|d| d.join(ASSET))
        .find(|p| p.is_file())
}

/// Where a downloaded payload is kept until it has been extracted.
fn temp_zip() -> PathBuf {
    paths::user_data_root().join("downloads").join(ASSET)
}

/// Obtain the payload. Returns the zip path and whether the launcher owns it
/// (downloaded, so delete after extraction) or not (staged by a developer,
/// so leave it alone).
pub fn obtain(
    say: &mut dyn FnMut(&str),
    progress: &mut dyn FnMut(u64, Option<u64>),
) -> Result<(PathBuf, bool), String> {
    if let Some(local) = local_zip() {
        logger::log(&format!("payload: using local {}", local.display()));
        say("Using local CraftBot package");
        return Ok((local, false));
    }
    let url = download_url();
    logger::log(&format!("payload: {url}"));
    say(&format!(
        "Downloading CraftBot {}…",
        if VERSION == "latest" { "" } else { VERSION }
    ));
    let dest = temp_zip();
    download::to_file(&url, &dest, progress).map_err(|e| {
        if e.contains("HTTP 404") {
            format!("{e}\nNo CraftBot {VERSION} release has a {ASSET} asset yet.")
        } else {
            e
        }
    })?;
    Ok((dest, true))
}

/// Extract the payload into `target` and return the directory holding
/// run.py. Tolerates both shapes a zip can have — files at the root, or
/// everything under one wrapper directory (what `git archive` and GitHub's
/// own zips produce) — because getting this wrong yields an install that
/// looks fine until nothing can find run.py.
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

/// Stamp an install root as managed — `app.paths.mark_managed_install()`.
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
