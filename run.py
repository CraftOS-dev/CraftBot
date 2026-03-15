#!/usr/bin/env python3
"""
CraftBot Run Script

Usage:
    python run.py             # Run the agent (browser interface - default)
    python run.py --tui       # Run in TUI mode
    python run.py --cli       # Run in CLI mode
    python run.py --gui       # Run with GUI mode enabled (AI can control VM)

Options:
    --gui                     Enable GUI mode (optional, requires: python install.py --gui)
    --tui                     Use TUI (terminal UI) interface instead of browser
    --cli                     Use CLI (command line) interface
    --conda                   Use conda environment (overrides config setting)
    --no-conda                Don't use conda (overrides config setting)
    --frontend-port PORT      Set frontend port (default: 7925)
    --backend-port PORT       Set backend port (default: 7926)

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

multiprocessing.freeze_support()

# Configuration is loaded from settings.json via the agent startup
# No .env file is used - all settings come from app/config/settings.json

# --- Base directory ---
# In a PyInstaller --onefile binary, bundled data is extracted to sys._MEIPASS
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _bootstrap_frozen():
    """Copy bundled config/data from _MEIPASS to CWD on first run.

    PyInstaller extracts bundled files into a temp directory (sys._MEIPASS)
    which is read-only and deleted on exit. The app expects mutable config
    and data directories under CWD so they persist between runs.
    """
    if not getattr(sys, 'frozen', False):
        return

    import shutil as _shutil

    meipass = sys._MEIPASS
    cwd = os.getcwd()

    # Directories to bootstrap (source relative to _MEIPASS)
    dirs_to_copy = [
        "app/config",
        "app/data",
        "agents",
        "assets",
        "skills",
    ]
    # Individual files to bootstrap
    files_to_copy = [
        "config.json",
        ".env.example",
    ]

    for rel_dir in dirs_to_copy:
        src = os.path.join(meipass, rel_dir)
        dst = os.path.join(cwd, rel_dir)
        if os.path.isdir(src) and not os.path.isdir(dst):
            print(f"  Bootstrapping {rel_dir}/...")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _shutil.copytree(src, dst)

    for rel_file in files_to_copy:
        src = os.path.join(meipass, rel_file)
        dst = os.path.join(cwd, rel_file)
        if os.path.isfile(src) and not os.path.isfile(dst):
            print(f"  Bootstrapping {rel_file}...")
            _shutil.copy2(src, dst)


_bootstrap_frozen()

# --- Configuration ---
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
MAIN_APP_SCRIPT = os.path.join(BASE_DIR, "main.py")
YML_FILE = os.path.join(BASE_DIR, "environment.yml")

OMNIPARSER_ENV_NAME = "omni"
OMNIPARSER_SERVER_URL = os.getenv("OMNIPARSER_BASE_URL", "http://localhost:7861")

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
                print(f"Warning: Invalid port value for {flag}, using default {default}")
                return default
        elif arg.startswith(f"{flag}="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                print(f"Warning: Invalid port value for {flag}, using default {default}")
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
        with open(CONFIG_FILE, 'r') as f:
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
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except IOError:
        pass

def run_command(cmd_list: list[str], cwd: Optional[str] = None, check: bool = True, capture: bool = False, env_extras: Dict[str, str] = None) -> subprocess.CompletedProcess:
    cmd_list = _wrap_windows_bat(cmd_list)
    my_env = os.environ.copy()
    if env_extras:
        my_env.update(env_extras)
    my_env["PYTHONUNBUFFERED"] = "1"

    kwargs = {}
    if capture:
        kwargs['capture_output'] = True
        kwargs['text'] = True
    else:
        kwargs['stdout'] = sys.stdout
        kwargs['stderr'] = sys.stderr

    try:
        return subprocess.run(cmd_list, cwd=cwd, check=check, env=my_env, **kwargs)
    except subprocess.CalledProcessError:
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Executable not found: {e.filename}")
        sys.exit(1)

def launch_background_command(cmd_list: list[str], cwd: Optional[str] = None, env_extras: Dict[str, str] = None) -> Optional[subprocess.Popen]:
    cmd_list = _wrap_windows_bat(cmd_list)
    my_env = os.environ.copy()
    if env_extras:
        my_env.update(env_extras)
    my_env["PYTHONUNBUFFERED"] = "1"

    print(f"Starting: {' '.join(cmd_list[:3])}...", flush=True)

    kwargs = {}
    if sys.platform != "win32":
        kwargs['start_new_session'] = True

    try:
        process = subprocess.Popen(
            cmd_list,
            cwd=cwd,
            env=my_env,
            stdout=sys.stdout,
            stderr=sys.stderr,
            **kwargs
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
        except:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    print(f" Timeout!")
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
            except:
                try:
                    proc.kill()
                except:
                    pass

# Register cleanup on exit
atexit.register(cleanup_background_processes)

def _try_install_nodejs_linux(silent: bool = False) -> bool:
    """
    Attempt to auto-install Node.js on Linux systems (including Kali).
    Returns True if successful, False otherwise.
    """
    if sys.platform == "win32":
        return False
    
    # Check if node is already installed
    if shutil.which("node") and shutil.which("npm"):
        return True
    
    if not silent:
        print("\n🔧 Attempting to install Node.js...")
    
    # Detect package manager and prepare commands
    package_managers = [
        ("apt-get", ["sudo", "apt-get", "update"], ["sudo", "apt-get", "install", "-y", "nodejs", "npm"]),
        ("apt", ["sudo", "apt", "update"], ["sudo", "apt", "install", "-y", "nodejs", "npm"]),
        ("dnf", None, ["sudo", "dnf", "install", "-y", "nodejs", "npm"]),
        ("yum", None, ["sudo", "yum", "install", "-y", "nodejs", "npm"]),
        ("pacman", None, ["sudo", "pacman", "-Sy", "nodejs", "npm"]),
        ("zypper", None, ["sudo", "zypper", "install", "-y", "nodejs", "npm"]),
    ]
    
    for pm_name, update_cmd, install_cmd in package_managers.items():
        if shutil.which(pm_name.split()[0]):
            if not silent:
                print(f"   Found {pm_name}, installing Node.js...")
            try:
                # Run update command if available
                if update_cmd:
                    try:
                        result = subprocess.run(update_cmd, capture_output=True, text=True, timeout=300)
                    except Exception:
                        pass  # Update failed, but continue with install
                
                # Run install command
                result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    if not silent:
                        print("✓ Node.js installed successfully")
                    # Small delay to ensure PATH is updated
                    time.sleep(1)
                    return True
                else:
                    if not silent:
                        print(f"   ⚠ {pm_name} installation failed, trying next...")
            except Exception as e:
                if not silent:
                    print(f"   ⚠ Error with {pm_name}: {str(e)[:100]}, trying next...")
    
    return False

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
                self.send_error(426, "WebSocket connections not proxied - connect directly to backend")
            else:
                # Serve static files; fall back to index.html for SPA routing
                # Check if file exists, otherwise serve index.html
                file_path = os.path.join(dist_dir, self.path.lstrip("/"))
                if not os.path.exists(file_path) or os.path.isdir(file_path):
                    if not os.path.exists(file_path + "/index.html") and "." not in os.path.basename(self.path):
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

    try:
        httpd = http.server.HTTPServer(("localhost", FRONTEND_PORT), FrontendHandler)
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


def launch_frontend(silent: bool = False) -> Optional[subprocess.Popen]:
    """Launch the frontend dev server for browser mode."""
    # If running as a PyInstaller binary, serve pre-built static files
    # instead of launching npm dev server (node/npm won't be available)
    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    is_frozen = getattr(sys, 'frozen', False)

    if is_frozen:
        if os.path.exists(dist_dir):
            return _launch_static_frontend(silent)
        else:
            # Binary mode but no dist folder bundled — can't start frontend
            if not silent:
                print(f"Error: Frontend dist not found at {dist_dir}")
                print(f"  BASE_DIR: {BASE_DIR}")
                print(f"  FRONTEND_DIR: {FRONTEND_DIR}")
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

    # Find npm command
    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        # Try to auto-install Node.js on Linux
        if sys.platform != "win32":
            if not silent:
                print("Node.js not found. Attempting auto-install on Linux...")
            if _try_install_nodejs_linux(silent=silent):
                npm_cmd = shutil.which("npm")

        if not npm_cmd:
            if not silent:
                print("Error: npm not found in PATH")
                print("\nNode.js is required for browser mode.")
                print("Install from: https://nodejs.org/ (choose LTS version)")
                print("\nAfter installation:")
                print("  1. Restart your terminal")
                print("  2. Run: python run.py")
            return None

    # Build command for npm run dev
    if sys.platform == "win32":
        # On Windows, use cmd.exe to run npm
        cmd = ["cmd.exe", "/c", "npm", "run", "dev"]
    else:
        cmd = [npm_cmd, "run", "dev"]

    try:
        # Start frontend in background
        # Redirect output to DEVNULL to prevent blocking when buffer fills
        process = subprocess.Popen(
            cmd,
            cwd=FRONTEND_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
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
        except:
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
    """Print the browser mode startup header."""
    print("\n🤖 CraftBot")
    print("━" * 52)
    print("\nMode: Browser\n")

def print_step(step_num: int, total: int, message: str, done: bool = False):
    """Print a formatted step line."""
    prefix = f"  [{step_num:>2}/{total}]"
    # Pad message to align checkmarks
    padded_msg = f"{message}...".ljust(STEP_WIDTH - len(prefix))
    if done:
        print(f"{prefix} {padded_msg}✓", flush=True)
    else:
        print(f"{prefix} {padded_msg}", end="", flush=True)

def print_step_done():
    """Print checkmark for current step."""
    print("✓", flush=True)

def print_progress_bar(percent: int, width: int = 40):
    """Print a progress bar from 0-100%."""
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r  [{bar}] {percent:3d}%")
    sys.stdout.flush()

def print_ready_banner(url: str):
    """Print the final ready banner."""
    print("\n" + "━" * 52)
    print(f"✓ Ready → CraftBot Browser Interface running at {url}")
    print("━" * 52 + "\n")

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
        except:
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
        except:
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
        except:
            pass
        print(".", end="", flush=True)
        time.sleep(0.5)
    print(" Timeout!")
    return False

def launch_agent_background(env_name: Optional[str], use_conda: bool, silent: bool = False) -> Optional[subprocess.Popen]:
    """Launch main.py in the background for browser mode."""
    main_script = os.path.abspath(MAIN_APP_SCRIPT)
    if not os.path.exists(main_script):
        if not silent:
            print(f"Error: {main_script} not found.")
        return None

    # Filter flags (--browser passes through to agent)
    skip_flags = {"--gui", "--conda", "--no-conda", "--tui"}
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

    # When running as a PyInstaller frozen binary, run main() in a thread
    # instead of spawning a subprocess (sys.executable is the binary itself)
    if getattr(sys, 'frozen', False):
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
        cmd = [conda_exe, "run", "--no-capture-output", "-n", env_name, "python", "-u", main_script] + pass_args

        # On Windows, wrap .bat files with cmd.exe
        if sys.platform == "win32" and conda_exe.lower().endswith((".bat", ".cmd")):
            cmd = ["cmd.exe", "/d", "/c"] + cmd
    else:
        cmd = [sys.executable, "-u", main_script] + pass_args

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
        with open(YML_FILE, 'r') as f:
            for line in f:
                if line.strip().startswith("name:"):
                    return line.split(":", 1)[1].strip().strip("'\"")
    except:
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
    except:
        return False

# ==========================================
# OMNIPARSER SERVER
# ==========================================
def launch_omniparser(use_conda: bool) -> bool:
    """Launch OmniParser server for GUI mode."""
    print("Starting GUI components (OmniParser)...")

    config = load_config()
    repo_path = config.get("omniparser_repo_path", os.path.abspath("OmniParser_CraftOS"))

    if not os.path.exists(repo_path):
        print(f"Error: GUI components not installed.")
        print("Run 'python install.py --gui --conda' first.")
        return False

    if use_conda:
        conda_cmd = get_conda_command()
        cmd = [conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "python", "-u", "-m", "gradio_demo"]
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

    # Filter flags (--cli and --tui pass through to agent)
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

    print(f"Starting CraftBot...\n")

    # When running as a PyInstaller frozen binary, sys.executable points to
    # the binary itself, so spawning "python main.py" would re-run run.py
    # in an infinite loop. Instead, import and call main() directly.
    if getattr(sys, 'frozen', False):
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
        cmd = [conda_exe, "run", "--no-capture-output", "-n", env_name, "python", "-u", main_script] + pass_args

        # On Windows, wrap .bat files with cmd.exe
        if sys.platform == "win32" and conda_exe.lower().endswith((".bat", ".cmd")):
            cmd = ["cmd.exe", "/d", "/c"] + cmd
    else:
        cmd = [sys.executable, "-u", main_script] + pass_args

    # Run in current terminal with all environment variables
    try:
        result = subprocess.run(cmd, cwd=os.path.dirname(main_script), env=os.environ.copy())
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    args_list = sys.argv[1:]
    args = set(args_list)

    # Parse flags
    gui_mode = "--gui" in args
    tui_mode = "--tui" in args
    cli_mode = "--cli" in args
    conda_flag = "--conda" in args
    no_conda_flag = "--no-conda" in args

    # Parse port arguments (override defaults)
    FRONTEND_PORT = parse_port_arg(args_list, "--frontend-port", FRONTEND_PORT)
    BACKEND_PORT = parse_port_arg(args_list, "--backend-port", BACKEND_PORT)
    FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"
    BACKEND_URL = f"http://localhost:{BACKEND_PORT}"

    # Browser mode is default (unless --tui or --cli specified)
    browser_mode = not tui_mode and not cli_mode

    # Load saved config to check what was actually installed
    config = load_config()
    use_conda = config.get("use_conda", False)  # Use config instead of defaulting to True

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
        if cli_mode:
            mode_str = "CLI"
        elif gui_mode:
            mode_str = "GUI + TUI"
        else:
            mode_str = "TUI"
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

    # Start OmniParser only if GUI mode and it was installed
    if gui_mode and gui_installed:
        if not launch_omniparser(use_conda):
            print("Warning: Continuing without OmniParser.")
            os.environ["USE_OMNIPARSER"] = "False"
    elif gui_mode and not gui_installed:
        print("\nGUI mode requested but components not installed.")
        print("Run: python install.py --gui --conda\n")
        sys.exit(1)

    # Browser mode: start frontend + agent, wait for both, then open browser
    if browser_mode:
        # Print browser mode header
        print_browser_header()

        # Step 1: Start frontend server (0% -> 10%)
        # Step 1: Start frontend server
        print_step(1, 8, "Starting frontend server")
        frontend_process = launch_frontend(silent=not getattr(sys, 'frozen', False))
        if not frontend_process:
            print(" ✗")
            print("\nError: Failed to start browser frontend.")
            print("\n" + "="*52)
            print("TROUBLESHOOTING:")
            print("="*52)
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
            print("="*52 + "\n")
            sys.exit(1)
        print_step_done()

        # Step 2: Start agent backend
        print_step(2, 8, "Starting agent backend")
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
            except:
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
            except:
                pass
            time.sleep(0.5)

        # Small delay to ensure agent's stdout is flushed before we print
        # The agent prints steps 3-8, and we want them to appear before the ready banner
        time.sleep(0.3)

        # Check if processes are still running
        frontend_alive = frontend_process and frontend_process.poll() is None
        backend_alive = agent_process and agent_process.poll() is None

        # Print ready banner and open browser
        if frontend_ready and backend_ready:
            print_ready_banner(FRONTEND_URL)
            webbrowser.open(FRONTEND_URL)
        elif not frontend_alive:
            print("\n⚠ Error: Frontend server crashed")
            print("   Check if Node.js and npm are properly installed")
            print("   Try running: cd app/ui_layer/browser/frontend && npm run dev")
        elif not backend_alive:
            print("\n⚠ Error: Agent backend crashed")
            print("   Check the error messages above for details")
            if use_conda:
                print(f"   Try running: conda activate {env_name} && python main.py --browser")
        else:
            # Frontend or backend may still be starting, but proceed anyway
            print_ready_banner(FRONTEND_URL)
            webbrowser.open(FRONTEND_URL)

        # Wait for agent to finish (keeps script running)
        try:
            agent_process.wait()
        except KeyboardInterrupt:
            print("\nShutting down...")
            cleanup_background_processes()
            sys.exit(0)
    else:
        # Non-browser mode: launch agent in foreground as before
        launch_agent(env_name, conda_base, use_conda)
