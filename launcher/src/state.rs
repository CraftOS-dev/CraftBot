//! What is CraftBot doing right now? Polled about once a second from a
//! worker thread (see main.rs); the window only ever renders the latest
//! snapshot.
//!
//! The rules are the ones the Tk window used, which came from the frozen
//! installer's state machine:
//!
//! * installed  — a launcher record exists AND its tree and interpreter do;
//! * running    — `craftbot.pid` names a live process;
//! * ready      — the agent has written `.agent-ready` for this run. A live
//!   PID is not a usable CraftBot: run.py spends a while initialising, and
//!   offering "Open CraftBot" before the marker exists sends the user to a
//!   tab that cannot serve yet.

use crate::paths;
use crate::record::InstallRecord;
use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    NotInstalled,
    InstalledStopped,
    InstalledStarting,
    InstalledRunning,
}

#[derive(Debug, Clone)]
pub struct Snapshot {
    pub phase: Phase,
    pub pid: Option<u32>,
    pub record: Option<InstallRecord>,
}

pub fn poll() -> Snapshot {
    let record = InstallRecord::load();
    let Some(rec) = record.as_ref() else {
        return Snapshot {
            phase: Phase::NotInstalled,
            pid: None,
            record: None,
        };
    };
    let pid = read_pid(&paths::pid_file(rec.dir()));
    let running = pid.map(pid_alive).unwrap_or(false);
    if !running {
        return Snapshot {
            phase: Phase::InstalledStopped,
            pid: None,
            record,
        };
    }
    let ready = paths::agent_ready_file().is_file();
    Snapshot {
        phase: if ready {
            Phase::InstalledRunning
        } else {
            Phase::InstalledStarting
        },
        pid,
        record,
    }
}

fn read_pid(path: &Path) -> Option<u32> {
    std::fs::read_to_string(path).ok()?.trim().parse().ok()
}

#[cfg(unix)]
pub fn pid_alive(pid: u32) -> bool {
    // kill(pid, 0): no signal is sent, but the permission and existence
    // checks still run. ESRCH means gone; EPERM means alive but not ours.
    let rc = unsafe { libc::kill(pid as libc::pid_t, 0) };
    if rc == 0 {
        return true;
    }
    std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

#[cfg(windows)]
pub fn pid_alive(pid: u32) -> bool {
    use windows_sys::Win32::Foundation::{CloseHandle, STILL_ACTIVE};
    use windows_sys::Win32::System::Threading::{
        GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return false;
        }
        let mut code: u32 = 0;
        let ok = GetExitCodeProcess(handle, &mut code);
        CloseHandle(handle);
        ok != 0 && code == STILL_ACTIVE as u32
    }
}
