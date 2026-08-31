#!/usr/bin/env python3
"""
CraftBot Run Script

Usage:
    python run.py             # Run the agent (browser interface - default)
    python run.py --cli       # Run in CLI mode

Options:
    --cli                     Use CLI (command line) interface
    --conda                   Use conda environment (overrides config setting)
    --no-conda                Don't use conda (overrides config setting)
    --frontend-port PORT      Set frontend port (default: 7925)
    --backend-port PORT       Set backend port (default: 7926)
    --no-open-browser         Start servers but do not auto-open the browser (used by service mode)

Note: The installation method (conda/pip) is saved from install.py and reused here.
"""

import multiprocessing
import os
import sys
import json
import subprocess
import shutil
import time
import urllib.request
import urllib.error
import webbrowser
import atexit
from typing import Tuple, Optional, Dict, Any, List

from app.runtime_preflight import (
    ensure_runtime_dependencies,
    mark_runtime_dependencies_checked,
)
from app import python_runtime

# Single resolved Node runtime — see app/node_runtime.py. install.py
# downloads the sidecar when nothing suitable exists; run.py never installs.
from app import node_runtime

multiprocessing.freeze_support()

CRAFTBOT_READY_MARKER = "CRAFTBOT IS READY"

# Configuration is loaded from settings.json via the agent startup
# No .env file is used - all settings come from app/config/settings.json

# --- Base directory ---
# app.paths is the single answer to code-vs-state (see app/paths.py). It is
# stdlib-only, so importing it here — before dependencies exist — is safe.
from app import paths as _paths  # noqa: E402

BASE_DIR = str(_paths.CODE_ROOT)


def _bootstrap_state():
    """Seed the per-user state directory from the shipped defaults.

    A managed install keeps CODE in the install directory (replaced wholesale
    by the next upgrade, and on Windows not reliably writable) and STATE in
    the per-user data dir. The app expects mutable app/config, app/data,
    agents, assets and skills trees, so on first run they are copied across.

    Only ever copies what is ABSENT — a user's edited settings.json or their
    customised skills must survive every upgrade.

    A dev checkout is skipped: there, code and state are the same tree, which
    is what makes a checkout convenient to work in.
    """
    if _paths.is_dev_checkout():
        return

    import shutil as _shutil

    user_data = str(_paths.STATE_ROOT)
    os.makedirs(user_data, exist_ok=True)

    # Switch CWD so any code still using relative paths writes into the state
    # dir rather than the install dir.
    os.chdir(user_data)

    src_root = str(_paths.CODE_ROOT)

    dirs_to_copy = [
        "app/config",
        "app/data",
        "agents",
        "assets",
        "skills",
    ]
    files_to_copy = [
        "config.json",
        ".env.example",
    ]

    for rel_dir in dirs_to_copy:
        src = os.path.join(src_root, rel_dir)
        dst = os.path.join(user_data, rel_dir)
        if os.path.isdir(src) and not os.path.isdir(dst):
            print(f"  Bootstrapping {rel_dir}/...")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _shutil.copytree(src, dst)

    for rel_file in files_to_copy:
        src = os.path.join(src_root, rel_file)
        dst = os.path.join(user_data, rel_file)
        if os.path.isfile(src) and not os.path.isfile(dst):
            print(f"  Bootstrapping {rel_file}...")
            _shutil.copy2(src, dst)


_bootstrap_state()

# --- Configuration ---
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
MAIN_APP_SCRIPT = os.path.join(BASE_DIR, "main.py")
YML_FILE = os.path.join(BASE_DIR, "environment.yml")

OMNIPARSER_ENV_NAME = "omni"
OMNIPARSER_SERVER_URL = os.getenv("OMNIPARSER_BASE_URL", "http://localhost:7861")


# ==========================================
# TERMINAL COLORS  (orange/white brand palette)
# ==========================================
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
_USE_COLOR = sys.stdout.isatty()


def _c(code: str) -> str:
    return code if _USE_COLOR else ""


ORANGE = _c("\033[38;2;255;79;24m")  # #FF4F18
WHITE = _c("\033[38;2;255;255;255m")  # #FFFFFF
BOLD = _c("\033[1m")
DIM = _c("\033[38;2;80;80;80m")
GREEN = _c("\033[38;2;80;220;100m")
RED = _c("\033[91m")
RESET = _c("\033[0m")


# ==========================================
# HELPER FUNCTIONS
# ==========================================
def parse_port_arg(args: list, flag: str, default: int) -> int:
    """Parse a port argument from command line args.

    Args:
        args: List of command line arguments
        flag: The flag to look for (e.g., '--frontend-port')
        default: Default port value if flag not found

    Returns:
        The port number (either from args or default)
    """
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            try:
                return int(args[i + 1])
            except ValueError:
                print(
                    f"Warning: Invalid port value for {flag}, using default {default}"
                )
                return default
        elif arg.startswith(f"{flag}="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                print(
                    f"Warning: Invalid port value for {flag}, using default {default}"
                )
                return default
    return default


def _wrap_windows_bat(cmd_list: list[str]) -> list[str]:
    if sys.platform != "win32":
        return cmd_list
    exe = shutil.which(cmd_list[0])
    if exe and exe.lower().endswith((".bat", ".cmd")):
        return ["cmd.exe", "/d", "/c", exe] + cmd_list[1:]
    return cmd_list


def load_config() -> Dict[str, Any]:
    """
    Load configuration from file safely.

    SECURITY FIX: Use try-except instead of check-then-use to prevent TOCTOU race conditions.
    """
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    except IOError:
        return {}


def save_config_value(key: str, value: Any) -> None:
    config = load_config()
    config[key] = value
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except IOError:
        pass


def run_command(
    cmd_list: list[str],
    cwd: Optional[str] = None,
    check: bool = True,
    capture: bool = False,
    env_extras: Dict[str, str] = None,
) -> subprocess.CompletedProcess:
    cmd_list = _wrap_windows_bat(cmd_list)
    my_env = os.environ.copy()
    if env_extras:
        my_env.update(env_extras)
    my_env["PYTHONUNBUFFERED"] = "1"

    kwargs = {}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    else:
        kwargs["stdout"] = sys.stdout
        kwargs["stderr"] = sys.stderr

    try:
        return subprocess.run(cmd_list, cwd=cwd, check=check, env=my_env, **kwargs)
    except subprocess.CalledProcessError:
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Executable not found: {e.filename}")
        sys.exit(1)


def launch_background_command(
    cmd_list: list[str], cwd: Optional[str] = None, env_extras: Dict[str, str] = None
) -> Optional[subprocess.Popen]:
    cmd_list = _wrap_windows_bat(cmd_list)
    my_env = os.environ.copy()
    if env_extras:
        my_env.update(env_extras)
    my_env["PYTHONUNBUFFERED"] = "1"

    print(f"Starting: {' '.join(cmd_list[:3])}...", flush=True)

    kwargs = {}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            cmd_list,
            cwd=cwd,
            env=my_env,
            stdout=sys.stdout,
            stderr=sys.stderr,
            **kwargs,
        )
        return process
    except Exception as e:
        print(f"Error: {e}")
        return None


def wait_for_server(url: str, timeout: int = 180) -> bool:
    print(f"Waiting for {url}...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status < 400:
                    print(" Ready!")
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                print(" Ready!")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    print(" Timeout!")
    return False


# ==========================================
# BROWSER FRONTEND
# ==========================================
FRONTEND_DIR = os.path.join(BASE_DIR, "app", "ui_layer", "browser", "frontend")
FRONTEND_PORT = 7925
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"

# Global list to track background processes for cleanup
_background_processes: List[subprocess.Popen] = []


def cleanup_background_processes():
    """Clean up all background processes on exit."""
    for proc in _background_processes:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


# Register cleanup on exit
atexit.register(cleanup_background_processes)


def _kill_stale_port_process(port: int) -> bool:
    """Kill any process listening on the given port (stale leftovers from previous runs).

    Returns True if a stale process was found and killed.
    """
    if sys.platform != "win32":
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for pid_str in result.stdout.strip().split():
                pid = int(pid_str)
                if pid != os.getpid():
                    subprocess.run(["kill", "-9", str(pid)], timeout=5)
                    return True
        except Exception:
            pass
        return False

    # Windows: parse netstat to find the PID, then taskkill it
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            # Match LISTENING lines for our port on any address
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid and pid != os.getpid():
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        timeout=10,
                    )
                    return True
    except Exception:
        pass
    return False


def _free_ports(*ports: int) -> None:
    """Kill stale processes on the given ports before startup."""
    for port in ports:
        if _kill_stale_port_process(port):
            # Give the OS a moment to release the socket
            time.sleep(0.5)


def _launch_static_frontend(silent: bool = False) -> Optional[subprocess.Popen]:
    """Serve pre-built frontend static files with proxy support.

    Used when running as a PyInstaller binary where npm/node aren't available
    but the built dist/ folder is bundled. Proxies /ws and /api requests to
    the backend server, mirroring the Vite dev server proxy config.
    """
    import http.server
    import threading
    import urllib.request

    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    backend_port = int(os.environ.get("VITE_BACKEND_PORT", BACKEND_PORT))
    backend_url = f"http://localhost:{backend_port}"

    class FrontendHandler(http.server.SimpleHTTPRequestHandler):
        """Serves static files and proxies /api and /ws to the backend."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=dist_dir, **kwargs)

        def do_GET(self):
            if self.path.startswith("/api/") or self.path.startswith("/api?"):
                self._proxy_request()
            elif self.path.startswith("/ws"):
                # WebSocket upgrade can't be proxied via HTTP; the frontend
                # will connect directly if we return 426
                self.send_error(
                    426,
                    "WebSocket connections not proxied - connect directly to backend",
                )
            else:
                # Serve static files; fall back to index.html for SPA routing
                # Check if file exists, otherwise serve index.html
                file_path = os.path.join(dist_dir, self.path.lstrip("/"))
                if not os.path.exists(file_path) or os.path.isdir(file_path):
                    if not os.path.exists(
                        file_path + "/index.html"
                    ) and "." not in os.path.basename(self.path):
                        self.path = "/index.html"
                super().do_GET()

        def do_POST(self):
            if self.path.startswith("/api/"):
                self._proxy_request()
            else:
                self.send_error(404)

        def do_PUT(self):
            if self.path.startswith("/api/"):
                self._proxy_request()
            else:
                self.send_error(404)

        def do_DELETE(self):
            if self.path.startswith("/api/"):
                self._proxy_request()
            else:
                self.send_error(404)

        def _proxy_request(self):
            """Forward request to the backend server."""
            target_url = f"{backend_url}{self.path}"
            try:
                # Read request body if present
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length) if content_length > 0 else None

                # Build proxy request
                req = urllib.request.Request(target_url, data=body, method=self.command)
                # Forward relevant headers
                for header in ("Content-Type", "Authorization", "Accept"):
                    if self.headers.get(header):
                        req.add_header(header, self.headers[header])

                with urllib.request.urlopen(req, timeout=120) as resp:
                    self.send_response(resp.status)
                    for key, val in resp.getheaders():
                        if key.lower() not in ("transfer-encoding", "connection"):
                            self.send_header(key, val)
                    self.end_headers()
                    self.wfile.write(resp.read())
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.end_headers()
                self.wfile.write(e.read())
            except Exception as e:
                self.send_error(502, f"Backend proxy error: {e}")

        def log_message(self, format, *args):
            pass  # Suppress request logging

    class _QuietHTTPServer(http.server.HTTPServer):
        """Swallows ConnectionAbortedError / ConnectionResetError /
        BrokenPipeError. These happen when a browser closes a connection
        mid-response (page reload, tab close, fetch().abort, devtools
        refresh, etc.) — completely normal and harmless, but the default
        BaseHTTPRequestHandler dumps a full traceback to stderr per
        occurrence. They were piling up in craftbot.log."""

        def handle_error(self, request, client_address):
            import sys as _sys

            exc_type = _sys.exc_info()[0]
            if exc_type is not None and issubclass(
                exc_type,
                (ConnectionAbortedError, ConnectionResetError, BrokenPipeError),
            ):
                return
            super().handle_error(request, client_address)

    try:
        httpd = _QuietHTTPServer(("localhost", FRONTEND_PORT), FrontendHandler)
    except OSError as e:
        if not silent:
            print(f"Error: Could not start static frontend server: {e}")
        return None

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    # Return a dummy Popen-like object so callers can treat it uniformly
    class _StaticServer:
        def __init__(self, server):
            self._server = server
            self.returncode = None

        def poll(self):
            return None  # always running

        def terminate(self):
            self._server.shutdown()

        def kill(self):
            self._server.shutdown()

    dummy = _StaticServer(httpd)
    _background_processes.append(dummy)
    return dummy


def _ensure_frontend_deps_fresh(npm_cmd: str, silent: bool = False) -> bool:
    """Run `npm install` when node_modules no longer satisfies package.json.

    node_modules merely existing does NOT mean it matches the CURRENT manifest.
    The installer (`craftbot.py install`) checks per-dependency, but the normal
    update flow — `git pull` then `craftbot.py start`/`restart` — never re-runs
    the installer. A pull that ADDS a dependency (e.g. driver.js for the guided
    tour) then leaves the old node_modules in place, and Vite fails to resolve
    the new import at startup. Reuse install.py's staleness check (the single
    source of truth) and reinstall here before launching Vite.

    Fail-loud on a real install failure, but never block startup on the check
    itself: if install.py can't be imported, fall through unchanged.
    """
    try:
        from install import _frontend_deps_stale
    except Exception:
        return True  # can't check — leave existing behavior unchanged

    reason = _frontend_deps_stale(FRONTEND_DIR)
    if reason is None:
        return True

    if not silent:
        print(f"Frontend dependencies out of date ({reason}); running npm install...")

    # npm is a .cmd shim on Windows — invoke via cmd.exe so subprocess can find it.
    if sys.platform == "win32" and npm_cmd.lower().endswith((".cmd", ".bat")):
        install_cmd = ["cmd.exe", "/d", "/c", npm_cmd, "install"]
    else:
        install_cmd = [npm_cmd, "install"]

    try:
        result = subprocess.run(
            install_cmd,
            cwd=FRONTEND_DIR,
            stdin=subprocess.DEVNULL,
            env=node_runtime.child_env(),
        )
    except Exception as e:
        if not silent:
            print(f"Error: npm install failed to run — {e}")
            print("  Fix manually: cd app/ui_layer/browser/frontend && npm install")
        return False

    if result.returncode != 0:
        if not silent:
            print("Error: npm install failed (see output above).")
            print("  Fix manually: cd app/ui_layer/browser/frontend && npm install")
        return False

    if not silent:
        print("Frontend dependencies installed.")
    return True


def launch_frontend(silent: bool = False) -> Optional[subprocess.Popen]:
    """Serve the browser UI: prebuilt files for an install, Vite for a checkout.

    The choice used to be "am I a PyInstaller binary?". That question no
    longer means anything — the agent is never frozen — and getting it wrong
    was expensive: a managed install fell through to the Vite dev-server
    path, which demands node_modules the install has no reason to have. The
    install payload already ships a COMPILED dist/, so it needs neither npm
    nor a build step to show a working UI.

    The real question is what this tree is:
      * managed install → serve the prebuilt dist statically. No Node, no
        npm, no network.
      * dev checkout    → run Vite, so hot reload works while editing.
    """
    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    prebuilt = os.path.isfile(os.path.join(dist_dir, "index.html"))

    if not _paths.is_dev_checkout():
        if prebuilt:
            return _launch_static_frontend(silent)
        if not silent:
            print(f"Error: Frontend dist not found at {dist_dir}")
            print(f"  BASE_DIR: {BASE_DIR}")
            print(f"  FRONTEND_DIR: {FRONTEND_DIR}")
            print("  The install payload should contain a prebuilt frontend.")
        return None

    if not os.path.exists(FRONTEND_DIR):
        if not silent:
            print(f"Error: Frontend directory not found at {FRONTEND_DIR}")
            print("Make sure the browser frontend is installed.")
        return None

    # Check if node_modules exists
    node_modules = os.path.join(FRONTEND_DIR, "node_modules")
    if not os.path.exists(node_modules):
        if not silent:
            print("Error: Frontend dependencies not installed.")
            print("\nTo fix this, run: python install.py")
            print("\nOr manually install with:")
            print("  cd app/ui_layer/browser/frontend")
            print("  npm install")
        return None

    # The single resolved Node runtime (sidecar/nvm/PATH); PATH npm of any
    # version is the fallback — the dev server runs fine on Node 20.
    npm_cmd = node_runtime.npm_cmd()
    if not npm_cmd:
        if not silent:
            print("Error: no Node.js/npm found")
            print("\nNode.js is required for browser mode.")
            print("Run: python install.py   (installs a sidecar Node,")
            print("no system changes; CRAFTBOT_NODE env var also works)")
        return None

    # node_modules exists and npm is available, but a later `git pull` may have
    # added a dependency the old install is missing. Reinstall before launching
    # Vite so start/restart self-heals instead of erroring on an unresolved import.
    if not _ensure_frontend_deps_fresh(npm_cmd, silent=silent):
        return None

    # Build command for npm run dev
    # On Windows, bypass npm/cmd.exe and invoke node directly with the vite script.
    # This avoids the grandchild node.exe allocating a new console (which Windows
    # Terminal intercepts and shows as a blank tab).
    if sys.platform == "win32":
        node_exe = node_runtime.node_cmd()
        vite_script = os.path.join(
            FRONTEND_DIR, "node_modules", "vite", "bin", "vite.js"
        )
        if node_exe and os.path.isfile(vite_script):
            cmd = [node_exe, vite_script]
        else:
            # Fallback: use cmd.exe if node/vite not found directly
            cmd = ["cmd.exe", "/c", "npm", "run", "dev"]
    else:
        cmd = [npm_cmd, "run", "dev"]

    try:
        # Start frontend in background
        # Redirect output to DEVNULL to prevent blocking when buffer fills
        # Redirect stdin to DEVNULL so npm/vite never blocks waiting for input
        popen_kwargs = dict(
            cwd=FRONTEND_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Resolved runtime first on PATH: npm's node children match too
            env=node_runtime.child_env(),
        )
        if sys.platform == "win32":
            # DETACHED_PROCESS + CREATE_NO_WINDOW on the direct node.exe call
            # ensures no console window is created or inherited
            DETACHED_PROCESS = 0x00000008
            popen_kwargs["creationflags"] = (
                DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
            )
        process = subprocess.Popen(cmd, **popen_kwargs)
        _background_processes.append(process)
        return process
    except FileNotFoundError:
        if not silent:
            print("Error: npm command not found")
            print("Install Node.js from: https://nodejs.org/")
        return None
    except Exception as e:
        if not silent:
            print(f"Error starting frontend: {e}")
        return None


def wait_for_frontend(timeout: int = 30) -> bool:
    """Wait for the frontend dev server to be ready."""
    print(f"Waiting for frontend at {FRONTEND_URL}...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(FRONTEND_URL, timeout=2) as r:
                if r.status < 400:
                    print(" Ready!")
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                print(" Ready!")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(0.5)
    print(" Timeout!")
    return False


def open_browser(url: str):
    """Open the default web browser to the given URL."""
    print(f"Opening browser at {url}...")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser automatically: {e}")
        print(f"Please open {url} manually in your browser.")


BACKEND_PORT = 7926
BACKEND_URL = f"http://localhost:{BACKEND_PORT}"

# ==========================================
# BROWSER MODE STARTUP UI
# ==========================================
STEP_WIDTH = 45  # Width for step text alignment


def print_browser_header():
    """Print the retro browser mode startup header."""
    _ART = [
        " ██████╗ ██████╗  █████╗  ███████╗ ████████╗██████╗   ██████╗ ████████╗",
        "██╔════╝ ██╔══██╗ ██╔══██╗ ██╔════╝ ╚══██╔══╝██╔══██╗ ██╔═══██╗╚══██╔══╝",
        "██║      ██████╔╝ ███████║ █████╗      ██║   ██████╔╝ ██║   ██║   ██║   ",
        "██║      ██╔══██╗ ██╔══██║ ██╔══╝      ██║   ██╔══██╗ ██║   ██║   ██║   ",
        "╚██████╗ ██║  ██║ ██║  ██║ ██║         ██║   ██████╔╝ ╚██████╔╝   ██║   ",
        " ╚═════╝ ╚═╝  ╚═╝ ╚═╝  ╚═╝ ╚═╝         ╚═╝   ╚═════╝   ╚═════╝    ╚═╝   ",
    ]
    _BW = 76
    _BT = f"{ORANGE}╔{'═' * _BW}╗{RESET}"
    _BB = f"{ORANGE}╚{'═' * _BW}╝{RESET}"
    _BE = f"{ORANGE}║{' ' * _BW}║{RESET}"
    print(f"\n{_BT}")
    print(_BE)
    for _row in _ART:
        print(f"{ORANGE}║{RESET}  {WHITE}{_row}{RESET}  {ORANGE}║{RESET}")
    print(_BE)
    _sub = "░░░  BROWSER MODE  ░░░"
    print(f"{ORANGE}║{RESET}{DIM}{_sub.center(_BW)}{RESET}{ORANGE}║{RESET}")
    print(_BE)
    print(f"{_BB}\n")


def print_step(step_num: int, total: int, message: str, done: bool = False):
    """Print a retro formatted step line."""
    line = f"  {ORANGE}▸ [{step_num:>1}/{total}]{RESET}  {DIM}░{RESET}  {WHITE}{message.upper()}{RESET}"
    if done:
        print(f"{line}  {GREEN}[ OK ]{RESET}", flush=True)
    else:
        print(line, end="", flush=True)


def print_step_done():
    """Print retro done marker for current step."""
    print(f"  {GREEN}[ OK ]{RESET}", flush=True)


def print_progress_bar(percent: int, width: int = 40):
    """Print a retro progress bar from 0-100%."""
    filled = int(width * percent / 100)
    bar = f"{ORANGE}{'▓' * filled}{DIM}{'░' * (width - filled)}{RESET}"
    sys.stdout.write(f"\r  {bar}  {ORANGE}[ {percent:3d}% ]{RESET}")
    sys.stdout.flush()


def print_ready_banner(url: str):
    """Print the retro ready banner."""
    W = 62
    print(f"\n{ORANGE}╔{'═' * W}╗{RESET}")
    print(f"{ORANGE}║{' ' * W}║{RESET}")
    _r1 = f"  ▸  {CRAFTBOT_READY_MARKER}"
    _r2 = f"  ░░ {url}"
    print(f"{ORANGE}║{RESET}{GREEN}{_r1.ljust(W)}{RESET}{ORANGE}║{RESET}")
    print(f"{ORANGE}║{RESET}{ORANGE}{_r2.ljust(W)}{RESET}{ORANGE}║{RESET}")
    print(f"{ORANGE}║{' ' * W}║{RESET}")
    print(f"{ORANGE}╚{'═' * W}╝{RESET}\n")
    # MUST flush. When craftbot.py starts us as a service our stdout is a log
    # FILE, not a terminal, so Python block-buffers it — and this banner is
    # only ~400 bytes into an 8 KB buffer. Anything watching the log for the
    # ready marker would wait forever while the text sat in memory.
    sys.stdout.flush()


def wait_for_backend_silent(timeout: int = 60) -> bool:
    """Wait for the agent backend WebSocket server to be ready (silent)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(BACKEND_URL, timeout=2) as r:
                if r.status < 400:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except urllib.error.URLError:
            pass
        except Exception:
            pass
        time.sleep(0.5)
    return False


def wait_for_frontend_silent(timeout: int = 30) -> bool:
    """Wait for the frontend dev server to be ready (silent)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(FRONTEND_URL, timeout=2) as r:
                if r.status < 400:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def wait_for_backend(timeout: int = 60) -> bool:
    """Wait for the agent backend WebSocket server to be ready."""
    print(f"Waiting for agent backend at {BACKEND_URL}...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(BACKEND_URL, timeout=2) as r:
                if r.status < 400:
                    print(" Ready!")
                    return True
        except urllib.error.HTTPError as e:
            # Any HTTP response means server is up
            if e.code < 500:
                print(" Ready!")
                return True
        except urllib.error.URLError:
            pass
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(0.5)
    print(" Timeout!")
    return False


def launch_agent_background(
    env_name: Optional[str], use_conda: bool, silent: bool = False
) -> Optional[subprocess.Popen]:
    """Launch main.py in the background for browser mode."""
    main_script = os.path.abspath(MAIN_APP_SCRIPT)
    if not os.path.exists(main_script):
        if not silent:
            print(f"Error: {main_script} not found.")
        return None

    # Filter flags (--browser passes through to agent)
    skip_flags = {"--gui", "--conda", "--no-conda"}
    # Also skip port flags and their values
    pass_args = []
    skip_next = False
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a in skip_flags:
            continue
        if a in ("--frontend-port", "--backend-port"):
            skip_next = True
            continue
        if a.startswith("--frontend-port=") or a.startswith("--backend-port="):
            continue
        pass_args.append(a)

    # Ensure --browser is in args (for default mode when no flags given)
    if "--browser" not in pass_args:
        pass_args.append("--browser")

    # Set environment variable for browser startup UI formatting and warning suppression
    agent_env = os.environ.copy()
    agent_env["BROWSER_STARTUP_UI"] = "1"
    agent_env["PYTHONWARNINGS"] = "ignore"
    # Hand the child the Node runtime this process already resolved, so it
    # skips re-resolution and both processes agree on the same binary. Not
    # in conda mode: there the env's own node (>= 24 via environment.yml,
    # first on PATH under conda run) is the intended runtime.
    if not use_conda and "CRAFTBOT_NODE" not in agent_env:
        _rt = node_runtime.resolve()
        if _rt:
            agent_env["CRAFTBOT_NODE"] = _rt.node

    # When running as a PyInstaller frozen binary, run main() in a thread
    # instead of spawning a subprocess (sys.executable is the binary itself)
    if getattr(sys, "frozen", False):
        import threading

        sys.argv = [sys.argv[0]] + pass_args
        for k, v in agent_env.items():
            os.environ[k] = v

        def _run_agent():
            try:
                from main import main as main_entry

                main_entry()
            except Exception as e:
                print(f"Agent error: {e}")

        thread = threading.Thread(target=_run_agent, daemon=True)
        thread.start()

        # Return a dummy Popen-like object
        class _AgentThread:
            def __init__(self):
                self.returncode = None

            def poll(self):
                return None if thread.is_alive() else 0

            def wait(self):
                thread.join()

            def terminate(self):
                pass  # Thread will exit when main process exits (daemon=True)

            def kill(self):
                pass

        dummy = _AgentThread()
        _background_processes.append(dummy)
        return dummy

    # Build command
    if use_conda and env_name:
        conda_exe = get_conda_command()
        cmd = [
            conda_exe,
            "run",
            "--no-capture-output",
            "-n",
            env_name,
            "python",
            "-u",
            main_script,
        ] + pass_args

        # On Windows, wrap .bat files with cmd.exe
        if sys.platform == "win32" and conda_exe.lower().endswith((".bat", ".cmd")):
            cmd = ["cmd.exe", "/d", "/c"] + cmd
    else:
        cmd = [
            python_runtime.resolve() or sys.executable,
            "-u",
            main_script,
        ] + pass_args

    try:
        process = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(main_script),
            env=agent_env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        _background_processes.append(process)
        return process
    except Exception as e:
        if not silent:
            print(f"Error starting agent: {e}")
        return None


# ==========================================
# ENVIRONMENT DETECTION
# ==========================================
def is_conda_installed() -> Tuple[bool, str, Optional[str]]:
    conda_exe = shutil.which("conda")
    if conda_exe:
        return True, conda_exe, os.path.dirname(os.path.dirname(conda_exe))

    if sys.platform == "win32":
        # Check common Miniconda/Anaconda installation paths
        common_paths = [
            os.path.join(os.path.expanduser("~"), "miniconda3"),
            os.path.join(os.path.expanduser("~"), "Miniconda3"),
            os.path.join(os.path.expanduser("~"), "anaconda3"),
            os.path.join(os.path.expanduser("~"), "Anaconda3"),
            "C:\\miniconda3",
            "C:\\Miniconda3",
            "C:\\anaconda3",
            "C:\\Anaconda3",
        ]

        for base_path in common_paths:
            conda_bat = os.path.join(base_path, "condabin", "conda.bat")
            if os.path.exists(conda_bat):
                return True, conda_bat, base_path

        # Also check current Python directory
        for base in [os.path.dirname(os.path.dirname(sys.executable))]:
            if os.path.exists(os.path.join(base, "condabin", "conda.bat")):
                return True, base, base

    return False, "", None


def get_env_name_from_yml() -> str:
    try:
        with open(YML_FILE, "r") as f:
            for line in f:
                if line.strip().startswith("name:"):
                    return line.split(":", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return "craftbot"


def get_conda_command() -> str:
    """Return conda command. Use full path on Windows if conda not in PATH."""
    # First try to find conda in PATH
    conda_exe = shutil.which("conda")
    if conda_exe:
        return conda_exe

    # On Windows, check common installation paths
    if sys.platform == "win32":
        common_paths = [
            os.path.join(os.path.expanduser("~"), "miniconda3"),
            os.path.join(os.path.expanduser("~"), "Miniconda3"),
            os.path.join(os.path.expanduser("~"), "anaconda3"),
            os.path.join(os.path.expanduser("~"), "Anaconda3"),
            "C:\\miniconda3",
            "C:\\Miniconda3",
            "C:\\anaconda3",
            "C:\\Anaconda3",
        ]

        for base_path in common_paths:
            conda_bat = os.path.join(base_path, "condabin", "conda.bat")
            if os.path.exists(conda_bat):
                return conda_bat

    # Fallback to just "conda" (will work if it's in PATH)
    return "conda"


def verify_env(env_name: str) -> bool:
    try:
        conda_cmd = get_conda_command()
        cmd = [conda_cmd, "run", "-n", env_name, "python", "-c", "print('ok')"]
        run_command(cmd, capture=True)
        return True
    except Exception:
        return False


# ==========================================
# OMNIPARSER SERVER
# ==========================================
def launch_omniparser(use_conda: bool) -> bool:
    """Launch OmniParser server for GUI mode."""
    print("Starting GUI components (OmniParser)...")

    config = load_config()
    repo_path = config.get(
        "omniparser_repo_path", os.path.abspath("OmniParser_CraftOS")
    )

    if not os.path.exists(repo_path):
        print("Error: GUI components not installed.")
        print("Run 'python install.py --gui --conda' first.")
        return False

    if use_conda:
        conda_cmd = get_conda_command()
        cmd = [
            conda_cmd,
            "run",
            "-n",
            OMNIPARSER_ENV_NAME,
            "python",
            "-u",
            "-m",
            "gradio_demo",
        ]
    else:
        cmd = [sys.executable, "-u", "-m", "gradio_demo"]

    launch_background_command(cmd, cwd=repo_path)

    if wait_for_server(OMNIPARSER_SERVER_URL, timeout=180):
        os.environ["OMNIPARSER_BASE_URL"] = OMNIPARSER_SERVER_URL
        return True

    print("Failed to start GUI components.")
    return False


# ==========================================
# MAIN LAUNCHER
# ==========================================
def launch_agent(env_name: Optional[str], conda_base: Optional[str], use_conda: bool):
    """Launch main.py in the current terminal."""
    main_script = os.path.abspath(MAIN_APP_SCRIPT)
    if not os.path.exists(main_script):
        print(f"Error: {main_script} not found.")
        sys.exit(1)

    # Filter flags (--cli passes through to agent)
    skip_flags = {"--gui", "--conda", "--no-conda", "--browser"}
    # Also skip port flags and their values
    pass_args = []
    skip_next = False
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a in skip_flags:
            continue
        if a in ("--frontend-port", "--backend-port"):
            skip_next = True
            continue
        if a.startswith("--frontend-port=") or a.startswith("--backend-port="):
            continue
        pass_args.append(a)

    print("Starting CraftBot...\n")

    # When running as a PyInstaller frozen binary, sys.executable points to
    # the binary itself, so spawning "python main.py" would re-run run.py
    # in an infinite loop. Instead, import and call main() directly.
    if getattr(sys, "frozen", False):
        try:
            sys.argv = [sys.argv[0]] + pass_args
            from main import main as main_entry

            main_entry()
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(0)
        return

    # Build command
    if use_conda and env_name:
        conda_exe = get_conda_command()
        cmd = [
            conda_exe,
            "run",
            "--no-capture-output",
            "-n",
            env_name,
            "python",
            "-u",
            main_script,
        ] + pass_args

        # On Windows, wrap .bat files with cmd.exe
        if sys.platform == "win32" and conda_exe.lower().endswith((".bat", ".cmd")):
            cmd = ["cmd.exe", "/d", "/c"] + cmd
    else:
        cmd = [
            python_runtime.resolve() or sys.executable,
            "-u",
            main_script,
        ] + pass_args

    # Run in current terminal with all environment variables.
    try:
        result = subprocess.run(
            cmd, cwd=os.path.dirname(main_script), env=os.environ.copy()
        )
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)


# ==========================================
# MAIN
# ==========================================
#: How long to wait for the agent to finish booting before giving up and
#: showing the UI anyway. Generous on purpose: a first run downloads the
#: embedding model, which on a slow connection is genuinely minutes. Timing
#: out is not an error — it just means we stop waiting to open the browser.
AGENT_READY_TIMEOUT_S = 900


def _clear_agent_ready() -> None:
    """Remove a previous run's readiness marker."""
    try:
        from app import paths

        paths.AGENT_READY_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _wait_for_agent_ready(process=None, timeout: float = AGENT_READY_TIMEOUT_S) -> bool:
    """Block until the agent says boot() finished. See app/paths.py.

    Returns True if the marker appeared, False if the agent died or the
    timeout expired — the caller proceeds either way, because refusing to
    show the UI just because the agent was slow would be worse than showing
    it early.

    Watching `process` matters: the marker is only written on a *successful*
    boot, so an agent that crashes part-way through would otherwise leave us
    sitting here for the full timeout with nothing to show for it.
    """
    try:
        from app import paths

        marker = paths.AGENT_READY_FILE
    except Exception:
        return True  # cannot check; do not block the boot on it

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if marker.is_file():
                return True
        except OSError:
            pass
        if process is not None and process.poll() is not None:
            print(
                f"\n  Agent exited during startup (code {process.returncode}).",
                flush=True,
            )
            return False
        time.sleep(0.4)
    print(
        f"\n  Agent still starting after {int(timeout)}s — continuing anyway.",
        flush=True,
    )
    return False


def _suppress_child_consoles() -> None:
    """Stop console children opening their own terminal windows.

    craftbot.py spawns run.py detached, so it has no console of its own. On
    Windows a *console* application launched from a process with no console
    gets a brand new console window — so npm, node, conda and the agent
    process each popped up a terminal during an installed start.

    The frozen agent never showed this: PyInstaller ran
    rthooks/rthook-windows-noflash.py, which patched subprocess for exactly
    this reason. The agent is no longer a frozen bundle, so that hook now
    applies only to the installer EXE and nothing covered run.py any more.
    This restores the behaviour at the same choke point.

    Only patch when we genuinely have no console. A developer running
    `python run.py` in a terminal has one, and there the children *should*
    inherit it — that is where the output is meant to go.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        if ctypes.windll.kernel32.GetConsoleWindow():
            return  # we have a console; children should inherit it
    except Exception:
        return

    CREATE_NO_WINDOW = 0x08000000
    _original_init = subprocess.Popen.__init__

    def _patched_init(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0) or 0
        # Idempotent: Windows ignores CREATE_NO_WINDOW when DETACHED_PROCESS
        # is already set, and the call sites that set it stay correct.
        kwargs["creationflags"] = flags | CREATE_NO_WINDOW
        return _original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init


if __name__ == "__main__":
    # Before anything spawns a child. See the docstring for why this is not
    # simply always-on.
    _suppress_child_consoles()

    # Whatever `python` launched us is a trampoline: hop onto the project's
    # interpreter (the one the dependencies live in) before doing anything.
    python_runtime.reexec_if_needed()

    args_list = sys.argv[1:]
    args = set(args_list)

    # Parse flags
    # [V1.2.2] GUI mode is temporarily disabled in this version.
    if "--gui" in args:
        print("\n[!] GUI mode is temporarily disabled in this version (V1.2.2).")
        print(
            "    This feature is experimental and will be re-enabled in a future release."
        )
        print("    Please run without --gui flag.\n")
        sys.exit(1)
    gui_mode = False  # "--gui" in args  # [V1.2.2] disabled
    cli_mode = "--cli" in args
    conda_flag = "--conda" in args
    no_conda_flag = "--no-conda" in args

    # Parse port arguments (override defaults)
    FRONTEND_PORT = parse_port_arg(args_list, "--frontend-port", FRONTEND_PORT)
    BACKEND_PORT = parse_port_arg(args_list, "--backend-port", BACKEND_PORT)
    FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"
    BACKEND_URL = f"http://localhost:{BACKEND_PORT}"

    # Browser mode is default (unless --cli specified)
    browser_mode = not cli_mode

    # Load saved config to check what was actually installed
    config = load_config()
    use_conda = config.get(
        "use_conda", False
    )  # Use config instead of defaulting to True

    # Override with command-line flags if provided
    if conda_flag:
        use_conda = True
    elif no_conda_flag:
        use_conda = False

    gui_installed = config.get("gui_mode_enabled", False)

    # Set environment variables
    os.environ["USE_CONDA"] = str(use_conda)
    os.environ["GUI_MODE_ENABLED"] = str(gui_mode)
    os.environ["USE_OMNIPARSER"] = str(gui_mode and gui_installed)
    # Set port environment variables for frontend (Vite) and backend
    os.environ["VITE_PORT"] = str(FRONTEND_PORT)
    os.environ["VITE_BACKEND_PORT"] = str(BACKEND_PORT)
    os.environ["BROWSER_PORT"] = str(BACKEND_PORT)

    # Determine mode string for display (only print for non-browser modes)
    if not browser_mode:
        mode_str = "GUI + CLI" if gui_mode else "CLI"
        print(f"\nMode: {mode_str}")

    # Check conda only if it was installed earlier
    conda_base = None
    env_name = None

    if use_conda:
        found, path, conda_base = is_conda_installed()
        if not found:
            print("Error: Conda not found.")
            print("If you want to use conda, run: python install.py --conda")
            print("Or run without conda: python run.py (global pip only)\n")
            sys.exit(1)
        env_name = get_env_name_from_yml()
        if not verify_env(env_name):
            print(f"\nEnvironment '{env_name}' not ready.")
            print("Run 'python install.py' or 'python install.py --conda' first.\n")
            sys.exit(1)

    ensure_runtime_dependencies(
        use_conda=use_conda,
        env_name=env_name,
        conda_command=get_conda_command() if use_conda else "conda",
    )
    mark_runtime_dependencies_checked()

    # Start OmniParser only if GUI mode and it was installed
    if gui_mode and gui_installed:
        if not launch_omniparser(use_conda):
            print("Warning: Continuing without OmniParser.")
            os.environ["USE_OMNIPARSER"] = "False"
    elif gui_mode and not gui_installed:
        print("\nGUI mode requested but components not installed.")
        print("Run: python install.py --gui --conda\n")
        sys.exit(1)

    no_open_browser = "--no-open-browser" in args

    # Browser mode: start frontend + agent, wait for both, then open browser
    if browser_mode:
        # Kill stale processes from previous runs that may still hold our ports
        _free_ports(FRONTEND_PORT, BACKEND_PORT)

        # Print browser mode header
        print_browser_header()

        # Step 1: Start frontend server (0% -> 10%)
        # Step 1: Start frontend server
        print_step(1, 8, "Starting frontend server")
        frontend_process = launch_frontend(silent=not getattr(sys, "frozen", False))
        if not frontend_process:
            print(" ✗")
            print("\nError: Failed to start browser frontend.")
            print("\n" + "=" * 52)
            print("TROUBLESHOOTING:")
            print("=" * 52)
            print("\n1. Make sure Node.js is installed:")
            print("   → Download from: https://nodejs.org/ (LTS version)")
            print("   → Verify: node --version && npm --version")
            print("\n2. Install frontend dependencies:")
            print("   → Run: python install.py")
            print("\n3. Manually install (if above doesn't work):")
            print("   → cd app/ui_layer/browser/frontend")
            print("   → npm install")
            print("\n4. Try running again:")
            print("   → python run.py")
            print("=" * 52 + "\n")
            sys.exit(1)
        print_step_done()

        # Step 2: Start agent backend
        print_step(2, 8, "Starting agent backend")
        # Clear last run's marker first, or we would read it as this run's
        # readiness and open the browser instantly.
        _clear_agent_ready()
        agent_process = launch_agent_background(env_name, use_conda, silent=True)
        if not agent_process:
            print(" ✗")
            print("\nError: Failed to start agent backend.")
            sys.exit(1)
        print_step_done()

        # Wait for services silently (agent prints steps 3-8)
        frontend_ready = False
        backend_ready = False

        # Wait for frontend
        frontend_start = time.time()
        while time.time() - frontend_start < 30:
            try:
                with urllib.request.urlopen(FRONTEND_URL, timeout=2) as r:
                    if r.status < 400:
                        frontend_ready = True
                        break
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    frontend_ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)

        # Wait for backend
        backend_start = time.time()
        while time.time() - backend_start < 60:
            try:
                with urllib.request.urlopen(BACKEND_URL, timeout=2) as r:
                    if r.status < 400:
                        backend_ready = True
                        break
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    backend_ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)

        # The backend port answering is NOT the agent being ready: it binds
        # early, while steps 3-7 (model download, MCP servers, skills,
        # integrations, scheduler) are still running. Treating the port as
        # readiness is what printed the ready banner — and opened the browser
        # — at step 2 of 8, onto a backend that could not serve yet.
        if backend_ready:
            backend_ready = _wait_for_agent_ready(agent_process)

        # Small delay to ensure agent's stdout is flushed before we print
        # The agent prints steps 3-8, and we want them to appear before the ready banner
        time.sleep(0.3)

        # Check if processes are still running
        frontend_alive = frontend_process and frontend_process.poll() is None
        backend_alive = agent_process and agent_process.poll() is None

        # Print ready banner and open browser
        if frontend_ready and backend_ready:
            print_ready_banner(FRONTEND_URL)
            if not no_open_browser:
                webbrowser.open(FRONTEND_URL)
        elif not frontend_alive:
            print("\n⚠ Error: Frontend server crashed")
            print("   Check if Node.js and npm are properly installed")
            print("   Try running: cd app/ui_layer/browser/frontend && npm run dev")
        elif not backend_alive:
            print("\n⚠ Error: Agent backend crashed")
            print("   Check the error messages above for details")
            if use_conda:
                print(
                    f"   Try running: conda activate {env_name} && python main.py --browser"
                )
        else:
            # Frontend or backend may still be starting, but proceed anyway
            print_ready_banner(FRONTEND_URL)
            if not no_open_browser:
                webbrowser.open(FRONTEND_URL)

        # Wait for agent to finish (keeps script running)
        # If the agent exits with code 42, it means an update was applied
        # and we need to restart the entire stack (frontend + backend).
        # Wait for agent to finish. Updates are handled by the external
        # updater script (scripts/updater.bat) which spawns in its own window
        # and relaunches us — no exit-code magic, no in-process restart.
        try:
            agent_process.wait()
        except KeyboardInterrupt:
            print("\nShutting down...")
            cleanup_background_processes()
            sys.exit(0)
    else:
        # Non-browser mode: launch agent in foreground as before
        launch_agent(env_name, conda_base, use_conda)
