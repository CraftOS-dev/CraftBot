//! Build script: compiles the Slint UI, pins the CraftBot version into the
//! binary, and (on Windows) embeds the icon.

use std::path::{Path, PathBuf};

fn main() {
    // ── Version ─────────────────────────────────────────────────────────
    // The launcher downloads the CraftBot release that matches its own
    // version, so the version has to be baked in. Resolution order:
    //   1. CRAFTBOT_VERSION in the environment (what release.yml sets from
    //      the git tag, e.g. "1.4.0").
    //   2. A VERSION file at the repository root (a local release build).
    //   3. "latest" — a dev build, which downloads the newest release.
    let version = std::env::var("CRAFTBOT_VERSION")
        .ok()
        .map(|v| v.trim().trim_start_matches('v').to_string())
        .filter(|v| !v.is_empty())
        .or_else(|| {
            std::fs::read_to_string(repo_root().join("VERSION"))
                .ok()
                .map(|v| v.trim().trim_start_matches('v').to_string())
                .filter(|v| !v.is_empty())
        })
        .unwrap_or_else(|| "latest".to_string());
    println!("cargo:rustc-env=CRAFTBOT_VERSION={version}");
    println!("cargo:rerun-if-env-changed=CRAFTBOT_VERSION");
    println!("cargo:rerun-if-changed={}", repo_root().join("VERSION").display());

    // ── UI ──────────────────────────────────────────────────────────────
    // One style everywhere. The window is drawn from primitives (rectangles,
    // text, touch areas), so the style only affects the few std-widgets used
    // and the default font; fluent's dark variant is closest to the design.
    let config = slint_build::CompilerConfiguration::new().with_style("fluent-dark".into());
    slint_build::compile_with_config("ui/app.slint", config).expect("Slint UI failed to compile");

    // ── Windows icon ────────────────────────────────────────────────────
    #[cfg(windows)]
    {
        let ico = Path::new("assets/craftbot_logo_1.ico");
        if ico.is_file() {
            let mut res = winresource::WindowsResource::new();
            res.set_icon(ico.to_str().unwrap());
            res.set("ProductName", "CraftBot Setup");
            res.set("FileDescription", "CraftBot Setup");
            res.set("LegalCopyright", "CraftOS");
            if let Err(e) = res.compile() {
                println!("cargo:warning=could not embed the Windows icon: {e}");
            }
        }
    }
    let _ = Path::new("assets");
}

/// The CraftBot repository root: this crate lives in `<repo>/launcher/`.
fn repo_root() -> PathBuf {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR");
    Path::new(&manifest)
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from(&manifest))
}
