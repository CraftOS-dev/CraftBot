//! Where things live. Every path here mirrors one in the Python side
//! (`app/paths.py`, `run.py`), because the launcher and the agent must agree
//! on them without talking to each other:
//!
//! * the data root is `app.paths.STATE_ROOT` for a managed install:
//!   `CRAFTBOT_HOME` when set, otherwise `app.paths._user_data_root()`;
//! * the Python sidecar location is `PythonStage._sidecar_exe()` in
//!   `app/provision/runtimes.py`. The launcher puts the interpreter exactly
//!   where install.py's provisioning would, so that stage finds it and does
//!   not download a second one;
//! * `craftbot.pid` and `ui.json` are written by run.py under STATE_ROOT,
//!   whoever started it: this window, a terminal, or the login item.

use std::path::{Path, PathBuf};

/// `app.paths`' override for the data root. Honoured here so the launcher and
/// the agent never disagree about where the runtimes, the pid file and the
/// ready marker are.
const HOME_OVERRIDE: &str = "CRAFTBOT_HOME";

/// The data root: launcher state, the Python sidecar, and the agent's own
/// data. Matches `app.paths.STATE_ROOT` for a managed install.
pub fn user_data_root() -> PathBuf {
    if let Some(dir) = home_override() {
        return dir;
    }
    #[cfg(target_os = "windows")]
    {
        let root = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .or_else(dirs::data_local_dir)
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

/// `CRAFTBOT_HOME` as an absolute path, if set. Children are handed this
/// absolute form (see craftbot.rs): they run in the install directory, so a
/// relative value would otherwise resolve somewhere else for them.
pub fn home_override() -> Option<PathBuf> {
    let raw = std::env::var(HOME_OVERRIDE).ok()?;
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    let path = match raw.strip_prefix('~') {
        Some(rest) => home().join(rest.trim_start_matches(['/', '\\'])),
        None => PathBuf::from(raw),
    };
    Some(if path.is_absolute() {
        path
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(&path))
            .unwrap_or(path)
    })
}

/// Where CraftBot is installed when the user does not choose. Per-user, so
/// no elevation is needed. On Linux the source tree sits in its own `source`
/// folder under the data root: the agent keeps its settings and databases in
/// `<data root>/app`, and that folder must never be what Uninstall removes.
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
        user_data_root().join("source")
    }
}

/// True when removing (or installing into) `dir` would touch the user's own
/// data: the data root itself, `<data root>/app` (settings with API keys,
/// databases), or any folder that contains them.
pub fn overlaps_user_data(dir: &Path) -> bool {
    let data = user_data_root().join("app");
    same_or_inside(&data, dir)
}

/// Whether `inner` is `outer` or lies under it. Compares canonical forms
/// where they exist, so `..`, symlinks and Windows 8.3 names cannot slip a
/// data folder past the check.
fn same_or_inside(inner: &Path, outer: &Path) -> bool {
    let canon = |p: &Path| {
        let mut probe = p.to_path_buf();
        let mut rest = Vec::new();
        while !probe.exists() {
            match (probe.file_name(), probe.parent()) {
                (Some(name), Some(parent)) => {
                    rest.push(name.to_os_string());
                    probe = parent.to_path_buf();
                }
                _ => return p.to_path_buf(),
            }
        }
        let mut real = std::fs::canonicalize(&probe).unwrap_or(probe);
        for part in rest.into_iter().rev() {
            real.push(part);
        }
        real
    };
    let (inner, outer) = (canon(inner), canon(outer));
    if cfg!(windows) {
        let lower = |p: &Path| p.to_string_lossy().to_lowercase();
        Path::new(&lower(&inner)).starts_with(Path::new(&lower(&outer)))
    } else {
        inner.starts_with(&outer)
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

/// Written by run.py when it starts and removed when it exits, however it
/// was started (this window, a terminal, or the login item).
pub fn pid_file() -> PathBuf {
    user_data_root().join("craftbot.pid")
}

/// Written by run.py once the browser UI is serving:
/// `{"url": "http://localhost:7925", "frontend_port": 7925, "backend_port": 7926}`.
/// The ports differ from the defaults when those were busy.
pub fn ui_file() -> PathBuf {
    user_data_root().join("ui.json")
}

/// Where the browser UI is served when run.py has not said otherwise.
pub const DEFAULT_BROWSER_URL: &str = "http://localhost:7925";

/// The URL "Open CraftBot" should open: `ui.json`'s, else the default.
pub fn browser_url() -> String {
    std::fs::read_to_string(ui_file())
        .ok()
        .and_then(|text| parse_ui_url(&text))
        .unwrap_or_else(|| DEFAULT_BROWSER_URL.to_string())
}

fn parse_ui_url(text: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    let url = value.get("url")?.as_str()?.trim();
    // Only a web address. Whatever is in the file is handed to the OS
    // "open" call, which would happily launch a program.
    (url.starts_with("http://") || url.starts_with("https://")).then(|| url.to_string())
}

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ui_json_url_is_read_and_checked() {
        assert_eq!(
            parse_ui_url(
                r#"{"url": "http://localhost:7935", "frontend_port": 7935, "backend_port": 7936}"#
            ),
            Some("http://localhost:7935".into())
        );
        assert_eq!(parse_ui_url(r#"{"url": "file:///etc/passwd"}"#), None);
        assert_eq!(parse_ui_url(r#"{"frontend_port": 7925}"#), None);
        assert_eq!(parse_ui_url("not json"), None);
    }

    #[test]
    fn data_folders_are_never_an_install_location() {
        let data = user_data_root();
        assert!(overlaps_user_data(&data));
        assert!(overlaps_user_data(&data.join("app")));
        if let Some(parent) = data.parent() {
            assert!(overlaps_user_data(parent));
        }
        assert!(!overlaps_user_data(&data.join("source")));
        assert!(!overlaps_user_data(&data.join("runtime")));
        assert!(!overlaps_user_data(&data.join("app2")));
    }

    #[test]
    fn linux_source_tree_is_apart_from_the_data() {
        if cfg!(all(unix, not(target_os = "macos"))) {
            assert!(!overlaps_user_data(&default_install_dir()));
        }
    }
}
