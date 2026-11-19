//! Checks that run before anything is downloaded.
//!
//! The dependency set CraftBot installs has a minimum macOS: its compiled
//! wheels are built for it. Finding that out an hour into a download helps
//! no one, so the launcher refuses up front, in plain words.

/// The oldest macOS CraftBot supports. packaging/macos/bundle.sh reads this
/// line for the bundle's LSMinimumSystemVersion, so the two cannot drift.
pub const MIN_MACOS: &str = "12.0";

/// Ok when this machine can run CraftBot; otherwise the message to show.
pub fn check() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        if let Some(found) = macos_version() {
            return check_macos(&found);
        }
    }
    Ok(())
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn check_macos(found: &str) -> Result<(), String> {
    match (numbers(found), numbers(MIN_MACOS)) {
        (Some(have), Some(need)) if have < need => Err(format!(
            "CraftBot needs macOS {MIN_MACOS} or later. This Mac has macOS {found}."
        )),
        _ => Ok(()),
    }
}

fn numbers(v: &str) -> Option<(u32, u32)> {
    let mut parts = v.trim().split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next().map_or(Some(0), |p| p.parse().ok())?;
    Some((major, minor))
}

/// The product version, e.g. "15.1", from `kern.osproductversion`.
#[cfg(target_os = "macos")]
fn macos_version() -> Option<String> {
    let name = c"kern.osproductversion";
    let mut buf = [0u8; 64];
    let mut len = buf.len();
    // SAFETY: `buf` and `len` describe a valid writable buffer.
    let rc = unsafe {
        libc::sysctlbyname(
            name.as_ptr(),
            buf.as_mut_ptr().cast(),
            &mut len,
            std::ptr::null_mut(),
            0,
        )
    };
    if rc != 0 {
        return None;
    }
    let text = &buf[..len.min(buf.len())];
    let end = text.iter().position(|&b| b == 0).unwrap_or(text.len());
    Some(String::from_utf8_lossy(&text[..end]).trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn macos_versions_below_the_minimum_are_refused() {
        assert!(check_macos("11.7.10").is_err());
        assert!(check_macos("12.0").is_ok());
        assert!(check_macos("12.7.6").is_ok());
        assert!(check_macos("26.1").is_ok());
        assert!(check_macos("garbage").is_ok());
        let msg = check_macos("11.2").unwrap_err();
        assert!(msg.contains("macOS 12.0 or later"));
        assert!(msg.contains("11.2"));
    }

    #[test]
    fn this_machine_passes() {
        // CI runs on supported systems only.
        assert!(check().is_ok());
    }
}
