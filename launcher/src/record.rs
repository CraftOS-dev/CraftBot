//! `launcher.json`: what the launcher installed, where, and with which
//! interpreter. This is the launcher's equivalent of the old frozen
//! installer's `install.json`; `craftbot.py` in source mode does not write
//! one, because a source install has always known where it is (beside
//! craftbot.py) — the launcher is the one that needs reminding.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const SCHEMA: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstallRecord {
    pub schema: u32,
    /// Directory holding run.py / craftbot.py / install.py.
    pub install_dir: PathBuf,
    /// The interpreter every CraftBot process runs under.
    pub python: PathBuf,
    /// CraftBot version the payload came from ("latest" for a dev build).
    pub version: String,
    /// Seconds since the Unix epoch.
    pub installed_at: u64,
}

impl InstallRecord {
    pub fn new(install_dir: PathBuf, python: PathBuf, version: &str) -> Self {
        let installed_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        Self { schema: SCHEMA, install_dir, python, version: version.to_string(), installed_at }
    }

    /// The record, if one exists and still describes a real install: the
    /// source tree and the interpreter must both be present. A record whose
    /// tree has been deleted by hand is treated as "not installed" rather
    /// than offering Start on nothing.
    pub fn load() -> Option<Self> {
        let text = std::fs::read_to_string(crate::paths::install_record()).ok()?;
        let rec: Self = serde_json::from_str(&text).ok()?;
        if rec.install_dir.join("run.py").is_file() && rec.python.is_file() {
            Some(rec)
        } else {
            None
        }
    }

    /// The recorded install directory even when the tree is gone — what
    /// "Change location" should default to, and what Repair reinstalls into.
    pub fn load_any() -> Option<Self> {
        let text = std::fs::read_to_string(crate::paths::install_record()).ok()?;
        serde_json::from_str(&text).ok()
    }

    pub fn save(&self) -> Result<(), String> {
        let path = crate::paths::install_record();
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
        }
        let text = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        std::fs::write(&path, text).map_err(|e| format!("cannot write {}: {e}", path.display()))
    }

    pub fn clear() {
        let _ = std::fs::remove_file(crate::paths::install_record());
    }

    pub fn craftbot_py(&self) -> PathBuf {
        self.install_dir.join("craftbot.py")
    }

    pub fn dir(&self) -> &Path {
        &self.install_dir
    }
}
