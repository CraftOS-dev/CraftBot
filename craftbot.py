#!/usr/bin/env python3
"""
CraftBot Service Manager

Run CraftBot as a background process that survives terminal closure,
and optionally register it to auto-start when your system boots.

Commands:
    python craftbot.py start [options]    Start CraftBot in background
    python craftbot.py open               Open CraftBot in the browser, starting it
                                          first if it is not running (desktop icon)
    python craftbot.py stop               Stop CraftBot
    python craftbot.py restart [options]  Stop then start
    python craftbot.py status             Show if CraftBot is running
    python craftbot.py logs [-n N]        Show last N log lines (default: 50)
    python craftbot.py tui [options]      Open the terminal edition in this console,
                                          starting CraftBot in the background first
                                          if it is not running
    python craftbot.py install [options]  Register for auto-start on boot/login
    python craftbot.py autostart enable   Enable automatic startup at login
    python craftbot.py autostart disable  Disable automatic startup (keep installed)
    python craftbot.py autostart status   Show automatic startup status
    python craftbot.py uninstall          Remove auto-start registration
    python craftbot.py repair [options]   Re-copy current EXE over the installed
                                          copy and restart (frozen EXE only)
    python craftbot.py wizard             Open the GUI wizard

When running as a frozen EXE (CraftBot.exe with no args), the wizard opens
automatically. Subcommands work the same as in source mode.

Options passed to 'start' / 'install':
    --tui                   Run the terminal edition instead of the browser (the
                            backend runs in the background; open it with `tui`)
    --no-open-browser       Don't open browser automatically (default for service)
    --frontend-port PORT    Frontend port (default: 7925, or the next free pair)
    --backend-port PORT     Backend port (default: 7926, or the next free pair)
    --agent-app-port PORT   First Agent App port, apps get PORT to PORT+99 (default: 3100)
    --conda                 Use conda environment
    --no-conda              Don't use conda
    --no-autostart          Install without automatic startup at login

'start' waits until CraftBot answers (or prints why it stopped).

Examples:
    python craftbot.py start                   # Start in background (browser mode)
    python craftbot.py tui                     # Open the terminal edition
    python craftbot.py install                 # Auto-start on login (browser mode)
    python craftbot.py install --no-open-browser  # Auto-start without opening browser
    python craftbot.py stop
    python craftbot.py logs -n 100
"""

import sys
import os

# In windowed (console=False) PyInstaller builds, sys.stdout and sys.stderr
# are None. Lots of libraries (including run.py at import time) call
# sys.stdout.isatty() unconditionally and crash with AttributeError. Install
# an output handle before ANY other import that might transitively hit
# stdout. Must be the very first thing this module does.
if sys.stdout is None or sys.stderr is None:
    # Real handles can also be passed through an interpreter handoff.
    output = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = output
    if sys.stderr is None:
        sys.stderr = output

import shlex
import shutil
import signal
import subprocess
import time
import webbrowser
from typing import Callable, List, Optional

from installer import helpers as _helpers
from installer import metadata as _metadata
from installer import payload as _payload
from installer import startup as _startup

# Store platform once so static analysers don't short-circuit platform branches
_PLATFORM: str = sys.platform

# ─── Frozen-mode detection ────────────────────────────────────────────────────

# True when running as a PyInstaller-bundled EXE. The frozen EXE is the
# *installer* — a small Tkinter wizard that downloads the agent payload from
# GitHub Releases and installs it into a chosen location. The installer does
# NOT contain the agent itself (no run.py, no openai/anthropic/etc bundled).
IS_FROZEN: bool = bool(getattr(sys, "frozen", False))
EXE_PATH: Optional[str] = sys.executable if IS_FROZEN else None

# --state-root=PATH names this install's data folder. The desktop icon passes
# it because, like a login start, it does not inherit CRAFTBOT_HOME from the
# shell that installed CraftBot. Applied before any app module is imported
# (app.paths resolves STATE_ROOT at import time) and removed from the args.
for _argument in list(sys.argv[1:]):
    if _argument.startswith("--state-root="):
        os.environ["CRAFTBOT_HOME"] = _argument.split("=", 1)[1]
        sys.argv.remove(_argument)

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


# The running CraftBot as seen from outside (app/instance.py). One pid file
# and one log for every launcher: run.py writes the pid file itself, so
# craftbot.py, the desktop launcher and service managers all read the same
# record, in STATE_ROOT next to the user's data.
from app import instance as _instance  # noqa: E402

PID_FILE = str(_instance.PID_FILE)
LOG_FILE = str(_instance.LOG_FILE)
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

from app.console import configure_console  # noqa: E402 -- after windowed stream initialization

configure_console()

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
    # On Windows prefer pythonw.exe (no console window): the service never
    # talks to a console (the terminal edition's client is `craftbot.py tui`)
    if _PLATFORM == "win32":
        pythonw = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.isfile(pythonw):
            return pythonw
    return python


# A pid alone is not an identity: once CraftBot exits (crash, reboot) the OS
# reuses the number, and `stop` would kill whatever holds it now — with /T,
# its whole tree. The PID file therefore also records the process's start
# time, and a pid is only treated as CraftBot when both still match.
_START_TIME_TOLERANCE_S = 2.0  # macOS `ps lstart` has 1s resolution


def _read_pid_record() -> Optional[tuple]:
    """(pid, recorded start time or None, file mtime), or None if no file.
    Accepts the legacy bare-integer format (no start time)."""
    try:
        with open(PID_FILE) as f:
            raw = f.read().strip()
        mtime = os.path.getmtime(PID_FILE)
    except OSError:
        return None
    try:
        if raw.startswith("{"):
            import json

            data = json.loads(raw)
            started = data.get("started")
            return int(data["pid"]), (float(started) if started else None), mtime
        return int(raw), None, mtime
    except (ValueError, KeyError, TypeError):
        return None


def _owned_pid() -> Optional[int]:
    """The pid in the PID file IF that process is still the CraftBot we
    started; otherwise None. A stale record (process gone, or pid reused by
    another program) is removed so nothing ever acts on it."""
    record = _read_pid_record()
    if record is None:
        return None
    pid, started, mtime = record
    actual = _helpers.process_start_time(pid)
    if actual is None:
        _remove_pid()
        return None
    if started is not None:
        ours = abs(actual - started) <= _START_TIME_TOLERANCE_S
    else:
        # Legacy file (or start time unreadable at spawn): the file was
        # written right after the spawn, so our process started before it.
        # A reused pid belongs to a process started after ours died — i.e.
        # after the file was written.
        ours = actual <= mtime + _START_TIME_TOLERANCE_S
    if not ours:
        _remove_pid()
        return None
    return pid


def _write_pid(pid: int) -> None:
    import json

    with open(PID_FILE, "w") as f:
        json.dump({"pid": pid, "started": _helpers.process_start_time(pid)}, f)


def _remove_pid() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def _claim_service_process() -> bool:
    """Publish a login service's PID without replacing an already running app."""
    if _owned_pid():
        print("CraftBot is already running; skipping automatic startup.")
        return False
    _write_pid(os.getpid())
    return True


def _release_service_process(pid: int) -> None:
    # A manual restart may already have replaced our PID record.
    if _owned_pid() == pid:
        _remove_pid()


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
        if arg in ("--frontend-port", "--backend-port", "--agent-app-port"):
            if i + 1 < len(args):
                result.extend([arg, args[i + 1]])
                skip_next = True
            continue
        if arg.startswith(("--frontend-port=", "--backend-port=", "--agent-app-port=")):
            result.append(arg)
    return result


def _tail_log_lines(n: int = 30, start_offset: int = 0) -> str:
    if not os.path.isfile(LOG_FILE):
        return ""
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            if start_offset:
                f.seek(start_offset)
            lines = f.readlines()
    except Exception:
        return ""
    return "".join(lines[-n:])


#: How long cmd_start waits for the agent to finish booting. Minutes, not
#: seconds: a first run downloads the embedding model, and on a slow
#: connection that dominates startup. Running out is not a failure while the
#: process is alive; start then says it is still starting.
BROWSER_READY_TIMEOUT_S = 600
#: How often cmd_start prints a progress line while it waits.
_PROGRESS_EVERY_S = 30
#: Log lines shown when a start fails.
_FAILURE_LOG_LINES = 40


def _clear_agent_ready() -> None:
    """Drop any previous run's readiness marker and ui.json before we launch."""
    try:
        paths.AGENT_READY_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    _instance.remove_ui()


def _ui_ready(start_offset: int = 0) -> bool:
    """Has this launch reached the point where the UI answers?

    run.py writes ui.json once the backend answers, after the agent's own
    ready marker. The ready banner in the log is kept only for an older
    installed run.py that predates ui.json. (The log used to be the ONLY
    signal, and run.py's stdout is a log FILE here, so the banner could sit
    unflushed in a buffer long after the agent was serving.)
    """
    if _instance.read_ui() is not None:
        return True
    return CRAFTBOT_READY_MARKER in _tail_log_lines(200, start_offset)


def _wait_until_ready(proc, start_offset: int, timeout: float) -> str:
    """Wait for the CraftBot just launched: "ready", "exited" or "timeout".

    Watches the process the whole time. This used to look for an early exit
    for 8 seconds only, and then wait up to 10 minutes for readiness without
    noticing that the process had died, so a crash at second 9 was reported
    as a running CraftBot.
    """
    started = time.time()
    next_note = started + _PROGRESS_EVERY_S
    while True:
        if proc.poll() is not None:
            return "exited"
        if _ui_ready(start_offset):
            return "ready"
        now = time.time()
        if now - started >= timeout:
            return "timeout"
        if now >= next_note:
            print(
                f"  {DIM}Still starting ({int(now - started)}s)...{RESET}", flush=True
            )
            next_note += _PROGRESS_EVERY_S
        time.sleep(0.5)


def _current_url(args: Optional[List[str]] = None) -> str:
    """Where the UI is. An explicit --frontend-port names it (run.py uses or
    refuses the ports it is given); otherwise ui.json of the running
    CraftBot does, as its ports move when another program holds 7925/7926;
    else the default address."""
    args = args or []
    if not _parse_port_arg(args, "--frontend-port", 0):
        ui = _instance.read_ui()
        if ui:
            return str(ui["url"])
    return _frontend_url(args)


def _is_running(pid: int) -> bool:
    """Return True if a process with the given PID is currently alive."""
    return _helpers.process_start_time(pid) is not None


def _orphan_listeners(args: Optional[List[str]] = None) -> List[tuple]:
    """(pid, description) for CraftBots of THIS installation on our ports
    that no PID file covers.

    Only this state root's own CraftBot counts (app.instance
    .belongs_to_this_home). A CraftBot from another checkout or another
    CRAFTBOT_HOME on the same port is a separate installation that is
    working for someone: it is never reported as an orphan of this one, and
    so never stopped by this one.

    Read-only — `status` reports them, `stop` acts on them.
    """
    try:
        from app.process_ledger import craftbot_listeners
    except Exception:
        return []  # psutil missing (pre-dependency install) — nothing to say
    ports = {
        _parse_port_arg(args or [], "--frontend-port", DEFAULT_FRONTEND_PORT),
        _parse_port_arg(args or [], "--backend-port", DEFAULT_BACKEND_PORT),
    }
    # The ports the last run actually used, when it had to move.
    ui = _instance.read_ui() or {}
    for key in ("frontend_port", "backend_port"):
        if isinstance(ui.get(key), int):
            ports.add(ui[key])
    found: List[tuple] = []
    for port in sorted(ports):
        for pid, description in craftbot_listeners(port):
            if pid in {p for p, _ in found}:
                continue
            if _instance.belongs_to_this_home(pid):
                found.append((pid, description))
    return found


def _stop_orphan_listeners(args: Optional[List[str]] = None) -> int:
    """Stop CraftBots on our ports that no PID file accounts for.

    The PID file is the normal way to find the running agent, and it is not
    enough on its own. It lives in STATE_ROOT, so an uninstall deletes it
    while the process it described keeps running — after which `stop` says
    "not running", `uninstall` leaves it alive, and the next install finds
    :7925 taken by something no CraftBot command can reach. The launcher log
    shows the other half of it: "could not remove runtime: Access is denied",
    because the orphan still has the DLLs open.

    Identity still has to be proved (app.process_ledger.identify_craftbot) —
    this finds candidates by port but only ever kills a process that
    describes itself as CraftBot.
    """
    orphans = _orphan_listeners(args)
    if not orphans:
        return 0
    from app.process_ledger import kill_tree

    stopped = 0
    failures = []
    for pid, description in orphans:
        print(
            f"  {ORANGE}▸{RESET} {WHITE}STOPPING ORPHANED CRAFTBOT{RESET}"
            f"  {DIM}{description}{RESET}"
        )
        try:
            kill_tree(pid)
            stopped += 1
        except Exception as e:
            print(f"  {DIM}(could not stop pid {pid}: {e}){RESET}")
            failures.append(str(pid))
    if failures:
        raise RuntimeError(
            "Could not stop orphaned CraftBot pids: " + ", ".join(failures)
        )
    return stopped


def _stop_running_agent_if_alive(
    grace_s: float = 1.0, args: Optional[List[str]] = None
) -> bool:
    """If an agent is currently running, stop it and pause briefly so the OS
    releases file handles before we try to overwrite the agent EXE. Used by
    install/repair so reinstall over a running agent doesn't fail with
    "Permission denied" on Windows. Returns True if a process was stopped.
    """
    if cmd_stop(quiet=True, args=args):
        time.sleep(grace_s)
        return True
    return False


def _build_run_args(extra: List[str], service_mode: bool = True) -> List[str]:
    """Build the argument list for run.py.

    Adds --no-open-browser by default in service mode (auto-start at boot
    should not pop open a browser without the user asking). The terminal
    edition's service serves the backend only: a background process has no
    console for the terminal client, which `craftbot.py tui` attaches.
    """
    args = list(extra)
    if "--tui" in args:
        if "--backend-only" not in args:
            args.append("--backend-only")
    elif service_mode and "--no-open-browser" not in args:
        args.append("--no-open-browser")
    return args


# ─── Core operations ──────────────────────────────────────────────────────────


def _open_browser_detached(url: str) -> None:
    """Open the UI in the user's browser.

    cmd_start only calls this once run.py has reported the UI as reachable
    (ui.json), so there is nothing left to poll for.
    """
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"  {DIM}Could not open a browser ({e}). Open {url} yourself.{RESET}")


_CLI_RETIRED = (
    "The CLI was replaced by the terminal edition.\n"
    "  Run it in this terminal:  python run.py --tui\n"
    "  Or as a service:  python craftbot.py start --tui, then python craftbot.py tui"
)


def _child_env() -> dict:
    """Environment for a CraftBot Python child (run.py, install.py, checks):
    nothing from the user's shell that would make CraftBot's interpreter load
    foreign packages (app.python_runtime.isolated_env), no proxy for
    loopback, and UTF-8 output."""
    if _python_runtime is not None and hasattr(_python_runtime, "isolated_env"):
        env = _python_runtime.isolated_env(os.environ)
    else:
        env = os.environ.copy()
    _instance.with_no_proxy(env)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def cmd_start(extra_args: List[str]) -> bool:
    """Start CraftBot as a detached background process.

    Returns True once the UI answers, or while the process is alive but still
    starting when the wait runs out. False when it exits first: then the last
    log lines and the log path are printed.
    """
    if "--cli" in extra_args:
        print(f"  {RED}✗{RESET} {WHITE}{_CLI_RETIRED}{RESET}")
        return False

    # Unconditional, not `if _owned_pid()`: the thing most likely to be
    # holding our port is the CraftBot this install has no PID file for.
    cmd_stop(quiet=True, args=extra_args)

    run_args = _build_run_args(extra_args, service_mode=False)
    terminal_edition = "--tui" in run_args
    # Always pass --no-open-browser to run.py; craftbot.py handles opening the browser
    if not terminal_edition and "--no-open-browser" not in run_args:
        run_args.append("--no-open-browser")

    if IS_FROZEN:
        # Launching an install is metadata.launch_command()'s job — it is the
        # only place that knows the difference between a schema-2 install
        # ([python, run.py]) and a legacy schema-1 frozen bundle ([agent.exe]).
        # Spreading that knowledge is how the entry points drifted before.
        launch = _metadata.launch_command(INSTALL_METADATA_FILE)
        if not launch:
            print("Error: no usable install found. Run install first.")
            return False
        cmd = launch + run_args
    else:
        cmd = [_python_exe(), RUN_SCRIPT] + run_args

    # Clear the readiness marker and ui.json BEFORE launching, so what the
    # previous run left cannot make this one look instantly ready.
    _clear_agent_ready()

    # UTF-8 with replace so the agent's Unicode banner / box-drawing chars
    # don't crash on Windows where the default file encoding is cp1252.
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    log_fh = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log_fh.write(f"\n{'=' * 60}\n")
    log_fh.write(f"CraftBot service started at {_timestamp()}\n")
    log_fh.write(f"Command: {' '.join(cmd)}\n")
    log_fh.write(f"{'=' * 60}\n")
    log_fh.flush()
    ready_log_offset = log_fh.tell()

    kwargs = dict(
        cwd=BASE_DIR,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=_child_env(),
        **_helpers.detached_popen_flags(new_process_group=True),
    )

    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except (FileNotFoundError, OSError) as e:
        log_fh.close()
        print(f"  {RED}✗{RESET} {WHITE}Could not launch CraftBot: {e}{RESET}")
        return False

    # Parent closes its copy — the child process (run.py) keeps the fd open
    log_fh.close()

    print(
        f"  {DIM}Starting CraftBot. This can take a few minutes on the first start.{RESET}"
    )
    state = _wait_until_ready(proc, ready_log_offset, BROWSER_READY_TIMEOUT_S)

    if state == "exited":
        # run.py removes its pid file on a clean exit; a crash may leave one.
        if _owned_pid() is None:
            _remove_pid()
        print(
            f"  {RED}✗{RESET} {WHITE}CraftBot failed to start{RESET}"
            f"  {DIM}exit {proc.returncode}{RESET}"
        )
        log_tail = _tail_log_lines(_FAILURE_LOG_LINES)
        if log_tail:
            print(f"\n{DIM}Last log lines:{RESET}\n{log_tail}", end="")
            if not log_tail.endswith("\n"):
                print()
        print(f"\nFull log: {LOG_FILE}")
        return False

    # run.py writes its own pid (after any interpreter hop) as it starts; an
    # older run.py does not, so record the process we launched instead.
    pid = _owned_pid()
    if pid is None:
        _write_pid(proc.pid)
        pid = proc.pid

    browser_url = _current_url(extra_args)
    if state == "timeout":
        print(
            f"  {GREEN}▸{RESET} {WHITE}CRAFTBOT IS STILL STARTING{RESET}  {DIM}PID {pid}{RESET}"
        )
        where = (
            "with: python craftbot.py tui" if terminal_edition else f"at {browser_url}"
        )
        print(
            f"  {DIM}It will be available {where} when it finishes. "
            f"Follow its progress with: python craftbot.py logs{RESET}"
        )
        return True

    print(f"  {GREEN}▸{RESET} {WHITE}CRAFTBOT STARTED{RESET}  {DIM}PID {pid}{RESET}")
    if terminal_edition:
        # No web UI and no desktop icon: the client is `craftbot.py tui`.
        print(f"  {DIM}░░{RESET} {WHITE}Open it with: python craftbot.py tui{RESET}")
        return True
    print(f"  {DIM}░░{RESET} {ORANGE}{browser_url}{RESET}")

    # Create a desktop shortcut so the user can reopen the browser anytime
    if _PLATFORM == "win32":
        _create_desktop_shortcut_windows(extra_args)
    else:
        _create_desktop_shortcut_unix(extra_args)

    if "--no-open-browser" not in extra_args:
        _open_browser_detached(browser_url)

    return True


def cmd_tui(extra_args: List[str]) -> int:
    """Open the terminal edition in this console.

    Attaches to the CraftBot this state root is running, whichever edition its
    backend serves, on the port its ui.json names. When none runs, starts the
    terminal edition in the background first. Quitting the client leaves the
    service running, so scheduled and proactive work goes on; `craftbot.py
    stop` stops it.
    """
    from app import edition, node_runtime

    ui = _instance.read_ui()
    if ui is None or not _instance.http_answers(str(ui["url"])):
        if _owned_pid() is not None and _wait_for_running(
            _owned_pid(), extra_args, lambda text: None
        ):
            ui = _instance.read_ui()
        else:
            start_args = list(extra_args)
            if "--tui" not in start_args:
                start_args.append("--tui")
            if not cmd_start(start_args):
                return 1
            ui = _instance.read_ui()
    port = (
        int(ui["backend_port"])
        if ui and isinstance(ui.get("backend_port"), int)
        else _parse_port_arg(extra_args, "--backend-port", DEFAULT_BACKEND_PORT)
    )

    bundle = edition.terminal_client_bundle()
    node = node_runtime.node_cmd()
    if not node:
        print(f"  {RED}✗{RESET} {WHITE}Node.js 24 or later is required{RESET}")
        print(f"  {DIM}Run `python craftbot.py install` to set it up.{RESET}")
        return 1
    if not bundle.is_file():
        print(f"  {RED}✗{RESET} {WHITE}The terminal client is not built{RESET}")
        print(f"  {DIM}Restart it: python craftbot.py restart --tui{RESET}")
        return 1
    try:
        return subprocess.run(
            [
                node,
                str(bundle),
                "--port",
                str(port),
                "--state-dir",
                str(paths.STATE_ROOT),
                "--log",
                LOG_FILE,
            ],
            env=node_runtime.child_env(),
        ).returncode
    except KeyboardInterrupt:
        return 130


def _running_ui_url(args: List[str]) -> Optional[str]:
    """The address of THIS install's CraftBot when it answers, else None.

    ui.json is written by this state root's run.py once its UI answers, so it
    names our CraftBot even when its ports moved. Without one (an older
    run.py), a listener that app.instance proves to be ours counts too. A
    program on 7925 that is not this CraftBot never does.
    """
    ui = _instance.read_ui()
    if ui and _instance.http_answers(str(ui["url"])):
        return str(ui["url"])
    if _orphan_listeners(args):
        url = _current_url(args)
        if _instance.http_answers(url):
            return url
    return None


def _wait_for_running(pid: int, args: List[str], status) -> Optional[str]:
    """Wait for a CraftBot that is already starting (a login start, or a
    second click on the icon) instead of starting another one. Its address
    once it answers; None when it exits or never answers."""
    started = time.time()
    while time.time() - started < BROWSER_READY_TIMEOUT_S:
        url = _running_ui_url(args)
        if url:
            return url
        if not _is_running(pid):
            return None
        status("CraftBot is starting. Your browser opens when it is ready.")
        time.sleep(1)
    return None


def _start_lock() -> str:
    return str(paths.STATE_ROOT / ".opening.lock")


def _claim_start() -> Optional[int]:
    """Become the one icon click that starts CraftBot.

    None when this process holds the lock now; otherwise the pid of the
    click that is already starting CraftBot. People double-click an icon
    twice: without this both clicks started CraftBot, and the second start's
    cleanup stopped the first one. A lock whose holder is gone is taken over.
    """
    for _ in range(2):
        try:
            fd = os.open(_start_lock(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                with open(_start_lock(), encoding="utf-8") as f:
                    holder = int(f.read().strip() or 0)
            except (OSError, ValueError):
                holder = 0
            if holder and holder != os.getpid() and _is_running(holder):
                return holder
            try:
                os.remove(_start_lock())
            except OSError:
                pass
            continue
        except OSError:
            return None  # an unwritable state root must not block the start
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return None
    return None


def _release_start() -> None:
    try:
        with open(_start_lock(), encoding="utf-8") as f:
            mine = f.read().strip() == str(os.getpid())
        if mine:
            os.remove(_start_lock())
    except (OSError, ValueError):
        pass


def _start_failure() -> str:
    tail = _tail_log_lines(8).strip().splitlines()
    detail = tail[-1][:300] if tail else "The start did not complete."
    return f"{detail}\n\nFull log: {LOG_FILE}"


def _open_or_start(args: List[str], status) -> tuple:
    """(ok, failure detail): open CraftBot, starting it first if needed."""
    url = _running_ui_url(args)
    if url is None:
        pid = _owned_pid()
        if pid is not None:
            url = _wait_for_running(pid, args, status)
    if url:
        _open_browser_detached(url)
        return True, None

    other_click = _claim_start()
    if other_click is not None:
        # Another click is starting CraftBot right now: wait for that start,
        # then for CraftBot itself if it is still booting when that click
        # stops waiting.
        url = _wait_for_running(other_click, args, status)
        if url is None and _owned_pid() is not None:
            url = _wait_for_running(_owned_pid(), args, status)
        if url:
            _open_browser_detached(url)
            return True, None
        return False, _start_failure()

    try:
        status("Starting CraftBot. Your browser opens when it is ready.")
        # cmd_start opens the browser itself once the UI answers.
        if cmd_start(_port_args(args)):
            return True, None
        return False, _start_failure()
    finally:
        _release_start()


def _has_console() -> bool:
    """True when started from a terminal; the desktop icon has none."""
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def cmd_open(extra_args: List[str]) -> bool:
    """What the desktop icon runs: show CraftBot in the browser, starting it
    first when it is not running.

    Never starts a second copy: a CraftBot that is already starting (the
    login start, or an earlier click) is waited for, not replaced. Started
    from the icon there is no console, so progress and any failure are shown
    in a small window instead; from a terminal they are printed.
    """
    if IS_FROZEN:
        # The legacy installer EXE has no run.py next to it to start.
        _open_browser_detached(_current_url(extra_args))
        return True

    url = _running_ui_url(extra_args)
    if url:  # the common case, and no window at all for it
        _open_browser_detached(url)
        return True

    if _has_console():
        said: List[str] = []

        def say(text: str) -> None:
            line = text.splitlines()[0]
            if not said or said[-1] != line:  # each message once, not per poll
                said.append(line)
                print(f"  {DIM}{line}{RESET}", flush=True)

        ok, detail = _open_or_start(extra_args, say)
        if not ok and detail:
            print(f"  {RED}✗{RESET} {WHITE}CraftBot could not start.{RESET}\n{detail}")
        return ok

    from installer.open_window import run_with_window

    return run_with_window(
        lambda status: _open_or_start(extra_args, status), log_file=LOG_FILE
    )


def cmd_stop(quiet: bool = False, args: Optional[List[str]] = None) -> bool:
    """Stop the running CraftBot service. True if anything was stopped.

    Two passes, because the PID file only covers a CraftBot that THIS install
    started. The port sweep covers the one it does not: an agent left running
    by a previous install, whose PID file went with it. Without that pass
    `stop` reported "not running" at an agent that was plainly still serving
    on :7925.

    `quiet` suppresses only the nothing-to-do message, for callers (install,
    uninstall) where "not running" is the expected case and not news. `args`
    carries --frontend-port/--backend-port through, so a non-default port is
    swept too.
    """
    had_record = _read_pid_record() is not None
    pid = _owned_pid()  # verified by start time; a reused pid is never ours
    stopped = False

    if pid is not None:
        stopped = True
        print(
            f"  {ORANGE}▸{RESET} {WHITE}STOPPING CRAFTBOT{RESET}  {DIM}PID {pid}{RESET}"
        )
        _kill_owned_pid(pid)
        _remove_pid()
        print(f"  {GREEN}▸{RESET} {WHITE}CRAFTBOT STOPPED{RESET}")

    if _stop_orphan_listeners(args):
        stopped = True

    # A forced termination (and a reboot) cannot run the agent's cleanup.
    # Do not leave the previous process's readiness or ui.json behind.
    _clear_agent_ready()

    if not stopped and not quiet:
        if had_record:
            print(f"  {DIM}▸ CraftBot not running — cleaned up stale PID file{RESET}")
        else:
            print("CraftBot does not appear to be running (no PID file found).")
    return stopped


def _kill_owned_pid(pid: int) -> None:
    """Terminate a pid already verified as ours, with its whole tree."""
    if _PLATFORM == "win32":
        from app.process_ledger import kill_tree

        kill_tree(pid)
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


def cmd_status() -> None:
    """Print whether CraftBot is currently running and whether auto-start is installed."""
    W = max(50, len(LOG_FILE) + 12)
    pid = _owned_pid()
    print(f"\n{ORANGE}╔{'═' * W}╗{RESET}")
    if pid:
        print(
            f"{ORANGE}║{RESET}  {GREEN}▸ RUNNING{RESET}  {DIM}PID {pid}{RESET}{' ' * (W - 17 - len(str(pid)))}{ORANGE}║{RESET}"
        )
        ui = _instance.read_ui()
        _url = f"░░ URL: {ui['url']}" if ui else "░░ URL: (still starting)"
        _url = _url[: W - 2]
        print(
            f"{ORANGE}║{RESET}  {DIM}{_url}{RESET}{' ' * max(0, W - 2 - len(_url))}{ORANGE}║{RESET}"
        )
        print(
            f"{ORANGE}║{RESET}  {DIM}░░ LOG: {LOG_FILE[: W - 8]}{RESET}{' ' * max(0, W - 10 - len(LOG_FILE[: W - 8]))}{ORANGE}║{RESET}"
        )
    else:
        print(
            f"{ORANGE}║{RESET}  {RED}▸ NOT RUNNING{RESET}{' ' * (W - 15)}{ORANGE}║{RESET}"
        )
        # "NOT RUNNING" on its own is a lie when a CraftBot from a previous
        # install is still serving on our port — which is precisely the state
        # someone runs `status` to understand.
        for _pid, _what in _orphan_listeners():
            _line = f"  ▸ ORPHAN ON OUR PORT: pid {_pid}"[: W - 1]
            print(
                f"{ORANGE}║{RESET}{RED}{_line}{RESET}"
                f"{' ' * max(0, W - len(_line))}{ORANGE}║{RESET}"
            )
            _hint = "    run `craftbot.py stop` to clear it"[: W - 1]
            print(
                f"{ORANGE}║{RESET}{DIM}{_hint}{RESET}"
                f"{' ' * max(0, W - len(_hint))}{ORANGE}║{RESET}"
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
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
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
    cmd_stop(args=extra_args)
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


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _open_command(extra_args: Optional[List[str]] = None) -> Optional[List[str]]:
    """What the desktop icon runs: `craftbot.py open` for this install, or
    None for the legacy installer EXE (its icon only opens the browser).

    It names the state root and keeps any custom ports, because the icon does
    not inherit CRAFTBOT_HOME or the install's arguments. On Windows it is
    pythonw, so no console window appears; `open` shows its own small window
    only while CraftBot starts.
    """
    if IS_FROZEN:
        return None
    python = _python_exe() if _PLATFORM == "win32" else _installed_python()
    return [
        python,
        os.path.abspath(__file__),
        "open",
        f"--state-root={paths.STATE_ROOT.resolve()}",
    ] + _port_args(extra_args or [])


def _create_desktop_shortcut_windows(extra_args: Optional[List[str]] = None) -> None:
    """Create a .lnk shortcut on the Windows Desktop with the CraftBot icon.

    It runs `craftbot.py open` (_open_command): the browser opens straight
    away when CraftBot is running, and CraftBot is started first when it is
    not. The link is rewritten every time, so upgrades and port changes take
    effect.
    """
    desktop = _find_desktop()
    if not desktop:
        return
    url = _current_url(extra_args)
    shortcut_path = os.path.join(desktop, SHORTCUT_NAME)
    # Refresh existing links too: upgrades and custom ports must take effect.
    ico_path = _ensure_ico()
    command = _open_command(extra_args)
    try:
        # Write the PS script to a temp file with UTF-8-BOM so PowerShell
        # handles non-ASCII paths (e.g. Japanese Desktop folder) correctly.
        import tempfile

        if command:
            target = command[0]
            arguments = subprocess.list2cmdline(command[1:])
            working_dir = BASE_DIR
            window_style = 1  # pythonw: there is no console to show
        else:
            target = "cmd.exe"
            arguments = '/c start "" ' + url
            working_dir = ""
            window_style = 7  # minimized (hides the cmd flash)
        ps_lines = [
            "$ws = New-Object -ComObject WScript.Shell",
            f"$s = $ws.CreateShortcut({_ps_literal(shortcut_path)})",
            f"$s.TargetPath = {_ps_literal(target)}",
            f"$s.Arguments = {_ps_literal(arguments)}",
            f"$s.WorkingDirectory = {_ps_literal(working_dir)}",
            f"$s.WindowStyle = {window_style}",
        ]
        if ico_path:
            ps_lines.append(f"$s.IconLocation = {_ps_literal(ico_path + ',0')}")
        ps_lines += [
            '$s.Description = "Open CraftBot"',
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
                check=True,
                **_quiet_windows_flags(),
            )
        finally:
            try:
                os.remove(tmp_ps1)
            except Exception:
                pass
        if os.path.exists(shortcut_path):
            print(f"  Desktop shortcut created: {shortcut_path}")
            print(
                "  Double-click it anytime to open CraftBot; it starts CraftBot "
                "first if it is not running."
            )
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


def _desktop_entry_arg(arg: str) -> str:
    r"""One Exec= argument, quoted per the Desktop Entry spec.

    An argument with a reserved character goes in double quotes, inside which
    " ` $ and \ are escaped with a backslash. The file's string escaping is
    applied on top, so each backslash is then written twice, and a literal %
    is written %%.
    """
    reserved = set(" \t\n\"'\\><~|&;$*?#()`")
    if arg and not any(c in reserved for c in arg):
        return arg.replace("%", "%%")
    quoted = "".join("\\" + c if c in '"`$\\' else c for c in arg)
    return '"' + quoted.replace("\\", "\\\\").replace("%", "%%") + '"'


def _create_desktop_shortcut_unix(extra_args: Optional[List[str]] = None) -> None:
    """Create a desktop shortcut on Linux or macOS.

    Like the Windows one it runs `craftbot.py open` (_open_command): the
    browser opens straight away when CraftBot is running, and CraftBot is
    started first when it is not.
    """
    if extra_args is None:
        extra_args = []
    desktop = _find_desktop()
    if not desktop:
        return
    try:
        # Where the UI is: its ports move when another program holds them.
        browser_url = _current_url(extra_args)
        command = _open_command(extra_args)
        if _PLATFORM == "darwin":
            # macOS does not support XDG .desktop files — create a double-clickable .command script
            shortcut_path = os.path.join(desktop, "CraftBot.command")
            if command:
                line = " ".join(shlex.quote(part) for part in command)
            else:
                line = f"open {shlex.quote(browser_url)}"
            content = f"#!/bin/sh\nexec {line}\n"
            with open(shortcut_path, "w") as f:
                f.write(content)
            os.chmod(shortcut_path, 0o755)
        else:
            # Linux: standard XDG .desktop entry
            shortcut_path = os.path.join(desktop, "CraftBot.desktop")
            if command:
                exec_line = " ".join(_desktop_entry_arg(part) for part in command)
            else:
                open_cmd = (
                    "xdg-open"
                    if os.path.isfile("/usr/bin/xdg-open")
                    or os.path.isfile("/usr/local/bin/xdg-open")
                    else "sensible-browser"
                )
                exec_line = f"{open_cmd} {browser_url}"
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=CraftBot\n"
                f"Exec={exec_line}\n"
                "Icon=web-browser\n"
                "Terminal=false\n"
            )
            with open(shortcut_path, "w") as f:
                f.write(content)
            os.chmod(shortcut_path, 0o755)
        print(f"  Desktop shortcut created: {shortcut_path}")
        print(
            "  Double-click it anytime to open CraftBot; it starts CraftBot "
            "first if it is not running."
        )
    except Exception as e:
        print(f"  (Could not create desktop shortcut: {e})")


# ─── Auto-start: environment of a login start ─────────────────────────────────


#: Network settings the user had when registering auto-start: proxies,
#: package mirrors and certificates. Task Scheduler, launchd and systemd do
#: not inherit the installing shell's environment, so without them Agent App
#: creation (npm, the PocketBase download) and model downloads fail at boot
#: behind a proxy or mirror that worked from the terminal.
_NETWORK_ENV = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_CERT",
    "npm_config_registry",
    "NPM_CONFIG_REGISTRY",
    "HF_ENDPOINT",
    "CRAFTBOT_MIRRORS",
    "SSL_CERT_FILE",
)


def _captured_settings() -> List[tuple]:
    """CraftBot and network settings from this environment, set ones only.
    (Windows names are case-insensitive, so each is taken once there.)

    CRAFTBOT_HOME is not among them: the registered command names the state
    root itself (--state-root, see _autostart_launch)."""
    names = ("CRAFTBOT_BIND_HOST",) + _NETWORK_ENV
    found: List[tuple] = []
    seen = set()
    for name in names:
        key = name.upper() if _PLATFORM == "win32" else name
        if key in seen:
            continue
        seen.add(key)
        value = os.environ.get(name)
        if value:
            found.append((key, value))
    return found


def _service_environment() -> List[tuple]:
    """Environment a launchd agent or systemd service needs, captured at
    install time.

    launchd and systemd start programs with a minimal PATH, on which Homebrew
    or .pkg Node, conda and git are not found: CraftBot then could not start
    its UI or its MCP servers at login although it worked from a terminal.
    Whatever this shell could run, the service can run, with the same
    CraftBot and network settings.
    """
    env = [
        ("PATH", os.environ.get("PATH", "")),
        ("PYTHONUNBUFFERED", "1"),
        ("PYTHONUTF8", "1"),
        ("PYTHONNOUSERSITE", "1"),
    ]
    for name in ("LANG", "LC_ALL"):
        value = os.environ.get(name)
        if value:
            env.append((name, value))
    env.extend(_captured_settings())
    return [(k, v) for k, v in env if v]


def _service_env_file() -> str:
    """Windows has no per-task environment: the captured settings go to this
    file, and run.py loads it when the login task starts it (--service)."""
    return os.path.join(str(paths.STATE_ROOT), "service-env.json")


def _write_service_env_file() -> bool:
    """Write the captured settings for a Windows login start. True if any."""
    import json

    settings = dict(_captured_settings())
    path = _service_env_file()
    try:
        if not settings:
            if os.path.isfile(path):
                os.remove(path)
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except OSError as e:
        print(f"Warning: could not save network settings for auto-start: {e}")
        return False


# ─── Auto-start: Windows Task Scheduler ───────────────────────────────────────


def _quiet_windows_flags() -> dict:
    return {"creationflags": 0x08000000} if _PLATFORM == "win32" else {}


def _autostart_launch(run_args: List[str]) -> Optional[List[str]]:
    launch = _installed_launch() if IS_FROZEN else [_python_exe(), RUN_SCRIPT]
    if not launch:
        print("No installed CraftBot found — run install first.")
        return None
    args = _build_run_args(run_args)
    if os.path.basename(launch[-1]) == "run.py":
        if "--service" not in args:
            args.append("--service")
        # Login managers do not inherit CRAFTBOT_HOME / XDG_DATA_HOME from
        # the installation shell. Keep the same data and preferences after
        # login, including when the user relocated them.
        args.append(f"--state-root={paths.STATE_ROOT.resolve()}")
    return launch + args


def _remove_windows_registry() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, TASK_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        print(f"Could not remove the old login registry entry: {exc}")
        return False


def _install_windows_registry(action: str) -> bool:
    """Fallback: register auto-start via HKCU Run registry key (no admin needed)."""
    try:
        import winreg

        key = winreg.CreateKeyEx(
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


def _install_windows(run_args: List[str]) -> bool:
    import csv
    import tempfile

    # Task Scheduler has no per-task environment: the network settings of
    # this shell go to service-env.json, which run.py --service loads.
    _write_service_env_file()

    command = _autostart_launch(run_args)
    if not command:
        return False
    directory = (
        os.path.dirname(command[1])
        if len(command) > 1 and command[1].endswith(".py")
        else BASE_DIR
    )
    # XML separates the executable from its arguments, preserving Unicode and
    # spaces without relying on 8.3 names. Configure background-app settings
    # explicitly; schtasks /sc ONLOGON otherwise inherits battery/72h limits.
    registered = False
    xml_file = None
    try:
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            **_quiet_windows_flags(),
        )
        user = next(csv.reader([identity.stdout.strip()]))[1]
        if not user.startswith("S-1-"):
            raise ValueError("Could not determine the current Windows user SID")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-16"
        ) as f:
            xml_file = f.name
            f.write(_startup.windows_task_xml(command, directory, user))
        result = subprocess.run(
            ["schtasks", "/create", "/tn", TASK_NAME, "/xml", xml_file, "/f"],
            capture_output=True,
            text=True,
            timeout=30,
            **_quiet_windows_flags(),
        )
        registered = result.returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        print(f"Task Scheduler registration unavailable: {exc}")
    finally:
        if xml_file:
            os.remove(xml_file)

    if registered:
        # An earlier non-admin installation may have used HKCU Run. Keep only
        # one launch trigger, rather than starting two agents at the next login.
        registered = _remove_windows_registry()
    else:
        # Remove an obsolete task before falling back, so its old action cannot
        # race the updated registry action. A missing task is fine.
        try:
            query = subprocess.run(
                ["schtasks", "/query", "/tn", TASK_NAME],
                capture_output=True,
                timeout=10,
                **_quiet_windows_flags(),
            )
            if query.returncode == 0:
                subprocess.run(
                    ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                    capture_output=True,
                    check=True,
                    timeout=15,
                    **_quiet_windows_flags(),
                )
            registered = _install_windows_registry(subprocess.list2cmdline(command))
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Could not replace the old startup task: {exc}")
    if registered:
        print("Auto-start registered. CraftBot will start automatically on login.")
        _create_desktop_shortcut_windows(run_args)
    else:
        print(
            "Could not register auto-start. Run 'python craftbot.py autostart enable' to retry."
        )
    return registered


def _uninstall_windows(*, stop: bool = True) -> bool:
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

    try:
        os.remove(_service_env_file())
    except OSError:
        pass

    if not removed_any:
        print("No auto-start registration found (already uninstalled?).")
    return not _is_installed()


# ─── Auto-start: Linux systemd (user service) ─────────────────────────────────


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", encoding="utf-8", errors="replace") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _systemd_running() -> bool:
    """systemd is PID 1 (sd_booted: /run/systemd/system exists)."""
    return os.path.isdir("/run/systemd/system")


def _explain_missing_systemd() -> None:
    """After a failed registration: say why when systemd is not running."""
    if _systemd_running():
        return
    if _is_wsl():
        print("systemd is not running in this WSL distribution. To enable it, add")
        print("these lines to /etc/wsl.conf:")
        print("  [boot]")
        print("  systemd=true")
        print(
            "then run `wsl --shutdown` in Windows, reopen WSL and run this command again."
        )
    else:
        print("This system does not run systemd, so it cannot start CraftBot at login.")
    print(
        "To install without automatic startup: python craftbot.py install --no-autostart"
    )


def _print_linger_hint() -> None:
    """A user unit stops when the user's last session ends (SSH logout)
    unless lingering is enabled for that user."""
    import getpass

    user = getpass.getuser()
    try:
        result = subprocess.run(
            ["loginctl", "show-user", user, "--property=Linger", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if result.returncode == 0 and (result.stdout or "").strip() == "yes":
        return
    print("\nCraftBot stops when you log out of your last session on this machine.")
    print("To keep it running after you log out (for example over SSH), run once:")
    print(f"  sudo loginctl enable-linger {user}")


def _install_linux(run_args: List[str]) -> bool:
    service_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(service_dir, exist_ok=True)

    service_file = os.path.join(service_dir, f"{SYSTEMD_SERVICE}.service")
    command = _autostart_launch(run_args)
    if not command:
        return False
    exec_start = " ".join(_startup.systemd_quote(arg, command=True) for arg in command)
    directory = (
        os.path.dirname(command[1])
        if len(command) > 1 and command[1].endswith(".py")
        else BASE_DIR
    )
    # systemd starts the service with a minimal environment: carry over the
    # PATH and network settings of the shell that registered it.
    environment = "\n".join(
        f"Environment={_startup.systemd_quote(f'{name}={value}')}"
        for name, value in _service_environment()
    )

    content = f"""[Unit]
Description=CraftBot AI Agent
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={_startup.systemd_path(directory)}
Restart=on-failure
RestartSec=5
{environment}

[Install]
WantedBy=default.target
"""
    with open(service_file, "w", encoding="utf-8") as f:
        f.write(content)

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=10)
        subprocess.run(
            ["systemctl", "--user", "enable", SYSTEMD_SERVICE], check=True, timeout=10
        )
        url = _current_url(run_args)
        print(f"Auto-start registered as systemd user service '{SYSTEMD_SERVICE}'.")
        print("CraftBot will start automatically when you log in.")
        print(f"\nOpen CraftBot: {url}")
        print(f"  Tip: Bookmark {url} so you never have to remember it!")
        _create_desktop_shortcut_unix(run_args)
        print(f"\nTo start it now: systemctl --user start {SYSTEMD_SERVICE}")
        print(f"To view logs:    journalctl --user -u {SYSTEMD_SERVICE} -f")
        _print_linger_hint()
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error enabling systemd service: {e}")
        print(f"Service file written to: {service_file}")
        print(
            "Try manually: systemctl --user daemon-reload && systemctl --user enable craftbot"
        )
    except FileNotFoundError:
        print("systemctl not found. Is systemd running on this system?")
    _explain_missing_systemd()
    return False


def _uninstall_linux(*, stop: bool = True) -> bool:
    service_file = os.path.expanduser(
        f"~/.config/systemd/user/{SYSTEMD_SERVICE}.service"
    )
    try:
        subprocess.run(
            ["systemctl", "--user", "disable", SYSTEMD_SERVICE],
            capture_output=True,
            timeout=10,
        )
        if stop:
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

    return not os.path.isfile(service_file)


# ─── Auto-start: macOS launchd ────────────────────────────────────────────────


def _install_macos(run_args: List[str]) -> bool:
    import plistlib

    agents_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(agents_dir, exist_ok=True)

    plist_file = os.path.join(agents_dir, f"{LAUNCHD_LABEL}.plist")
    program_args = _autostart_launch(run_args)
    if not program_args:
        return False
    directory = (
        os.path.dirname(program_args[1])
        if len(program_args) > 1 and program_args[1].endswith(".py")
        else BASE_DIR
    )
    with open(plist_file, "wb") as f:
        plistlib.dump(
            {
                "Label": LAUNCHD_LABEL,
                "ProgramArguments": program_args,
                "WorkingDirectory": directory,
                "RunAtLoad": True,
                "KeepAlive": False,
                "StandardOutPath": LOG_FILE,
                "StandardErrorPath": LOG_FILE,
                # launchd starts agents with a minimal environment: carry over
                # the PATH and network settings of the shell that registered it.
                "EnvironmentVariables": dict(_service_environment()),
            },
            f,
        )

    # launchd reads ~/Library/LaunchAgents at login. Do not load RunAtLoad
    # now: changing the login preference must not start a second agent.
    print(f"Auto-start registered as launchd agent '{LAUNCHD_LABEL}'.")
    print("CraftBot will start automatically at your next login.")
    _print_launchd_hints(plist_file, run_args)
    return True


def _print_launchd_hints(plist_file: str, run_args: List[str]) -> None:
    url = _current_url(run_args)
    print(f"\nOpen CraftBot: {url}")
    print(f"  Tip: Bookmark {url} so you never have to remember it!")
    _create_desktop_shortcut_unix(run_args)
    print(f"\nPlist file: {plist_file}")


def _uninstall_macos(*, stop: bool = True) -> bool:
    plist_file = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")
    if os.path.isfile(plist_file):
        try:
            if stop:
                subprocess.run(
                    ["launchctl", "unload", plist_file], capture_output=True, timeout=10
                )
        except Exception:
            pass
        os.remove(plist_file)
        print("Auto-start removed.")
    else:
        print("No launchd agent found.")
    return not os.path.isfile(plist_file)


# ─── Install / Uninstall dispatch ─────────────────────────────────────────────


def _is_installed() -> bool:
    """Return True if CraftBot is registered for auto-start on this platform."""
    plat = _PLATFORM
    if plat == "win32":
        # Check Task Scheduler
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", TASK_NAME, "/xml"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                import xml.etree.ElementTree as ET

                root = ET.fromstring(result.stdout)
                enabled = root.find("{*}Settings/{*}Enabled")
                if enabled is None or enabled.text != "false":
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
        if not os.path.isfile(service_file):
            return False
        try:
            return (
                subprocess.run(
                    ["systemctl", "--user", "is-enabled", "--quiet", SYSTEMD_SERVICE],
                    capture_output=True,
                    timeout=10,
                ).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError):
            return False


def _startup_options(extra_args: List[str]) -> tuple:
    settings = _startup.read(paths.STATE_ROOT)
    enabled = settings["enabled"] and "--no-autostart" not in extra_args
    return _startup.merge_args(settings["args"], extra_args), enabled


def _configure_autostart(enabled: bool, run_args: List[str]) -> bool:
    """Refresh OS registration on every install/repair, honoring an opt-out."""
    if enabled and "--cli" in run_args:
        print(f"  {RED}✗{RESET} {WHITE}{_CLI_RETIRED}{RESET}")
        return False
    try:
        if enabled:
            ok = _helpers.dispatch_per_platform(
                win=_install_windows, mac=_install_macos, linux=_install_linux
            )(_build_run_args(run_args))
        else:
            ok = _helpers.dispatch_per_platform(
                win=_uninstall_windows, mac=_uninstall_macos, linux=_uninstall_linux
            )(stop=False)
        if not ok:
            print(
                "Automatic startup could not be updated; installation is not complete."
            )
            return False
        _startup.write(paths.STATE_ROOT, enabled, run_args)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Could not update automatic startup: {exc}")
        return False


def cmd_autostart(args: List[str]) -> bool:
    if not args or args[0] not in ("enable", "disable", "status"):
        print("Usage: python craftbot.py autostart enable|disable|status [options]")
        return False
    action = args[0]
    if action == "status":
        print(
            "Automatic startup at login: "
            + ("enabled" if _is_installed() else "disabled")
        )
        return True
    try:
        settings = _startup.read(paths.STATE_ROOT)
    except (ValueError, OSError):
        # An explicit command can repair corrupt preference data.
        settings = {"args": []}
    run_args = _startup.merge_args(settings["args"], args[1:])
    if not _configure_autostart(action == "enable", run_args):
        return False
    print(
        f"Automatic startup {'enabled' if action == 'enable' else 'disabled'} for future logins."
    )
    return True


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
        extra_args: User-supplied flags (--tui, --conda, etc.).
        progress_cb: Optional download-progress callback (bytes_read, total_or_none).
    """
    if not IS_FROZEN:
        raise RuntimeError("_full_install_frozen called outside frozen mode")

    extra_args, auto_start = _startup_options(extra_args)
    target_dir = os.path.normpath(target_dir)

    from app import paths, provision
    from app.provision.default_agent_app import is_new_install, prepare_install

    install_context = provision.Context(
        code_root=target_dir,
        state_root=str(paths.STATE_ROOT),
        new_install=read_install_metadata() is None
        and is_new_install(str(paths.STATE_ROOT)),
    )
    prepare_install(install_context)

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
    print("  Setting up the runtime — this takes a few minutes on first install.")
    ctx = install_context
    ctx.code_root = src_root
    report = provision.install(log=print, ctx=ctx)

    resolved_python = None
    python_stage = dict(report.results).get("python")
    if python_stage is not None:
        resolved_python = python_stage.data.get("python")

    if not report.ok:
        print()
        print(provision.format_report(report))
        required_failed = [name for name, _ in report.required_failures]
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
    mode = "tui" if "--tui" in extra_args else "browser"
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

    # Start before registering RunAtLoad on macOS, as in source installs.
    if not cmd_start(extra_args):
        raise RuntimeError("CraftBot installed but failed to start.")
    if not _configure_autostart(auto_start, extra_args):
        raise RuntimeError(
            "CraftBot started but automatic startup could not be configured."
        )


def _recorded_conda() -> Optional[str]:
    """config.json `conda_executable`: the conda install.py used, by path."""
    try:
        import json

        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
            path = json.load(f).get("conda_executable")
    except (OSError, ValueError, AttributeError):
        return None
    return path if isinstance(path, str) and os.path.isfile(path) else None


def _install_failed(message: str, hint: Optional[str] = None) -> bool:
    """Report a failed install and keep its window open long enough to read."""
    print(f"\n  {RED}✗{RESET} {WHITE}{message}{RESET}")
    if hint:
        print(f"  {DIM}{hint}{RESET}")
    _hold_console_on_failure()
    return False


def cmd_install(extra_args: List[str]) -> bool:
    """Install dependencies (source mode) or copy-and-register (frozen mode),
    then start the service."""
    if "--cli" in extra_args:
        print(f"  {RED}✗{RESET} {WHITE}{_CLI_RETIRED}{RESET}")
        return False
    if IS_FROZEN:
        # Frozen mode: skip pip, run the full installer in the default location.
        # The wizard provides a UI for picking a custom location; the CLI just
        # uses the default to keep `CraftBot.exe install` non-interactive.
        _warn_path_issues()
        target_dir = default_install_location()
        print(f"  {ORANGE}▸{RESET} {WHITE}Installing CraftBot to {target_dir}{RESET}")
        _full_install_frozen(target_dir, extra_args)
        return True

    extra_args, auto_start = _startup_options(extra_args)
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
            env=_child_env(),
        )
        if result.returncode != 0:
            return _install_failed(
                "Dependency installation failed. Aborting.",
                "Run 'python install.py' directly to see the full error.",
            )

        # install.py just recorded the interpreter it provisioned (often a
        # downloaded sidecar). This process resolved — and cached — before
        # that existed, so drop the cache or the check, start and auto-start
        # below all fall back to the launcher Python (e.g. a system 3.14).
        if _python_runtime is not None:
            _python_runtime.resolve(refresh=True)

        # Verify critical packages are actually importable with the interpreter
        # that will run the service. install.py may exit 0 while packages ended
        # up in a different site-packages. In conda mode they live in the env
        # from environment.yml, not necessarily in sys.executable.
        _imports = "import openai, anthropic, requests, aiohttp, websockets"
        if "--conda" in install_flags:
            _env_name = "craftbot"
            try:
                # UTF-8 explicitly: environment.yml holds non-ASCII text, and
                # the locale encoding (cp936, cp932...) cannot decode it.
                with open(
                    os.path.join(BASE_DIR, "environment.yml"), encoding="utf-8"
                ) as _f:
                    for _line in _f:
                        if _line.strip().startswith("name:"):
                            _env_name = _line.split(":", 1)[1].strip().strip("'\"")
                            break
            except (OSError, UnicodeDecodeError):
                pass
            _check_python = f"conda env '{_env_name}'"
            _check_cmd = [
                _recorded_conda() or shutil.which("conda") or "conda",
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
        _critical_check = subprocess.run(
            _check_cmd, capture_output=True, env=_child_env()
        )
        if _critical_check.returncode != 0:
            print(f"  {DIM}Checked interpreter: {_check_python}{RESET}")
            return _install_failed(
                "Packages installed but not importable. Wrong interpreter?",
                "Run 'python install.py' to reinstall with this Python.",
            )
        print()
    else:
        print(f"  {DIM}(install.py not found, skipping dependency install){RESET}\n")

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
        return _install_failed(
            "CraftBot failed to start.",
            f"The log above shows why. Full log: {LOG_FILE}",
        )
    print()

    # ── Step 3: Register auto-start ────────────────────────────────────────
    _retro_step(3, 3, "Updating automatic startup")
    if not _configure_autostart(auto_start, extra_args):
        _hold_console_on_failure()
        return False
    print()

    url = _current_url(extra_args)
    if _instance.read_ui() is not None:
        print(
            f"\n  {GREEN}▸{RESET} {WHITE}CRAFTBOT IS RUNNING IN THE BACKGROUND{RESET}"
        )
    else:
        print(
            f"\n  {GREEN}▸{RESET} {WHITE}CRAFTBOT IS STARTING IN THE BACKGROUND{RESET}"
        )
        print(f"  {DIM}It will be available at this address when it finishes.{RESET}")
    print(f"  {DIM}░░{RESET} {ORANGE}{url}{RESET}")
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

    # Source mode: remove what CraftBot itself provisioned, and nothing else.
    #
    # This used to `pip uninstall -r requirements.txt` and `pip cache purge`
    # on whichever interpreter was recorded, which could be the user's own
    # Python: it stripped packages other programs depended on and emptied a
    # cache that was not ours. CraftBot's interpreter and Node are private
    # copies under STATE_ROOT/runtime, so removing that directory removes
    # them; the npm trees it installed are removed too.
    #
    # Not for a managed install: there the launcher removes the runtime
    # right after this returns.
    if paths.is_managed_install():
        print("\n(managed install: the launcher removes the runtime)")
        print("\nUninstall complete.")
        return

    targets = [
        os.path.join(BASE_DIR, *rel.split("/"), "node_modules")
        for rel in (
            "app/ui_layer/browser/frontend",
            "agent-app",
            "craftos_integrations/providers/whatsapp_web",
        )
    ]
    targets.append(str(paths.RUNTIME_DIR))
    for target in targets:
        if os.path.isdir(target):
            _remove_tree_now_or_after_exit(target)

    print("\nUninstall complete.")


def _remove_tree_now_or_after_exit(path: str) -> None:
    """Delete a directory. On Windows a file in use (this very interpreter,
    when it is the private one) cannot be deleted; then the rest is removed
    by a hidden cmd.exe once this process has exited."""
    print(f"Removing {path}")
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.isdir(path):
        return
    if _PLATFORM != "win32":
        print(f"Warning: could not remove everything in {path}. Delete it yourself.")
        return
    try:
        subprocess.Popen(
            [
                "cmd.exe",
                "/d",
                "/c",
                f'ping -n 4 127.0.0.1 >nul & rmdir /s /q "{path}"',
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_helpers.detached_popen_flags(),
        )
        print("  (some files are in use and are removed when this window closes)")
    except OSError as e:
        print(f"Warning: could not remove {path}: {e}")


def cmd_repair(
    extra_args: List[str],
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> None:
    """Re-download and re-extract the agent payload over the installed location,
    then re-register and restart. Useful for upgrading: a newer installer EXE
    is pinned to a newer agent version, and Repair fetches that version.

    Args:
        extra_args: User flags (--tui, etc.).
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
    mode_flag_map = {"tui": ["--tui"], "browser": []}
    mode_args = mode_flag_map.get(meta.get("mode", "browser"), [])
    _full_install_frozen(target_dir, mode_args + extra_args, progress_cb=progress_cb)
    print("\n  REPAIR COMPLETE")


# ─── Utility ──────────────────────────────────────────────────────────────────


def _console_owned_alone() -> bool:
    """True when the console window exists only for this CraftBot command.

    That is the case when craftbot.py was started by double-clicking (or by
    the launcher with a fresh console): the window closes by itself once we
    exit. Any other process on the console (cmd.exe, PowerShell, an IDE
    terminal) means it is the user's window. A python.exe parent is the
    interpreter hop of app.python_runtime, which belongs to us.
    """
    if _PLATFORM != "win32":
        return False
    try:
        import ctypes

        buffer = (ctypes.c_uint32 * 16)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buffer, 16)
    except Exception:
        return False
    if count <= 0 or count > 16:
        return False
    ours = {os.getpid()}
    try:
        import psutil

        parent = psutil.Process().parent()
        if parent is not None and parent.name().lower().startswith("python"):
            ours.add(parent.pid)
    except Exception:
        pass
    return all(pid in ours for pid in list(buffer)[:count])


def _hold_console_on_failure() -> None:
    """Never let a failure vanish with its window: when the window is only
    ours (it would close the moment we exit), wait for Enter first."""
    if not _console_owned_alone():
        return
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("\nPress Enter to close this window.")
    except (EOFError, OSError, KeyboardInterrupt):
        pass


def _close_console_window() -> None:
    """Finish a successful install.

    Never kills another process: this used to find the parent shell with
    wmic (gone from Windows 11 24H2) and force-stop it, which took IDE
    terminals and the user's own shells down with it. A window that exists
    only for this command closes by itself when we exit; any other window is
    the user's to close.
    """
    if _console_owned_alone():
        print("This window will close in a moment.")
        time.sleep(3)
    else:
        print("You can close this window now.")


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
            _hold_console_on_failure()
            sys.exit(1)

    elif command == "open":
        # What the desktop icon runs.
        if not cmd_open(rest):
            sys.exit(1)

    elif command == "stop":
        cmd_stop(args=rest)

    elif command == "restart":
        if not cmd_restart(rest):
            _hold_console_on_failure()
            sys.exit(1)

    elif command == "tui":
        sys.exit(cmd_tui(rest))

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

    elif command == "autostart":
        if not cmd_autostart(rest):
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
