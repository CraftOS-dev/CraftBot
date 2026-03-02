#!/usr/bin/env python3
"""
CraftBot Run Script

Usage:
    python run.py           # Run the agent (CLI mode)
    python run.py --gui     # Run with GUI mode enabled

Options:
    --gui           Enable GUI mode (requires: python install.py --gui)
    --no-conda      Use global pip instead of conda
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
from typing import Tuple, Optional, Dict, Any

multiprocessing.freeze_support()

from dotenv import load_dotenv
load_dotenv()

# --- Base directory ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration ---
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
MAIN_APP_SCRIPT = os.path.join(BASE_DIR, "main.py")
YML_FILE = os.path.join(BASE_DIR, "environment.yml")

OMNIPARSER_ENV_NAME = "omni"
OMNIPARSER_SERVER_URL = os.getenv("OMNIPARSER_BASE_URL", "http://localhost:7861")

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def _wrap_windows_bat(cmd_list: list[str]) -> list[str]:
    if sys.platform != "win32":
        return cmd_list
    exe = shutil.which(cmd_list[0])
    if exe and exe.lower().endswith((".bat", ".cmd")):
        return ["cmd.exe", "/d", "/c", exe] + cmd_list[1:]
    return cmd_list

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
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
# ENVIRONMENT DETECTION
# ==========================================
def is_conda_installed() -> Tuple[bool, str, Optional[str]]:
    conda_exe = shutil.which("conda")
    if conda_exe:
        return True, conda_exe, os.path.dirname(os.path.dirname(conda_exe))

    if sys.platform == "win32":
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

def verify_env(env_name: str) -> bool:
    try:
        cmd = ["conda", "run", "-n", env_name, "python", "-c", "print('ok')"]
        run_command(cmd, capture=True)
        return True
    except:
        return False

# ==========================================
# OMNIPARSER SERVER
# ==========================================
def launch_omniparser(use_conda: bool) -> bool:
    """Launch OmniParser server for GUI mode."""
    print("\nStarting OmniParser server...")

    config = load_config()
    repo_path = config.get("omniparser_repo_path", os.path.abspath("OmniParser_CraftOS"))

    if not os.path.exists(repo_path):
        print(f"Error: OmniParser not installed at {repo_path}")
        print("Run 'python install.py --gui' first.")
        return False

    if use_conda:
        cmd = ["conda", "run", "-n", OMNIPARSER_ENV_NAME, "python", "-u", "-m", "gradio_demo"]
    else:
        cmd = [sys.executable, "-u", "-m", "gradio_demo"]

    launch_background_command(cmd, cwd=repo_path)

    if wait_for_server(OMNIPARSER_SERVER_URL, timeout=180):
        os.environ["OMNIPARSER_BASE_URL"] = OMNIPARSER_SERVER_URL
        return True

    print("OmniParser server failed to start.")
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

    # Filter flags
    skip_flags = {"--gui", "--no-conda"}
    pass_args = [a for a in sys.argv[1:] if a not in skip_flags]

    print(f"\nLaunching CraftBot...\n")

    # Build command
    if use_conda and env_name:
        # Find conda executable
        if conda_base:
            conda_exe = os.path.join(conda_base, "condabin", "conda.bat")
            if not os.path.exists(conda_exe):
                conda_exe = shutil.which("conda") or "conda"
        else:
            conda_exe = shutil.which("conda") or "conda"

        cmd = [conda_exe, "run", "--no-capture-output", "-n", env_name, "python", "-u", main_script] + pass_args

        # On Windows, wrap .bat files with cmd.exe
        if sys.platform == "win32" and conda_exe.lower().endswith((".bat", ".cmd")):
            cmd = ["cmd.exe", "/d", "/c"] + cmd
    else:
        cmd = [sys.executable, "-u", main_script] + pass_args

    # Run in current terminal
    try:
        result = subprocess.run(cmd, cwd=os.path.dirname(main_script))
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    print("="*50)
    print(" CraftBot")
    print("="*50)

    args = set(sys.argv[1:])

    # Parse flags
    gui_mode = "--gui" in args
    use_conda = "--no-conda" not in args

    # Load saved config
    config = load_config()
    gui_installed = config.get("gui_mode_enabled", False)

    # Set environment variables
    os.environ["USE_CONDA"] = str(use_conda)
    os.environ["GUI_MODE_ENABLED"] = str(gui_mode)
    os.environ["USE_OMNIPARSER"] = str(gui_mode)

    print(f"\nMode: {'GUI' if gui_mode else 'CLI'}")

    # Check conda
    conda_base = None
    env_name = None

    if use_conda:
        found, path, conda_base = is_conda_installed()
        if not found:
            print("Error: Conda not found. Use --no-conda or install conda.")
            sys.exit(1)
        env_name = get_env_name_from_yml()
        if not verify_env(env_name):
            print(f"\nEnvironment '{env_name}' not ready.")
            print("Run 'python install.py' first.")
            sys.exit(1)

    # Start OmniParser if GUI mode
    if gui_mode:
        if not gui_installed:
            print("\nGUI components not installed.")
            print("Run 'python install.py --gui' first.")
            sys.exit(1)

        if not launch_omniparser(use_conda):
            print("Warning: Continuing without OmniParser.")
            os.environ["USE_OMNIPARSER"] = "False"

    # Launch agent
    launch_agent(env_name, conda_base, use_conda)
