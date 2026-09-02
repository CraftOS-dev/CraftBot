//! Running `craftbot.py` — the one place the launcher talks to the Python
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
//! caller so the last meaningful line can become the window's status.

use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Command, Stdio};

/// A Command that never flashes a console window on Windows.
pub fn quiet_command(program: &Path) -> Command {
    #[allow(unused_mut)]
    let mut cmd = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

/// Run `craftbot.py args…` and stream its output. Returns the exit code.
pub fn run(
    python: &Path,
    install_dir: &Path,
    args: &[&str],
    on_line: &mut dyn FnMut(&str),
) -> Result<i32, String> {
    let script = install_dir.join("craftbot.py");
    if !script.is_file() {
        return Err(format!("{} is missing — the install is incomplete", script.display()));
    }
    crate::logger::log(&format!("run: {} craftbot.py {}", python.display(), args.join(" ")));

    let mut cmd = quiet_command(python);
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
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        // Nothing to answer prompts with: any input() the Python side hits
        // fails immediately instead of hanging forever behind the window.
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| format!("cannot start {}: {e}", python.display()))?;

    // stderr is drained on its own thread so neither pipe can fill up and
    // block the child while we wait on the other.
    let stderr = child.stderr.take();
    let err_thread = std::thread::spawn(move || {
        let mut lines = Vec::new();
        if let Some(err) = stderr {
            for line in BufReader::new(err).lines().map_while(Result::ok) {
                crate::logger::raw(&format!("[stderr] {line}"));
                lines.push(line);
            }
        }
        lines
    });

    if let Some(out) = child.stdout.take() {
        for line in BufReader::new(out).lines().map_while(Result::ok) {
            let clean = crate::logger::strip_ansi(&line);
            crate::logger::raw(&clean);
            on_line(&clean);
        }
    }

    let status = child.wait().map_err(|e| format!("waiting for craftbot.py: {e}"))?;
    let err_lines = err_thread.join().unwrap_or_default();
    let code = status.code().unwrap_or(-1);
    crate::logger::log(&format!("craftbot.py {} exited {code}", args.first().unwrap_or(&"")));

    if code != 0 {
        // Surface the last error line so the status can say something
        // better than "exit 1".
        let tail = err_lines
            .iter()
            .rev()
            .map(|l| crate::logger::strip_ansi(l))
            .find(|l| !l.trim().is_empty())
            .unwrap_or_default();
        if !tail.is_empty() {
            on_line(&tail);
        }
    }
    Ok(code)
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
