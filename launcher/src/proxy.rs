//! Which proxy, if any, a download should go through.
//!
//! ureq only reads proxy variables, and not NO_PROXY, so the choice is made
//! here, per URL, in the order curl and pip use:
//!
//!   1. the proxy variables: `HTTPS_PROXY` / `HTTP_PROXY` for the URL's
//!      scheme, then `ALL_PROXY` (either case), with `NO_PROXY` exceptions;
//!   2. otherwise the operating system's setting: Windows Internet Options,
//!      macOS Network settings (`scutil --proxy`), GNOME's proxy settings,
//!      each with its own exception list.
//!
//! Automatic configuration scripts (PAC) need a JavaScript engine to
//! evaluate; they are logged, and the proxy variables are the way around
//! them. Only HTTP proxies are supported (SOCKS is skipped and logged).

use crate::logger;
use std::sync::OnceLock;

/// The proxy URL (`http://host:port`) for `url`, or None to connect directly.
pub fn for_url(url: &str) -> Option<String> {
    let host = host_of(url)?;
    let https = url.to_ascii_lowercase().starts_with("https://");

    if let Some(server) = from_env(https) {
        let no_proxy = env_any(&["NO_PROXY", "no_proxy"]).unwrap_or_default();
        if bypassed(&host, no_proxy.split(',')) {
            return None;
        }
        return Some(server);
    }

    let system = system()?;
    if bypassed(&host, system.bypass.iter().map(String::as_str)) {
        return None;
    }
    let server = if https {
        system.https.clone().or_else(|| system.http.clone())
    } else {
        system.http.clone()
    }?;
    Some(server)
}

fn env_any(names: &[&str]) -> Option<String> {
    names
        .iter()
        .filter_map(|n| std::env::var(n).ok())
        .map(|v| v.trim().to_string())
        .find(|v| !v.is_empty())
}

fn from_env(https: bool) -> Option<String> {
    let scheme = if https {
        env_any(&["HTTPS_PROXY", "https_proxy"])
    } else {
        env_any(&["HTTP_PROXY", "http_proxy"])
    };
    scheme
        .or_else(|| env_any(&["ALL_PROXY", "all_proxy"]))
        .and_then(|v| normalize(&v))
}

/// `host:port` or `http://host:port` → `http://host:port`. SOCKS and
/// anything else ureq cannot speak are dropped (and logged).
fn normalize(server: &str) -> Option<String> {
    let s = server.trim().trim_end_matches('/');
    if s.is_empty() {
        return None;
    }
    match s.split_once("://") {
        None => Some(format!("http://{s}")),
        Some((scheme, _)) if scheme.eq_ignore_ascii_case("http") => Some(s.to_string()),
        Some((scheme, _)) => {
            logger::log(&format!(
                "proxy {}: {scheme} proxies are not supported; connecting directly",
                redact(s)
            ));
            None
        }
    }
}

/// The host part of a URL, lowercased, without user info or port.
pub fn host_of(url: &str) -> Option<String> {
    let rest = url.split_once("://")?.1;
    let authority = rest.split(['/', '?', '#']).next()?;
    let authority = authority.rsplit_once('@').map_or(authority, |(_, h)| h);
    let host = if let Some(v6) = authority.strip_prefix('[') {
        v6.split(']').next()?
    } else {
        authority.split(':').next()?
    };
    (!host.is_empty()).then(|| host.to_ascii_lowercase())
}

/// A proxy URL fit for a log or a message: any password replaced.
pub fn redact(server: &str) -> String {
    match server.split_once("://") {
        Some((scheme, rest)) => match rest.rsplit_once('@') {
            Some((_, host)) => format!("{scheme}://***@{host}"),
            None => server.to_string(),
        },
        None => match server.rsplit_once('@') {
            Some((_, host)) => format!("***@{host}"),
            None => server.to_string(),
        },
    }
}

/// Whether any exception pattern covers `host`. Understands the NO_PROXY
/// forms (`*`, `example.com`, `.example.com`, `host:port`) and the
/// Windows/macOS forms (`*.example.com`, `10.*`, `<local>`).
fn bypassed<'a>(host: &str, patterns: impl Iterator<Item = &'a str>) -> bool {
    patterns.into_iter().any(|p| pattern_matches(host, p))
}

fn pattern_matches(host: &str, pattern: &str) -> bool {
    let mut p = pattern.trim().to_ascii_lowercase();
    if p.is_empty() {
        return false;
    }
    if p == "*" {
        return true;
    }
    if p == "<local>" {
        return !host.contains('.') && !host.contains(':');
    }
    // A scheme or a port does not change which host is meant.
    if let Some((_, rest)) = p.split_once("://") {
        p = rest.to_string();
    }
    if let Some((h, port)) = p.rsplit_once(':') {
        if !h.contains(':') && port.chars().all(|c| c.is_ascii_digit()) {
            p = h.to_string();
        }
    }
    let p = p.trim_matches(|c| c == '[' || c == ']');
    if p.contains('*') {
        return glob(host, p);
    }
    let p = p.trim_start_matches('.');
    host == p || host.ends_with(&format!(".{p}"))
}

/// `*` matches any run of characters; everything else is literal.
fn glob(text: &str, pattern: &str) -> bool {
    let parts: Vec<&str> = pattern.split('*').collect();
    let (first, last) = (parts[0], parts[parts.len() - 1]);
    if !text.starts_with(first) || text.len() < first.len() + last.len() {
        return false;
    }
    let mut pos = first.len();
    for middle in &parts[1..parts.len() - 1] {
        match text[pos..].find(middle) {
            Some(i) => pos += i + middle.len(),
            None => return false,
        }
    }
    text.len() - last.len() >= pos && text.ends_with(last)
}

#[derive(Debug, Default, Clone, PartialEq)]
struct SystemProxy {
    http: Option<String>,
    https: Option<String>,
    bypass: Vec<String>,
}

/// The OS setting, read once per run.
fn system() -> Option<&'static SystemProxy> {
    static CACHE: OnceLock<Option<SystemProxy>> = OnceLock::new();
    CACHE
        .get_or_init(|| {
            let found = read_system();
            if let Some(p) = &found {
                logger::log(&format!(
                    "system proxy: https={:?} http={:?} exceptions={:?}",
                    p.https, p.http, p.bypass
                ));
            }
            found
        })
        .as_ref()
}

#[cfg(windows)]
fn read_system() -> Option<SystemProxy> {
    use windows_sys::Win32::System::Registry::{
        RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_DWORD, RRF_RT_REG_SZ,
    };
    const KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings";
    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }
    let key = wide(KEY);
    let dword = |name: &str| -> Option<u32> {
        let name = wide(name);
        let mut value: u32 = 0;
        let mut size = std::mem::size_of::<u32>() as u32;
        // SAFETY: the buffers outlive the call and `size` matches `value`.
        let rc = unsafe {
            RegGetValueW(
                HKEY_CURRENT_USER,
                key.as_ptr(),
                name.as_ptr(),
                RRF_RT_REG_DWORD,
                std::ptr::null_mut(),
                (&mut value as *mut u32).cast(),
                &mut size,
            )
        };
        (rc == 0).then_some(value)
    };
    let string = |name: &str| -> Option<String> {
        let name = wide(name);
        let mut size: u32 = 0;
        // SAFETY: a null buffer asks only for the size.
        let rc = unsafe {
            RegGetValueW(
                HKEY_CURRENT_USER,
                key.as_ptr(),
                name.as_ptr(),
                RRF_RT_REG_SZ,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut size,
            )
        };
        if rc != 0 || size == 0 {
            return None;
        }
        let mut buf = vec![0u16; (size as usize).div_ceil(2) + 1];
        let mut size = (buf.len() * 2) as u32;
        // SAFETY: `size` is the byte length of `buf`.
        let rc = unsafe {
            RegGetValueW(
                HKEY_CURRENT_USER,
                key.as_ptr(),
                name.as_ptr(),
                RRF_RT_REG_SZ,
                std::ptr::null_mut(),
                buf.as_mut_ptr().cast(),
                &mut size,
            )
        };
        if rc != 0 {
            return None;
        }
        let len = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
        Some(String::from_utf16_lossy(&buf[..len]))
    };

    if let Some(pac) = string("AutoConfigURL").filter(|s| !s.trim().is_empty()) {
        logger::log(&format!(
            "system proxy uses a configuration script ({pac}), which the installer cannot \
             evaluate; set HTTPS_PROXY if downloads fail"
        ));
    }
    if dword("ProxyEnable") != Some(1) {
        return None;
    }
    let mut proxy = parse_windows(&string("ProxyServer")?);
    if let Some(over) = string("ProxyOverride") {
        proxy.bypass = over.split(';').map(str::to_string).collect();
    }
    (proxy.http.is_some() || proxy.https.is_some()).then_some(proxy)
}

/// `host:port` (every scheme) or `http=h:p;https=h:p;socks=h:p`.
#[cfg_attr(not(windows), allow(dead_code))]
fn parse_windows(server: &str) -> SystemProxy {
    let mut proxy = SystemProxy::default();
    if !server.contains('=') {
        proxy.http = normalize(server);
        proxy.https = proxy.http.clone();
        return proxy;
    }
    for part in server.split(';') {
        let Some((scheme, addr)) = part.split_once('=') else {
            continue;
        };
        match scheme.trim().to_ascii_lowercase().as_str() {
            "http" => proxy.http = normalize(addr),
            "https" => proxy.https = normalize(addr),
            _ => {}
        }
    }
    proxy
}

#[cfg(target_os = "macos")]
fn read_system() -> Option<SystemProxy> {
    let out = std::process::Command::new("/usr/sbin/scutil")
        .arg("--proxy")
        .output()
        .ok()?;
    let proxy = parse_scutil(&String::from_utf8_lossy(&out.stdout));
    (proxy.http.is_some() || proxy.https.is_some()).then_some(proxy)
}

/// `scutil --proxy`: a `key : value` dictionary, ExceptionsList an array.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn parse_scutil(text: &str) -> SystemProxy {
    let mut map = std::collections::HashMap::new();
    let mut bypass = Vec::new();
    let mut in_exceptions = false;
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with("ExceptionsList") {
            in_exceptions = true;
            continue;
        }
        if in_exceptions {
            if line.starts_with('}') {
                in_exceptions = false;
            } else if let Some((_, v)) = line.split_once(" : ") {
                bypass.push(v.trim().to_string());
            }
            continue;
        }
        if let Some((k, v)) = line.split_once(" : ") {
            map.insert(k.trim().to_string(), v.trim().to_string());
        }
    }
    if map.get("ProxyAutoConfigEnable").map(String::as_str) == Some("1") {
        logger::log(
            "system proxy uses a configuration script, which the installer cannot evaluate; \
             set HTTPS_PROXY if downloads fail",
        );
    }
    let server = |prefix: &str| -> Option<String> {
        if map.get(&format!("{prefix}Enable")).map(String::as_str) != Some("1") {
            return None;
        }
        let host = map.get(&format!("{prefix}Proxy"))?;
        match map.get(&format!("{prefix}Port")) {
            Some(port) => normalize(&format!("{host}:{port}")),
            None => normalize(host),
        }
    };
    if map.get("ExcludeSimpleHostnames").map(String::as_str) == Some("1") {
        bypass.push("<local>".into());
    }
    SystemProxy {
        http: server("HTTP"),
        https: server("HTTPS"),
        bypass,
    }
}

#[cfg(all(unix, not(target_os = "macos")))]
fn read_system() -> Option<SystemProxy> {
    // GNOME (and the desktops built on it) keep the setting in gsettings and
    // do not export it to programs started from the desktop.
    let get = |schema: &str, key: &str| -> Option<String> {
        let out = std::process::Command::new("gsettings")
            .args(["get", schema, key])
            .stderr(std::process::Stdio::null())
            .output()
            .ok()?;
        out.status
            .success()
            .then(|| String::from_utf8_lossy(&out.stdout).trim().to_string())
    };
    let mode = get("org.gnome.system.proxy", "mode")?;
    if mode.trim_matches('\'') == "auto" {
        logger::log(
            "system proxy uses a configuration script, which the installer cannot evaluate; \
             set HTTPS_PROXY if downloads fail",
        );
    }
    if mode.trim_matches('\'') != "manual" {
        return None;
    }
    let server = |schema: &str| -> Option<String> {
        let host = get(schema, "host")?.trim_matches('\'').to_string();
        let port = get(schema, "port")?;
        if host.is_empty() || port == "0" {
            return None;
        }
        normalize(&format!("{host}:{port}"))
    };
    let bypass = get("org.gnome.system.proxy", "ignore-hosts")
        .map(|list| parse_gsettings_list(&list))
        .unwrap_or_default();
    let proxy = SystemProxy {
        http: server("org.gnome.system.proxy.http"),
        https: server("org.gnome.system.proxy.https"),
        bypass,
    };
    (proxy.http.is_some() || proxy.https.is_some()).then_some(proxy)
}

/// `['localhost', '127.0.0.0/8', '::1']` → the strings.
#[cfg_attr(not(all(unix, not(target_os = "macos"))), allow(dead_code))]
fn parse_gsettings_list(text: &str) -> Vec<String> {
    text.trim()
        .trim_start_matches("@as")
        .trim()
        .trim_start_matches('[')
        .trim_end_matches(']')
        .split(',')
        .map(|s| s.trim().trim_matches('\'').to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hosts_are_extracted() {
        assert_eq!(
            host_of("https://GitHub.com/a/b").as_deref(),
            Some("github.com")
        );
        assert_eq!(
            host_of("https://user:pw@mirror.example:8443/x?y").as_deref(),
            Some("mirror.example")
        );
        assert_eq!(host_of("http://[::1]:7925/").as_deref(), Some("::1"));
        assert_eq!(host_of("not a url"), None);
    }

    #[test]
    fn exception_patterns() {
        let h = "objects.githubusercontent.com";
        assert!(pattern_matches(h, "githubusercontent.com"));
        assert!(pattern_matches(h, ".githubusercontent.com"));
        assert!(pattern_matches(h, "*.githubusercontent.com"));
        assert!(pattern_matches(h, "*"));
        assert!(pattern_matches(h, "githubusercontent.com:443"));
        assert!(!pattern_matches(h, "usercontent.com.evil"));
        assert!(!pattern_matches(h, "hubusercontent.com"));
        assert!(pattern_matches("10.1.2.3", "10.*"));
        assert!(pattern_matches("intranet", "<local>"));
        assert!(!pattern_matches("github.com", "<local>"));
        assert!(!pattern_matches("github.com", ""));
    }

    #[test]
    fn proxy_servers_are_normalized() {
        assert_eq!(
            normalize("proxy:8080").as_deref(),
            Some("http://proxy:8080")
        );
        assert_eq!(
            normalize("http://u:p@proxy:8080/").as_deref(),
            Some("http://u:p@proxy:8080")
        );
        assert_eq!(normalize("socks5://proxy:1080"), None);
        assert_eq!(normalize(" "), None);
    }

    #[test]
    fn windows_proxy_server_forms() {
        let all = parse_windows("corp:3128");
        assert_eq!(all.https.as_deref(), Some("http://corp:3128"));
        assert_eq!(all.http.as_deref(), Some("http://corp:3128"));
        let split = parse_windows("http=web:80;https=secure:443;socks=s:1080");
        assert_eq!(split.http.as_deref(), Some("http://web:80"));
        assert_eq!(split.https.as_deref(), Some("http://secure:443"));
    }

    #[test]
    fn scutil_output_is_parsed() {
        let text = "<dictionary> {
  ExceptionsList : <array> {
    0 : *.local
    1 : 169.254/16
  }
  ExcludeSimpleHostnames : 1
  FTPPassive : 1
  HTTPEnable : 1
  HTTPPort : 8080
  HTTPProxy : proxy.corp
  HTTPSEnable : 1
  HTTPSPort : 8443
  HTTPSProxy : secure.corp
}";
        let p = parse_scutil(text);
        assert_eq!(p.http.as_deref(), Some("http://proxy.corp:8080"));
        assert_eq!(p.https.as_deref(), Some("http://secure.corp:8443"));
        assert_eq!(p.bypass, vec!["*.local", "169.254/16", "<local>"]);
        assert_eq!(
            parse_scutil("<dictionary> {\n  HTTPEnable : 0\n}"),
            SystemProxy::default()
        );
    }

    #[test]
    fn gsettings_lists() {
        assert_eq!(
            parse_gsettings_list("['localhost', '127.0.0.0/8', '::1']"),
            vec!["localhost", "127.0.0.0/8", "::1"]
        );
        assert!(parse_gsettings_list("@as []").is_empty());
    }

    #[test]
    fn credentials_never_reach_messages() {
        assert_eq!(redact("http://user:pw@proxy:8080"), "http://***@proxy:8080");
        assert_eq!(redact("http://proxy:8080"), "http://proxy:8080");
        assert_eq!(redact("u:p@proxy:1"), "***@proxy:1");
    }

    #[test]
    fn glob_matching() {
        assert!(glob("a.b.c", "a.*"));
        assert!(glob("a.b.c", "*.c"));
        assert!(glob("a.b.c", "a*c"));
        assert!(!glob("ab", "a*b*c"));
        assert!(!glob("a", "a*a"));
    }
}
