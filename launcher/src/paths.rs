//! Where things live. Every path here mirrors one in the Python side
//! (`app/paths.py`, `craftbot.py`), because the launcher and the agent must
//! agree on them without talking to each other:
//!
//! * the per-user data root is `app.paths._user_data_root()` — the agent
//!   keeps its state there once the install is marked managed;
//! * the Python sidecar location is `PythonStage._sidecar_exe()` in
//!   `app/provision/runtimes.py` — the launcher puts the interpreter exactly
//!   where install.py's provisioning would, so that stage finds it and does
//!   not download a second one;
//! * the pid and log files are `craftbot.py`'s `PID_FILE`/`LOG_FILE` in
//!   source mode, which is beside `craftbot.py` in the install directory.

use std::path::{Path, PathBuf};

/// Per-user writable directory for launcher state, the Python sidecar and
/// the agent's own data. Matches `app.paths._user_data_root()`.
pub fn user_data_root() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        let root = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .or_else(|| dirs::data_local_dir())
            .unwrap_or_else(|| home().join("AppData").join("Local"));
        root.join("CraftBot")
    }
    #[cfg(target_os = "macos")]
    {
        home()
            .join("Library")
            .join("Application Support")
            .join("CraftBot")
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let root = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| home().join(".local").join("share"));
        root.join("craftbot")
    }
}

/// Where CraftBot is installed when the user does not choose. Per-user, so
/// no elevation is needed. Matches `craftbot.default_install_location()`
/// except on Linux, where the Python default coincides with the data root;
/// a subdirectory keeps the source tree (replaced on upgrade) apart from the
/// user's data (never replaced).
pub fn default_install_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        let root = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home().join("AppData").join("Local"));
        root.join("Programs").join("CraftBot")
    }
    #[cfg(target_os = "macos")]
    {
        home().join("Applications").join("CraftBot")
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        user_data_root().join("app")
    }
}

/// The launcher's own record of what it installed: `launcher.json`.
pub fn install_record() -> PathBuf {
    user_data_root().join("launcher.json")
}

/// Everything the launcher and the subprocesses it runs print.
pub fn launcher_log() -> PathBuf {
    user_data_root().join("launcher.log")
}

/// Root of the Python sidecar tree, matching `PythonStage`.
pub fn python_runtime_dir() -> PathBuf {
    user_data_root().join("runtime").join("python")
}

/// The sidecar interpreter, matching `PythonStage._sidecar_exe()`.
pub fn python_exe() -> PathBuf {
    let root = python_runtime_dir().join("python");
    if cfg!(windows) {
        root.join("python.exe")
    } else {
        root.join("bin").join("python3")
    }
}

/// `app.paths.AGENT_READY_FILE`: written by the agent once boot() has
/// finished, deleted by run.py just before each launch.
pub fn agent_ready_file() -> PathBuf {
    user_data_root().join(".agent-ready")
}

/// `app.paths.MANAGED_MARKER`, stamped into an install root.
pub const MANAGED_MARKER: &str = ".craftbot-managed";

/// `craftbot.py`'s PID file in source mode: beside craftbot.py. (Its log,
/// craftbot.log, is in the same place.)
pub fn pid_file(install_dir: &Path) -> PathBuf {
    install_dir.join("craftbot.pid")
}

/// The URL the browser UI is served at (`craftbot.BROWSER_URL`).
pub const BROWSER_URL: &str = "http://localhost:7925";

/// Directory holding the running launcher binary. On macOS that is
/// `CraftBotInstaller.app/Contents/MacOS/`; callers that look for files
/// "beside the app" want the directory the bundle sits in, see
/// [`beside_app_dirs`].
pub fn exe_dir() -> Option<PathBuf> {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
}

/// Directories a locally staged file (the dev-loop `CraftBot-src.zip`) may
/// sit in, most specific first.
pub fn beside_app_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Some(dir) = exe_dir() {
        dirs.push(dir.clone());
        // Walk out of a macOS bundle: MacOS/ -> Contents/ -> Foo.app -> dir.
        if cfg!(target_os = "macos") {
            if let Some(outside) = dir
                .parent()
                .and_then(|c| c.parent())
                .and_then(|a| a.parent())
            {
                dirs.push(outside.to_path_buf());
            }
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        dirs.push(cwd.join("dist"));
        dirs.push(cwd);
    }
    dirs
}

fn home() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("."))
}

/// Shorten a path from the middle so both the drive and the final folder
/// stay readable. Same rule as the Tk window's `elide()`.
pub fn elide(path: &str, limit: usize) -> String {
    let chars: Vec<char> = path.chars().collect();
    if chars.len() <= limit {
        return path.to_string();
    }
    let keep = (limit.saturating_sub(3)) / 2;
    let head: String = chars[..keep].iter().collect();
    let tail: String = chars[chars.len() - keep..].iter().collect();
    format!("{head}...{tail}")
}
