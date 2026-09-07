#!/usr/bin/env python3
"""
CraftBot Service Manager

Run CraftBot as a background process that survives terminal closure,
and optionally register it to auto-start when your system boots.

Commands:
    python craftbot.py start [options]    Start CraftBot in background
    python craftbot.py stop               Stop CraftBot
    python craftbot.py restart [options]  Stop then start
    python craftbot.py status             Show if CraftBot is running
    python craftbot.py logs [-n N]        Show last N log lines (default: 50)
    python craftbot.py install [options]  Register for auto-start on boot/login
    python craftbot.py uninstall          Remove auto-start registration
    python craftbot.py repair [options]   Re-copy current EXE over the installed
                                          copy and restart (frozen EXE only)
    python craftbot.py wizard             Open the GUI wizard

When running as a frozen EXE (CraftBot.exe with no args), the wizard opens
automatically. Subcommands work the same as in source mode.

Options passed to 'start' / 'install':
    --cli                   Run in CLI mode instead of browser
    --no-open-browser       Don't open browser automatically (default for service)
    --frontend-port PORT    Frontend port (default: 7925)
    --backend-port PORT     Backend port (default: 7926)
    --conda                 Use conda environment
    --no-conda              Don't use conda

Examples:
    python craftbot.py start                   # Start in background (browser mode)
    python craftbot.py start --cli             # Start in background (CLI mode)
    python craftbot.py install                 # Auto-start on login (browser mode)
    python craftbot.py install --no-open-browser  # Auto-start without opening browser
    python craftbot.py stop
    python craftbot.py logs -n 100
"""

import sys

# In windowed (console=False) PyInstaller builds, sys.stdout and sys.stderr
# are None. Lots of libraries (including run.py at import time) call
# sys.stdout.isatty() unconditionally and crash with AttributeError. Install
# a dummy file-like before ANY other import that might transitively hit
# stdout. Must be the very first thing this module does.
if sys.stdout is None or sys.stderr is None:
    import io

    class _NullIO(io.TextIOBase):
        def isatty(self) -> bool:
            return False

        def write(self, s: str) -> int:
            return len(s)

        def flush(self) -> None:
            pass

    if sys.stdout is None:
        sys.stdout = _NullIO()
    if sys.stderr is None:
        sys.stderr = _NullIO()

import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
import webbrowser
from typing import Callable, List, Optional

from installer import helpers as _helpers
from installer import metadata as _metadata
from installer import payload as _payload

# Store platform once so static analysers don't short-circuit platform branches
_PLATFORM: str = sys.platform

# ─── Frozen-mode detection ────────────────────────────────────────────────────

# True when running as a PyInstaller-bundled EXE. The frozen EXE is the
# *installer* — a small Tkinter wizard that downloads the agent payload from
# GitHub Releases and installs it into a chosen location. The installer does
# NOT contain the agent itself (no run.py, no openai/anthropic/etc bundled).
IS_FROZEN: bool = bool(getattr(sys, "frozen", False))
EXE_PATH: Optional[str] = sys.executable if IS_FROZEN else None

# Single interpreter for every CraftBot process (see app/python_runtime.py).
# Absent in the frozen installer EXE, which bundles no agent code.
try:
    from app import python_runtime as _python_runtime
except ImportError:
    _python_runtime = None

# Where code and state live, for every install path (see app/paths.py).
# Imported unconditionally — it is stdlib-only, so it is available in the
# frozen installer EXE too, unlike the rest of app/.
from app import paths  # noqa: E402

# Agent payload (download/extract/version) lives in craftbot_payload.
# These re-exports keep external callers (e.g. CraftBotInstaller.spec docstring,
# any future tooling) working with the legacy `craftbot.GITHUB_OWNER` etc.
GITHUB_OWNER = _payload.GITHUB_OWNER
GITHUB_REPO = _payload.GITHUB_REPO

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_bundled_version() -> str:
    return _payload.read_bundled_version(BASE_DIR)


def _user_data_dir() -> str:
    """Return the per-user persistent data directory for CraftBot.

    Used for PID file, log file, and install metadata when running as a
    frozen EXE (BASE_DIR points at the temp-extracted bundle, which is
    wiped between runs). For source installs we keep the legacy behaviour
    of writing alongside craftbot.py, since BASE_DIR is already stable.
    """
    if not IS_FROZEN:
        return BASE_DIR
    if _PLATFORM == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        path = os.path.join(root, "CraftBot")
    elif _PLATFORM == "darwin":
        path = os.path.expanduser("~/Library/Application Support/CraftBot")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        path = os.path.join(root, "craftbot")
    os.makedirs(path, exist_ok=True)
    return path


PID_FILE = os.path.join(_user_data_dir(), "craftbot.pid")
LOG_FILE = os.path.join(_user_data_dir(), "craftbot.log")
INSTALL_METADATA_FILE = os.path.join(_user_data_dir(), "install.json")

# Source-mode only — relative to craftbot.py. The frozen installer never
# uses this; it spawns the installed agent EXE directly.
RUN_SCRIPT = os.path.join(BASE_DIR, "run.py")


def default_install_location() -> str:
    """Return the default install directory used by the wizard's location chooser.

    Picks a per-user path that does NOT require admin elevation. The wizard
    lets the user override this via filedialog.askdirectory().
    """
    if _PLATFORM == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        return os.path.join(root, "Programs", "CraftBot")
    if _PLATFORM == "darwin":
        return os.path.expanduser("~/Applications/CraftBot")
    return os.path.expanduser("~/.local/share/craftbot")


# Install metadata helpers — pure-function impls live in craftbot_metadata.
# We keep these no-arg wrappers so the wizard (and any external caller) can
# use the legacy `craftbot.installed_exe_path()` API without threading the
# metadata-file path through every call site.


def read_install_metadata() -> Optional[dict]:
    return _metadata.read(INSTALL_METADATA_FILE)


def write_install_metadata(
    installed_path: str,
    mode: str,
    python: Optional[str] = None,
    version: Optional[str] = None,
) -> None:
    """Record what was installed, where, and what runs it.

    python/version are schema-2 fields: an install is now a source tree plus
    an interpreter, so both have to be recorded for cmd_start and auto-start
    registration to reconstruct the launch command.
    """
    _metadata.write(
        INSTALL_METADATA_FILE, installed_path, mode, python=python, version=version
    )


def clear_install_metadata() -> None:
    _metadata.clear(INSTALL_METADATA_FILE)


def installed_exe_path() -> Optional[str]:
    return _metadata.installed_exe_path(INSTALL_METADATA_FILE)


TASK_NAME = "CraftBot"  # Windows Task Scheduler task name
SYSTEMD_SERVICE = "craftbot"  # Linux systemd service name
LAUNCHD_LABEL = "com.craftbot.agent"  # macOS launchd label
DEFAULT_FRONTEND_PORT = 7925
DEFAULT_BACKEND_PORT = 7926
BROWSER_URL = f"http://localhost:{DEFAULT_FRONTEND_PORT}"
CRAFTBOT_READY_MARKER = "CRAFTBOT IS READY"
SHORTCUT_NAME = "CraftBot.lnk"
# Bundled icons live in sys._MEIPASS in frozen mode (PyInstaller's runtime
# extract dir) and alongside craftbot.py in source mode. _ensure_ico() copies
# the bundled icon to the persistent user data dir during install so the
# desktop shortcut keeps a stable path after _MEIPASS is wiped.
_BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
LOGO_PNG = os.path.join(_BUNDLE_DIR, "craftbot_logo_1.png")
LOGO_ICO = os.path.join(_BUNDLE_DIR, "craftbot_logo_1.ico")
# ─── Terminal colors (orange/white brand palette) ─────────────────────────────


def _enable_windows_vtp() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        m = ctypes.c_ulong()
        k32.GetConsoleMode(h, ctypes.byref(m))
        k32.SetConsoleMode(h, m.value | 0x0004)
    except Exception:
        pass


_enable_windows_vtp()

# Force UTF-8 output on Windows so Unicode box-drawing characters don't crash
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_USE_COLOR = sys.stdout.isatty()


def _c(code: str) -> str:
    return code if _USE_COLOR else ""


ORANGE = _c("\033[38;2;255;79;24m")  # #FF4F18
WHITE = _c("\033[38;2;255;255;255m")  # #FFFFFF
BOLD = _c("\033[1m")
DIM = _c("\033[38;2;80;80;80m")  # dark gray
GREEN = _c("\033[38;2;80;220;100m")
RED = _c("\033[91m")
RESET = _c("\033[0m")


def _retro_step(num: int, total: int, desc: str) -> None:
    """Print a retro-style step header box."""
    W = 62
    visible = f"  ▸ STEP {num}/{total}  ░░  {desc.upper()}"
    pad = max(0, W - len(visible))
    content = (
        f"  {ORANGE}▸ STEP {num}/{total}{RESET}"
        f"  {DIM}░░{RESET}"
        f"  {WHITE}{desc.upper()}{RESET}" + " " * pad
    )
    print(f"\n{ORANGE}╔{'═' * W}╗{RESET}")
    print(f"{ORANGE}║{RESET}{content}{ORANGE}║{RESET}")
    print(f"{ORANGE}╚{'═' * W}╝{RESET}")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _to_short_path(path: str) -> str:
    """Return the Windows 8.3 short path form to avoid Unicode / long-path
    issues when embedding paths inside command strings (e.g. schtasks /tr)."""
    if _PLATFORM != "win32":
        return path
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)):
            return buf.value
    except Exception:
        pass
    return path


def _warn_path_issues() -> None:
    """Print warnings if BASE_DIR is too long or contains non-ASCII characters."""
    if len(BASE_DIR) > 200:
        print(f"WARNING: Installation path is very long ({len(BASE_DIR)} chars).")
        print("         Windows MAX_PATH limit may cause failures.")
        print("         Consider moving CraftBot to a shorter path.\n")
    try:
        BASE_DIR.encode("ascii")
    except UnicodeEncodeError:
        print(
            "WARNING: Installation path contains non-ASCII characters (e.g. Japanese)."
        )
        print(
            "         Some commands may fail. Short paths will be used where possible.\n"
        )


def _installed_python() -> str:
    """The single CraftBot interpreter (app/python_runtime.py), else this
    process's own. main() re-execs onto it first thing, so normally the two
    are the same; the fallback covers the frozen installer EXE."""
    if _python_runtime is not None:
        return _python_runtime.resolve() or sys.executable
    return sys.executable


def _python_exe() -> str:
    """Return the Python executable to use for the service process."""
    python = _installed_python()
    # On Windows prefer pythonw.exe (no console window) when not in CLI mode
    if _PLATFORM == "win32":
        pythonw = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.isfile(pythonw):
            return pythonw
    return python


def _read_pid() -> Optional[int]:
    """Read PID from the PID file. Returns None if file missing or invalid."""
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _write_pid(pid: int) -> None:
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def _remove_pid() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def _parse_port_arg(args: List[str], flag: str, default: int) -> int:
    prefix = f"{flag}="
    for i, arg in enumerate(args):
        value = None
        if arg == flag and i + 1 < len(args):
            value = args[i + 1]
        elif arg.startswith(prefix):
            value = arg[len(prefix) :]
        if value is not None:
            try:
                return int(value)
            except ValueError:
                return default
    return default


def _frontend_url(args: List[str]) -> str:
    port = _parse_port_arg(args, "--frontend-port", DEFAULT_FRONTEND_PORT)
    return f"http://localhost:{port}"


def _backend_url(args: List[str]) -> str:
    port = _parse_port_arg(args, "--backend-port", DEFAULT_BACKEND_PORT)
    return f"http://localhost:{port}"


def _port_args(args: List[str]) -> List[str]:
    result = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg in ("--frontend-port", "--backend-port"):
            if i + 1 < len(args):
                result.extend([arg, args[i + 1]])
                skip_next = True
            continue
        if arg.startswith("--frontend-port=") or arg.startswith("--backend-port="):
            result.append(arg)
    return result


def _tail_log_lines(n: int = 30, start_offset: int = 0) -> str:
    if not os.path.isfile(LOG_FILE):
        return ""
    try:
        with open(LOG_FILE, "r", errors="replace") as f:
            if start_offset:
                f.seek(start_offset)
            lines = f.readlines()
    except Exception:
        return ""
    return "".join(lines[-n:])


def _wait_for_startup_exit(
    proc, timeout: float = 8.0, ready_log_offset: int = 0
) -> Optional[int]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return proc.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            if CRAFTBOT_READY_MARKER in _tail_log_lines(80, ready_log_offset):
                return None
    return None


#: How long cmd_start waits for the agent to finish booting before it gives
#: up on opening the browser. Minutes, not seconds: a first run downloads the
#: embedding model, and on a slow connection that dominates startup.
BROWSER_READY_TIMEOUT_S = 600


def _clear_agent_ready() -> None:
    """Drop any previous run's readiness marker before we launch."""
    try:
        paths.AGENT_READY_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _wait_for_ready_marker(start_offset: int, timeout: float) -> bool:
    """Block until the agent reports that it finished booting.

    `_wait_for_startup_exit` is not a substitute: it returns after 8 seconds
    whether or not anything is ready, because its job is only to catch a
    launch that dies immediately. Opening the browser on that signal put a
    tab in front of the user at around step 2 of 8.

    Two signals, checked in this order:

      1. app.paths.AGENT_READY_FILE, written by the agent itself. This is
         authoritative and is what we actually wait on.
      2. The ready banner in the log, kept only as a fallback for an older
         installed agent that predates the marker file.

    The log used to be the ONLY signal, and that was a bug: run.py's stdout
    is a log FILE here, so Python block-buffers it. The banner sat unflushed
    in an 8 KB buffer while this function timed out around it — the install
    looked stuck on "Working..." long after the agent was serving.

    Returns False on timeout; the caller decides what that means.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if paths.AGENT_READY_FILE.is_file():
                return True
        except OSError:
            pass
        if CRAFTBOT_READY_MARKER in _tail_log_lines(200, start_offset):
            return True
        time.sleep(0.5)
    return False


def _is_running(pid: int) -> bool:
    """Return True if a process with the given PID is currently alive."""
    if _PLATFORM == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def _stop_running_agent_if_alive(grace_s: float = 1.0) -> bool:
    """If an agent is currently running, stop it and pause briefly so the OS
    releases file handles before we try to overwrite the agent EXE. Used by
    install/repair so reinstall over a running agent doesn't fail with
    "Permission denied" on Windows. Returns True if a process was stopped.
    """
    pid = _read_pid()
    if pid and _is_running(pid):
        cmd_stop()
        time.sleep(grace_s)
        return True
    return False


def _build_run_args(extra: List[str], service_mode: bool = True) -> List[str]:
    """Build the argument list for run.py.

    Adds --no-open-browser by default in service mode (auto-start at boot
    should not pop open a browser without the user asking).
    """
    args = list(extra)
    # CLI mode doesn't use the browser flag
    if service_mode and "--cli" not in args:
        if "--no-open-browser" not in args:
            args.append("--no-open-browser")
    return args


# ─── Core operations ──────────────────────────────────────────────────────────


def _open_browser_detached(url: str) -> None:
    """Poll the server URL and open the browser once it responds.

    In frozen mode (installer EXE) sys.executable is CraftBotInstaller.exe,
    not python — so spawning `sys.executable -c <script>` would just re-launch
    the wizard. We run the poll in-process on a daemon thread instead. In
    source mode we keep the detached-subprocess path so `python craftbot.py
    start` returns immediately even on slow agent boots.
    """
    if IS_FROZEN:

        def _poll_and_open() -> None:
            from urllib.request import urlopen

            deadline = time.time() + 120
            while time.time() < deadline:
                try:
                    urlopen(url, timeout=1).close()
                    break
                except Exception:
                    time.sleep(1)
            webbrowser.open(url)

        threading.Thread(target=_poll_and_open, daemon=True).start()
        return

    poll_script = (
        "import sys, time, webbrowser\n"
        "try:\n"
        "    from urllib.request import urlopen\n"
        "    deadline = time.time() + 120\n"
        "    while time.time() < deadline:\n"
        "        try:\n"
        f"            urlopen('{url}', timeout=1).close()\n"
        "            break\n"
        "        except Exception:\n"
        "            time.sleep(1)\n"
        "except Exception:\n"
        "    pass\n"
        f"webbrowser.open('{url}')\n"
    )

    python = _installed_python()
    if _PLATFORM == "win32":
        pythonw = python.replace("python.exe", "pythonw.exe")
        if os.path.isfile(pythonw):
            python = pythonw

    kwargs: dict = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_helpers.detached_popen_flags(),
    )

    subprocess.Popen([python, "-c", poll_script], **kwargs)


def cmd_start(extra_args: List[str]) -> bool:
    """Start CraftBot as a detached background process.

    Returns True once the service survives the early startup check; False when
    launch fails before CraftBot can be used.
    """
    pid = _read_pid()
    if pid and _is_running(pid):
        cmd_stop()

    # service_mode=False — don't suppress the browser; we open it ourselves below
    run_args = _build_run_args(extra_args, service_mode=False)
    # Always pass --no-open-browser to run.py; craftbot.py handles opening the browser
    if "--cli" not in run_args:
        if "--no-open-browser" not in run_args:
            run_args.append("--no-open-browser")

    if IS_FROZEN:
        # Launching an install is metadata.launch_command()'s job — it is the
        # only place that knows the difference between a schema-2 install
        # ([python, run.py]) and a legacy schema-1 frozen bundle ([agent.exe]).
        # Spreading that knowledge is how the entry points drifted before.
        launch = _metadata.launch_command(INSTALL_METADATA_FILE)
        if not launch:
            print("Error: no usable install found — run install first.")
            return False
        cmd = launch + run_args
    else:
        python = _python_exe()
        # Use plain python.exe for CLI because pythonw has no console
        if "--cli" in run_args:
            python = _installed_python()
        cmd = [python, RUN_SCRIPT] + run_args

    # UTF-8 with replace so the agent's Unicode banner / box-drawing chars
    # don't crash on Windows where the default file encoding is cp1252.
    # Clear the readiness marker BEFORE launching, so a marker left by the
    # previous run cannot make this one look instantly ready.
    _clear_agent_ready()

    log_fh = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log_fh.write(f"\n{'=' * 60}\n")
    log_fh.write(f"CraftBot service started at {_timestamp()}\n")
    log_fh.write(f"Command: {' '.join(cmd)}\n")
    log_fh.write(f"{'=' * 60}\n")
    log_fh.flush()
    ready_log_offset = log_fh.tell()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    kwargs = dict(
        cwd=BASE_DIR,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        **_helpers.detached_popen_flags(new_process_group=True),
    )

    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except FileNotFoundError as e:
        log_fh.close()
        print(f"  {RED}✗{RESET} {WHITE}Could not launch CraftBot — {e}{RESET}")
        return False

    # Parent closes its copy — the child process (run.py) keeps the fd open
    log_fh.close()
    _write_pid(proc.pid)

    # Catch immediate startup failures before reporting success. This surfaces
    # wrong-Python dependency errors from run.py instead of leaving a stale PID.
    exit_code = _wait_for_startup_exit(proc, ready_log_offset=ready_log_offset)

    if exit_code is not None:
        _remove_pid()
        print(
            f"  {RED}✗{RESET} {WHITE}CraftBot failed to start{RESET}  {DIM}exit {exit_code}{RESET}"
        )
        log_tail = _tail_log_lines()
        if log_tail:
            print(f"\n{DIM}Last log lines:{RESET}\n{log_tail}", end="")
        print(f"\nCheck logs: {sys.executable} craftbot.py logs")
        return False

    print(
        f"  {GREEN}▸{RESET} {WHITE}CRAFTBOT STARTED{RESET}  {DIM}PID {proc.pid}{RESET}"
    )

    # Create a desktop shortcut so the user can reopen the browser anytime
    if "--cli" not in run_args:
        if _PLATFORM == "win32":
            _create_desktop_shortcut_windows()
        else:
            _create_desktop_shortcut_unix(extra_args)

    open_browser = "--cli" not in run_args and "--no-open-browser" not in extra_args
    if open_browser:
        browser_url = _frontend_url(extra_args)
        print(f"  {DIM}░░{RESET} {ORANGE}{browser_url}{RESET}")
        # Wait for the agent to actually be up before opening a tab at it.
        #
        # This used to open immediately after _wait_for_startup_exit(), which
        # returns after 8 seconds — around step 2 of 8, while the model
        # download, MCP servers, skills, integrations and the scheduler were
        # all still to come. The browser then showed a backend that could not
        # serve it.
        #
        # run.py only prints the ready marker once the agent signals that
        # boot() finished (see app/paths.py AGENT_READY_FILE), so waiting for
        # the marker here is waiting for the real thing.
        if _wait_for_ready_marker(ready_log_offset, BROWSER_READY_TIMEOUT_S):
            _open_browser_detached(browser_url)
        else:
            print(
                f"  {DIM}Still starting — open {browser_url} "
                f"once it finishes.{RESET}"
            )

    return True


def cmd_stop() -> None:
    """Stop the running CraftBot service."""
    pid = _read_pid()
    if pid is None:
        print("CraftBot does not appear to be running (no PID file found).")
        return

    if not _is_running(pid):
        print(f"  {DIM}▸ PID {pid} not running — cleaning up stale PID file{RESET}")
        _remove_pid()
        return

    print(f"  {ORANGE}▸{RESET} {WHITE}STOPPING CRAFTBOT{RESET}  {DIM}PID {pid}{RESET}")

    if _PLATFORM == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                timeout=15,
            )
        except Exception as e:
            print(f"Warning: taskkill failed — {e}")
    else:
        try:
            # Kill the entire process group so child processes also die
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            # Give it a moment to exit gracefully
            for _ in range(10):
                time.sleep(0.5)
                if not _is_running(pid):
                    break
            else:
                os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception as e:
            print(f"Warning: {e}")

    _remove_pid()
    print(f"  {GREEN}▸{RESET} {WHITE}CRAFTBOT STOPPED{RESET}")


def cmd_status() -> None:
    """Print whether CraftBot is currently running and whether auto-start is installed."""
    W = max(50, len(LOG_FILE) + 12)
    pid = _read_pid()
    print(f"\n{ORANGE}╔{'═' * W}╗{RESET}")
    if pid and _is_running(pid):
        print(
            f"{ORANGE}║{RESET}  {GREEN}▸ RUNNING{RESET}  {DIM}PID {pid}{RESET}{' ' * (W - 17 - len(str(pid)))}{ORANGE}║{RESET}"
        )
        print(
            f"{ORANGE}║{RESET}  {DIM}░░ LOG: {LOG_FILE[: W - 8]}{RESET}{' ' * max(0, W - 10 - len(LOG_FILE[: W - 8]))}{ORANGE}║{RESET}"
        )
    else:
        if pid:
            _remove_pid()
        print(
            f"{ORANGE}║{RESET}  {RED}▸ NOT RUNNING{RESET}{' ' * (W - 15)}{ORANGE}║{RESET}"
        )
    print(f"{ORANGE}║{' ' * W}║{RESET}")
    if _is_installed():
        print(
            f"{ORANGE}║{RESET}  {GREEN}▸ AUTO-START: INSTALLED{RESET}{' ' * (W - 25)}{ORANGE}║{RESET}"
        )
    else:
        print(
            f"{ORANGE}║{RESET}  {DIM}▸ AUTO-START: NOT INSTALLED{RESET}{' ' * (W - 27)}{ORANGE}║{RESET}"
        )
    print(f"{ORANGE}╚{'═' * W}╝{RESET}\n")


def cmd_logs(n: int = 50) -> None:
    """Print the last N lines of the CraftBot log."""
    if not os.path.isfile(LOG_FILE):
        print(f"No log file found at {LOG_FILE}")
        return
    try:
        with open(LOG_FILE, "r", errors="replace") as f:
            lines = f.readlines()
        tail = lines[-n:] if len(lines) > n else lines
        print(f"\n{ORANGE}╔{'═' * 60}╗{RESET}")
        print(
            f"{ORANGE}║{RESET}  {WHITE}CRAFTBOT LOG{RESET}  {DIM}last {len(tail)} lines{RESET}{' ' * (44 - len(str(len(tail))))}{ORANGE}║{RESET}"
        )
        print(f"{ORANGE}╚{'═' * 60}╝{RESET}\n")
        print("".join(tail), end="")
    except Exception as e:
        print(f"  {RED}✗{RESET} {WHITE}Error reading log: {e}{RESET}")


def cmd_restart(extra_args: List[str]) -> bool:
    cmd_stop()
    time.sleep(1)
    return cmd_start(extra_args)


# ─── Desktop shortcut ─────────────────────────────────────────────────────────


def _find_desktop() -> Optional[str]:
    """Return the path to the user's Desktop folder.

    Works for all users regardless of language, OneDrive config, or custom paths.
    On Windows reads the Shell Folders registry key directly (no subprocess).
    """
    if _PLATFORM == "win32":
        # Method 1: Read the registry directly — fast, no subprocess
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                0,
                winreg.KEY_READ,
            )
            raw, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            path = os.path.expandvars(raw)
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass

        # Method 2: ctypes SHGetFolderPath (CSIDL_DESKTOPDIRECTORY = 0x0010)
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
            path = buf.value
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass

    # Fallback: check common paths
    for candidate in [
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
    ]:
        if os.path.isdir(candidate):
            return candidate
    return None


def _ensure_ico() -> Optional[str]:
    """Return a path to a .ico file the desktop shortcut can reference long-term.

    In frozen mode prefer the persistent copy in _user_data_dir() (the bundled
    _MEIPASS path is wiped when the EXE exits, which would break the shortcut's
    icon after the first run).
    """
    persistent_ico = os.path.join(_user_data_dir(), "craftbot_logo_1.ico")
    if os.path.isfile(persistent_ico):
        return persistent_ico
    if os.path.isfile(LOGO_ICO):
        return LOGO_ICO
    if not os.path.isfile(LOGO_PNG):
        return None
    try:
        from PIL import Image

        img = Image.open(LOGO_PNG)
        # Write the converted .ico into the persistent dir so it survives
        # process exit when running as a frozen EXE.
        os.makedirs(os.path.dirname(persistent_ico), exist_ok=True)
        img.save(
            persistent_ico,
            format="ICO",
            sizes=[(256, 256), (48, 48), (32, 32), (16, 16)],
        )
        return persistent_ico
    except Exception:
        return None


def _create_desktop_shortcut_windows() -> None:
    """Create a .lnk shortcut on the Windows Desktop with the CraftBot icon."""
    desktop = _find_desktop()
    if not desktop:
        return
    shortcut_path = os.path.join(desktop, SHORTCUT_NAME)
    if os.path.exists(shortcut_path):
        return  # already exists, don't recreate
    ico_path = _ensure_ico()
    try:
        # Write the PS script to a temp file with UTF-8-BOM so PowerShell
        # handles non-ASCII paths (e.g. Japanese Desktop folder) correctly.
        import tempfile

        ps_lines = [
            "$ws = New-Object -ComObject WScript.Shell",
            f'$s = $ws.CreateShortcut("{shortcut_path}")',
            '$s.TargetPath = "cmd.exe"',
            f'$s.Arguments = "/c start {BROWSER_URL}"',
            "$s.WindowStyle = 7",  # minimized (hides the cmd flash)
        ]
        if ico_path:
            ps_lines.append(f'$s.IconLocation = "{ico_path},0"')
        ps_lines += [
            '$s.Description = "Open CraftBot in your browser"',
            "$s.Save()",
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8-sig"
        ) as tf:
            tf.write("\n".join(ps_lines))
            tmp_ps1 = tf.name
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    tmp_ps1,
                ],
                capture_output=True,
                timeout=15,
            )
        finally:
            try:
                os.remove(tmp_ps1)
            except Exception:
                pass
        if os.path.exists(shortcut_path):
            print(f"  Desktop shortcut created: {shortcut_path}")
            print("  Double-click it anytime to open CraftBot in your browser.")
        else:
            print(f"  (Shortcut creation may have failed — check {desktop})")
    except Exception as e:
        print(f"  (Could not create desktop shortcut: {e})")


def _installed_launch() -> Optional[List[str]]:
    """Command that starts the installed CraftBot, or None.

    One accessor for all of auto-start registration, the desktop shortcut and
    cmd_start. Under schema 2 an install is [python, run.py] rather than a
    single EXE, and having four call sites each rebuild that is exactly how
    the entry points drifted before.
    """
    return _metadata.launch_command(INSTALL_METADATA_FILE)


def _shortcut_start_command(extra_args: List[str]) -> Optional[str]:
    restart_args = _port_args(extra_args)
    if IS_FROZEN:
        launch = _installed_launch()
        if not launch:
            return None
        return shlex.join(launch + restart_args)
    return shlex.join([_python_exe(), "craftbot.py", "start"] + restart_args)


def _create_desktop_shortcut_unix(extra_args: Optional[List[str]] = None) -> None:
    """Create a desktop shortcut on Linux or macOS."""
    if extra_args is None:
        extra_args = []
    desktop = _find_desktop()
    if not desktop:
        return
    try:
        browser_url = _frontend_url(extra_args)
        if _PLATFORM == "darwin":
            # macOS does not support XDG .desktop files — create a double-clickable .command script
            shortcut_path = os.path.join(desktop, "CraftBot.command")
            backend_url = _backend_url(extra_args)
            start_cmd = _shortcut_start_command(extra_args)
            if not start_cmd:
                print("  (Could not create desktop shortcut: no installed agent found)")
                return
            content = (
                "#!/bin/sh\n"
                f"cd {shlex.quote(BASE_DIR)} || exit 1\n"
                f"backend_status=$(curl -sS -o /dev/null -w '%{{http_code}}' "
                f"{shlex.quote(backend_url)} 2>/dev/null || true)\n"
                f"if curl -fsS {shlex.quote(browser_url)} >/dev/null 2>&1 "
                '&& [ "$backend_status" -ge 100 ] 2>/dev/null '
                '&& [ "$backend_status" -lt 500 ] 2>/dev/null; then\n'
                f"  open {shlex.quote(browser_url)}\n"
                "else\n"
                f"  exec {start_cmd}\n"
                "fi\n"
            )
            with open(shortcut_path, "w") as f:
                f.write(content)
            os.chmod(shortcut_path, 0o755)
        else:
            # Linux: standard XDG .desktop entry
            shortcut_path = os.path.join(desktop, "CraftBot.desktop")
            open_cmd = (
                "xdg-open"
                if os.path.isfile("/usr/bin/xdg-open")
                or os.path.isfile("/usr/local/bin/xdg-open")
                else "sensible-browser"
            )
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=CraftBot\n"
                f"Exec={open_cmd} {browser_url}\n"
                "Icon=web-browser\n"
                "Terminal=false\n"
            )
            with open(shortcut_path, "w") as f:
                f.write(content)
            os.chmod(shortcut_path, 0o755)
        print(f"  Desktop shortcut created: {shortcut_path}")
        print("  Double-click it anytime to open CraftBot in your browser.")
    except Exception as e:
        print(f"  (Could not create desktop shortcut: {e})")


# ─── Auto-start: Windows Task Scheduler ───────────────────────────────────────


def _install_windows_registry(action: str) -> bool:
    """Fallback: register auto-start via HKCU Run registry key (no admin needed)."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, action)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _install_windows(run_args: List[str]) -> None:
    if IS_FROZEN:
        # Register the installed CraftBot for auto-start: [python, run.py].
        launch = _installed_launch()
        if not launch:
            print(
                f"  {RED}✗{RESET} {WHITE}No installed CraftBot found — run install first.{RESET}"
            )
            return
        # 8.3 short paths avoid quoting trouble in Task Scheduler's XML for
        # paths containing spaces, which %LOCALAPPDATA%\Programs often does.
        quoted = " ".join(f'"{_to_short_path(part)}"' for part in launch)
        action = f"{quoted} {' '.join(run_args)}".strip()
    else:
        python = _python_exe()
        # Use 8.3 short paths to avoid Unicode/long-path failures in schtasks /tr
        python_s = _to_short_path(python)
        script_s = _to_short_path(RUN_SCRIPT)
        action = f'"{python_s}" "{script_s}" {" ".join(run_args)}'

    # Try Task Scheduler first; silently fall back to Registry on failure
    registered = False
    try:
        result = subprocess.run(
            [
                "schtasks",
                "/create",
                "/tn",
                TASK_NAME,
                "/tr",
                action,
                "/sc",
                "ONLOGON",
                "/f",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        registered = result.returncode == 0
    except Exception:
        pass

    if not registered:
        registered = _install_windows_registry(action)

    if registered:
        print("Auto-start registered. CraftBot will start automatically on login.")
        print(f"Open CraftBot: {BROWSER_URL}")
        _create_desktop_shortcut_windows()
    else:
        print(
            "Could not register auto-start. Use 'python craftbot.py start' to start manually."
        )


def _uninstall_windows() -> None:
    removed_any = False

    # Remove from Task Scheduler
    try:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print(f"Auto-start removed (task '{TASK_NAME}' deleted).")
            removed_any = True
    except Exception as e:
        print(f"Warning: Could not query Task Scheduler — {e}")

    # Remove from Registry (HKCU\...\Run) — the fallback auto-start method
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, TASK_NAME)
            print(f"Auto-start removed (registry entry '{TASK_NAME}' deleted).")
            removed_any = True
        except FileNotFoundError:
            pass  # Entry didn't exist in registry — that's fine
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        print(f"Warning: Could not clean registry — {e}")

    if not removed_any:
        print("No auto-start registration found (already uninstalled?).")


# ─── Auto-start: Linux systemd (user service) ─────────────────────────────────


def _install_linux(run_args: List[str]) -> None:
    service_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(service_dir, exist_ok=True)

    service_file = os.path.join(service_dir, f"{SYSTEMD_SERVICE}.service")
    if IS_FROZEN:
        launch = _installed_launch()
        if not launch:
            print("Error: no installed CraftBot found — run install first.")
            return
        exec_start = f"{' '.join(launch)} {' '.join(run_args)}".strip()
    else:
        python = _installed_python()
        exec_start = f"{python} {RUN_SCRIPT} {' '.join(run_args)}"

    content = f"""[Unit]
Description=CraftBot AI Agent
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={BASE_DIR}
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    with open(service_file, "w") as f:
        f.write(content)

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=10)
        subprocess.run(
            ["systemctl", "--user", "enable", SYSTEMD_SERVICE], check=True, timeout=10
        )
        print(f"Auto-start registered as systemd user service '{SYSTEMD_SERVICE}'.")
        print("CraftBot will start automatically when you log in.")
        print(f"\nOpen CraftBot: {BROWSER_URL}")
        print(f"  Tip: Bookmark {BROWSER_URL} so you never have to remember it!")
        _create_desktop_shortcut_unix()
        print(f"\nTo start it now: systemctl --user start {SYSTEMD_SERVICE}")
        print(f"To view logs:    journalctl --user -u {SYSTEMD_SERVICE} -f")
    except subprocess.CalledProcessError as e:
        print(f"Error enabling systemd service: {e}")
        print(f"Service file written to: {service_file}")
        print(
            "Try manually: systemctl --user daemon-reload && systemctl --user enable craftbot"
        )
    except FileNotFoundError:
        print("systemctl not found. Is systemd running on this system?")


def _uninstall_linux() -> None:
    service_file = os.path.expanduser(
        f"~/.config/systemd/user/{SYSTEMD_SERVICE}.service"
    )
    try:
        subprocess.run(
            ["systemctl", "--user", "disable", SYSTEMD_SERVICE],
            capture_output=True,
            timeout=10,
        )
        subprocess.run(
            ["systemctl", "--user", "stop", SYSTEMD_SERVICE],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass
    if os.path.isfile(service_file):
        os.remove(service_file)
        print("Auto-start removed (service file deleted).")
    else:
        print("No systemd service file found.")
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=10
        )
    except Exception:
        pass


# ─── Auto-start: macOS launchd ────────────────────────────────────────────────


def _install_macos(run_args: List[str]) -> None:
    agents_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(agents_dir, exist_ok=True)

    plist_file = os.path.join(agents_dir, f"{LAUNCHD_LABEL}.plist")
    if IS_FROZEN:
        launch = _installed_launch()
        if not launch:
            print("Error: no installed CraftBot found — run install first.")
            return
        program_args = launch + run_args
    else:
        python = _installed_python()
        program_args = [python, RUN_SCRIPT] + run_args
    program_args_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{program_args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{BASE_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
"""
    with open(plist_file, "w") as f:
        f.write(content)

    # `launchctl load` honours RunAtLoad, so loading the agent starts CraftBot
    # then and there. When one is already running — the normal case, since
    # install starts it first — that second process fights the first for ports
    # 7925/7926 and one of them loses. Writing the plist is enough on its own:
    # launchd bootstraps ~/Library/LaunchAgents at login, so auto-start works
    # from the next login whether or not it was loaded now.
    pid = _read_pid()
    if pid and _is_running(pid):
        print(f"Auto-start registered as launchd agent '{LAUNCHD_LABEL}'.")
        print("CraftBot is already running — auto-start begins at your next login.")
        _print_launchd_hints(plist_file)
        return

    try:
        subprocess.run(["launchctl", "load", plist_file], check=True, timeout=10)
        print(f"Auto-start registered as launchd agent '{LAUNCHD_LABEL}'.")
        print("CraftBot will start automatically when you log in.")
        _print_launchd_hints(plist_file)
    except subprocess.CalledProcessError as e:
        print(f"Error loading launchd agent: {e}")
        print(f"Plist written to: {plist_file}")
        print(f"Try manually: launchctl load {plist_file}")


def _print_launchd_hints(plist_file: str) -> None:
    print(f"\nOpen CraftBot: {BROWSER_URL}")
    print(f"  Tip: Bookmark {BROWSER_URL} so you never have to remember it!")
    _create_desktop_shortcut_unix()
    print(f"\nPlist file: {plist_file}")


def _uninstall_macos() -> None:
    plist_file = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")
    if os.path.isfile(plist_file):
        try:
            subprocess.run(
                ["launchctl", "unload", plist_file], capture_output=True, timeout=10
            )
        except Exception:
            pass
        os.remove(plist_file)
        print("Auto-start removed.")
    else:
        print("No launchd agent found.")


# ─── Install / Uninstall dispatch ─────────────────────────────────────────────


def _is_installed() -> bool:
    """Return True if CraftBot is registered for auto-start on this platform."""
    plat = _PLATFORM
    if plat == "win32":
        # Check Task Scheduler
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", TASK_NAME],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        # Check Registry fallback
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            )
            winreg.QueryValueEx(key, TASK_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False
    elif plat == "darwin":
        plist = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")
        return os.path.isfile(plist)
    else:
        service_file = os.path.expanduser(
            f"~/.config/systemd/user/{SYSTEMD_SERVICE}.service"
        )
        return os.path.isfile(service_file)


def _remove_legacy_agent_bundle(target_dir: str) -> None:
    """Delete a schema-1 frozen-agent install, if one is here.

    Upgrading from <= 1.4.x leaves a ~2 GB CraftBotAgent/ folder that nothing
    will ever run again — the agent is no longer a PyInstaller bundle. Silence
    here would mean every upgraded machine quietly keeps it forever.

    User DATA is untouched: it lives in the per-user data dir, never in the
    install dir (see app/paths.py).
    """
    legacy = os.path.join(target_dir, "CraftBotAgent")
    if not os.path.isdir(legacy):
        return
    print("  Removing the previous frozen agent bundle (no longer used)…")
    try:
        shutil.rmtree(legacy)
    except OSError as e:
        # Not fatal — it wastes disk but breaks nothing.
        print(f"  (could not remove {legacy}: {e})")


def _full_install_frozen(
    target_dir: str,
    extra_args: List[str],
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> None:
    """Install CraftBot: fetch the source payload, provision a runtime around
    it, register auto-start, and launch.

    This no longer downloads a frozen agent. The agent used to ship as a
    PyInstaller bundle, which made an installer-based CraftBot a *different
    kind of thing* from a source install — different module graph, different
    data files, different embedding model — and every difference was a bug
    waiting to be found one at a time. Now the installer produces a real
    source install: the same tree a developer checks out, with an interpreter
    and dependency set provisioned by the same app.provision pipeline that
    `python install.py` runs.

    See docs/plans/unified-install-architecture.md.

    Args:
        target_dir: Directory to install the source into.
        extra_args: User-supplied flags (--cli, --browser, etc.).
        progress_cb: Optional download-progress callback (bytes_read, total_or_none).
    """
    if not IS_FROZEN:
        raise RuntimeError("_full_install_frozen called outside frozen mode")

    target_dir = os.path.normpath(target_dir)

    # 0. Stop anything running from this location first — on Windows an open
    #    file cannot be replaced, so extraction would fail midway and leave a
    #    half-written tree.
    if _stop_running_agent_if_alive():
        print("  Stopped running CraftBot before reinstalling.")

    _remove_legacy_agent_bundle(target_dir)

    # 1. Source payload.
    print(f"  Downloading CraftBot (version {_read_bundled_version()})…")
    zip_path = _payload.download_source_zip(BASE_DIR, EXE_PATH, progress_cb=progress_cb)
    try:
        src_root = _payload.extract_source_zip(zip_path, target_dir)
        # Stamp it BEFORE anything imports app.paths from that tree: the
        # payload contains install.py and requirements.txt, so without this
        # marker the installed copy looks exactly like a dev checkout and
        # would put the user's agent_file_system, databases and logs inside
        # the install directory — which the next upgrade replaces wholesale.
        paths.mark_managed_install(src_root)
        print(f"  Installed source at {src_root}")
    finally:
        # Only delete a copy we downloaded. A locally-staged zip beside the
        # installer is the dev workflow and must survive.
        if _payload.is_temp_zip(zip_path):
            try:
                os.unlink(zip_path)
            except OSError:
                pass

    # 2. Provision everything the source needs to run: the interpreter, the
    #    locked dependency set, Node, both npm trees, Playwright.
    #
    #    This is the same pipeline `python install.py` drives. The installer
    #    used to run NONE of it — that is why an installer-based machine had
    #    no Node at all and Agent App could not start.
    #
    #    CRAFTBOT_HOME is not set here: state belongs in the per-user data
    #    dir (app/paths.py), separate from this install dir, so an upgrade
    #    that replaces the source tree cannot take the user's data with it.
    from app import provision

    print("  Setting up the runtime — this takes a few minutes on first install.")
    ctx = provision.Context(
        code_root=src_root,
        state_root=str(paths.STATE_ROOT),
    )
    report = provision.install(log=print, ctx=ctx)

    resolved_python = None
    python_stage = dict(report.results).get("python")
    if python_stage is not None:
        resolved_python = python_stage.data.get("python")

    if not report.ok:
        print()
        print(provision.format_report(report))
        required_failed = [
            name
            for name, res in report.results
            if not res.ok
            and name in ("python", "python-deps", "native-runtime", "smoke", "frontend")
        ]
        if required_failed:
            raise RuntimeError(
                "Setup could not complete: "
                + ", ".join(required_failed)
                + ". Re-run the installer to retry — finished steps are not redone."
            )
        # Optional stages only (Playwright, the WhatsApp bridge): those
        # degrade a feature. Refusing to finish the install over one would be
        # worse than starting without it.
        print("  Some optional components are unavailable; continuing.")

    if not resolved_python:
        raise RuntimeError(
            "Setup finished without resolving a Python interpreter — cannot "
            "record how to start CraftBot."
        )

    # 3. Record what was installed and how to launch it. Schema 2: the install
    #    root plus the interpreter, because there is no longer an EXE to point
    #    at. installer/metadata.launch_command() is the only place that turns
    #    this back into a command.
    mode = "cli" if "--cli" in extra_args else "browser"
    write_install_metadata(
        src_root, mode, python=resolved_python, version=_read_bundled_version()
    )

    # 4. Copy the icon out of the bundled _MEIPASS dir into the persistent
    #    user data dir. The desktop shortcut's IconLocation points at this
    #    stable copy — _MEIPASS is wiped when the installer exits.
    persistent_icon = os.path.join(_user_data_dir(), "craftbot_logo_1.ico")
    persistent_png = os.path.join(_user_data_dir(), "craftbot_logo_1.png")
    for src, dest in ((LOGO_ICO, persistent_icon), (LOGO_PNG, persistent_png)):
        if os.path.isfile(src) and not os.path.isfile(dest):
            try:
                shutil.copy2(src, dest)
            except OSError as e:
                print(f"  (could not copy icon: {e})")

    # 5. Register auto-start.
    run_args = _build_run_args(extra_args, service_mode=True)
    _helpers.dispatch_per_platform(
        win=_install_windows, mac=_install_macos, linux=_install_linux
    )(run_args)

    # 6. Start.
    if not cmd_start(extra_args):
        raise RuntimeError("CraftBot installed but failed to start.")


def cmd_install(extra_args: List[str]) -> bool:
    """Install dependencies (source mode) or copy-and-register (frozen mode),
    then start the service."""
    if IS_FROZEN:
        # Frozen mode: skip pip, run the full installer in the default location.
        # The wizard provides a UI for picking a custom location; the CLI just
        # uses the default to keep `CraftBot.exe install` non-interactive.
        _warn_path_issues()
        target_dir = default_install_location()
        print(f"  {ORANGE}▸{RESET} {WHITE}Installing CraftBot to {target_dir}{RESET}")
        _full_install_frozen(target_dir, extra_args)
        return True

    _warn_path_issues()
    # ── Step 1: Install dependencies via install.py ────────────────────────
    install_script = os.path.join(BASE_DIR, "install.py")
    if os.path.isfile(install_script):
        _retro_step(1, 3, "Installing dependencies")
        # Pass through any user flags (--conda etc.) and add --no-launch
        install_flags = [
            a for a in extra_args if a in ("--conda", "--mamba", "--cpu-only")
        ]
        result = subprocess.run(
            [sys.executable, install_script, "--no-launch"] + install_flags,
            cwd=BASE_DIR,
        )
        if result.returncode != 0:
            print(
                f"\n  {RED}✗{RESET} {WHITE}Dependency installation failed. Aborting.{RESET}"
            )
            print(
                f"  {DIM}Run 'python install.py' directly to see the full error.{RESET}"
            )
            return False

        # Verify critical packages are actually importable with the interpreter
        # that will run the service. install.py may exit 0 while packages ended
        # up in a different site-packages. In conda mode they live in the env
        # from environment.yml, not necessarily in sys.executable.
        _imports = "import openai, anthropic, requests, aiohttp, websockets"
        if "--conda" in install_flags:
            _env_name = "craftbot"
            try:
                with open(os.path.join(BASE_DIR, "environment.yml")) as _f:
                    for _line in _f:
                        if _line.strip().startswith("name:"):
                            _env_name = _line.split(":", 1)[1].strip().strip("'\"")
                            break
            except OSError:
                pass
            _check_python = f"conda env '{_env_name}'"
            _check_cmd = [
                shutil.which("conda") or "conda",
                "run",
                "-n",
                _env_name,
                "python",
                "-c",
                _imports,
            ]
        else:
            # The interpreter install.py just recorded — not necessarily the
            # one running this script (see _installed_python).
            _check_python = _installed_python()
            _check_cmd = [_check_python, "-c", _imports]
        _critical_check = subprocess.run(_check_cmd, capture_output=True)
        if _critical_check.returncode != 0:
            print(
                f"\n  {RED}✗{RESET} {WHITE}Packages installed but not importable — wrong interpreter?{RESET}"
            )
            print(f"  {DIM}Checked interpreter: {_check_python}{RESET}")
            print(
                f"  {DIM}Run 'python install.py' to reinstall with this Python.{RESET}"
            )
            return False
        print()
    else:
        print(f"  {DIM}(install.py not found — skipping dependency install){RESET}\n")

    # ── Step 2: Start the service now ──────────────────────────────────────
    #
    # Starting BEFORE registering auto-start, not after. The macOS plist
    # carries RunAtLoad, so `launchctl load` starts an instance there and
    # then; registering first therefore left two run.py processes racing for
    # ports 7925/7926, and the loser died with "Failed to start browser
    # frontend" while the winner quietly served the UI. cmd_start's own guard
    # could not catch it — it reads craftbot.pid, which the launchd instance
    # has not written yet a second into its boot. Start first and the pid
    # exists by the time registration looks for it (see _install_macos).
    _retro_step(2, 3, "Starting CraftBot")
    if not cmd_start(extra_args):
        print(f"\n  {RED}✗{RESET} {WHITE}CraftBot failed to start.{RESET}")
        return False
    print()

    # ── Step 3: Register auto-start ────────────────────────────────────────
    if _is_installed():
        print(
            f"\n  {DIM}▸ STEP 3/3  ░░  AUTO-START ALREADY REGISTERED — SKIPPING{RESET}"
        )
        if _PLATFORM == "win32":
            _create_desktop_shortcut_windows()
        elif _PLATFORM != "darwin":
            _create_desktop_shortcut_unix()
    else:
        _retro_step(3, 3, "Registering auto-start")
        run_args = _build_run_args(extra_args, service_mode=True)
        _helpers.dispatch_per_platform(
            win=_install_windows, mac=_install_macos, linux=_install_linux
        )(run_args)
        print()

    print(f"\n  {GREEN}▸{RESET} {WHITE}CRAFTBOT IS RUNNING IN THE BACKGROUND{RESET}")
    print(f"  {DIM}░░{RESET} {ORANGE}{_frontend_url(extra_args)}{RESET}")
    print("You can close this window now.")
    time.sleep(2)
    _close_console_window()
    return True


def _remove_desktop_shortcut() -> None:
    """Remove the CraftBot desktop shortcut if it exists."""
    desktop = _find_desktop()
    if not desktop:
        return
    shortcut_path = os.path.join(
        desktop,
        _helpers.dispatch_per_platform(
            win=SHORTCUT_NAME, mac="CraftBot.command", linux="CraftBot.desktop"
        ),
    )
    if os.path.isfile(shortcut_path):
        try:
            os.remove(shortcut_path)
            print(f"Desktop shortcut removed: {shortcut_path}")
        except Exception as e:
            print(f"Warning: Could not remove desktop shortcut — {e}")


def cmd_uninstall() -> None:
    """Remove auto-start registration and uninstall dependencies."""
    # Stop the service first if running
    _stop_running_agent_if_alive(grace_s=0)

    # Clean up PID file
    _remove_pid()

    # Remove auto-start registration
    _helpers.dispatch_per_platform(
        win=_uninstall_windows, mac=_uninstall_macos, linux=_uninstall_linux
    )()

    # Remove desktop shortcut
    _remove_desktop_shortcut()

    if IS_FROZEN:
        # Frozen mode: remove the install dir and everything in the user data
        # dir EXCEPT a small allow-list of user-generated state. Deletes:
        #   - The extracted agent install dir (Programs\CraftBot\CraftBotAgent)
        #   - %LOCALAPPDATA%\CraftBot\: bootstrapped folders (app/, agents/,
        #     assets/, skills/), logs, PID, icons, install metadata,
        #     config.json, .env.example, rthook marker
        # Keeps in %LOCALAPPDATA%\CraftBot\:
        #   - agent_file_system/  (memory, conversation history, workspace)
        #   - chroma_db_memory/   (vector store)
        # Reinstall regenerates everything else from the bundled defaults.
        _remove_pid()
        installed = installed_exe_path()
        install_dir = None
        if installed:
            # Schema 2 records the install ROOT (a directory holding run.py).
            # Schema 1 recorded the agent EXE, so walk up from it — and up
            # again past the CraftBotAgent/ wrapper the old zip extracted to.
            if os.path.isdir(installed):
                install_dir = installed
            elif os.path.isfile(installed):
                install_dir = os.path.dirname(installed)
                if os.path.basename(install_dir).lower() == "craftbotagent":
                    install_dir = os.path.dirname(install_dir)
        if install_dir and os.path.isdir(install_dir):
            try:
                shutil.rmtree(install_dir, ignore_errors=False)
                print(f"Removed installed directory: {install_dir}")
            except OSError as e:
                print(f"Warning: could not remove {install_dir} — {e}")
                print("(It may be in use; close the wizard / stop CraftBot first.)")

        # Compute user data dir path independently of _user_data_dir() (that
        # helper recreates the dir, which we don't want here).
        if _PLATFORM == "win32":
            _root = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
                r"~\AppData\Local"
            )
            user_data = os.path.join(_root, "CraftBot")
        elif _PLATFORM == "darwin":
            user_data = os.path.expanduser("~/Library/Application Support/CraftBot")
        else:
            _root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
                "~/.local/share"
            )
            user_data = os.path.join(_root, "craftbot")

        # Allow-list: anything else in user_data gets removed.
        keep = {"agent_file_system", "chroma_db_memory"}
        if os.path.isdir(user_data):
            removed_any = False
            for entry in os.listdir(user_data):
                if entry in keep:
                    continue
                path = os.path.join(user_data, entry)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
                    removed_any = True
                except OSError as e:
                    print(f"Warning: could not remove {path} — {e}")
            if removed_any:
                print(
                    f"Cleaned bootstrapped files in {user_data} (kept: {', '.join(sorted(keep))})"
                )

        # Final: clear install metadata. Done last so the print() lines above
        # could still reference installed_exe_path() if needed.
        clear_install_metadata()

        print("\nUninstall complete.")
        return

    # Source mode: uninstall pip packages.
    #
    # Not for a managed install: there the interpreter is a sidecar under the
    # user data directory that the launcher removes wholesale right after
    # this returns, so uninstalling packages from it one by one would only
    # add minutes to the uninstall.
    if paths.is_managed_install():
        print("\n(managed install — the launcher removes the runtime)")
        print("\nUninstall complete.")
        return

    req_file = os.path.join(BASE_DIR, "requirements.txt")
    if os.path.isfile(req_file):
        print("\nUninstalling pip packages...")
        subprocess.run(
            [_installed_python(), "-m", "pip", "uninstall", "-r", req_file, "-y"],
            cwd=BASE_DIR,
        )
    else:
        print("\n(requirements.txt not found — skipping pip uninstall)")

    # Purge pip cache
    print("\nPurging pip cache...")
    subprocess.run([_installed_python(), "-m", "pip", "cache", "purge"])

    print("\nUninstall complete.")


def cmd_repair(
    extra_args: List[str],
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> None:
    """Re-download and re-extract the agent payload over the installed location,
    then re-register and restart. Useful for upgrading: a newer installer EXE
    is pinned to a newer agent version, and Repair fetches that version.

    Args:
        extra_args: User flags (--cli, etc.).
        progress_cb: Optional download-progress callback (bytes_read, total_or_none).
    """
    if not IS_FROZEN:
        print(f"  {DIM}Repair is only meaningful for frozen EXE installs.{RESET}")
        print(
            f"  {DIM}For source installs, just `git pull` and `python craftbot.py restart`.{RESET}"
        )
        return

    meta = read_install_metadata()
    if not meta:
        print(
            f"  {RED}✗{RESET} {WHITE}No install metadata found — run install first.{RESET}"
        )
        return

    installed = meta["installed_path"]
    if _metadata.schema_of(meta) >= 2:
        # Schema 2 records the install root directly.
        target_dir = installed
    else:
        # Schema 1 recorded the agent EXE: walk up to the directory it was
        # extracted into, past the CraftBotAgent/ wrapper if present. Repair
        # from a legacy install is also the upgrade path — the reinstall below
        # replaces the frozen bundle with a real source install and
        # _remove_legacy_agent_bundle() deletes what it superseded.
        target_dir = os.path.dirname(installed)
        if os.path.basename(target_dir).lower() == "craftbotagent":
            target_dir = os.path.dirname(target_dir)
    print(f"  Repairing CraftBot at {target_dir}")

    # Stop the existing service so we can overwrite the agent files
    _stop_running_agent_if_alive()

    # Re-run the install flow at the existing location with the existing mode
    mode_flag_map = {"cli": ["--cli"], "browser": []}
    mode_args = mode_flag_map.get(meta.get("mode", "browser"), [])
    _full_install_frozen(target_dir, mode_args + extra_args, progress_cb=progress_cb)
    print("\n  REPAIR COMPLETE")


# ─── Utility ──────────────────────────────────────────────────────────────────


def _get_parent_pid() -> Optional[int]:
    """Return the PID of the parent process (cmd.exe / terminal)."""
    try:
        result = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                f"ProcessId={os.getpid()}",
                "get",
                "ParentProcessId",
                "/value",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "ParentProcessId=" in line:
                return int(line.split("=")[1].strip())
    except Exception:
        pass
    return None


def _close_console_window() -> None:
    """Close the current console/terminal window on Windows then exit.

    Only when this process owns a console. Launched from a script, a pipe or
    the CraftBot launcher, the "parent" is not a cmd.exe window at all — it
    is whatever started us, and killing it would take the launcher's window
    down with it.
    """
    if _PLATFORM != "win32" or not sys.stdout.isatty():
        sys.exit(0)
    # Use PowerShell to kill the parent cmd.exe after a short delay
    try:
        parent_pid = _get_parent_pid()
        if parent_pid:
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Start-Sleep -Milliseconds 500; Stop-Process -Id {parent_pid} -Force -ErrorAction SilentlyContinue",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_helpers.detached_popen_flags(),
            )
    except Exception:
        pass
    sys.exit(0)


def _timestamp() -> str:
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _usage() -> None:
    print(__doc__)


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]

    # Whatever `python` launched us is a trampoline: hop onto the project's
    # interpreter (the one the dependencies live in) before doing anything.
    if not IS_FROZEN and _python_runtime is not None:
        _python_runtime.reexec_if_needed()

    # Frozen EXE double-clicked with no args → launch the Tkinter wizard.
    # Source installs (no IS_FROZEN) keep the legacy "print usage" behaviour
    # so `python craftbot.py` still helps developers find the CLI.
    if not args and IS_FROZEN:
        from installer.wizard import launch_wizard

        launch_wizard()
        return

    if not args or args[0] in ("-h", "--help"):
        _usage()
        return

    command = args[0]
    rest = args[1:]

    if command == "start":
        if not cmd_start(rest):
            sys.exit(1)

    elif command == "stop":
        cmd_stop()

    elif command == "restart":
        if not cmd_restart(rest):
            sys.exit(1)

    elif command == "status":
        cmd_status()

    elif command == "logs":
        n = 50
        if "-n" in rest:
            idx = rest.index("-n")
            try:
                n = int(rest[idx + 1])
            except (IndexError, ValueError):
                print("Warning: invalid -n value, using 50")
        cmd_logs(n)

    elif command == "install":
        if not cmd_install(rest):
            sys.exit(1)

    elif command == "uninstall":
        cmd_uninstall()

    elif command == "repair":
        cmd_repair(rest)

    elif command == "wizard":
        # Explicit wizard launch (works even on source installs for dev/testing).
        from installer.wizard import launch_wizard

        launch_wizard()

    elif command == "doctor":
        # Every provisioning stage's check(), and nothing else — no downloads,
        # no installs. This is the same pipeline `install` runs, so what it
        # reports is exactly what an install would act on. Answers "why won't
        # it start?" without anyone guessing which of the three install paths
        # this machine went through.
        from app import provision

        report = provision.doctor(log=print)
        print()
        print(provision.format_report(report))
        print()
        print(f"  code : {paths.CODE_ROOT}")
        print(f"  state: {paths.STATE_ROOT}")
        if not report.ok:
            print("\n  Run `python craftbot.py install` to fix.")
            sys.exit(1)

    else:
        print(f"Unknown command: '{command}'")
        print("Run 'python craftbot.py --help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
