//! HTTP downloads with progress. Synchronous on purpose: every caller is
//! already on the worker thread, and a blocking read loop is the simplest
//! thing that reports bytes as they arrive.

use std::io::{Read, Write};
use std::path::Path;
use std::time::Duration;

const USER_AGENT: &str = concat!("CraftBotInstaller/", env!("CARGO_PKG_VERSION"));

pub type Progress<'a> = &'a mut dyn FnMut(u64, Option<u64>);

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .user_agent(USER_AGENT)
        .timeout_connect(Duration::from_secs(30))
        // Reads are bounded per call, not per download: a 100 MB file on a
        // slow link legitimately takes minutes.
        .timeout_read(Duration::from_secs(120))
        .redirects(10)
        .build()
}

/// Fetch a small JSON document (a GitHub release listing).
pub fn get_json(url: &str) -> Result<serde_json::Value, String> {
    let resp = agent()
        .get(url)
        .set("Accept", "application/vnd.github+json")
        .call()
        .map_err(|e| describe(url, e))?;
    resp.into_json().map_err(|e| format!("{url}: bad JSON: {e}"))
}

/// Download `url` to `dest`, writing to a `.part` file first so a partial
/// download is never mistaken for a finished one. `progress` is called with
/// (bytes so far, total if the server said).
pub fn to_file(url: &str, dest: &Path, progress: Progress) -> Result<(), String> {
    let resp = agent().get(url).call().map_err(|e| describe(url, e))?;
    let total = resp
        .header("Content-Length")
        .and_then(|v| v.trim().parse::<u64>().ok());

    let part = dest.with_extension(match dest.extension().and_then(|e| e.to_str()) {
        Some(ext) => format!("{ext}.part"),
        None => "part".to_string(),
    });
    if let Some(dir) = dest.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    }
    let mut file = std::fs::File::create(&part)
        .map_err(|e| format!("cannot write {}: {e}", part.display()))?;

    let mut reader = resp.into_reader();
    let mut buf = vec![0u8; 256 * 1024];
    let mut read: u64 = 0;
    progress(0, total);
    loop {
        let n = reader.read(&mut buf).map_err(|e| format!("download interrupted: {e}"))?;
        if n == 0 {
            break;
        }
        file.write_all(&buf[..n]).map_err(|e| format!("write failed: {e}"))?;
        read += n as u64;
        progress(read, total);
    }
    file.flush().map_err(|e| e.to_string())?;
    drop(file);

    if let Some(t) = total {
        if read != t {
            let _ = std::fs::remove_file(&part);
            return Err(format!("download incomplete: {read} of {t} bytes"));
        }
    }
    std::fs::rename(&part, dest).map_err(|e| format!("cannot finish {}: {e}", dest.display()))
}

fn describe(url: &str, e: ureq::Error) -> String {
    match e {
        ureq::Error::Status(code, resp) => {
            let text = resp.status_text().to_string();
            format!("{url}: HTTP {code} {text}")
        }
        ureq::Error::Transport(t) => format!("{url}: {t}"),
    }
}

pub fn mb(bytes: u64) -> String {
    format!("{:.0}", bytes as f64 / (1024.0 * 1024.0))
}
