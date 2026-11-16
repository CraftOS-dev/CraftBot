//! Running `craftbot.py`: the one place the launcher talks to the Python
//! side.
//!
//! The launcher never reimplements what craftbot.py does. It runs
//! `python craftbot.py <install|start|stop|uninstall>` inside the installed
//! tree with `CRAFTBOT_PYTHON` pointing at the sidecar, which is how
//! `app/python_runtime.py` is told which interpreter every CraftBot process
//! must use. `install` there runs install.py; `start` runs run.py. Those two
//! files stay the source of truth for what an installation is.
//!
//! Output is streamed line by line: into launcher.log in full, and to the
//! caller so the last meaningful line can become the window's status. The
//! last [`TAIL_LINES`] lines are kept for the error panel.

use std::collections::VecDeque;
use std::ffi::OsString;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Command, Stdio};

/// How many trailing output lines a failure shows.
pub const TAIL_LINES: usize = 15;

/// Variables that would point the private interpreter at someone else's
/// packages, site customisation or virtual environment.
const STRIPPED: &[&str] = &[
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONEXECUTABLE",
    "PYTHONUSERBASE",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
];

/// The pip settings a user may need on a restricted network (a package
/// mirror, a corporate CA). Every other `PIP_*` variable is removed: options
/// such as PIP_TARGET, PIP_PREFIX, PIP_USER or PIP_REQUIRE_VIRTUALENV would
/// redirect or refuse the locked install.
const PIP_KEPT: &[&str] = &[
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_TRUSTED_HOST",
    "PIP_CERT",
];

/// A Command for any child the launcher starts: never flashes a console
/// window on Windows, and runs the private Python in isolation from
/// whatever Python setup the user's environment carries.
pub fn child_command(program: &Path) -> Command {
    let mut cmd = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    for name in removed_vars(std::env::vars_os().map(|(k, _)| k)) {
        cmd.env_remove(name);
    }
    cmd.env("PYTHONNOUSERSITE", "1")
        .env("PYTHONUTF8", "1")
        .env("PIP_DISABLE_PIP_VERSION_CHECK", "1");
    // app.paths resolves CRAFTBOT_HOME relative to its own working directory
    // (the install tree); hand it the absolute form the launcher uses.
    if let Some(home) = crate::paths::home_override() {
        cmd.env("CRAFTBOT_HOME", home);
    }
    cmd
}

/// Which of the inherited variable names `child_command` removes.
fn removed_vars(names: impl Iterator<Item = OsString>) -> Vec<OsString> {
    names
        .filter(|name| {
            let upper = name.to_string_lossy().to_ascii_uppercase();
            STRIPPED.contains(&upper.as_str())
                || (upper.starts_with("PIP_") && !PIP_KEPT.contains(&upper.as_str()))
        })
        .collect()
}

/// How a craftbot.py run ended.
pub struct Outcome {
    pub code: i32,
    /// The last [`TAIL_LINES`] non-blank lines it printed, stdout and stderr
    /// together, oldest first.
    pub tail: Vec<String>,
}

/// Run `craftbot.py args…` and stream its output.
pub fn run(
    python: &Path,
    install_dir: &Path,
    args: &[&str],
    on_line: &mut dyn FnMut(&str),
) -> Result<Outcome, String> {
    let script = install_dir.join("craftbot.py");
    if !script.is_file() {
        return Err(format!(
            "{} is missing. The install is incomplete; use Repair.",
            script.display()
        ));
    }
    crate::logger::log(&format!(
        "run: {} craftbot.py {}",
        python.display(),
        args.join(" ")
    ));

    let mut cmd = child_command(python);
    cmd.arg(&script)
        .args(args)
        .current_dir(install_dir)
        // The interpreter for every CraftBot process. Without this the Python
        // side would go looking for a 3.10 on the machine, which is exactly
        // the dependency the launcher exists to remove.
        .env("CRAFTBOT_PYTHON", python)
        // Line-buffered, UTF-8 output regardless of console code page, so
        // progress reaches the window as it happens and box-drawing
        // characters do not become mojibake.
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONIOENCODING", "utf-8")
        // Nothing to answer prompts with: any input() the Python side hits
        // fails immediately instead of hanging forever behind the window.
        .stdin(Stdio::null());

    // stdout and stderr share one pipe, as `2>&1` would, so the lines arrive
    // in the order they were printed: a traceback stays at the end of the
    // tail instead of racing the progress lines before it.
    let (reader, writer) =
        std::io::pipe().map_err(|e| format!("cannot capture craftbot.py output: {e}"))?;
    let writer_err = writer
        .try_clone()
        .map_err(|e| format!("cannot capture craftbot.py output: {e}"))?;
    cmd.stdout(writer).stderr(writer_err);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("cannot start {}: {e}", python.display()))?;
    // The Command holds the pipe's write ends; until they are closed here
    // the read loop below would never see the end of the output.
    drop(cmd);

    let mut tail: VecDeque<String> = VecDeque::with_capacity(TAIL_LINES);
    for line in BufReader::new(reader).lines().map_while(Result::ok) {
        let clean = crate::logger::strip_ansi(&line);
        crate::logger::raw(&clean);
        if !clean.trim().is_empty() {
            if tail.len() == TAIL_LINES {
                tail.pop_front();
            }
            tail.push_back(clean.trim_end().to_string());
        }
        on_line(&clean);
    }

    let status = child
        .wait()
        .map_err(|e| format!("waiting for craftbot.py: {e}"))?;
    let code = status.code().unwrap_or(-1);
    crate::logger::log(&format!(
        "craftbot.py {} exited {code}",
        args.first().unwrap_or(&"")
    ));
    let tail: Vec<String> = tail.into_iter().collect();
    Ok(Outcome { code, tail })
}

/// The last line worth putting on a status line: skips blanks, rules and
/// progress noise. Same rule as the Tk window's `_last_meaningful_line`.
pub fn meaningful(line: &str) -> Option<String> {
    let text = line.trim();
    if text.chars().count() < 3 {
        return None;
    }
    if text.chars().all(|c| "-=_─━ *#░▸║╔╗╚╝═".contains(c)) {
        return None;
    }
    // Strip the decorative prefixes craftbot.py/install.py use.
    let text = text
        .trim_start_matches(|c: char| "▸░║✓✗•·".contains(c) || c.is_whitespace())
        .trim();
    if text.is_empty() {
        return None;
    }
    let mut out: String = text.chars().take(72).collect();
    if text.chars().count() > 72 {
        out.push('…');
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_environment_is_isolated_but_mirrors_survive() {
        let names = [
            "PYTHONPATH",
            "pythonhome",
            "PYTHONSTARTUP",
            "PYTHONEXECUTABLE",
            "PYTHONUSERBASE",
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
            "PIP_TARGET",
            "PIP_USER",
            "pip_require_virtualenv",
            "PIP_INDEX_URL",
            "PIP_EXTRA_INDEX_URL",
            "PIP_TRUSTED_HOST",
            "PIP_CERT",
            "PATH",
            "CRAFTBOT_HOME",
            "HTTPS_PROXY",
            "PYTHONIOENCODING",
        ];
        let removed: Vec<String> = removed_vars(names.iter().map(OsString::from))
            .into_iter()
            .map(|s| s.to_string_lossy().into_owned())
            .collect();
        assert_eq!(
            removed,
            vec![
                "PYTHONPATH",
                "pythonhome",
                "PYTHONSTARTUP",
                "PYTHONEXECUTABLE",
                "PYTHONUSERBASE",
                "VIRTUAL_ENV",
                "CONDA_PREFIX",
                "PIP_TARGET",
                "PIP_USER",
                "pip_require_virtualenv",
            ]
        );
    }
}
