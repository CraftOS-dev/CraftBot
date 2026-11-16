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
    --agent-app-port PORT     First Agent App port; apps get PORT to PORT+99 (default: 3100)
    --no-open-browser         Start servers but do not auto-open the browser (used by service mode)
    --dev-ui                  Serve the frontend with the Vite dev server (hot reload) instead of
                              the production build (default; rebuilt automatically when sources change)

Environment:
    CRAFTBOT_BIND_HOST        Interface the UI servers listen on (default: loopback; 0.0.0.0 in Docker)

Note: The installation method (conda/pip) is saved from install.py and reused here.
"""

import multiprocessing
import os
import sys
import json
import signal
import subprocess
import shutil
import time
import urllib.request
import urllib.error
import webbrowser
import atexit
from typing import Tuple, Optional, Dict, Any, List

# Internal service argument: apply before importing any app module, because
# app.paths resolves STATE_ROOT at import time. Keep it out of the agent's
# arguments; interpreter handoffs inherit the resulting environment.
for _argument in sys.argv[1:]:
    if _argument.startswith("--state-root="):
        os.environ["CRAFTBOT_HOME"] = _argument.split("=", 1)[1]
        sys.argv.remove(_argument)

from app.runtime_preflight import (  # noqa: E402
    ensure_runtime_dependencies,
    mark_runtime_dependencies_checked,
)
from app import python_runtime  # noqa: E402

# Single resolved Node runtime — see app/node_runtime.py. install.py
# downloads the sidecar when nothing suitable exists; run.py never installs.
from app import node_runtime  # noqa: E402
from app import instance as _instance  # noqa: E402
from app.console import configure_console  # noqa: E402

# A windowless launch (pythonw from Task Scheduler or the Run key) has no
# stdout at all. Its output goes to the CraftBot log in STATE_ROOT, the one
# craftbot.py and the launcher read, instead of the first print() killing it.
configure_console(log_file=str(_instance.LOG_FILE))

multiprocessing.freeze_support()

CRAFTBOT_READY_MARKER = "CRAFTBOT IS READY"

# Configuration is loaded from settings.json via the agent startup
# No .env file is used - all settings come from app/config/settings.json

# --- Base directory ---
# app.paths is the single answer to code-vs-state (see app/paths.py). It is
# stdlib-only, so importing it here — before dependencies exist — is safe.
from app import paths as _paths  # noqa: E402

BASE_DIR = str(_paths.CODE_ROOT)

# _bootstrap_state() below may chdir into the state directory, and the
# interpreter hop in __main__ re-runs sys.argv: a relative "run.py" would then
# name a file that is not there, and the re-launched process exited (code 2)
# before printing anything.
if __name__ == "__main__" and sys.argv and sys.argv[0]:
    sys.argv[0] = os.path.abspath(sys.argv[0])


def _bootstrap_state():
    """Seed the per-user state directory from the shipped defaults.

    A managed install keeps CODE in the install directory (replaced wholesale
    by the next upgrade, and on Windows not reliably writable) and STATE in
    the per-user data dir. The app expects mutable app/config, app/data,
    agents, assets and skills trees, so on first run they are copied across.

    Only ever copies what is ABSENT — a user's edited settings.json or their
    customised skills must survive every upgrade. An upgrade also brings in
    the action files and skills that are NEW in the release, and enables the
    newly shipped default skills (app/state_sync.py: never overwrites a file,
    never restores one the user deleted).

    When code and state share a tree no copy is needed. An explicit separate
    CRAFTBOT_HOME is seeded in a dev checkout too.

    Either way, every runtime file CraftBot rewrites while it runs
    (app/config/*.json, the agent's markdown files) is created from its
    shipped default when it is missing (app/state_sync.py). Those files are
    not tracked, so `git pull` never collides with a user's edits, and a
    managed install or a Docker image gets AGENT.md and SOUL.md too.
    """
    if _paths.CODE_ROOT.resolve() == _paths.STATE_ROOT.resolve():
        # Login tasks do not inherit the installer's working directory.
        os.chdir(_paths.STATE_ROOT)
    else:
    import shutil as _shutil

    user_data = str(_paths.STATE_ROOT)
    os.makedirs(user_data, exist_ok=True)

        # Switch CWD so any code still using relative paths writes into the
        # state dir rather than the install dir.
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

    # The trees above are copied once, so an upgrade would otherwise never
    # deliver a new action file or skill (or enable a new default skill).
    try:
        from app.state_sync import sync_shipped_files

        sync_shipped_files(_paths.CODE_ROOT, _paths.STATE_ROOT)
    except Exception as exc:  # never block startup over it
        print(f"  Warning: could not sync newly shipped files: {exc}")

    try:
        from app.state_sync import seed_runtime_files

        seed_runtime_files(_paths.CODE_ROOT, _paths.STATE_ROOT)
    except Exception as exc:  # never block startup over it
        print(f"  Warning: could not create default files: {exc}")


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
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
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
        # No proxy: a corporate HTTP(S)_PROXY cannot reach local servers.
        if _instance.http_answers(url, timeout=3):
                    print(" Ready!")
                    return True
        print(".", end="", flush=True)
        time.sleep(1)
    print(" Timeout!")
    return False


# ==========================================
# BROWSER FRONTEND
# ==========================================
FRONTEND_DIR = os.path.join(BASE_DIR, "app", "ui_layer", "browser", "frontend")
FRONTEND_PORT = _instance.DEFAULT_FRONTEND_PORT
FRONTEND_URL = _instance.display_url(FRONTEND_PORT)
# Interface the UI servers listen on (CRAFTBOT_BIND_HOST; loopback unless set).
BIND_HOST = _instance.bind_host()

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


def _launcher_ledger():
    """Processes this launcher started (frontend, agent backend), recorded by
    pid + start time so a later run can free our ports without touching
    anything else. None if the ledger cannot load — then nothing is killed."""
    try:
        from app.process_ledger import get_ledger

        return get_ledger("launcher")
    except Exception:
        return None


def _record_launched(process, label: str) -> None:
    ledger = _launcher_ledger()
    pid = getattr(process, "pid", None)
    if ledger is not None and pid:
        from app.process_ledger import ROLE_LAUNCHER

        ledger.register(pid, ROLE_LAUNCHER, label=label)


def _adopt_port_listeners(*ports: int) -> None:
    """Record the servers on our ports once they are up — only ones descended
    from a process we launched, plus this launcher itself (it serves the
    static frontend in-process, and in frozen mode the agent too). That is what lets the NEXT run
    free a port a crashed run left bound, without ever adopting a foreign
    service that happened to answer on it."""
    ledger = _launcher_ledger()
    if ledger is None:
        return
    from app.process_ledger import ROLE_LAUNCHER

    for port in ports:
        ledger.adopt_listeners(
            port,
            ROLE_LAUNCHER,
            label=f"listener :{port}",
            # This process serves the static frontend in-process (and, when
            # frozen, the agent too), so it is itself a port holder.
            include_self=True,
        )


def _free_ports(*ports: int, recorded_pids=()) -> List[str]:
    """Free our ports of leftovers, and describe whatever still holds one.

    Two kinds of leftover, and they need different evidence:

      * a process THIS install recorded starting: the ledger stops it;
      * a CraftBot of THIS state root that the ledger does not cover, such as
        one left by a previous install whose ledger went with the uninstall.
        identify_craftbot proves it is CraftBot, and
        app.instance.belongs_to_this_home proves it is this one: started by
        the run.py our pid file names, or running from a tree whose state
        root is ours.

    A CraftBot from another checkout or another CRAFTBOT_HOME is a separate
    installation, and is left running like any other program: stopping it
    would take down someone's working agent. Whatever is left is returned,
    and the caller moves to free ports or refuses to start. Previously a
    leftover here meant a Warning and carrying on into launch_frontend(),
    whose readiness probe got a 200 from the OLD server still on the port.
    """
    from app.process_ledger import craftbot_listeners, describe_pid
    from app.process_ledger import kill_tree, listening_pids

    ledger = _launcher_ledger()
    blockers: List[str] = []
    for port in ports:
        freed = ledger.kill_port_listeners(port) if ledger is not None else False
        for pid, description in craftbot_listeners(port):
            if not _instance.belongs_to_this_home(pid, recorded_pids):
                continue  # another installation: it is a blocker, not ours
            print(f"  Stopping an older CraftBot on port {port} ({description})")
            kill_tree(pid)
            freed = True
        if freed:
            time.sleep(0.5)  # let the OS release the socket
        for pid in listening_pids(port):
            if pid != os.getpid():
                blockers.append(f"port {port} is held by {describe_pid(pid)}")
    return blockers


def _launch_static_frontend(silent: bool = False) -> Optional[subprocess.Popen]:
    """Serve the pre-built frontend (dist/) with proxy support, in-process.

    Proxies /api requests to the backend server, mirroring the Vite dev
    server proxy config. index.html is served with the backend port this run
    uses (app.instance.inject_runtime_config): the bundle has a port compiled
    in, which is wrong whenever the backend is not on 7926.
    """
    import http.server
    import socket
    import threading
    from urllib.parse import urlsplit

    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    backend_port = int(os.environ.get("VITE_BACKEND_PORT", BACKEND_PORT))
    backend_url = f"http://{_instance.connect_host(BIND_HOST)}:{backend_port}"
    index_file = os.path.join(dist_dir, "index.html")

    class FrontendHandler(http.server.SimpleHTTPRequestHandler):
        """Serves static files and proxies /api to the backend."""

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
                route = urlsplit(self.path).path
                if route in ("/", "/index.html"):
                    self._serve_index()
                    return
                file_path = os.path.join(dist_dir, route.lstrip("/"))
                if not os.path.exists(file_path) or os.path.isdir(file_path):
                    if not os.path.exists(
                        file_path + "/index.html"
                    ) and "." not in os.path.basename(route):
                        self._serve_index()
                        return
                super().do_GET()

        def _serve_index(self):
            try:
                with open(index_file, "rb") as f:
                    body = _instance.inject_runtime_config(f.read(), backend_port)
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
                # Forward relevant headers. Host, Origin and Sec-Fetch-Site are
                # what the backend's /api guard judges (ws_auth.py): dropping
                # them would turn this proxy into a way around it — a
                # cross-site upload would arrive Origin-less, and a
                # DNS-rebinding Host would arrive as localhost.
                for header in (
                    "Content-Type",
                    "Authorization",
                    "Accept",
                    "Host",
                    "Origin",
                    "Sec-Fetch-Site",
                ):
                    if self.headers.get(header):
                        req.add_header(header, self.headers[header])

                # Never through a proxy: HTTP(S)_PROXY cannot reach loopback.
                with _instance.loopback_opener().open(req, timeout=120) as resp:
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

        def end_headers(self):
            # Hashed /assets/ files are immutable; everything else (index.html
            # via SPA fallback) must revalidate so a rebuild shows up at once.
            if not self.path.startswith("/api") and self.command != "OPTIONS":
                if self.path.startswith("/assets/"):
                    self.send_header(
                        "Cache-Control", "public, max-age=31536000, immutable"
                    )
                else:
                    self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def log_message(self, format, *args):
            pass  # Suppress request logging

    host = BIND_HOST.strip("[]")

    class _QuietHTTPServer(http.server.ThreadingHTTPServer):
        """Threaded, so a slow proxied /api request never blocks static files.

        Swallows ConnectionAbortedError / ConnectionResetError /
        BrokenPipeError. These happen when a browser closes a connection
        mid-response (page reload, tab close, fetch().abort, devtools
        refresh, etc.) — completely normal and harmless, but the default
        BaseHTTPRequestHandler dumps a full traceback to stderr per
        occurrence. They were piling up in craftbot.log."""

        # IPv6 when CRAFTBOT_BIND_HOST is an IPv6 address such as "::".
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

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
        httpd = _QuietHTTPServer((host, FRONTEND_PORT), FrontendHandler)
    except OSError as e:
        if not silent:
            print(f"Error: could not serve the UI on port {FRONTEND_PORT}: {e}")
            print("  Another program may already hold that port.")
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
    the new import at startup. Reuse the provisioning pipeline's staleness
    check (app.provision.deps.npm_tree_stale, the single source of truth) and
    reinstall here before building or launching Vite.

    Fail-loud on a real install failure, but never block startup on the check
    itself: if it can't be imported, fall through unchanged.
    """
    try:
        from app.provision.deps import npm_tree_stale
    except Exception:
        return True  # can't check — leave existing behavior unchanged

    reason = npm_tree_stale(FRONTEND_DIR)
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
            print(f"Error: npm install failed to run: {e}")
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


# Frontend sources; a change to any of them makes the production build stale.
_FRONTEND_BUILD_INPUTS = (
    "src",
    "public",
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
)


def _newest_mtime(paths: List[str]) -> float:
    newest = 0.0
    for path in paths:
        if os.path.isfile(path):
            newest = max(newest, os.path.getmtime(path))
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in ("node_modules", "dist")]
                for name in files:
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
    return newest


def _frontend_build_current() -> bool:
    """dist/ exists and is newer than every frontend source.

    The backend port is not part of this: index.html is served with the port
    of the current run (inject_runtime_config), so a build made for one port
    serves any other and a port change no longer costs a rebuild.
    """
    dist_index = os.path.join(FRONTEND_DIR, "dist", "index.html")
    if not os.path.isfile(dist_index):
        return False
    inputs = [os.path.join(FRONTEND_DIR, name) for name in _FRONTEND_BUILD_INPUTS]
    # Shared mascot components are compiled in through the @mascot alias.
    inputs.append(os.path.join(BASE_DIR, "app", "ui_layer", "components", "Mascot"))
    return os.path.getmtime(dist_index) >= _newest_mtime(inputs)


def _ensure_frontend_build(silent: bool = False) -> bool:
    """Build the production frontend unless dist/ is current."""
    dist_index = os.path.join(FRONTEND_DIR, "dist", "index.html")
    if _frontend_build_current():
        return True

    node_exe = node_runtime.node_cmd()
    vite_script = os.path.join(FRONTEND_DIR, "node_modules", "vite", "bin", "vite.js")
    if not node_exe or not os.path.isfile(vite_script):
        return False
    if not silent:
        print("Building the frontend (first start after a change)...")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [node_exe, vite_script, "build"],
            cwd=FRONTEND_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=node_runtime.child_env(),
            timeout=600,
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        if not silent:
            print(f"Error building frontend: {e}")
        return False
    if result.returncode != 0 or not os.path.isfile(dist_index):
        if not silent:
            print(
                "Error building frontend:\n"
                + result.stderr.decode("utf-8", errors="replace")[-2000:]
            )
        return False
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

    In a dev checkout the production build is still the default (rebuilt when
    sources change): the Vite dev server's React dev mode, StrictMode double
    rendering and Redux dev checks made everyday use noticeably slower.
    ``--dev-ui`` keeps the dev server with hot reload for frontend work, and
    it's also the fallback when a build isn't possible.

    A current dist/ is served without looking for Node or npm at all: a login
    item or service starts with a minimal PATH, and refusing to show a UI
    that is already built because npm is not on that PATH helped no one.
    """
    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    prebuilt = os.path.isfile(os.path.join(dist_dir, "index.html"))
    dev_ui = "--dev-ui" in sys.argv[1:]

    if not _paths.is_dev_checkout():
        if prebuilt:
            return _launch_static_frontend(silent)
        if not silent:
            print(f"Error: Frontend dist not found at {dist_dir}")
            print(f"  BASE_DIR: {BASE_DIR}")
            print(f"  FRONTEND_DIR: {FRONTEND_DIR}")
            print("  The install payload should contain a prebuilt frontend.")
        return None

    if not dev_ui and _frontend_build_current():
        return _launch_static_frontend(silent)

    def _serve_existing_build(reason: str) -> Optional[subprocess.Popen]:
        """Last resort: an out-of-date build beats no UI at all."""
        if not prebuilt or dev_ui:
            return None
        if not silent:
            print(f"Warning: {reason}.")
            print("  Serving the existing frontend build, which may be out of date.")
        return _launch_static_frontend(silent)

    if not os.path.exists(FRONTEND_DIR):
        if not silent:
            print(f"Error: Frontend directory not found at {FRONTEND_DIR}")
            print("Make sure the browser frontend is installed.")
        return None

    # Check if node_modules exists
    node_modules = os.path.join(FRONTEND_DIR, "node_modules")
    if not os.path.exists(node_modules):
        fallback = _serve_existing_build("frontend dependencies are not installed")
        if fallback is not None:
            return fallback
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
        fallback = _serve_existing_build("Node.js/npm was not found")
        if fallback is not None:
            return fallback
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
        return _serve_existing_build("frontend dependencies could not be updated")

    if not dev_ui:
        if _ensure_frontend_build(silent=silent):
            return _launch_static_frontend(silent)
        if not silent:
            print("Warning: production frontend build failed; using the dev server")

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
        _record_launched(process, "frontend dev server")
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
        if _instance.http_answers(_local_url(FRONTEND_PORT)):
                    print(" Ready!")
                    return True
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


BACKEND_PORT = _instance.DEFAULT_BACKEND_PORT
BACKEND_URL = _instance.display_url(BACKEND_PORT)


def _local_url(port: int) -> str:
    """URL this process uses to reach one of its own servers: the loopback
    address they listen on, whatever CRAFTBOT_BIND_HOST is."""
    return f"http://{_instance.connect_host(BIND_HOST)}:{int(port)}"


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
        if _instance.http_answers(_local_url(BACKEND_PORT)):
                    return True
        time.sleep(0.5)
    return False


def wait_for_frontend_silent(timeout: int = 30) -> bool:
    """Wait for the frontend server to be ready (silent)."""
    start = time.time()
    while time.time() - start < timeout:
        if _instance.http_answers(_local_url(FRONTEND_PORT)):
                    return True
        time.sleep(0.5)
    return False


def wait_for_backend(timeout: int = 60) -> bool:
    """Wait for the agent backend WebSocket server to be ready."""
    print(f"Waiting for agent backend at {BACKEND_URL}...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        if _instance.http_answers(_local_url(BACKEND_PORT)):
                    print(" Ready!")
                    return True
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
    skip_flags = {"--gui", "--conda", "--no-conda", "--dev-ui"}
    # Also skip port flags and their values
    pass_args = []
    skip_next = False
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a in skip_flags:
            continue
        if a in ("--frontend-port", "--backend-port", "--agent-app-port"):
            skip_next = True
            continue
        if a.startswith(("--frontend-port=", "--backend-port=", "--agent-app-port=")):
            continue
        pass_args.append(a)

    # Ensure --browser is in args (for default mode when no flags given)
    if "--browser" not in pass_args:
        pass_args.append("--browser")

    # Set environment variable for browser startup UI formatting and warning suppression.
    # isolated_env: no PYTHONPATH/PYTHONHOME/user site from the user's shell
    # leaking into CraftBot's interpreter. NO_PROXY was set in __main__.
    agent_env = python_runtime.isolated_env(os.environ)
    agent_env["BROWSER_STARTUP_UI"] = "1"
    agent_env["PYTHONWARNINGS"] = "ignore"
    # Hand the child the Node runtime this process already resolved, so it
    # skips re-resolution and both processes agree on the same binary. Not
    # in conda mode: there the env's own node (>= 24 via environment.yml,
    # first on PATH under conda run) is the intended runtime.
    if not use_conda:
        # MCP servers invoke bare npx/node too. Passing only CRAFTBOT_NODE
        # helps our wrappers but leaves those subprocesses unable to start
        # on a machine without a system Node installation.
        agent_env.update(node_runtime.path_env())
        if "CRAFTBOT_NODE" not in agent_env:
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
        _record_launched(process, "agent backend")
        return process
    except Exception as e:
        if not silent:
            print(f"Error starting agent: {e}")
        return None


# ==========================================
# ENVIRONMENT DETECTION
# ==========================================
def _recorded_conda() -> Optional[str]:
    """config.json `conda_executable`: the conda install.py used, by absolute
    path. A login item or service starts with a minimal PATH (launchd,
    systemd), where `conda` does not resolve even though it is installed."""
    path = load_config().get("conda_executable")
    if isinstance(path, str) and path and os.path.isfile(path):
        return path
    return None


def is_conda_installed() -> Tuple[bool, str, Optional[str]]:
    recorded = _recorded_conda()
    if recorded:
        return True, recorded, os.path.dirname(os.path.dirname(recorded))

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
        with open(YML_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("name:"):
                    return line.split(":", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return "craftbot"


def get_conda_command() -> str:
    """Return conda command. Use full path on Windows if conda not in PATH."""
    recorded = _recorded_conda()
    if recorded:
        return recorded

    # Then try to find conda in PATH
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
        if a in ("--frontend-port", "--backend-port", "--agent-app-port"):
            skip_next = True
            continue
        if a.startswith(("--frontend-port=", "--backend-port=", "--agent-app-port=")):
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
#: How long to wait for the agent to finish booting before saying that it is
#: slow. Generous on purpose: a first run downloads the embedding model, which
#: on a slow connection is genuinely minutes. It is not a failure: run.py keeps
#: waiting for as long as the agent process is alive.
AGENT_READY_TIMEOUT_S = 900
#: How often a progress line is printed while waiting for the agent.
_PROGRESS_EVERY_S = 30


def _clear_agent_ready() -> None:
    """Remove a previous run's readiness marker."""
    try:
        from app import paths

        paths.AGENT_READY_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _wait_for_agent_ready(process=None, timeout: float = AGENT_READY_TIMEOUT_S) -> str:
    """Block until the agent says boot() finished. See app/paths.py.

    Returns "ready" when the marker appeared, "exited" when the agent process
    died first, "timeout" when it is still starting after `timeout` seconds.

    Watching `process` matters: the marker is only written on a *successful*
    boot, so an agent that crashes part-way through would otherwise leave us
    sitting here for the full timeout with nothing to show for it.
    """
    try:
        from app import paths

        marker = paths.AGENT_READY_FILE
    except Exception:
        return "ready"  # cannot check; do not block the boot on it

    started = time.time()
    next_note = started + _PROGRESS_EVERY_S
    while time.time() - started < timeout:
        try:
            if marker.is_file():
                return "ready"
        except OSError:
            pass
        if process is not None and process.poll() is not None:
            return "exited"
        now = time.time()
        if now >= next_note:
            print(f"  Still starting ({int(now - started)}s)...", flush=True)
            next_note += _PROGRESS_EVERY_S
        time.sleep(0.4)
    return "timeout"


def _wait_for_backend_port(process=None, timeout: Optional[float] = None) -> str:
    """Block until the backend answers HTTP: "ready", "exited" or "timeout".

    The backend binds its port when boot() is done, so this follows the
    ready marker within moments. Without a timeout it waits for as long as
    the agent process is alive.
    """
    started = time.time()
    while timeout is None or time.time() - started < timeout:
        if _instance.http_answers(_local_url(BACKEND_PORT)):
            return "ready"
        if process is not None and process.poll() is not None:
            return "exited"
        time.sleep(0.4)
    return "timeout"


def _fail_agent_exited(process, use_conda: bool, env_name: Optional[str]) -> None:
    """The agent died before CraftBot was usable: say so and exit non-zero."""
    code = getattr(process, "returncode", None)
    print("\n" + "=" * 52)
    print("ERROR: CraftBot stopped while starting.")
    print("=" * 52)
    print(f"   The agent process exited with code {code} before it was ready.")
    print("   The messages above show the cause.")
    if use_conda and env_name:
    print(
            f"   To run it directly: conda run -n {env_name} python main.py --browser"
    )
    else:
        print("   To run it directly: python main.py --browser")
    print("=" * 52 + "\n", flush=True)
    sys.exit(code if isinstance(code, int) and code > 0 else 1)


def _ports_given(argv: List[str]) -> bool:
    """Did the user choose the ports? Then they are used or refused, never
    replaced by others."""
    return any(
        a in ("--frontend-port", "--backend-port")
        or a.startswith(("--frontend-port=", "--backend-port="))
        for a in argv
    )


def _apply_ports(frontend_port: int, backend_port: int) -> None:
    """Make these the ports of this run, for us and every child process."""
    global FRONTEND_PORT, BACKEND_PORT, FRONTEND_URL, BACKEND_URL
    FRONTEND_PORT = int(frontend_port)
    BACKEND_PORT = int(backend_port)
    FRONTEND_URL = _instance.display_url(FRONTEND_PORT)
    BACKEND_URL = _instance.display_url(BACKEND_PORT)
    # Frontend (Vite, the static server, ws_auth's allowed origins) and backend.
    os.environ["VITE_PORT"] = str(FRONTEND_PORT)
    os.environ["VITE_BACKEND_PORT"] = str(BACKEND_PORT)
    os.environ["BROWSER_PORT"] = str(BACKEND_PORT)


def _claim_instance() -> Optional[Tuple[int, Optional[float]]]:
    """Record this run.py as the running CraftBot (app/instance.py).

    Returns the record it replaces, so a CraftBot it names can be recognised
    as this installation's own leftover. A login start has claimed the record
    already (craftbot._claim_service_process, which never replaces a running
    CraftBot), and that record stays as it is.
    """
    previous = _instance.read_pid_record()
    _instance.remove_ui()
    if previous is None or previous[0] != os.getpid():
        try:
            _instance.write_pid()
        except OSError as e:
            print(f"Warning: could not write {_instance.PID_FILE}: {e}")
    atexit.register(_release_instance)
    return previous


def _release_instance() -> None:
    """On a clean exit, drop the pid file and ui.json, unless a newer
    CraftBot has already replaced them."""
    record = _instance.read_pid_record()
    if record is not None and record[0] == os.getpid():
        _instance.remove_ui()
        _instance.remove_pid(only_if=os.getpid())


def _stop_previous_instance(record) -> Optional[int]:
    """Stop the CraftBot this state root's pid file still names, if it runs.

    Two agents on one state root would share its databases and workspace, so
    a new start replaces the old one, as `craftbot.py start` always did. Only
    a process that is provably CraftBot is stopped.
    """
    pid = _instance.live_pid(record)
    if not pid or pid == os.getpid():
        return None
    try:
        from app.process_ledger import identify_craftbot, kill_tree
    except Exception:
        return None
    description = identify_craftbot(pid)
    if not description:
        return None
    print(f"  Stopping the CraftBot already running from this folder ({description})")
    try:
        kill_tree(pid)
    except Exception as e:
        print(f"  Warning: could not stop pid {pid}: {e}")
    time.sleep(0.5)  # let the OS release its sockets
    return pid


def _load_service_env() -> None:
    """A login start (--service): restore the settings saved at install.

    Task Scheduler has no per-task environment, so `craftbot.py install`
    saves the user's network settings (proxies, mirrors, certificates) and
    CRAFTBOT_BIND_HOST to STATE_ROOT/service-env.json (Windows only; launchd
    and systemd carry them in the service file). A value already set in the
    environment wins.
    """
    if "--service" not in sys.argv[1:]:
        return
    try:
        with open(_paths.STATE_ROOT / "service-env.json", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(saved, dict):
        return
    for name, value in saved.items():
        if isinstance(name, str) and isinstance(value, str) and name not in os.environ:
            os.environ[name] = value


def _exit_on_sigterm(signum, frame) -> None:
    """systemd/launchd/`craftbot.py stop` send SIGTERM: leave through the
    normal exit path, so the pid file and ui.json are removed and the agent
    is stopped with us."""
    raise SystemExit(0)


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

    # Before the interpreter hop, so the re-launched process inherits them.
    _load_service_env()

    # Whatever `python` launched us is a trampoline: hop onto the project's
    # interpreter (the one the dependencies live in) before doing anything.
    python_runtime.reexec_if_needed()

    # Login services run this script directly, rather than through cmd_start.
    # Record their identity too, so status/stop/the installer can find them.
    # Consume the internal flag here; it must not reach the agent's CLI.
    if "--service" in sys.argv:
        sys.argv.remove("--service")
        import craftbot

        if not craftbot._claim_service_process():
            sys.exit(0)
        atexit.register(craftbot._release_service_process, os.getpid())

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

    # Loopback traffic never goes through a proxy, in this process and in
    # every child (the agent, Vite, MCP servers, Agent Apps): a corporate
    # HTTP(S)_PROXY without NO_PROXY cannot reach this machine's localhost.
    _instance.with_no_proxy(os.environ)

    # Parse port arguments (override defaults)
    explicit_ports = _ports_given(args_list)
    _apply_ports(
        parse_port_arg(args_list, "--frontend-port", FRONTEND_PORT),
        parse_port_arg(args_list, "--backend-port", BACKEND_PORT),
    )
    AGENT_APP_PORT = parse_port_arg(args_list, "--agent-app-port", 3100)

    # Browser mode is default (unless --cli specified)
    browser_mode = not cli_mode

    # The pid file says which process is the running CraftBot, for
    # craftbot.py, the launcher and service managers. Written now, after the
    # interpreter hop, so it names this process and not the trampoline.
    previous_instance = None
    if browser_mode:
        previous_instance = _claim_instance()
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _exit_on_sigterm)

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
    os.environ["AGENT_APP_PORT"] = str(AGENT_APP_PORT)

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
        # A CraftBot this folder's pid file still names is replaced, wherever
        # it listens; then leftovers of this installation on our ports go.
        stopped = _stop_previous_instance(previous_instance)
        blockers = _free_ports(
            FRONTEND_PORT, BACKEND_PORT, recorded_pids=[stopped] if stopped else []
        )
        if blockers:
            # What remains belongs to another program (or another CraftBot
            # installation). The readiness checks below probe a URL, not our
            # own socket, so a foreign server would answer them and the run
            # would report success for someone else's process: never start
            # on a port we could not take.
            if explicit_ports:
            print("\n" + "=" * 52)
                print("ERROR: CraftBot cannot start because its ports are in use.")
            print("=" * 52)
            for blocker in blockers:
                print(f"   {blocker}")
            print(
                "\n   Close that program, or choose different ports:"
                "\n     python run.py --frontend-port 8925 --backend-port 8926"
            )
            print("=" * 52 + "\n")
            sys.exit(1)
            pair = _instance.find_free_port_pair(FRONTEND_PORT, BACKEND_PORT, BIND_HOST)
            if pair is None:
                print("\n" + "=" * 52)
                print("ERROR: CraftBot could not find free ports to use.")
                print("=" * 52)
                for blocker in blockers:
                    print(f"   {blocker}")
                print(
                    "\n   Choose ports yourself:"
                    "\n     python run.py --frontend-port 8925 --backend-port 8926"
                )
                print("=" * 52 + "\n")
                sys.exit(1)
            print(
                f"\n  Ports {FRONTEND_PORT} and {BACKEND_PORT} are in use by another "
                f"program, so CraftBot will use ports {pair[0]} and {pair[1]}."
            )
            for blocker in blockers:
                print(f"    ({blocker})")
            _apply_ports(*pair)

        # Print browser mode header
        print_browser_header()

        # Step 1: Start agent backend. FIRST, so its boot (memory index,
        # MCP servers, skills) overlaps the frontend build below instead of
        # waiting for it: on a first start the two took ~2.5 and ~3 minutes
        # back to back. Neither needs the other; the browser opens only once
        # both are ready.
        print_step(1, 8, "Starting agent backend")
        # Clear last run's marker first, or we would read it as this run's
        # readiness and open the browser instantly.
        _clear_agent_ready()
        agent_process = launch_agent_background(env_name, use_conda, silent=True)
        if not agent_process:
            print(" ✗")
            print("\nError: Failed to start agent backend.")
            sys.exit(1)
        print_step_done()

        # Step 2: Start frontend server
        print_step(2, 8, "Starting frontend server")
        # Not silent. This used to be `silent=not sys.frozen`, which made
        # sense while the agent shipped as a PyInstaller binary; nothing is
        # frozen since that was retired, so the flag was always True and every
        # specific reason this can fail — a busy port, a missing dist/ — was
        # swallowed in favour of the generic "install Node.js" advice below.
        frontend_process = launch_frontend()
        if not frontend_process:
            print(" ✗")
            # Do not leave the already-started agent running headless.
            try:
                agent_process.terminate()
                agent_process.wait(timeout=15)
            except Exception:
                pass
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

            try:
            # The agent prints steps 3-8 itself while these waits run.
            frontend_ready = wait_for_frontend_silent(30)

            # The backend port only opens once boot() has finished (model
            # download, MCP servers, skills, integrations, scheduler), so the
            # ready marker is what to wait for. Waiting on the port with a
            # 60 s limit is what opened the browser onto 502 errors on a
            # slow first start, and printed "crashed" with exit code 0 when
            # the agent had in fact died.
            agent_state = _wait_for_agent_ready(agent_process)
            if agent_state == "exited":
                _fail_agent_exited(agent_process, use_conda, env_name)
            if agent_state == "timeout":
                print(
                    f"  The agent is taking longer than usual to start. CraftBot "
                    f"will be available at {FRONTEND_URL} when it finishes.",
                    flush=True,
                )
            if _wait_for_backend_port(agent_process) == "exited":
                _fail_agent_exited(agent_process, use_conda, env_name)

            # Record the listeners into the owned-process ledger: a port that
            # answered is a process we spawned, and recording it is what lets
            # the next run stop it if this one is killed.
        _adopt_port_listeners(
            *([FRONTEND_PORT] if frontend_ready else []),
                BACKEND_PORT,
        )

        # Small delay to ensure agent's stdout is flushed before we print
        # The agent prints steps 3-8, and we want them to appear before the ready banner
        time.sleep(0.3)

            if frontend_process.poll() is not None:
                print("\nError: the frontend server stopped.")
            print("   Try running: cd app/ui_layer/browser/frontend && npm run dev")
                sys.exit(1)

            # The UI answers: tell craftbot.py, the launcher and the desktop
            # shortcut where it is (the ports may not be the defaults).
            try:
                _instance.write_ui(FRONTEND_PORT, BACKEND_PORT)
            except OSError as e:
                print(f"Warning: could not write {_instance.UI_FILE}: {e}")
            print_ready_banner(FRONTEND_URL)
            if BIND_HOST not in ("localhost", "127.0.0.1", "::1", "[::1]"):
                print(
                    f"  Listening on {BIND_HOST} (ports {FRONTEND_PORT} and "
                    f"{BACKEND_PORT}). Open {FRONTEND_URL} on this machine, or "
                    "the same ports where they are published.\n",
                    flush=True,
                )
            if not no_open_browser:
                webbrowser.open(FRONTEND_URL)

            # Wait for the agent to finish (keeps script running). Updates
            # are handled by the external updater script (scripts/updater.bat)
            # which spawns in its own window and relaunches us: no exit-code
            # magic, no in-process restart.
            agent_process.wait()
        except KeyboardInterrupt:
            print("\nShutting down...")
            cleanup_background_processes()
            sys.exit(0)

        # Exit with the agent's status, so a crash is a failure to whoever
        # started us (craftbot.py, systemd Restart=on-failure, launchd).
        code = agent_process.returncode
        if isinstance(code, int) and code != 0:
            print(f"\nThe agent exited with code {code}.", flush=True)
            sys.exit(code if code > 0 else 1)
        sys.exit(0)
    else:
        # Non-browser mode: launch agent in foreground as before
        launch_agent(env_name, conda_base, use_conda)
