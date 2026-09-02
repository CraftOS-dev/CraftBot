//! CraftBot setup window.
//!
//! A native launcher: one binary per platform, no runtime to install first.
//! It downloads the CraftBot source payload and a portable Python, then
//! hands everything else to `craftbot.py` in the installed tree — `install`
//! (which runs install.py) and `start` (which runs run.py). Those two
//! scripts are the source of truth for what an installation is; this window
//! is a way to press the buttons without a terminal.
//!
//! Threads:
//!   * UI thread — Slint's event loop. Owns the window, applies state.
//!   * poll thread — asks `state::poll()` once a second, sends snapshots.
//!   * job thread — one at a time, runs an `install::Job`, sends events.
//!
//! Both channels are drained by a 200 ms Slint timer on the UI thread, so
//! nothing but the UI thread ever touches a widget.

#![cfg_attr(windows, windows_subsystem = "windows")]

mod craftbot;
mod download;
mod install;
mod logger;
mod paths;
mod payload;
mod python;
mod record;
mod state;

use install::{Event, Job};
use record::InstallRecord;
use slint::{ComponentHandle, SharedString};
use state::{Phase, Snapshot};
use std::cell::{Cell, RefCell};
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::mpsc::{self, Receiver, Sender};
use std::time::{Duration, Instant};

slint::include_modules!();

/// How long a measured byte count keeps the bar determinate before the
/// once-a-second state poll is allowed to take it back to indeterminate.
const MEASURED_GRACE: Duration = Duration::from_secs(3);
/// A second click on Uninstall within this window confirms it.
const CONFIRM_WINDOW: Duration = Duration::from_secs(6);

struct App {
    ui: slint::Weak<InstallerWindow>,
    target_dir: RefCell<PathBuf>,
    busy: Cell<bool>,
    snapshot: RefCell<Option<Snapshot>>,
    last_measured: Cell<Option<Instant>>,
    /// Until when the status line is spoken for — a job's own lines, a
    /// confirmation prompt, or an error that must stay until the user acts —
    /// so the once-a-second state poll does not write over it.
    status_hold: Cell<Option<Instant>>,
    uninstall_armed: Cell<Option<Instant>>,
    close_armed: Cell<Option<Instant>>,
    events_tx: Sender<Event>,
    events_rx: Receiver<Event>,
    states_rx: Receiver<Snapshot>,
}

fn main() {
    logger::log("──────────────────────────────────────────────");
    logger::log(&format!(
        "launcher {} for CraftBot {} starting ({} {})",
        env!("CARGO_PKG_VERSION"),
        payload::VERSION,
        std::env::consts::OS,
        std::env::consts::ARCH
    ));

    // `CraftBotInstaller --headless <job> [dir]` runs one job with no window
    // and prints its events. This is how CI exercises the real pipeline on a
    // runner with no display, and how a support case can be reproduced from
    // a terminal. It is not a user-facing CLI: craftbot.py is that.
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--headless") {
        std::process::exit(headless(&args[1..]));
    }

    let ui = match InstallerWindow::new() {
        Ok(ui) => ui,
        Err(e) => {
            logger::log(&format!("could not create the window: {e}"));
            eprintln!("CraftBot Setup could not open a window: {e}");
            std::process::exit(1);
        }
    };

    let (events_tx, events_rx) = mpsc::channel::<Event>();
    let (states_tx, states_rx) = mpsc::channel::<Snapshot>();

    // State poll, off the UI thread: on Windows a liveness check can stall,
    // and a stalled UI thread is a frozen window.
    std::thread::Builder::new()
        .name("state-poll".into())
        .spawn(move || loop {
            if states_tx.send(state::poll()).is_err() {
                break;
            }
            std::thread::sleep(Duration::from_secs(1));
        })
        .expect("spawn poll thread");

    let initial_target = InstallRecord::load_any()
        .map(|r| r.install_dir)
        .unwrap_or_else(paths::default_install_dir);

    let app = Rc::new(App {
        ui: ui.as_weak(),
        target_dir: RefCell::new(initial_target),
        busy: Cell::new(false),
        snapshot: RefCell::new(None),
        last_measured: Cell::new(None),
        status_hold: Cell::new(None),
        uninstall_armed: Cell::new(None),
        close_armed: Cell::new(None),
        events_tx,
        events_rx,
        states_rx,
    });

    // ── Static bits ─────────────────────────────────────────────────────
    let version = payload::VERSION;
    ui.set_version_label(if matches!(version, "" | "latest" | "dev" | "unknown") {
        SharedString::new()
    } else {
        format!("Version {version}").into()
    });
    app.show_target();

    // ── Callbacks ───────────────────────────────────────────────────────
    {
        let app = app.clone();
        ui.on_primary_clicked(move || app.on_primary());
    }
    {
        let app = app.clone();
        ui.on_stop_clicked(move || app.start_job(Job::Stop));
    }
    {
        let app = app.clone();
        ui.on_repair_clicked(move || app.start_job(Job::Repair));
    }
    {
        let app = app.clone();
        ui.on_uninstall_clicked(move || app.on_uninstall());
    }
    {
        let app = app.clone();
        ui.on_change_location_clicked(move || app.on_change_location());
    }
    ui.on_open_log_clicked(|| {
        let path = paths::launcher_log();
        if let Err(e) = open::that(&path) {
            logger::log(&format!("could not open the log: {e}"));
        }
    });
    {
        let app = app.clone();
        ui.window()
            .on_close_requested(move || app.on_close_requested());
    }

    // ── Tick: drain both channels on the UI thread ──────────────────────
    let tick = slint::Timer::default();
    {
        let app = app.clone();
        tick.start(
            slint::TimerMode::Repeated,
            Duration::from_millis(200),
            move || app.tick(),
        );
    }

    logger::log("entering event loop");
    if let Err(e) = ui.run() {
        logger::log(&format!("event loop ended with error: {e}"));
    }
    logger::log("window closed");
}

/// Run one job without a window; see main().
fn headless(args: &[String]) -> i32 {
    let job = match args.first().map(String::as_str) {
        Some("install") => Job::Install {
            target: args
                .get(1)
                .map(PathBuf::from)
                .unwrap_or_else(paths::default_install_dir),
        },
        Some("repair") => Job::Repair,
        Some("uninstall") => Job::Uninstall,
        Some("start") => Job::Start,
        Some("stop") => Job::Stop,
        Some("status") => {
            let snap = state::poll();
            println!("{:?}", snap.phase);
            if let Some(rec) = snap.record {
                println!("install_dir: {}", rec.install_dir.display());
                println!("python: {}", rec.python.display());
                println!("version: {}", rec.version);
            }
            return 0;
        }
        _ => {
            eprintln!("usage: CraftBotInstaller --headless <install [dir]|repair|uninstall|start|stop|status>");
            return 2;
        }
    };
    let (tx, rx) = mpsc::channel::<Event>();
    let worker = std::thread::spawn(move || install::run(job, tx));
    let mut code = 1;
    for event in rx {
        match event {
            Event::Status(text) => println!("{text}"),
            Event::Progress { read, total } => {
                if let Some(t) = total {
                    if read == t || read % (8 * 1024 * 1024) < 256 * 1024 {
                        println!("  {} / {} MB", download::mb(read), download::mb(t));
                    }
                }
            }
            Event::Working => {}
            Event::Finished(Ok(())) => code = 0,
            Event::Finished(Err(e)) => {
                eprintln!("FAILED: {e}");
                code = 1;
            }
        }
    }
    let _ = worker.join();
    code
}

impl App {
    fn ui(&self) -> InstallerWindow {
        self.ui.unwrap()
    }

    // ── Actions ─────────────────────────────────────────────────────────

    fn on_primary(&self) {
        if self.busy.get() {
            return;
        }
        let phase = self.snapshot.borrow().as_ref().map(|s| s.phase);
        match phase {
            Some(Phase::InstalledRunning) => {
                if let Err(e) = open::that(paths::BROWSER_URL) {
                    logger::log(&format!("could not open the browser: {e}"));
                    self.set_status(
                        &format!("Open {} in your browser", paths::BROWSER_URL),
                        Tone::Dim,
                    );
                    self.hold_status(CONFIRM_WINDOW);
                }
            }
            Some(Phase::InstalledStopped) => self.start_job(Job::Start),
            Some(Phase::InstalledStarting) | None => {}
            Some(Phase::NotInstalled) => {
                let target = self.target_dir.borrow().clone();
                self.start_job(Job::Install { target });
            }
        }
    }

    fn on_uninstall(&self) {
        if self.busy.get() {
            return;
        }
        let armed = self.uninstall_armed.get();
        if armed.map(|t| t.elapsed() < CONFIRM_WINDOW).unwrap_or(false) {
            self.uninstall_armed.set(None);
            self.start_job(Job::Uninstall);
        } else {
            self.uninstall_armed.set(Some(Instant::now()));
            self.set_status("Press Uninstall again to remove CraftBot", Tone::Amber);
            self.hold_status(CONFIRM_WINDOW);
        }
    }

    fn on_change_location(&self) {
        if self.busy.get() {
            return;
        }
        let current = self.target_dir.borrow().clone();
        let start_in = current
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or(current.clone());
        let picked = rfd::FileDialog::new()
            .set_title("Choose where to install CraftBot")
            .set_directory(start_in)
            .pick_folder();
        let Some(mut chosen) = picked else { return };
        // If they picked a parent rather than a CraftBot folder, append one
        // so the install does not scatter itself through e.g. Documents.
        let is_craftbot = chosen
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.eq_ignore_ascii_case("craftbot"))
            .unwrap_or(false);
        if !is_craftbot {
            chosen = chosen.join("CraftBot");
        }
        *self.target_dir.borrow_mut() = chosen;
        self.show_target();
    }

    fn on_close_requested(&self) -> slint::CloseRequestResponse {
        if !self.busy.get() {
            return slint::CloseRequestResponse::HideWindow;
        }
        let armed = self.close_armed.get();
        if armed.map(|t| t.elapsed() < CONFIRM_WINDOW).unwrap_or(false) {
            logger::log("closed while a job was running");
            return slint::CloseRequestResponse::HideWindow;
        }
        self.close_armed.set(Some(Instant::now()));
        self.set_status(
            "Setup is still working — close again to quit anyway",
            Tone::Amber,
        );
        self.hold_status(CONFIRM_WINDOW);
        slint::CloseRequestResponse::KeepWindowShown
    }

    fn start_job(&self, job: Job) {
        if self.busy.get() {
            return;
        }
        self.busy.set(true);
        self.status_hold.set(None);
        self.uninstall_armed.set(None);
        let ui = self.ui();
        ui.set_busy(true);
        ui.set_progress_visible(true);
        ui.set_progress_indeterminate(true);
        let tx = self.events_tx.clone();
        std::thread::Builder::new()
            .name(format!("job-{}", job.label()))
            .spawn(move || install::run(job, tx))
            .expect("spawn job thread");
    }

    // ── Tick ────────────────────────────────────────────────────────────

    fn tick(&self) {
        while let Ok(event) = self.events_rx.try_recv() {
            self.apply_event(event);
        }
        let mut latest = None;
        while let Ok(snap) = self.states_rx.try_recv() {
            latest = Some(snap);
        }
        if let Some(snap) = latest {
            self.apply_snapshot(snap);
        }
    }

    fn apply_event(&self, event: Event) {
        let ui = self.ui();
        match event {
            Event::Status(text) => self.set_status(&text, Tone::Dim),
            Event::Progress { read, total } => {
                ui.set_progress_visible(true);
                match total {
                    Some(t) if t > 0 => {
                        self.last_measured.set(Some(Instant::now()));
                        ui.set_progress_indeterminate(false);
                        ui.set_progress((read as f64 / t as f64).clamp(0.0, 1.0) as f32);
                        self.set_status(
                            &format!(
                                "Downloading… {} of {} MB",
                                download::mb(read),
                                download::mb(t)
                            ),
                            Tone::Dim,
                        );
                    }
                    _ => {
                        ui.set_progress_indeterminate(true);
                        self.set_status(
                            &format!("Downloading… {} MB", download::mb(read)),
                            Tone::Dim,
                        );
                    }
                }
            }
            Event::Working => {
                ui.set_progress_visible(true);
                ui.set_progress_indeterminate(true);
            }
            Event::Finished(result) => {
                self.busy.set(false);
                ui.set_busy(false);
                ui.set_progress_visible(false);
                ui.set_progress(0.0);
                match result {
                    Ok(()) => {
                        // The next snapshot writes the real state.
                        self.status_hold.set(None);
                    }
                    Err(e) => {
                        // Keep the error on screen until the user does
                        // something else; the state poll must not replace
                        // it with a cheerful "Installed · not running".
                        let first = e.lines().next().unwrap_or("Something went wrong");
                        self.set_status(first, Tone::Red);
                        self.hold_status(Duration::from_secs(24 * 3600));
                    }
                }
            }
        }
    }

    fn apply_snapshot(&self, snap: Snapshot) {
        let ui = self.ui();
        let busy = self.busy.get();
        let phase = snap.phase;

        // Once an install is recorded, the location is no longer a choice.
        if let Some(rec) = &snap.record {
            if *self.target_dir.borrow() != rec.install_dir {
                *self.target_dir.borrow_mut() = rec.install_dir.clone();
                self.show_target();
            }
        }

        // While a job is running the status line belongs to it; a held
        // status (a prompt, or the last job's error) stays put as well.
        let held = self
            .status_hold
            .get()
            .map(|t| Instant::now() < t)
            .unwrap_or(false);
        if !busy && !held {
            match phase {
                Phase::InstalledStarting => self.set_status("Starting CraftBot…", Tone::Amber),
                Phase::InstalledRunning => {
                    let text = match snap.pid {
                        Some(pid) => format!("Running · PID {pid}"),
                        None => "Running".to_string(),
                    };
                    self.set_status(&text, Tone::Green);
                }
                Phase::InstalledStopped => self.set_status("Installed · not running", Tone::Amber),
                Phase::NotInstalled => self.set_status("Not installed", Tone::Dim),
            }
        }

        let (label, enabled) = match phase {
            Phase::InstalledStarting => ("Starting…", false),
            Phase::InstalledRunning => ("Open CraftBot", true),
            Phase::InstalledStopped => ("Start CraftBot", true),
            Phase::NotInstalled => ("Install CraftBot", true),
        };
        ui.set_primary_label(label.into());
        ui.set_primary_enabled(enabled && !busy);

        let installed = !matches!(phase, Phase::NotInstalled);
        let running = matches!(phase, Phase::InstalledRunning | Phase::InstalledStarting);
        ui.set_stop_enabled(running && !busy);
        ui.set_repair_enabled(installed && !busy);
        ui.set_uninstall_enabled(installed && !busy);
        ui.set_change_enabled(!installed && !busy);

        // Any busy stage gets a bar; a measured download upgrades it to a
        // real percentage. Never over the top of a live download, though.
        let starting = matches!(phase, Phase::InstalledStarting);
        if busy || starting {
            let measured_recently = self
                .last_measured
                .get()
                .map(|t| t.elapsed() < MEASURED_GRACE)
                .unwrap_or(false);
            if !measured_recently {
                ui.set_progress_visible(true);
                ui.set_progress_indeterminate(true);
            }
        } else if ui.get_progress_visible() {
            ui.set_progress_visible(false);
            ui.set_progress(0.0);
        }

        *self.snapshot.borrow_mut() = Some(snap);
    }

    // ── Small helpers ───────────────────────────────────────────────────

    fn show_target(&self) {
        let text = self.target_dir.borrow().display().to_string();
        self.ui().set_install_path(paths::elide(&text, 46).into());
    }

    fn hold_status(&self, for_how_long: Duration) {
        self.status_hold.set(Some(Instant::now() + for_how_long));
    }

    fn set_status(&self, text: &str, tone: Tone) {
        let ui = self.ui();
        let palette = ui.global::<Palette>();
        let color = match tone {
            Tone::Dim => palette.get_text_dim(),
            Tone::Green => palette.get_green(),
            Tone::Amber => palette.get_amber(),
            Tone::Red => palette.get_red(),
        };
        ui.set_status(text.into());
        ui.set_status_color(color);
    }
}

#[derive(Clone, Copy)]
enum Tone {
    Dim,
    Green,
    Amber,
    Red,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn elide_keeps_both_ends() {
        let p = "C:\\Users\\someone\\AppData\\Local\\Programs\\CraftBot";
        let e = paths::elide(p, 20);
        assert!(e.starts_with("C:\\Users"));
        assert!(e.ends_with("CraftBot"));
        assert!(e.contains("..."));
        assert_eq!(paths::elide("short", 20), "short");
    }

    #[test]
    fn ansi_is_stripped() {
        assert_eq!(
            logger::strip_ansi("\x1b[38;2;255;79;24m▸\x1b[0m hi"),
            "▸ hi"
        );
    }

    #[test]
    fn meaningful_lines() {
        assert_eq!(craftbot::meaningful("═══════════"), None);
        assert_eq!(craftbot::meaningful("  "), None);
        assert_eq!(
            craftbot::meaningful("  ▸ STEP 1/3  Installing dependencies"),
            Some("STEP 1/3  Installing dependencies".into())
        );
    }

    #[test]
    fn extract_handles_wrapper_dir() {
        let tmp =
            std::env::temp_dir().join(format!("craftbot-launcher-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let zip_path = tmp.join("src.zip");
        {
            let f = std::fs::File::create(&zip_path).unwrap();
            let mut w = zip::ZipWriter::new(f);
            let opts = zip::write::SimpleFileOptions::default();
            w.start_file("CraftBot-1.0/run.py", opts).unwrap();
            std::io::Write::write_all(&mut w, b"print('hi')\n").unwrap();
            w.start_file("CraftBot-1.0/app/__init__.py", opts).unwrap();
            w.finish().unwrap();
        }
        let target = tmp.join("install");
        let root = payload::extract(&zip_path, &target).unwrap();
        assert!(root.join("run.py").is_file());
        assert!(root.ends_with("CraftBot-1.0"));
        payload::mark_managed(&root).unwrap();
        assert!(root.join(paths::MANAGED_MARKER).is_file());
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn version_is_baked_in() {
        assert!(!payload::VERSION.is_empty());
        assert!(payload::download_url().contains("CraftBot-src.zip"));
    }
}
