# CraftBot launcher

The setup window: one native binary per platform, written in Rust with a
[Slint](https://slint.dev) UI. It replaces the CustomTkinter window that was
frozen with PyInstaller.

## Why it exists

The Tk installer was fine on Windows and unusable on macOS, and the reason
turned out not to be Tk. A PyInstaller *onefile* binary inside an `.app` is
two processes — a bootloader that unpacks, then a child that runs the Python
code. LaunchServices activates the bootloader; the window belongs to the
child. macOS shows two Dock icons, the process with the window is never the
active one, and Tk discards mouse presses that arrive while its app is
inactive. Taps were dropped, hover flickered, and the per-launch unpack was
scanned by Gatekeeper on every open.

A native binary is one process, no bootloader, no unpacking. It also needs
nothing on the user's machine: Slint draws its own widgets (no web engine,
no WebView2), and the binary is 8–15 MB.

## What it does — and what it deliberately does not

`install.py` and `run.py` are the source of truth for what an installation
is. The launcher never reimplements them. Its own work is limited to getting
two things onto the disk that Python cannot fetch for itself:

1. **A Python interpreter.** It downloads
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
   3.10 — the same build `app/provision/runtimes.py` uses — into the same
   location (`<user data>/runtime/python/python/`). When install.py's own
   `python` stage runs later, it finds this one and accepts it.
2. **The source payload.** `CraftBot-src.zip` from the GitHub release
   matching the launcher's version, extracted into the install directory and
   stamped with `.craftbot-managed` (see `app/paths.py`).

Everything after that is `craftbot.py` in the installed tree, run with
`CRAFTBOT_PYTHON` pointing at the sidecar:

| Button | Command |
|---|---|
| Install CraftBot | `craftbot.py install --no-open-browser` → runs `install.py --no-launch`, registers auto-start, starts |
| Start CraftBot | `craftbot.py start --no-open-browser` → runs `run.py` |
| Open CraftBot | opens `http://localhost:7925` in the browser |
| Stop | `craftbot.py stop` |
| Repair | the install steps again over the existing location (also the upgrade path) |
| Uninstall | `craftbot.py uninstall`, then removes the install directory and the runtimes; user data is left alone |

State is read the same way `craftbot.py` writes it in source mode:
`craftbot.pid` beside `craftbot.py`, and `.agent-ready` under the user data
directory for "running and actually serving" versus "still starting".

### Files the launcher owns

| | Windows | macOS | Linux |
|---|---|---|---|
| user data root | `%LOCALAPPDATA%\CraftBot` | `~/Library/Application Support/CraftBot` | `~/.local/share/craftbot` |
| default install dir | `%LOCALAPPDATA%\Programs\CraftBot` | `~/Applications/CraftBot` | `~/.local/share/craftbot/app` |

Under the user data root: `launcher.json` (what was installed, where, with
which interpreter), `launcher.log` (everything, including the full output of
`craftbot.py install` — this is what "Open log" opens), and `runtime/`.

## Building

```bash
cd launcher
cargo build --release          # target/release/CraftBotInstaller[.exe]
cargo test
```

Rust 1.85+ (`rustup` installs it). No system libraries are needed on Windows
or macOS; on Linux the runtime uses the system's X11/Wayland and OpenGL via
`dlopen`, with a software renderer as fallback.

The CraftBot version is baked in at build time: `CRAFTBOT_VERSION=1.4.0
cargo build --release`, or a `VERSION` file at the repo root, or "latest"
for a dev build (downloads the newest release).

### macOS bundle

```bash
packaging/macos/bundle.sh target/release/CraftBotInstaller dist 1.4.0
```

writes `dist/CraftBotInstaller.app`, ad-hoc signed. Right-click → Open the
first time, as before. Replace `-s -` in the script with a Developer ID when
one exists.

### The developer loop

Put a `CraftBot-src.zip` beside the binary (or the `.app`), in `./dist/`, or
name it with `CRAFTBOT_SRC_ZIP=…`, and the launcher installs from it instead
of downloading. `python scripts/package_source.py` builds one.

### Headless mode

```bash
CraftBotInstaller --headless install [dir]
CraftBotInstaller --headless status | start | stop | repair | uninstall
```

Runs one job with no window and prints its events; exit code 0 on success.
This is how CI can exercise the real pipeline on a runner without a display,
and how a support case can be reproduced from a terminal. It is not a user
CLI — `craftbot.py` is that.

### Rendering fallback

Slint tries the GPU renderer first and falls back to its software renderer
where OpenGL is unavailable (Windows Sandbox, most VMs, some remote
desktops). To force one: `SLINT_BACKEND=winit-software` or
`SLINT_BACKEND=winit-femtovg`.

## How it is wired into the repo

- `.github/workflows/release.yml` is `launcher/packaging/release.yml`: the
  `docker`, `source` and `release` jobs are the originals; the `launcher`
  job builds the three binaries (universal on macOS) on every `v*` tag.
- `.github/workflows/launcher.yml` runs `cargo test` and `cargo build` on
  all three platforms for pushes and PRs that touch `launcher/**`.
- `launcher/packaging/patch_craftbot.py` has been applied to `craftbot.py`
  (idempotent; re-running it is a no-op). It adds a guard so
  `_close_console_window()` does not kill the launcher on Windows, and a
  shortcut so `uninstall` on a managed install does not pip-uninstall from
  a sidecar the launcher is about to delete.
- `scripts/package_source.py` excludes `launcher/` from `CraftBot-src.zip`
  and requires `installer/{helpers,metadata,payload}.py`, which
  `craftbot.py` imports at module scope.
- The Tk installer (`installer/ui/`, `installer/wizard.py`,
  `installer/api.py`, `packaging/`) and the PyInstaller hooks (`hooks/`,
  `rthooks/`) are gone. `craftbot.py`'s `wizard` subcommand and its
  `IS_FROZEN` branches remain and are inert under the launcher.

## Layout

```
launcher/
  Cargo.toml
  build.rs              compiles the UI, bakes in the version, Windows icon
  ui/app.slint          the window — layout, palette, buttons, progress
  assets/               logo mark (two blink frames) and the .ico
  src/main.rs           window ↔ state wiring, headless mode
  src/state.rs          installed / stopped / starting / running
  src/install.rs        the jobs behind the buttons
  src/python.rs         the Python sidecar
  src/payload.rs        CraftBot-src.zip: locate, download, extract, mark
  src/craftbot.rs       running craftbot.py and streaming its output
  src/paths.rs          every path, mirrored from app/paths.py and craftbot.py
  src/record.rs         launcher.json
  src/download.rs       HTTP with progress
  src/logger.rs         launcher.log
  packaging/macos/bundle.sh
  packaging/release.yml         drop-in replacement for .github/workflows/release.yml
  packaging/patch_craftbot.py   the two craftbot.py edits
```
