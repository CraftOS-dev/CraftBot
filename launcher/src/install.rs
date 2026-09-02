//! The jobs behind the buttons, run on a worker thread.
//!
//! Only `Install` and `Repair` do real work of their own — and even that is
//! limited to getting a source tree and an interpreter onto the disk. Once
//! those exist, everything is `craftbot.py <command>`: install (which runs
//! install.py), start (which runs run.py), stop, uninstall. See craftbot.rs.

use crate::craftbot;
use crate::download;
use crate::logger;
use crate::paths;
use crate::payload;
use crate::python;
use crate::record::InstallRecord;
use crate::state;
use std::path::{Path, PathBuf};
use std::sync::mpsc::Sender;

/// install.py refuses to proceed below this (and would prompt, which no one
/// can answer behind a window), so check first and say so plainly.
const MIN_FREE_GB: u64 = 5;

#[derive(Debug, Clone)]
pub enum Job {
    Install { target: PathBuf },
    Repair,
    Uninstall,
    Start,
    Stop,
}

impl Job {
    pub fn label(&self) -> &'static str {
        match self {
            Job::Install { .. } => "install",
            Job::Repair => "repair",
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
    /// The job ended. Err carries a one-line reason for the status line;
    /// the full story is in launcher.log.
    Finished(Result<(), String>),
}

pub fn run(job: Job, tx: Sender<Event>) {
    logger::log(&format!("job {} started", job.label()));
    let result = match &job {
        Job::Install { target } => install(target, &tx),
        Job::Repair => repair(&tx),
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

    if let Some(free) = python::free_space(target) {
        let need = MIN_FREE_GB * 1024 * 1024 * 1024;
        if free < need {
            return Err(format!(
                "Not enough disk space: {} GB free, {MIN_FREE_GB} GB needed",
                free / (1024 * 1024 * 1024)
            ));
        }
    }

    // Anything running from an earlier install would hold files open — on
    // Windows that makes extraction fail halfway and leaves a broken tree.
    stop_if_running(tx)?;

    // 1. An interpreter. Same build, same place as install.py's own python
    //    stage, which will find it and not download another.
    let python = {
        let mut progress = |read, total| {
            let _ = tx.send(Event::Progress { read, total });
        };
        python::ensure(&mut say, &mut progress)?
    };
    let _ = tx.send(Event::Working);

    // 2. The source tree.
    let (zip, owned) = {
        let mut progress = |read, total| {
            let _ = tx.send(Event::Progress { read, total });
        };
        payload::obtain(&mut say, &mut progress)?
    };
    let _ = tx.send(Event::Working);
    say("Unpacking CraftBot…");
    let extracted = payload::extract(&zip, target);
    if owned {
        let _ = std::fs::remove_file(&zip);
    }
    let src_root = extracted?;
    payload::mark_managed(&src_root)?;
    logger::log(&format!("source at {}", src_root.display()));

    // 3. Remember it before running install.py, so a failure partway still
    //    leaves Repair pointing at the right place.
    InstallRecord::new(src_root.clone(), python.clone(), payload::VERSION).save()?;

    // 4. Everything else is install.py's business, via craftbot.py install:
    //    the locked dependency set, Node, the npm trees, Playwright, the
    //    auto-start registration, and the first start.
    say("Setting up the runtime — this takes a few minutes on first install");
    let code = run_craftbot(&python, &src_root, &["install", "--no-open-browser"], tx)?;
    if code != 0 {
        return Err(format!("Setup did not complete (craftbot.py install exited {code}). See the log."));
    }
    say("Installed");
    Ok(())
}

fn repair(tx: &Sender<Event>) -> Result<(), String> {
    // Repair is an install over the existing location. It re-downloads the
    // payload for this launcher's version, which is also the upgrade path.
    let rec = InstallRecord::load_any().ok_or("Nothing to repair: CraftBot is not installed")?;
    install(rec.dir(), tx)
}

fn start(tx: &Sender<Event>) -> Result<(), String> {
    let rec = InstallRecord::load().ok_or("CraftBot is not installed")?;
    let _ = tx.send(Event::Working);
    let _ = tx.send(Event::Status("Starting CraftBot…".into()));
    // --no-open-browser: craftbot.py would otherwise block until the agent is
    // ready and then open a tab. The window watches readiness itself and
    // offers "Open CraftBot" when it is real.
    let code = run_craftbot(&rec.python, rec.dir(), &["start", "--no-open-browser"], tx)?;
    if code != 0 {
        return Err(format!("CraftBot failed to start (exit {code}). See the log."));
    }
    Ok(())
}

fn stop(tx: &Sender<Event>) -> Result<(), String> {
    let rec = InstallRecord::load().ok_or("CraftBot is not installed")?;
    let _ = tx.send(Event::Working);
    let _ = tx.send(Event::Status("Stopping CraftBot…".into()));
    let code = run_craftbot(&rec.python, rec.dir(), &["stop"], tx)?;
    if code != 0 {
        return Err(format!("Stop failed (exit {code}). See the log."));
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
        let code = run_craftbot(&rec.python, rec.dir(), &["uninstall"], tx)?;
        if code != 0 {
            logger::log(&format!("craftbot.py uninstall exited {code}; removing files anyway"));
        }
    }

    // The source tree and the runtimes are the launcher's to remove. The
    // user's own data (agent_file_system, databases, the vector store) lives
    // elsewhere under the data root and is deliberately left alone.
    let _ = tx.send(Event::Status("Removing files…".into()));
    remove_tree(rec.dir())?;
    remove_tree(&paths::user_data_root().join("runtime"))?;
    let _ = std::fs::remove_file(paths::agent_ready_file());
    InstallRecord::clear();
    let _ = tx.send(Event::Status("Uninstalled".into()));
    Ok(())
}

// ── Helpers ─────────────────────────────────────────────────────────────

fn run_craftbot(python: &Path, dir: &Path, args: &[&str], tx: &Sender<Event>) -> Result<i32, String> {
    let mut on_line = |line: &str| {
        if let Some(text) = craftbot::meaningful(line) {
            let _ = tx.send(Event::Status(text));
        }
    };
    craftbot::run(python, dir, args, &mut on_line)
}

fn stop_if_running(tx: &Sender<Event>) -> Result<(), String> {
    let snap = state::poll();
    if !matches!(snap.phase, state::Phase::InstalledRunning | state::Phase::InstalledStarting) {
        return Ok(());
    }
    if let Some(rec) = snap.record {
        let _ = tx.send(Event::Status("Stopping the running CraftBot first…".into()));
        let _ = run_craftbot(&rec.python, rec.dir(), &["stop"], tx)?;
    }
    Ok(())
}

fn remove_tree(dir: &Path) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }
    // Refuse anything that is not clearly ours. Deleting the user's home
    // because a record was hand-edited would be unforgivable.
    let is_root_like = dir.parent().is_none()
        || dirs::home_dir().map(|h| h == dir).unwrap_or(false);
    if is_root_like {
        return Err(format!("refusing to remove {}", dir.display()));
    }
    std::fs::remove_dir_all(dir).map_err(|e| format!("could not remove {}: {e}", dir.display()))
}

#[allow(dead_code)]
pub fn describe_progress(read: u64, total: Option<u64>) -> String {
    match total {
        Some(t) => format!("Downloading… {} of {} MB", download::mb(read), download::mb(t)),
        None => format!("Downloading… {} MB", download::mb(read)),
    }
}
