//! HTTP downloads with progress. Synchronous on purpose: every caller is
//! already on the worker thread, and a blocking read loop is the simplest
//! thing that reports bytes as they arrive.

use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::path::Path;
use std::time::Duration;

const USER_AGENT: &str = concat!("CraftBotInstaller/", env!("CARGO_PKG_VERSION"));

pub type Progress<'a> = &'a mut dyn FnMut(u64, Option<u64>);

fn agent() -> Result<ureq::Agent, String> {
    let builder = ureq::AgentBuilder::new()
        .user_agent(USER_AGENT)
        .try_proxy_from_env(true)
        .timeout_connect(Duration::from_secs(30))
        // Reads are bounded per call, not per download: a 100 MB file on a
        // slow link legitimately takes minutes.
        .timeout_read(Duration::from_secs(120))
        .redirects(10);
    // Loading a snapshot of Windows' root store misses roots fetched on demand
    // on clean PCs. Schannel performs the normal Windows chain validation and
    // respects locally installed enterprise CAs without weakening verification.
    #[cfg(windows)]
    let builder = builder.tls_connector(std::sync::Arc::new(
        native_tls::TlsConnector::new()
            .map_err(|e| format!("cannot initialize Windows TLS: {e}"))?,
    ));
    Ok(builder.build())
}

/// Runtime pins carry a digest. Check it before anything can execute.
pub fn verified_to_file(
    url: &str,
    dest: &Path,
    sha256: &str,
    progress: Progress,
) -> Result<(), String> {
    for attempt in 0..3 {
        match to_file(url, dest, progress) {
            Ok(()) => return verify_sha256(dest, sha256),
            Err(e) if attempt == 2 => return Err(e),
            Err(_) => std::thread::sleep(Duration::from_secs(attempt + 1)),
        }
    }
    unreachable!()
}

fn verify_sha256(path: &Path, expected: &str) -> Result<(), String> {
    let mut source = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let mut digest = Sha256::new();
    let mut buf = [0; 256 * 1024];
    loop {
        let count = source.read(&mut buf).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        digest.update(&buf[..count]);
    }
    if format!("{:x}", digest.finalize()) != expected {
        let _ = std::fs::remove_file(path);
        return Err(format!(
            "SHA-256 verification failed for {}",
            path.display()
        ));
    }
    Ok(())
}

/// Download `url` to `dest`, writing to a `.part` file first so a partial
/// download is never mistaken for a finished one. `progress` is called with
/// (bytes so far, total if the server said).
pub fn to_file(url: &str, dest: &Path, progress: Progress) -> Result<(), String> {
    let resp = agent()?.get(url).call().map_err(|e| describe(url, e))?;
    let total = resp
        .header("Content-Length")
        .and_then(|v| v.trim().parse::<u64>().ok());

    let part = dest.with_extension(match dest.extension().and_then(|e| e.to_str()) {
        Some(ext) => format!("{ext}.part"),
        None => "part".to_string(),
    });
    if let Some(dir) = dest.parent() {
        std::fs::create_dir_all(dir)
            .map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    }
    let mut file = std::fs::File::create(&part)
        .map_err(|e| format!("cannot write {}: {e}", part.display()))?;

    let mut reader = resp.into_reader();
    let mut buf = vec![0u8; 256 * 1024];
    let mut read: u64 = 0;
    progress(0, total);
    loop {
        let n = reader
            .read(&mut buf)
            .map_err(|e| format!("download interrupted: {e}"))?;
        if n == 0 {
            break;
        }
        file.write_all(&buf[..n])
            .map_err(|e| format!("write failed: {e}"))?;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn corrupted_download_is_rejected_and_removed() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("runtime");
        std::fs::write(&file, b"truncated").unwrap();
        assert!(verify_sha256(&file, &"0".repeat(64)).is_err());
        assert!(!file.exists());
    }

    #[test]
    fn complete_download_matches_digest() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("runtime");
        std::fs::write(&file, b"abc").unwrap();
        assert!(verify_sha256(
            &file,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        .is_ok());
    }
}
