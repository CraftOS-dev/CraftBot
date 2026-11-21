//! HTTP downloads with progress. Synchronous on purpose: every caller is
//! already on the worker thread, and a blocking read loop is the simplest
//! thing that reports bytes as they arrive.
//!
//! Every request goes through the same three steps:
//!   1. `CRAFTBOT_MIRRORS` may rewrite the URL (see [`mirror`]);
//!   2. the proxy is chosen for that URL (see proxy.rs: proxy variables,
//!      then the operating system's proxy setting);
//!   3. transient failures are retried, three attempts in all, with backoff.
//!
//! Checksums are enforced whatever the URL was rewritten to.

use crate::logger;
use crate::proxy;
use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::path::Path;
use std::time::Duration;

const USER_AGENT: &str = concat!("CraftBotInstaller/", env!("CARGO_PKG_VERSION"));

/// Attempts per download, and the pause before each retry.
const ATTEMPTS: u32 = 3;
const BACKOFF: [Duration; 2] = [Duration::from_secs(2), Duration::from_secs(6)];

/// Semicolon-separated `prefix=replacement` pairs; the first prefix that
/// matches a URL is replaced. The Python side reads the same variable.
pub const MIRRORS_ENV: &str = "CRAFTBOT_MIRRORS";

pub type Progress<'a> = &'a mut dyn FnMut(u64, Option<u64>);

/// Why an attempt failed, and whether trying again could help.
enum Failure {
    /// Network trouble, a server error, a truncated body, a digest that did
    /// not match what was published: worth another attempt.
    Transient(String),
    /// The server answered definitively (404, 403...), or the disk failed.
    Permanent(String),
}

impl Failure {
    fn message(self) -> String {
        match self {
            Failure::Transient(m) | Failure::Permanent(m) => m,
        }
    }
}

/// `url` after `CRAFTBOT_MIRRORS` rewriting.
pub fn mirror(url: &str) -> String {
    match std::env::var(MIRRORS_ENV) {
        Ok(spec) => rewrite(url, &spec),
        Err(_) => url.to_string(),
    }
}

fn rewrite(url: &str, spec: &str) -> String {
    for pair in spec.split(';') {
        let Some((prefix, replacement)) = pair.split_once('=') else {
            continue;
        };
        let (prefix, replacement) = (prefix.trim(), replacement.trim());
        if prefix.is_empty() {
            continue;
        }
        if let Some(rest) = url.strip_prefix(prefix) {
            return format!("{replacement}{rest}");
        }
    }
    url.to_string()
}

fn agent(proxy: Option<&str>) -> Result<ureq::Agent, Failure> {
    let mut builder = ureq::AgentBuilder::new()
        .user_agent(USER_AGENT)
        // proxy.rs decides, per URL, including NO_PROXY and the system
        // setting, which ureq's own environment lookup does not know about.
        .try_proxy_from_env(false)
        .timeout_connect(Duration::from_secs(30))
        // Reads are bounded per call, not per download: a 100 MB file on a
        // slow link legitimately takes minutes.
        .timeout_read(Duration::from_secs(120))
        .redirects(10);
    if let Some(server) = proxy {
        let p = ureq::Proxy::new(server).map_err(|e| {
            Failure::Permanent(format!(
                "The proxy setting {} is not usable: {e}",
                proxy::redact(server)
            ))
        })?;
        builder = builder.proxy(p);
    }
    // A fresh Windows installation populates trusted roots on demand.
    // Reading its current store into rustls misses that Windows chain-building
    // step and rejects legitimate GitHub downloads with UnknownIssuer.
    // Schannel retains the OS certificate and hostname validation policies.
    #[cfg(windows)]
    let builder = builder.tls_connector(std::sync::Arc::new(
        native_tls::TlsConnector::new()
            .map_err(|e| Failure::Permanent(format!("cannot initialize Windows TLS: {e}")))?,
    ));
    Ok(builder.build())
}

/// One GET. Errors read as a plain sentence first (the status line), then
/// the technical detail.
fn get(url: &str, accept: Option<&str>) -> Result<ureq::Response, Failure> {
    let proxy = proxy::for_url(url);
    let host = proxy::host_of(url).unwrap_or_else(|| url.to_string());
    let via = proxy
        .as_deref()
        .map(|p| format!(" through the proxy {}", proxy::redact(p)))
        .unwrap_or_default();
    let mut request = agent(proxy.as_deref())?.get(url);
    if let Some(accept) = accept {
        request = request.set("Accept", accept);
    }
    request
        .call()
        .map_err(|e| match e {
            ureq::Error::Status(code, resp) => {
                let text = format!("{url}: HTTP {code} {}", resp.status_text());
                if code >= 500 || code == 408 || code == 429 {
                    Failure::Transient(format!(
                        "{host} is not answering (HTTP {code}).\n{text}"
                    ))
                } else {
                    Failure::Permanent(text)
                }
            }
            ureq::Error::Transport(t) => Failure::Transient(format!(
                "Could not connect to {host}{via}. Check the internet connection or proxy settings.\n{t}"
            )),
        })
}

/// Run `attempt` up to [`ATTEMPTS`] times, pausing between transient
/// failures.
fn with_retries<T>(
    what: &str,
    mut attempt: impl FnMut() -> Result<T, Failure>,
) -> Result<T, String> {
    let mut n = 0;
    loop {
        match attempt() {
            Ok(v) => return Ok(v),
            Err(Failure::Transient(e)) if (n as usize) < BACKOFF.len() => {
                let pause = BACKOFF[n as usize];
                n += 1;
                logger::log(&format!(
                    "{what}: attempt {n} of {ATTEMPTS} failed ({e}); retrying in {}s",
                    pause.as_secs()
                ));
                std::thread::sleep(pause);
            }
            Err(e) => return Err(e.message()),
        }
    }
}

/// A small text file (a published checksum), with retries.
pub fn fetch_text(url: &str) -> Result<String, String> {
    let url = mirror(url);
    logger::log(&format!("fetch: {url}"));
    with_retries(&url, || {
        let mut text = String::new();
        get(&url, None)?
            .into_reader()
            .take(64 * 1024)
            .read_to_string(&mut text)
            .map_err(|e| Failure::Transient(format!("{url}: {e}")))?;
        Ok(text)
    })
}

/// Download `url` to `dest` and check its SHA-256 before anything can use
/// it. A mismatch is retried too: a mirror or cache can hand out a stale or
/// partial file once and the right one next time.
pub fn verified_to_file(
    url: &str,
    dest: &Path,
    sha256: &str,
    progress: Progress,
) -> Result<(), String> {
    let url = mirror(url);
    logger::log(&format!("download: {url}"));
    with_retries(&url, || {
        to_file_once(&url, dest, progress)?;
        verify_sha256(dest, sha256).map_err(Failure::Transient)
    })
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
    if !format!("{:x}", digest.finalize()).eq_ignore_ascii_case(expected) {
        let _ = std::fs::remove_file(path);
        return Err(format!(
            "SHA-256 verification failed for {}",
            path.display()
        ));
    }
    Ok(())
}

/// One attempt: download to a `.part` file first so a partial download is
/// never mistaken for a finished one. `progress` is called with (bytes so
/// far, total if the server said).
fn to_file_once(url: &str, dest: &Path, progress: Progress) -> Result<(), Failure> {
    let resp = get(url, None)?;
    let total = resp
        .header("Content-Length")
        .and_then(|v| v.trim().parse::<u64>().ok());

    let part = dest.with_extension(match dest.extension().and_then(|e| e.to_str()) {
        Some(ext) => format!("{ext}.part"),
        None => "part".to_string(),
    });
    if let Some(dir) = dest.parent() {
        std::fs::create_dir_all(dir)
            .map_err(|e| Failure::Permanent(format!("cannot create {}: {e}", dir.display())))?;
    }
    let mut file = std::fs::File::create(&part)
        .map_err(|e| Failure::Permanent(format!("cannot write {}: {e}", part.display())))?;

    let mut reader = resp.into_reader();
    let mut buf = vec![0u8; 256 * 1024];
    let mut read: u64 = 0;
    progress(0, total);
    loop {
        let n = reader
            .read(&mut buf)
            .map_err(|e| Failure::Transient(format!("download interrupted: {e}")))?;
        if n == 0 {
            break;
        }
        file.write_all(&buf[..n])
            .map_err(|e| Failure::Permanent(format!("write failed: {e}")))?;
        read += n as u64;
        progress(read, total);
    }
    file.flush()
        .map_err(|e| Failure::Permanent(format!("write failed: {e}")))?;
    drop(file);

    if let Some(t) = total {
        if read != t {
            let _ = std::fs::remove_file(&part);
            return Err(Failure::Transient(format!(
                "download incomplete: {read} of {t} bytes"
            )));
        }
    }
    std::fs::rename(&part, dest)
        .map_err(|e| Failure::Permanent(format!("cannot finish {}: {e}", dest.display())))
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
            "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"
        )
        .is_ok());
    }

    #[test]
    fn mirrors_rewrite_the_first_matching_prefix() {
        let spec = "https://github.com/=https://mirror.example/github/; \
                    https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/;\
                    https://github.com/CraftOS-dev/=https://never.example/";
        assert_eq!(
            rewrite(
                "https://github.com/CraftOS-dev/CraftBot/releases/download/v1/CraftBot-src.zip",
                spec
            ),
            "https://mirror.example/github/CraftOS-dev/CraftBot/releases/download/v1/CraftBot-src.zip"
        );
        assert_eq!(
            rewrite("https://nodejs.org/dist/v22.0.0/node.tar.gz", spec),
            "https://npmmirror.com/mirrors/node/v22.0.0/node.tar.gz"
        );
        assert_eq!(
            rewrite("https://example.org/file?a=b", spec),
            "https://example.org/file?a=b"
        );
        assert_eq!(rewrite("https://x/", ";;=nothing;garbage"), "https://x/");
        assert_eq!(
            rewrite("https://x/a", "https://x/=https://y/?k=v&"),
            "https://y/?k=v&a"
        );
    }

    #[test]
    fn retries_stop_on_permanent_failures() {
        let mut calls = 0;
        let r: Result<(), String> = with_retries("t", || {
            calls += 1;
            Err(Failure::Permanent("HTTP 404".into()))
        });
        assert!(r.is_err());
        assert_eq!(calls, 1);
    }
}
