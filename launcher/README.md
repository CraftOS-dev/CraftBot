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

Python download locations and the fallback release are maintained in
`app/provision/python_downloads.json`. It defines the API/download hosts,
repository, release tag, Python patch version, and published platforms.
The Rust launcher embeds this file at build time; the Python provisioner
reads the copy shipped in `CraftBot-src.zip`. Update the file and rebuild
both artifacts when the upstream location or compatible fallback changes.
The fallback must match the Python major/minor required by the dependency
locks; changing this file alone does not upgrade CraftBot to another Python
version. Release metadata is still preferred over the direct archive URL.

Everything after that is `craftbot.py` in the installed tree, run with
`CRAFTBOT_PYTHON` pointing at the sidecar:

| Button | Command |
|---|---|
| Install CraftBot | `craftbot.py install --no-open-browser` → runs `install.py --no-launch`, registers auto-start, starts |
| Start CraftBot | `craftbot.py start --no-open-browser` → runs `run.py` |
| Open CraftBot | opens the URL in `<data root>/ui.json` (written by run.py), else `http://localhost:7925` |
| Stop | `craftbot.py stop` |
| Repair | the install steps again over the existing location; also finishes a failed setup |
| Update CraftBot | shown instead of Start/Open when this launcher is newer than the installed version; the same code path as Repair |
| Uninstall | `craftbot.py uninstall`, then removes the install directory and the runtimes; user data is left alone |

An install is recorded in `launcher.json` only after `craftbot.py install`
succeeds. A failed setup leaves no record: the window offers Repair and
shows the last 15 lines of the setup output (the full output is in
`launcher.log`, behind "Open log").

State comes from files run.py writes under the data root, whoever started
it (this window, a terminal or the login item): `craftbot.pid` (written on
start, removed on exit; checked against a live process) for "running", and
`.agent-ready` for "running and actually serving" versus "still starting".

Before anything is downloaded the launcher checks the macOS version
(`MIN_MACOS` in `src/preflight.rs`, also the bundle's
`LSMinimumSystemVersion`), that the install location does not hold the
user's data, and that the drive holding the data root (which receives the
packages and runtimes) has `MIN_FREE_GB` (3 GB) free.

Install and Repair refresh login startup through `craftbot.py install`, using
the current interpreter, source directory and saved ports. Automatic startup
defaults to enabled; `craftbot.py autostart disable` opts out without uninstalling
or stopping the current session, and `autostart enable` restores it. The choice
is kept in `startup.json` under the user data directory and survives Repair.
Desktop shortcuts only open the browser. Login startup writes its own PID and
logs, so the launcher can also recognize an agent started after a reboot.

### Files the launcher owns

| | Windows | macOS | Linux |
|---|---|---|---|
| user data root | `%LOCALAPPDATA%\CraftBot` | `~/Library/Application Support/CraftBot` | `~/.local/share/craftbot` |
| default install dir | `%LOCALAPPDATA%\Programs\CraftBot` | `~/Applications/CraftBot` | `~/.local/share/craftbot/source` |

`CRAFTBOT_HOME`, when set, replaces the data root for the launcher exactly
as it does for `app/paths.py`. On Linux the source tree has its own `source`
folder because the agent keeps its settings and databases in
`<data root>/app`; Uninstall refuses to remove any folder that holds them.

Under the user data root: `launcher.json` (what was installed, where, with
which interpreter), `launcher.log` (everything, including the full output of
`craftbot.py install` — this is what "Open log" opens), and `runtime/`.

## Building

```bash
cd launcher
cargo build --release          # target/release/CraftBotInstaller[.exe]
cargo test
```

Rust 1.87+ (`rustup` installs it). No system libraries are needed on Windows
or macOS; on Linux the runtime uses the system's X11/Wayland and OpenGL via
`dlopen`; the setup window uses software rendering by default. Minimal X11
desktops also need `libxkbcommon-x11-0` (in addition to their display server
and a browser).

Windows downloads use Schannel so certificate chains resolve on a fresh
machine, including roots Windows retrieves on demand. Other platforms use
rustls with the OS trust store.

Every download (`src/download.rs`) is retried up to three times with
backoff. `CraftBot-src.zip` is verified by SHA-256 against the
`CraftBot-src.zip.sha256` asset the release publishes beside it; the Python
runtime comes from the release metadata described above and is accepted
only once the unpacked interpreter reports Python 3.10. The proxy is chosen
per URL (`src/proxy.rs`):
`HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY` with `NO_PROXY`, otherwise the OS
setting (Windows Internet Options, macOS `scutil --proxy`, GNOME gsettings).
Configuration scripts (PAC) are not evaluated; set `HTTPS_PROXY` instead.
`CRAFTBOT_MIRRORS` rewrites URLs before they are fetched: semicolon-separated
`prefix=replacement` pairs, the first matching prefix wins, for example
`https://github.com/=https://mirror.example/github/;https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/`.
The Python side reads the same variable. Checksums apply whatever the
rewritten URL.

Every child process (install.py, craftbot.py, the interpreter probe) runs
the private Python in isolation: `PYTHONHOME`, `PYTHONPATH`,
`PYTHONSTARTUP`, `PYTHONEXECUTABLE`, `PYTHONUSERBASE`, `VIRTUAL_ENV`,
`CONDA_PREFIX` and every `PIP_*` variable except `PIP_INDEX_URL`,
`PIP_EXTRA_INDEX_URL`, `PIP_TRUSTED_HOST` and `PIP_CERT` are removed, and
`PYTHONNOUSERSITE=1`, `PYTHONUTF8=1`, `PIP_DISABLE_PIP_VERSION_CHECK=1` set.

Linux builds run inside `manylinux_2_28` (glibc 2.28), so one binary per
architecture starts on Ubuntu 20.04+, Debian 10+, RHEL 8+ and WSL.
`packaging/linux/check_binary.sh` fails the build if any symbol needs a
newer glibc or if anything beyond glibc's own libraries is linked: X11,
Wayland, OpenGL and fontconfig are all loaded with `dlopen`, so the headless
installer starts on a minimal OS; opening the window still requires a
working graphical session. To build one locally:

```bash
docker run --rm -v "$PWD:/src" -w /src/launcher quay.io/pypa/manylinux_2_28_x86_64 bash -c \
  'curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal && . ~/.cargo/env &&
   cargo build --release && bash packaging/linux/check_binary.sh target/release/CraftBotInstaller'
```

The CraftBot version is baked in at build time: `CRAFTBOT_VERSION=1.4.0
cargo build --release`, or a `VERSION` file at the repo root, or "latest"
for a dev build (downloads the newest release).

### macOS bundle

```bash
packaging/macos/bundle.sh target/release/CraftBotInstaller dist 1.4.0
```

writes `dist/CraftBotInstaller.app`. With `MACOS_SIGN_IDENTITY` set to a
"Developer ID Application" identity it is signed with the hardened runtime
and a timestamp, ready to notarize; otherwise it is ad-hoc signed and users
must allow it once in System Settings > Privacy & Security. The release
workflow imports the certificate, notarizes with `xcrun notarytool` and
staples the ticket when the signing secrets exist (see below).

### The developer loop

Put a `CraftBot-src.zip` beside the binary (or the `.app`) or in `./dist/`,
and the launcher installs from it instead of downloading, provided the
`VERSION` inside it is the launcher's own version (a zip without one counts
as "latest", which matches a dev build). A leftover zip from another
release is ignored and logged. `CRAFTBOT_SRC_ZIP=…` names a zip explicitly
and is always used. `python scripts/package_source.py` builds one.

### Headless mode

```bash
CraftBotInstaller --headless install [dir]
CraftBotInstaller --headless status | start | stop | repair | uninstall
```

Runs one job with no window and prints its events; exit code 0 on success.
This is how CI can exercise the real pipeline on a runner without a display,
and how a support case can be reproduced from a terminal. It is not a user
CLI — `craftbot.py` is that.

### Rendering

The setup window uses Slint's software renderer by default, including on
Windows with the basic display driver, virtual machines, and remote desktops.
An OpenGL driver is not required. `SLINT_BACKEND=winit-femtovg` explicitly
selects GPU rendering; `SLINT_BACKEND=winit-software` selects software rendering.

## How it is wired into the repo

- `.github/workflows/release.yml` builds, on every `v*` tag:
  `CraftBot-src.zip` with its `VERSION` and a `.sha256`;
  `CraftBotInstaller-linux-x86_64` and `-linux-aarch64` (manylinux_2_28,
  then started on Ubuntu 20.04 to Debian 13 and AlmaLinux 8/9);
  `CraftBotInstaller-windows.exe`; `CraftBotInstaller-macos.zip`
  (universal). Signing runs when its secrets exist and is skipped with a
  warning when they do not; the release notes follow what was signed.
  Windows (Azure Artifact Signing): `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
  `AZURE_CLIENT_SECRET`, `TRUSTED_SIGNING_ENDPOINT`,
  `TRUSTED_SIGNING_ACCOUNT`, `TRUSTED_SIGNING_PROFILE`. macOS:
  `MACOS_CERT_P12_BASE64`, `MACOS_CERT_PASSWORD` (Developer ID
  Application), plus `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` to
  notarize.
- `.github/workflows/launcher.yml` runs the same Linux build, check and
  distribution start-up on PRs, plus tests on Windows and on arm64 and
  Intel macOS, for pushes and PRs that touch `launcher/**`.
- `.github/workflows/install-e2e.yml` runs a real `install.py` and starts
  the agent until it is ready and serving, on Windows, macOS arm64 and
  Intel, Linux x86_64 and ARM64, each with the runner's stock Python (and
  once with Python 3.8).
- `launcher/packaging/patch_craftbot.py` has been applied to `craftbot.py`
  (idempotent; re-running it is a no-op). It adds a guard so
  `_close_console_window()` does not kill the launcher on Windows, and a
  shortcut so `uninstall` on a managed install does not pip-uninstall from
  a sidecar the launcher is about to delete.
- `scripts/package_source.py` excludes `launcher/` from `CraftBot-src.zip`
  and requires `installer/{helpers,metadata,payload,startup}.py`, which
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
  src/download.rs       HTTP with progress, retries, checksums, mirrors
  src/proxy.rs          proxy choice: variables, NO_PROXY, the OS setting
  src/preflight.rs      checks before any download (MIN_MACOS)
  src/logger.rs         launcher.log
  packaging/macos/bundle.sh     the .app; Developer ID or ad-hoc signing
  packaging/linux/check_binary.sh   glibc floor and linked-library check
  packaging/patch_craftbot.py   the two craftbot.py edits
```
