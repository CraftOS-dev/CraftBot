//! The launcher's log file.
//!
//! The launcher is a windowed program: before its window is up, and for
//! everything a subprocess prints, a file is the only channel that survives.
//! Everything goes here — launcher events, the full output of `craftbot.py
//! install`, errors — so "Open log" always has something useful to show.

use std::fs::{File, OpenOptions};
use std::io::Write;
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

static LOG: OnceLock<Mutex<Option<File>>> = OnceLock::new();

fn handle() -> &'static Mutex<Option<File>> {
    LOG.get_or_init(|| {
        let path = crate::paths::launcher_log();
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .ok();
        Mutex::new(file)
    })
}

/// Append one line, timestamped. Never fails; a log that cannot be written
/// must not stop an install.
pub fn log(line: &str) {
    if let Ok(mut guard) = handle().lock() {
        if let Some(file) = guard.as_mut() {
            let _ = writeln!(file, "{}  {}", stamp(), line);
        }
    }
}

/// Append raw subprocess output (already a complete line).
pub fn raw(line: &str) {
    if let Ok(mut guard) = handle().lock() {
        if let Some(file) = guard.as_mut() {
            let _ = writeln!(file, "    {line}");
        }
    }
}

fn stamp() -> String {
    // Wall-clock seconds since the epoch, rendered as HH:MM:SS UTC. Enough to
    // correlate with craftbot.log without pulling in a date crate.
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (h, m, s) = ((secs / 3600) % 24, (secs / 60) % 60, secs % 60);
    let days = secs / 86_400;
    // Civil date from days since epoch (Howard Hinnant's algorithm).
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let mo = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if mo <= 2 { y + 1 } else { y };
    format!("{y:04}-{mo:02}-{d:02} {h:02}:{m:02}:{s:02}Z")
}

/// Strip ANSI colour codes: the Python side colours its output for a
/// terminal, and the status line has nowhere to put escape sequences.
pub fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\u{1b}' {
            // CSI: ESC [ ... final byte in 0x40..=0x7E
            if chars.peek() == Some(&'[') {
                chars.next();
                for n in chars.by_ref() {
                    if ('\u{40}'..='\u{7e}').contains(&n) {
                        break;
                    }
                }
            }
            continue;
        }
        out.push(c);
    }
    out
}
