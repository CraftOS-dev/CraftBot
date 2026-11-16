//! The jobs behind the buttons, run on a worker thread.
//!
//! Only `Install` and `Repair` do real work of their own, and even that is
//! limited to getting a source tree and an interpreter onto the disk. Once
//! those exist, everything is `craftbot.py <command>`: install (which runs
//! install.py), start (which runs run.py), stop, uninstall. See craftbot.rs.
//!
//! An install is recorded in launcher.json only once `craftbot.py install`
//! has succeeded. Until then the window offers Repair, never Start.

use crate::craftbot;
use crate::download;
use crate::logger;
use crate::paths;
use crate::payload;
use crate::preflight;
use crate::python;
use crate::record::InstallRecord;
use crate::state;
use std::cmp::Ordering;
use std::path::{Path, PathBuf};
use std::sync::mpsc::Sender;

/// Free space needed on the drive holding the data root, which receives
/// the bulk of an install: the Python packages, Node and the npm trees.
/// Checked before anything is downloaded.
pub const MIN_FREE_GB: u64 = 3;

#[derive(Debug, Clone)]
pub enum Job {
    Install {
        target: PathBuf,
    },
    /// Install again over `target`: fixes a broken install, finishes a
    /// failed one, and is the update path for a newer launcher.
    Repair {
        target: PathBuf,
    },
    Uninstall,
    Start,
    Stop,
}

impl Job {
    pub fn label(&self) -> &'static str {
        match self {
            Job::Install { .. } => "install",
            Job::Repair { .. } => "repair",
            Job::Uninstall => "uninstall",
            Job::Start => "start",
            Job::Stop => "stop",
        }
    }
}

/// What the worker reports back to the window.
#[derive(Debug, Clone)]
pub enum Event {
    /// A line for the status text.
    Status(String),
    /// A measured download: bytes so far, total if known.
    Progress { read: u64, total: Option<u64> },
    /// Busy with nothing measurable.
    Working,
    /// The job ended. Err's first line is the status line; any further
    /// lines are the end of the setup output, for the error panel. The full
    /// story is in launcher.log.
    Finished(Result<(), String>),
}

pub fn run(job: Job, tx: Sender<Event>) {
    logger::log(&format!("job {} started", job.label()));
    let result = match &job {
        Job::Install { target } => install(target, &tx),
        Job::Repair { target } => repair(target, &tx),
        Job::Uninstall => uninstall(&tx),
        Job::Start => start(&tx),
        Job::Stop => stop(&tx),
    };
    match &result {
        Ok(()) => logger::log(&format!("job {} finished", job.label())),
        Err(e) => logger::log(&format!("job {} FAILED: {e}", job.label())),
    }
    let _ = tx.send(Event::Finished(result));
}

// ── Steps ───────────────────────────────────────────────────────────────

fn install(target: &Path, tx: &Sender<Event>) -> Result<(), String> {
    let mut say = |s: &str| {
        let _ = tx.send(Event::Status(s.to_string()));
    };
    let _ = tx.send(Event::Working);

    // Everything that can refuse does so before the first byte is fetched.
    preflight::check()?;
    if paths::overlaps_user_data(target) {
        return Err(format!(
            "{} holds your CraftBot data. Choose another install location.",
            target.display()
        ));
    }
    let data_root = paths::user_data_root();
    if let Some(free) = python::free_space(&data_root) {
        let need = MIN_FREE_GB * 1024 * 1024 * 1024;
        if free < need {
            return Err(format!(
                "Not enough disk space: {} GB free on the drive with {}, {MIN_FREE_GB} GB needed",
                free / (1024 * 1024 * 1024),
                data_root.display()
            ));
        }
    }

    // 1. The source payload, downloaded and verified while anything already
    //    installed keeps running: a failed download changes nothing.
    let zip = {
        let mut progress = |read, total| {
            let _ = tx.send(Event::Progress { read, total });
        };
        let (path, owned) = payload::obtain(&mut say, &mut progress)?;
        Download { path, owned }
    };
    let _ = tx.send(Event::Working);

    // Anything running from an earlier install would hold files open; on
    // Windows that makes extraction fail halfway and leaves a broken tree.
    stop_if_running(tx)?;

    // 2. An interpreter. Same build, same place as install.py's own python
    //    stage, which will find it and not download another.
    let python = {
        let mut progress = |read, total| {
            let _ = tx.send(Event::Progress { read, total });
        };
        python::ensure(&mut say, &mut progress)?
    };
    let _ = tx.send(Event::Working);

    // 3. The source tree. From here until setup succeeds, the tree on disk
    //    is not a working install, so no record may say it is.
    InstallRecord::clear();
    say("Unpacking CraftBot…");
    let src_root = payload::extract(&zip.path, target)?;
    drop(zip);
    payload::mark_managed(&src_root)?;
    logger::log(&format!("source at {}", src_root.display()));

    // 4. Everything else is install.py's business, via craftbot.py install:
    //    the locked dependency set, Node, the npm trees, Playwright, the
    //    auto-start registration, and the first start.
    say("Setting up the runtime. The first install takes a few minutes.");
    let outcome = run_craftbot(&python, &src_root, &["install", "--no-open-browser"], tx)?;
    if outcome.code != 0 {
        return Err(with_tail(
            &format!(
                "Setup did not finish (exit {}). Use Repair to try again.",
                outcome.code
            ),
            &outcome.tail,
        ));
    }

    // 5. Only now is it an install.
    InstallRecord::new(src_root, python, payload::VERSION).save()?;
    say("Installed");
    Ok(())
}

fn repair(target: &Path, tx: &Sender<Event>) -> Result<(), String> {
    // A repair installs this launcher's payload. Over a newer install that
    // would be a silent downgrade, which the user's data may not survive.
    if let Some(rec) = InstallRecord::load_any() {
        if payload::compare_with_installed(&rec.version) == Some(Ordering::Less) {
            return Err(format!(
                "CraftBot {} is installed, and this installer is for {}. Download the latest installer to repair it.",
                rec.version,
                payload::VERSION
            ));
        }
    }
    install(target, tx)
}

fn start(tx: &Sender<Event>) -> Result<(), String> {
    let rec = InstallRecord::load().ok_or("CraftBot is not installed")?;
    let _ = tx.send(Event::Working);
    let _ = tx.send(Event::Status("Starting CraftBot…".into()));
    // --no-open-browser: craftbot.py would otherwise block until the agent is
    // ready and then open a tab. The window watches readiness itself and
    // offers "Open CraftBot" when it is real.
    let outcome = run_craftbot(&rec.python, rec.dir(), &["start", "--no-open-browser"], tx)?;
    if outcome.code != 0 {
        return Err(with_tail(
            &format!("CraftBot did not start (exit {}).", outcome.code),
            &outcome.tail,
        ));
    }
    Ok(())
}

fn stop(tx: &Sender<Event>) -> Result<(), String> {
    let rec = InstallRecord::load().ok_or("CraftBot is not installed")?;
    let _ = tx.send(Event::Working);
    let _ = tx.send(Event::Status("Stopping CraftBot…".into()));
    let outcome = run_craftbot(&rec.python, rec.dir(), &["stop"], tx)?;
    if outcome.code != 0 {
        return Err(with_tail(
            &format!("CraftBot did not stop (exit {}).", outcome.code),
            &outcome.tail,
        ));
    }
    Ok(())
}

fn uninstall(tx: &Sender<Event>) -> Result<(), String> {
    let rec = InstallRecord::load_any().ok_or("CraftBot is not installed")?;
    let _ = tx.send(Event::Working);
    let _ = tx.send(Event::Status("Uninstalling…".into()));

    // craftbot.py uninstall stops the agent, removes auto-start and the
    // desktop shortcut. Only if the tree is still there to run it from.
    if rec.craftbot_py().is_file() && rec.python.is_file() {
        let outcome = run_craftbot(&rec.python, rec.dir(), &["uninstall"], tx)?;
        if outcome.code != 0 {
            logger::log(&format!(
                "craftbot.py uninstall exited {}; removing files anyway",
                outcome.code
            ));
        }
    }

    // The source tree and the runtimes are the launcher's to remove. The
    // user's own data (agent_file_system, settings, databases, the vector
    // store) lives elsewhere under the data root and is deliberately left
    // alone.
    let _ = tx.send(Event::Status("Removing files…".into()));
    // The source tree is removed wholesale, so it must not be (or contain)
    // the folder the agent keeps its settings and databases in.
    let shared = paths::overlaps_user_data(rec.dir());
    if !shared {
        remove_tree(rec.dir())?;
    }
    remove_tree(&paths::user_data_root().join("runtime"))?;
    let _ = std::fs::remove_file(paths::agent_ready_file());
    InstallRecord::clear();
    if shared {
        return Err(format!(
            "Uninstalled. {} was kept because it also holds your CraftBot settings and data.",
            rec.dir().display()
        ));
    }
    let _ = tx.send(Event::Status("Uninstalled".into()));
    Ok(())
}

// ── Helpers ─────────────────────────────────────────────────────────────

/// The payload zip for one install. A downloaded one is deleted however the
/// install ends; a locally staged one is left where it was.
struct Download {
    path: PathBuf,
    owned: bool,
}

impl Drop for Download {
    fn drop(&mut self) {
        if self.owned {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

fn run_craftbot(
    python: &Path,
    dir: &Path,
    args: &[&str],
    tx: &Sender<Event>,
) -> Result<craftbot::Outcome, String> {
    let mut on_line = |line: &str| {
        if let Some(text) = craftbot::meaningful(line) {
            let _ = tx.send(Event::Status(text));
        }
    };
    craftbot::run(python, dir, args, &mut on_line)
}

/// A failure message: the status line, then the output tail for the panel.
fn with_tail(summary: &str, tail: &[String]) -> String {
    let mut text = summary.to_string();
    for line in tail {
        text.push('\n');
        text.push_str(line);
    }
    text
}

fn stop_if_running(tx: &Sender<Event>) -> Result<(), String> {
    let snap = state::poll();
    if !matches!(
        snap.phase,
        state::Phase::InstalledRunning | state::Phase::InstalledStarting
    ) {
        return Ok(());
    }
    if let Some(rec) = snap.record {
        let _ = tx.send(Event::Status("Stopping the running CraftBot first…".into()));
        let outcome = run_craftbot(&rec.python, rec.dir(), &["stop"], tx)?;
        if outcome.code != 0 {
            return Err(with_tail(
                &format!(
                    "Could not stop CraftBot before setup (exit {}).",
                    outcome.code
                ),
                &outcome.tail,
            ));
        }
    }
    Ok(())
}

fn remove_tree(dir: &Path) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }
    // Refuse anything that is not clearly ours. Deleting the user's home
    // because a record was hand-edited would be unforgivable.
    let is_root_like =
        dir.parent().is_none() || dirs::home_dir().map(|h| h == dir).unwrap_or(false);
    if is_root_like || paths::overlaps_user_data(dir) {
        return Err(format!("refusing to remove {}", dir.display()));
    }
    std::fs::remove_dir_all(dir).map_err(|e| format!("could not remove {}: {e}", dir.display()))
}

#[allow(dead_code)]
pub fn describe_progress(read: u64, total: Option<u64>) -> String {
    match total {
        Some(t) => format!(
            "Downloading… {} of {} MB",
            download::mb(read),
            download::mb(t)
        ),
        None => format!("Downloading… {} MB", download::mb(read)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failure_text_carries_the_tail() {
        let text = with_tail("Setup did not finish (exit 1).", &["a".into(), "b".into()]);
        let mut lines = text.lines();
        assert_eq!(lines.next(), Some("Setup did not finish (exit 1)."));
        assert_eq!(lines.collect::<Vec<_>>(), vec!["a", "b"]);
    }
}
