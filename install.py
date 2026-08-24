#!/usr/bin/env python3
"""
CraftBot Installation Script

Usage:
    python install.py              # Install core dependencies with global pip
    python install.py --conda      # Install with conda environment

Options:
    --conda         Use conda environment (optional)
    --mamba         Use mamba instead of conda (faster, optional with --conda)

Note: GUI mode (--gui) is temporarily disabled in V1.2.2.

After installation completes, CraftBot will automatically launch in browser mode.
To use the CLI instead, run: python run.py --cli
"""

import math
import multiprocessing
import os
import sys
import json
import subprocess
import shutil
import time
import threading
from typing import Tuple, Optional, Dict, Any

multiprocessing.freeze_support()

# Configuration is loaded from settings.json - no .env file is used
# All settings come from app/config/settings.json

# --- Base directory ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration ---
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
YML_FILE = os.path.join(BASE_DIR, "environment.yml")
REQUIREMENTS_FILE = os.path.join(BASE_DIR, "requirements.txt")

OMNIPARSER_REPO_URL = "https://github.com/zfoong/OmniParser_CraftOS.git"
OMNIPARSER_BRANCH = "CraftOS"
OMNIPARSER_ENV_NAME = "omni"
OMNIPARSER_MARKER_FILE = ".omniparser_setup_complete_v1"


# ==========================================
# TERMINAL COLORS  (orange/white brand palette)
# ==========================================
def _enable_windows_vtp() -> None:
    """Enable ANSI/VT100 virtual terminal processing on Windows 10+."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        m = ctypes.c_ulong()
        k32.GetConsoleMode(h, ctypes.byref(m))
        k32.SetConsoleMode(h, m.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _download_progress(count: int, block_size: int, total_size: int) -> None:
    """urllib reporthook that draws a retro progress bar."""
    if total_size <= 0:
        return
    pct = min(100, int(count * block_size * 100 / total_size))
    filled = int(40 * pct / 100)
    bar = f"{ORANGE}{'▓' * filled}{DIM}{'░' * (40 - filled)}{RESET}"
    sys.stdout.write(f"\r  Downloading  {bar}  {ORANGE}[ {pct:3d}% ]{RESET}")
    sys.stdout.flush()


def _find_existing_python310() -> Optional[str]:
    """Return a verified Python 3.10 executable path if one is already installed, else None."""
    candidates = []

    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(local_app, "Programs", "Python", "Python310", "python.exe"),
            r"C:\Python310\python.exe",
            os.path.join(
                os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                "Python310",
                "python.exe",
            ),
        ]
        # Also try the py launcher
        py_launcher = shutil.which("py")
        if py_launcher:
            try:
                r = subprocess.run(
                    [py_launcher, "-3.10", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                if "3.10" in (r.stdout + r.stderr):
                    return py_launcher  # caller uses it with "-3.10" flag
            except Exception:
                pass
    elif sys.platform == "darwin":
        candidates = [
            shutil.which("python3.10") or "",
            "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10",
            "/usr/local/bin/python3.10",
            "/opt/homebrew/bin/python3.10",
        ]
    else:
        candidates = [shutil.which("python3.10") or ""]

    for path in candidates:
        if path and os.path.isfile(path):
            try:
                r = subprocess.run(
                    [path, "--version"], capture_output=True, text=True, timeout=8
                )
                if "3.10" in (r.stdout + r.stderr):
                    return path
            except Exception:
                pass
    return None


def _auto_install_python_310() -> None:
    """Download and silently install Python 3.10 (tries recent patch versions in order), then re-launch install.py with it."""
    import urllib.request

    # Try recent patch versions in descending order.
    PYTHON_VERSION_CANDIDATES = [
        "3.10.17",
        "3.10.16",
        "3.10.15",
        "3.10.14",
        "3.10.13",
        "3.10.12",
        "3.10.11",
    ]

    if sys.platform == "win32":
        is_64bit = sys.maxsize > 2**32

        installer = None
        chosen_version = None
        for version in PYTHON_VERSION_CANDIDATES:
            suffix = "-amd64.exe" if is_64bit else ".exe"
            filename = f"python-{version}{suffix}"
            url = f"https://www.python.org/ftp/python/{version}/{filename}"
            dest = os.path.join(BASE_DIR, filename)
            print(f"\n  {WHITE}Trying Python {version}...{RESET}")
            print(f"  Source : {url}")
            print("  Size   : ~25 MB\n")
            try:
                urllib.request.urlretrieve(url, dest, reporthook=_download_progress)
                print()  # newline after progress bar
                installer = dest
                chosen_version = version
                break
            except Exception as exc:
                print(f"\n  {RED}✗{RESET} Download failed: {exc}")
                try:
                    os.remove(dest)
                except Exception:
                    pass

        if installer is None or chosen_version is None:
            print(
                f"\n  {RED}✗{RESET} {WHITE}Could not download Python automatically.{RESET}"
            )
            print("  All download attempts failed (HTTP 404 or network error).")
            print("\n  Please install Python 3.10 manually:")
            print("  1. Go to: https://www.python.org/downloads/")
            print("  2. Download the latest Python 3.10 installer for Windows")
            print("  3. Run the installer (check 'Add Python to PATH')")
            print("  4. Open a NEW terminal and run: python install.py")
            sys.exit(1)

        print(
            f"\n  {WHITE}Installing Python {chosen_version} (this window may briefly flash)...{RESET}"
        )
        result = subprocess.run(
            [
                installer,
                "/passive",  # minimal UI — shows a small progress dialog
                "InstallAllUsers=0",  # current user only (no admin needed)
                "PrependPath=1",  # adds python to PATH
                "AssociateFiles=1",
                "Include_pip=1",
                "Include_launcher=1",
            ],
            timeout=300,
        )

        try:
            os.remove(installer)
        except Exception:
            pass

        if result.returncode != 0:
            print(f"\n  {RED}✗{RESET} Installer exited with code {result.returncode}.")
            print("\n  Please install Python 3.10 manually:")
            print("  1. Go to: https://www.python.org/downloads/")
            print("  2. Download the latest Python 3.10 installer for Windows")
            print("  3. Run the installer (check 'Add Python to PATH')")
            print("  4. Open a NEW terminal and run: python install.py")
            sys.exit(1)

        print(f"\n  {GREEN}✓{RESET} {WHITE}Python {chosen_version} installed!{RESET}")

        # Locate the freshly installed python.exe and verify it is actually 3.10.
        local_app = os.environ.get("LOCALAPPDATA", "")
        search_paths = [
            os.path.join(local_app, "Programs", "Python", "Python310", "python.exe"),
            r"C:\Python310\python.exe",
            os.path.join(
                os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                "Python310",
                "python.exe",
            ),
        ]
        new_python310 = None
        for path in search_paths:
            if os.path.isfile(path):
                try:
                    ver_result = subprocess.run(
                        [path, "--version"], capture_output=True, text=True, timeout=10
                    )
                    ver_text = (ver_result.stdout + ver_result.stderr).strip()
                    if "3.10" in ver_text:
                        new_python310 = path
                        break
                except Exception:
                    pass

        # Fallback: try the py launcher with -3.10 and verify it resolves to 3.10
        if new_python310 is None:
            py_launcher = shutil.which("py")
            if py_launcher:
                try:
                    ver_result = subprocess.run(
                        [py_launcher, "-3.10", "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    ver_text = (ver_result.stdout + ver_result.stderr).strip()
                    if "3.10" in ver_text:
                        new_python310 = py_launcher  # will use with -3.10 flag below
                except Exception:
                    pass

        if new_python310:
            print(f"\n  {ORANGE}▸{RESET} Re-launching installer with Python 3.10...\n")
            if new_python310.lower().endswith("py.exe"):
                cmd = [new_python310, "-3.10", __file__]
            else:
                cmd = [new_python310, __file__]
            # Pass --skip-python-check so the re-launched process skips the
            # version gate and doesn't loop back into auto-install again.
            # Keep ALL flags — dropping --no-launch here made a craftbot.py
            # install boot the agent in the foreground mid-install.
            extra = list(sys.argv[1:])
            result = subprocess.run(cmd + extra + ["--skip-python-check"])
            sys.exit(result.returncode)
        else:
            print(
                f"\n  {ORANGE}▸{RESET} {WHITE}Python 3.10 installed — please open a NEW terminal and run:{RESET}"
            )
            print(f"  {ORANGE}python install.py{RESET}")
            print("  (The new terminal will pick up Python 3.10 automatically.)")

        # Only the could-not-relaunch path reaches here: dependencies were NOT
        # installed, so signal failure to any orchestrating caller.
        sys.exit(1)

    elif sys.platform == "darwin":
        installer = None
        chosen_version = None
        for version in PYTHON_VERSION_CANDIDATES:
            url = f"https://www.python.org/ftp/python/{version}/python-{version}-macos11.pkg"
            dest = os.path.join(BASE_DIR, f"python-{version}.pkg")
            print(f"\n  {WHITE}Trying Python {version}...{RESET}")
            print(f"  Source : {url}")
            try:
                urllib.request.urlretrieve(url, dest, reporthook=_download_progress)
                print()
                installer = dest
                chosen_version = version
                break
            except Exception as exc:
                print(f"\n  {RED}✗{RESET} Download failed: {exc}")
                try:
                    os.remove(dest)
                except Exception:
                    pass

        if installer is None or chosen_version is None:
            print(
                f"\n  {RED}✗{RESET} {WHITE}Could not download Python automatically.{RESET}"
            )
            print("\n  Please install Python 3.10 manually:")
            print("  1. Go to: https://www.python.org/downloads/")
            print("  2. Download the latest Python 3.10 macOS installer")
            print("  3. Run the installer")
            print("  4. Open a NEW terminal and run: python3.10 install.py")
            sys.exit(1)

        print(f"\n  {WHITE}Installing (sudo required)...{RESET}")
        result = subprocess.run(
            ["sudo", "installer", "-pkg", installer, "-target", "/"], timeout=300
        )
        try:
            os.remove(installer)
        except Exception:
            pass
        if result.returncode != 0:
            print(f"\n  {RED}✗{RESET} Installation failed.")
            print(
                "\n  Please install Python 3.10 manually from: https://www.python.org/downloads/"
            )
            sys.exit(1)
        print(f"\n  {GREEN}✓{RESET} {WHITE}Python {chosen_version} installed!{RESET}")
        _mac_candidates = [
            shutil.which("python3.10"),
            "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10",
            "/usr/local/bin/python3.10",
            "/opt/homebrew/bin/python3.10",
        ]
        new_python = next((p for p in _mac_candidates if p and os.path.isfile(p)), None)
        if new_python:
            print(f"\n  {ORANGE}▸{RESET} Re-launching with Python 3.10...\n")
            os.execv(new_python, [new_python, __file__] + sys.argv[1:])
        else:
            print("\n  Please open a new terminal and run: python3.10 install.py")
        sys.exit(0)

    else:  # Linux — try multiple package managers in order

        def _run_step(cmd: list) -> bool:
            print(f"  {DIM}▸ {' '.join(cmd)}{RESET}")
            return subprocess.run(cmd).returncode == 0

        installed = False

        if shutil.which("apt-get") or shutil.which("apt"):
            apt = shutil.which("apt-get") or shutil.which("apt")
            print("  Detected apt — installing Python 3.10 (sudo required)...\n")

            # Step 1: try direct install first (works on Kali, Debian 12, Ubuntu 22.04+)
            _run_step(["sudo", apt, "update", "-qq"])
            ok = _run_step(
                ["sudo", apt, "install", "-y", "python3.10", "python3.10-venv"]
            )

            if not ok:
                # Step 2: add deadsnakes PPA (Ubuntu/Mint where direct install fails)
                print("\n  Direct install failed — trying deadsnakes PPA...\n")
                _run_step(["sudo", apt, "install", "-y", "software-properties-common"])
                _run_step(["sudo", "add-apt-repository", "-y", "ppa:deadsnakes/ppa"])
                _run_step(["sudo", apt, "update", "-qq"])
                ok = _run_step(
                    ["sudo", apt, "install", "-y", "python3.10", "python3.10-venv"]
                )

            if ok:
                # python3.10-distutils was removed in Ubuntu 23.04+ — ignore failure
                subprocess.run(
                    ["sudo", apt, "install", "-y", "python3.10-distutils"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                installed = True

        elif shutil.which("dnf"):
            print(
                "  Detected dnf (Fedora/RHEL) — installing Python 3.10 (sudo required)...\n"
            )
            installed = _run_step(["sudo", "dnf", "install", "-y", "python3.10"])

        elif shutil.which("pacman"):
            # Arch ships Python 3.11+ as 'python'; 3.10 available via AUR or python310 package
            print(
                "  Detected pacman (Arch) — installing python3.10 (sudo required)...\n"
            )
            installed = _run_step(["sudo", "pacman", "-Sy", "--noconfirm", "python310"])
            if not installed:
                # Fallback: current python package (3.11+) is still compatible
                installed = _run_step(
                    ["sudo", "pacman", "-Sy", "--noconfirm", "python"]
                )

        elif shutil.which("zypper"):
            print(
                "  Detected zypper (openSUSE) — installing Python 3.10 (sudo required)...\n"
            )
            installed = _run_step(["sudo", "zypper", "install", "-y", "python310"])

        if not installed:
            print(
                f"\n  {RED}✗{RESET} Could not install Python 3.10 automatically on this system."
            )
            print(
                "\n  Please install Python 3.10 manually using pyenv (works on any distro):"
            )
            print("    curl https://pyenv.run | bash")
            print("    pyenv install 3.10.17")
            print("    pyenv local 3.10.17")
            print("    python install.py")
            sys.exit(1)

        new_python = shutil.which("python3.10")
        if new_python:
            print(f"\n  {GREEN}✓{RESET} {WHITE}Python 3.10 installed!{RESET}")
            print(f"\n  {ORANGE}▸{RESET} Re-launching installer with Python 3.10...\n")
            os.execv(new_python, [new_python, __file__] + sys.argv[1:])
        else:
            print(f"\n  {GREEN}✓{RESET} {WHITE}Python 3.10 installed!{RESET}")
            print("\n  Please open a new terminal and run: python3.10 install.py")
            sys.exit(0)


_enable_windows_vtp()
_USE_COLOR = sys.stdout.isatty()


def _c(code: str) -> str:
    return code if _USE_COLOR else ""


ORANGE = _c("\033[38;2;255;79;24m")  # #FF4F18
WHITE = _c("\033[38;2;255;255;255m")  # #FFFFFF
BOLD = _c("\033[1m")
DIM = _c("\033[38;2;80;80;80m")  # dark gray for empty bar
GREEN = _c("\033[38;2;80;220;100m")
RED = _c("\033[91m")
RESET = _c("\033[0m")


# ==========================================
# PROGRESS BAR
# ==========================================
class ProgressBar:
    """Simple progress bar showing 0% to 100%."""

    def __init__(self, total_steps: int = 10):
        self.total_steps = max(1, total_steps)
        self.current_step = 0
        self.bar_length = 40

    def update(self, step: int = None):
        """Update progress to step number."""
        if step is not None:
            self.current_step = min(step, self.total_steps - 1)
        else:
            self.current_step = min(self.current_step + 1, self.total_steps - 1)

        self._draw_bar()

    def _draw_bar(self):
        """Draw the progress bar."""
        if self.total_steps > 0:
            percent = int((self.current_step / self.total_steps) * 100)
        else:
            percent = 100

        filled = int(self.bar_length * self.current_step / max(1, self.total_steps))
        bar = "=" * filled + "-" * (self.bar_length - filled)

        sys.stdout.write(f"\r[{bar}] {percent}%")
        sys.stdout.flush()

    def finish(self, message: str = "Complete"):
        """Finish with 100%."""
        self.current_step = self.total_steps
        bar = "=" * self.bar_length
        sys.stdout.write(f"\r[{bar}] 100% - {message}\n")
        sys.stdout.flush()


# ==========================================
# ANIMATED PROGRESS INDICATOR
# ==========================================
class AnimatedProgress:
    """Retro-style animated progress bar."""

    def __init__(self, message: str = "Installing"):
        self.message = message.upper()
        self.percent = 0
        self.bar_length = 40

    def update(self, percent: int):
        self.percent = min(percent, 100)
        filled = int(self.bar_length * self.percent / 100)
        bar = f"{ORANGE}{'▓' * filled}{DIM}{'░' * (self.bar_length - filled)}{RESET}"
        pct = f"{self.percent}%".rjust(4)
        sys.stdout.write(
            f"\r  {WHITE}{self.message}{RESET}  {bar}  {ORANGE}[ {pct} ]{RESET}"
        )
        sys.stdout.flush()

    def finish(self):
        bar = f"{ORANGE}{'▓' * self.bar_length}{RESET}"
        sys.stdout.write(
            f"\r  {WHITE}{self.message}{RESET}  {bar}  {GREEN}[ 100% ]{RESET}\n"
        )
        sys.stdout.flush()


def run_command_with_progress(
    cmd_list: list[str],
    message: str = "Processing",
    cwd: Optional[str] = None,
    check: bool = True,
    capture: bool = False,
    env_extras: Dict[str, str] = None,
) -> subprocess.CompletedProcess:
    """Run command with animated progress bar."""
    # Validate command
    if not cmd_list or not isinstance(cmd_list, list) or len(cmd_list) == 0:
        print(f"\n✗ Invalid command: {cmd_list}")
        if check:
            sys.exit(1)
        return None

    cmd_list = _wrap_windows_bat(cmd_list)
    my_env = os.environ.copy()
    if env_extras:
        my_env.update(env_extras)
    my_env["PYTHONUNBUFFERED"] = "1"

    progress = AnimatedProgress(message)

    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }

    try:
        # Start process
        process = subprocess.Popen(cmd_list, cwd=cwd, env=my_env, **kwargs)

        # Asymptotic progress: continuously moves, decelerates near 95%, never sticks
        # Formula: pct = 95 * (1 - e^(-elapsed / tau))
        # tau=45s → ~60% at 45s, ~86% at 90s, ~95% at ~135s
        def update_progress():
            start = time.time()
            tau = 45.0
            while process.poll() is None:
                elapsed = time.time() - start
                pct = int(95 * (1 - math.exp(-elapsed / tau)))
                progress.update(pct)
                time.sleep(0.5)

        # Start progress thread
        progress_thread = threading.Thread(target=update_progress, daemon=True)
        progress_thread.start()

        # Wait for process to finish
        stdout, stderr = process.communicate()

        # Complete progress
        progress.finish()

        if process.returncode != 0 and check:
            print("\n✗ Error during installation:")
            if stderr:
                print(stderr[:500])
            sys.exit(1)

        return subprocess.CompletedProcess(cmd_list, process.returncode, stdout, stderr)

    except FileNotFoundError as e:
        exe_name = e.filename or cmd_list[0]
        print(f"\n✗ Executable not found: {exe_name}")
        print(f"   Command: {' '.join(cmd_list)}")
        print("   Make sure this program is installed and in your PATH")
        if check:
            sys.exit(1)
        return None


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


# ==========================================
# DISK SPACE CHECKING (for Kali & other systems)
# ==========================================
def get_disk_space(path: str = ".") -> Tuple[float, float, float]:
    """
    Get disk space info for a path (total, used, free in GB).
    Returns: (total_gb, used_gb, free_gb)
    Silent failure - returns (0, 0, 0) if unable to check
    """
    try:
        if sys.platform == "win32":
            import ctypes

            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceEx(
                ctypes.c_wchar_p(path), None, None, ctypes.pointer(free_bytes)
            )
            free_gb = free_bytes.value / (1024**3)
            # For Windows, we'll estimate total as free + a reasonable amount
            total_gb = free_gb + 50  # Estimate
            used_gb = 0
        else:
            # Unix/Linux/Mac
            st = os.statvfs(path)
            free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
            total_gb = (st.f_blocks * st.f_frsize) / (1024**3)
            used_gb = ((st.f_blocks - st.f_bfree) * st.f_frsize) / (1024**3)

        return total_gb, used_gb, free_gb
    except Exception:
        # Silently fail - disk space check is not critical
        return 0, 0, 0


def check_disk_space_for_installation(min_free_gb: float = 5.0) -> bool:
    """
    Check if there's enough disk space for installation.
    Returns True if OK, False if insufficient space.
    """
    home_free_gb = get_disk_space(os.path.expanduser("~"))[2]
    home_total_gb = get_disk_space(os.path.expanduser("~"))[0]
    home_used_gb = get_disk_space(os.path.expanduser("~"))[1]

    if home_total_gb == 0:  # Couldn't get info
        return True  # Assume it's okay

    percent_used = (home_used_gb / home_total_gb * 100) if home_total_gb > 0 else 0

    print("\n" + "=" * 60)
    print(" 📊 Disk Space Check")
    print("=" * 60)
    print(f"Home directory: {os.path.expanduser('~')}")
    print(f"Total space:   {home_total_gb:.1f} GB")
    print(f"Used space:    {home_used_gb:.1f} GB ({percent_used:.1f}%)")
    print(f"Free space:    {home_free_gb:.1f} GB")

    if home_free_gb < min_free_gb:
        print(
            f"\n⚠️  WARNING: Low disk space ({home_free_gb:.1f} GB free, need {min_free_gb:.1f} GB)"
        )
        print("\nRecommended fixes:")
        print("\n1. Clean up pip cache:")
        print("   pip cache purge")
        print("\n2. Clean up npm cache (if Node.js installed):")
        print("   npm cache clean --force")
        print("\n3. Remove old files/packages:")
        print("   rm -rf ~/.cache/*  # On Linux/Mac")
        print("   rmdir /s %LocalAppData%\\pip  # On Windows")
        print("\n4. Use a different disk with more space:")
        mkdir_path = (
            "/mnt/large-disk/pip-tmp" if sys.platform != "win32" else "D:/pip-tmp"
        )
        print(f"   mkdir -p {mkdir_path}")
        print(f"   TMPDIR={mkdir_path} python install.py")
        print("\n5. Or continue anyway (may fail): ", end="")

        choice = input("Continue? (y/n): ").strip().lower()
        if choice != "y":
            print("Installation cancelled. Please free up disk space and try again.")
            return False
        else:
            print("\nAttempting installation anyway...\n")

    print("=" * 60 + "\n")
    return True


def suggest_cleanup_steps():
    """Show cleanup steps if disk is full."""
    print("\n" + "=" * 60)
    print(" 🧹 Disk Space Cleanup Guide (for Kali & other systems)")
    print("=" * 60)
    print("\nTo free up disk space:\n")

    print("1. Clear pip cache (usually 1-5 GB):")
    print("   pip cache purge\n")

    print("2. Clear npm cache (if Node.js installed):")
    print("   npm cache clean --force\n")

    print("3. Clear system caches (Linux/Mac):")
    print("   sudo apt-get clean      # Apt packages")
    print("   sudo pacman -Sc         # Pacman packages")
    print("   rm -rf ~/.cache/*       # User cache\n")

    print("4. Remove temporary files:")
    print("   rm -rf /tmp/*           # System temp (Linux/Mac)")
    print("   rmdir /s /q %temp%      # Windows temp\n")

    print("5. Check what's using space:")
    print("   du -sh ~/*              # Home directory breakdown (Linux/Mac)")
    print("   dir /-s C:\\             # Windows directory sizes\n")

    print("6. Use alternate location with more space:")
    print("   mkdir -p /mnt/external-drive/pip-tmp")
    print("   TMPDIR=/mnt/external-drive/pip-tmp python install.py\n")

    print("=" * 60 + "\n")


def load_config() -> Dict[str, Any]:
    """
    Load configuration from file safely.

    SECURITY FIX: Use try-except instead of check-then-use to prevent TOCTOU race conditions.
    This ensures atomic read operation.
    """
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        # File doesn't exist - return empty config
        return {}
    except json.JSONDecodeError:
        print(f"Warning: {CONFIG_FILE} is corrupted. Starting with empty config.")
        return {}
    except IOError as e:
        print(f"Warning: Cannot read config: {e}")
        return {}


def save_config_value(key: str, value: Any) -> None:
    config = load_config()
    config[key] = value
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except IOError:
        pass  # Silently fail if config can't be saved


def run_command(
    cmd_list: list[str],
    cwd: Optional[str] = None,
    check: bool = True,
    capture: bool = False,
    env_extras: Dict[str, str] = None,
    quiet: bool = False,
    show_error: bool = True,
) -> subprocess.CompletedProcess:
    # Validate command
    if not cmd_list or not isinstance(cmd_list, list) or len(cmd_list) == 0:
        if show_error:
            print(f"\n✗ Invalid command: {cmd_list}")
        if check:
            sys.exit(1)
        return None

    cmd_list = _wrap_windows_bat(cmd_list)
    my_env = os.environ.copy()
    if env_extras:
        my_env.update(env_extras)
    my_env["PYTHONUNBUFFERED"] = "1"

    kwargs = {}
    if capture or quiet:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    try:
        result = subprocess.run(cmd_list, cwd=cwd, check=check, env=my_env, **kwargs)
        return result
    except subprocess.CalledProcessError as e:
        if show_error:
            if capture or quiet:
                print(f"\n✗ Error running: {' '.join(cmd_list)}")
                if e.stdout:
                    print(f"STDOUT: {e.stdout[:1000]}")
                if e.stderr:
                    print(f"STDERR: {e.stderr[:1000]}")
            else:
                print(f"\n✗ Command failed: {' '.join(cmd_list)}")
        if check:
            sys.exit(1)
        return e
    except FileNotFoundError as e:
        if show_error:
            exe_name = e.filename or cmd_list[0]
            print(f"\n✗ Executable not found: {exe_name}")
            print(f"   Command: {' '.join(cmd_list)}")
            print("   Make sure this program is installed and in your PATH")
        if check:
            sys.exit(1)
        return None


# ==========================================
# ENVIRONMENT SETUP
# ==========================================
def is_conda_installed() -> Tuple[bool, str, Optional[str]]:
    conda_exe = shutil.which("conda")
    if conda_exe:
        conda_base_path = os.path.dirname(os.path.dirname(conda_exe))
        return True, f"Found at {conda_exe}", conda_base_path

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
                return True, f"Found at {base_path}", base_path

        # Also check current Python directory
        current_python_dir = os.path.dirname(sys.executable)
        potential_base_paths = [
            os.path.dirname(current_python_dir),
            os.path.dirname(os.path.dirname(current_python_dir)),
        ]
        for base_path in potential_base_paths:
            activate_bat = os.path.join(base_path, "Scripts", "activate.bat")
            condabin_bat = os.path.join(base_path, "condabin", "conda.bat")
            if os.path.exists(activate_bat) or os.path.exists(condabin_bat):
                return True, f"Found at {base_path}", base_path

    return False, "Not found", None


def get_env_name_from_yml(yml_path: str = YML_FILE) -> str:
    try:
        with open(yml_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("name:"):
                    return stripped.split(":", 1)[1].strip().strip("'").strip('"')
    except FileNotFoundError:
        print(f"Error: {yml_path} not found.")
        sys.exit(1)
    print(f"Error: Could not find 'name:' in {yml_path}.")
    sys.exit(1)


def install_miniconda():
    """Auto-install Miniconda for the current platform."""
    import urllib.request
    import subprocess as sp

    print("\n🔧 Auto-installing Miniconda...\n")

    # Detect OS and architecture
    if sys.platform == "win32":
        # Windows
        if sys.maxsize > 2**32:
            url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
            installer = os.path.join(BASE_DIR, "Miniconda-installer.exe")
        else:
            url = (
                "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86.exe"
            )
            installer = os.path.join(BASE_DIR, "Miniconda-installer.exe")
    elif sys.platform == "linux":
        # Linux
        if sys.maxsize > 2**32:
            url = (
                "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
            )
        else:
            url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86.sh"
        installer = os.path.join(BASE_DIR, "miniconda-installer.sh")
    elif sys.platform == "darwin":
        # macOS
        if sys.maxsize > 2**32:
            url = (
                "https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh"
            )
        else:
            url = (
                "https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh"
            )
        installer = os.path.join(BASE_DIR, "miniconda-installer.sh")
    else:
        print(f"❌ Unsupported platform: {sys.platform}")
        return False

    try:
        print(f"📥 Downloading Miniconda ({os.path.basename(url)})...")
        urllib.request.urlretrieve(url, installer)
        print(f"✓ Downloaded to {installer}\n")

        if sys.platform == "win32":
            print("🔧 Running Miniconda installer...")
            print("   An installation dialog will appear. Select:")
            print("   - Add Miniconda to PATH (important!)")
            print("   - Install for current user\n")
            sp.run([installer], check=True)
            print("\n✓ Miniconda installed!")
            print("   Please restart your terminal and run the installation again.\n")
            os.remove(installer)
            return True
        else:
            print("🔧 Running Miniconda installer...")
            sp.run(
                ["bash", installer, "-b", "-p", os.path.expanduser("~/miniconda3")],
                check=True,
            )
            print("✓ Miniconda installed!")
            print(
                "   Please add conda to PATH, then restart terminal and run installation again.\n"
            )
            os.remove(installer)
            return True
    except Exception as e:
        print(f"❌ Miniconda installation failed: {e}")
        if os.path.exists(installer):
            try:
                os.remove(installer)
            except Exception:
                pass
        return False


def get_conda_command() -> str:
    """Return conda command. Use full path on Windows if conda not in PATH."""
    # Mamba can have compatibility issues, so use conda by default
    # Users can pass --mamba flag if they want to use mamba
    if "--mamba" in sys.argv:
        if shutil.which("mamba"):
            return "mamba"

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


def setup_conda_environment(env_name: str, yml_path: str = YML_FILE):
    conda_cmd = get_conda_command()
    try:
        print(f"🔧 Setting up conda environment '{env_name}'...")
        result = run_command_with_progress(
            [conda_cmd, "env", "update", "-f", yml_path, "-n", env_name],
            "Installing dependencies via conda",
            check=False,
        )
        if result and hasattr(result, "returncode") and result.returncode == 0:
            print("✓ Conda environment ready")
        else:
            print("\n✗ Failed to set up conda environment")
            if result and hasattr(result, "stderr"):
                print(result.stderr[:500])
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error setting up conda environment: {e}")
        sys.exit(1)


def verify_conda_env(env_name: str) -> bool:
    try:
        conda_cmd = get_conda_command()
        verification_cmd = [
            conda_cmd,
            "run",
            "-n",
            env_name,
            "python",
            "-c",
            "print('OK')",
        ]
        result = run_command(
            verification_cmd, capture=True, quiet=True, check=False, show_error=False
        )
        return result and hasattr(result, "returncode") and result.returncode == 0
    except Exception:
        return False


def install_nodejs_linux():
    """
    Automatically install Node.js on Linux/macOS systems (including Kali).
    Detects the package manager (brew, apt, pacman, yum) and installs accordingly.
    """
    if sys.platform == "win32":
        return True  # Windows users should install Node.js manually from nodejs.org

    # Check if node is already installed
    if shutil.which("node") and shutil.which("npm"):
        print("✓ Node.js and npm are already installed")
        return True

    print("\n🔧 Installing Node.js...")

    # macOS: try Homebrew first, then nvm
    if sys.platform == "darwin":
        if shutil.which("brew"):
            print("   Found Homebrew, installing Node.js...")
            try:
                result = run_command(
                    ["brew", "install", "node"],
                    check=False,
                    capture=True,
                    quiet=True,
                    show_error=False,
                )
                if result and hasattr(result, "returncode") and result.returncode == 0:
                    print("✓ Node.js installed via Homebrew")
                    time.sleep(1)
                    if shutil.which("node") and shutil.which("npm"):
                        return True
                    print(
                        "⚠ Node.js installed but not yet in PATH. Restart your terminal."
                    )
                    return False
            except Exception as e:
                print(f"   ⚠ brew install node failed: {str(e)[:100]}")
        print("\n⚠ Could not automatically install Node.js on macOS")
        print("\nOptions:")
        print("  1. Install Homebrew (https://brew.sh), then run: brew install node")
        print("  2. Download Node.js from: https://nodejs.org/ (LTS version)")
        print(
            "  3. Use nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash"
        )
        print("     then: nvm install --lts")
        print(
            "\n  After installation, restart your terminal and run: python3 install.py"
        )
        return False

    # Detect package manager and prepare install commands
    # Format: (package_manager, update_cmd, install_cmd)
    package_managers = [
        (
            "apt-get",
            ["sudo", "apt-get", "update"],
            ["sudo", "apt-get", "install", "-y", "nodejs", "npm"],
        ),
        (
            "apt",
            ["sudo", "apt", "update"],
            ["sudo", "apt", "install", "-y", "nodejs", "npm"],
        ),
        ("dnf", None, ["sudo", "dnf", "install", "-y", "nodejs", "npm"]),
        ("yum", None, ["sudo", "yum", "install", "-y", "nodejs", "npm"]),
        ("pacman", None, ["sudo", "pacman", "-Sy", "nodejs", "npm"]),
        ("zypper", None, ["sudo", "zypper", "install", "-y", "nodejs", "npm"]),
    ]

    installed = False
    for pm_name, update_cmd, install_cmd in package_managers:
        if shutil.which(pm_name.split()[0]):
            print(f"   Found {pm_name}, installing Node.js...")
            try:
                # Run update command if available
                if update_cmd:
                    update_result = run_command(
                        update_cmd,
                        check=False,
                        capture=True,
                        quiet=True,
                        show_error=False,
                    )
                    if (
                        update_result
                        and hasattr(update_result, "returncode")
                        and update_result.returncode != 0
                    ):
                        print(
                            "   ⚠ Package manager update failed, continuing anyway..."
                        )

                # Run install command
                install_result = run_command(
                    install_cmd, check=False, capture=True, quiet=True, show_error=False
                )

                if (
                    install_result
                    and hasattr(install_result, "returncode")
                    and install_result.returncode == 0
                ):
                    print("✓ Node.js installed successfully")
                    installed = True
                    break
                else:
                    print(f"   ⚠ {pm_name} installation failed, trying next...")
            except Exception as e:
                print(f"   ⚠ Error with {pm_name}: {str(e)[:100]}, trying next...")

    if not installed:
        print("\n⚠ Could not automatically install Node.js")
        print("\nOptions:")
        print("  1. Enter sudo password when prompted")
        print("  2. Manual installation via NodeSource (Debian/Ubuntu/Kali):")
        print("     curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -")
        print("     sudo apt-get install -y nodejs")
        print("\n  3. Install from official website: https://nodejs.org/ (LTS version)")
        print("\n  4. After installation, run: python install.py")
        return False

    # Verify installation (with small delay)
    time.sleep(1)
    if shutil.which("node") and shutil.which("npm"):
        try:
            node_version = run_command(
                [shutil.which("node"), "--version"],
                capture=True,
                quiet=True,
                show_error=False,
            )
            npm_version = run_command(
                [shutil.which("npm"), "--version"],
                capture=True,
                quiet=True,
                show_error=False,
            )
            if node_version and hasattr(node_version, "stdout"):
                print(f"   Node.js {node_version.stdout.strip()}")
            if npm_version and hasattr(npm_version, "stdout"):
                print(f"   npm {npm_version.stdout.strip()}")
        except Exception:
            pass
        return True
    else:
        print("⚠ Node.js verification failed - it may not be in PATH")
        print("  Please restart your terminal and verify: node --version")
        return False


def install_playwright_browser(use_conda: bool = False):
    """Install Playwright Chromium for the agent's browser-automation
    actions. (The WhatsApp bridge no longer uses a browser — it speaks the
    protocol directly via Baileys.)"""
    print("\nInstalling Playwright Chromium browser...")
    try:
        if use_conda:
            conda_cmd = get_conda_command()
            env_name = get_env_name_from_yml()
            result = run_command(
                [
                    conda_cmd,
                    "run",
                    "-n",
                    env_name,
                    "python",
                    "-m",
                    "playwright",
                    "install",
                    "chromium",
                ],
                check=False,
                capture=True,
                show_error=False,
            )
        else:
            result = run_command(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=False,
                capture=True,
                show_error=False,
            )
        if result and hasattr(result, "returncode") and result.returncode == 0:
            print("✓ Playwright Chromium installed")
            return True
        else:
            print("⚠ Warning: Playwright browser installation failed")
            if result and hasattr(result, "stderr") and result.stderr:
                error_msg = result.stderr[:300].strip()
                if error_msg:
                    print(f"  Error details: {error_msg}")
            print("  Browser-automation actions may not work")
            print("  You can manually install later with: playwright install chromium")
            return False
    except Exception as e:
        print(f"⚠ Warning: Failed to install Playwright browser: {e}")
        print("  Browser-automation actions may not work")
        print("  You can manually install later with: playwright install chromium")
        return False


def _frontend_deps_stale(frontend_dir: str) -> Optional[str]:
    """Why node_modules does NOT satisfy the current package.json, or None.

    "node_modules exists" only proves npm install ran *once*; it says nothing
    about whether it ran for the CURRENT manifest. Pulling a branch that adds
    a dependency (e.g. react-grid-layout in the dashboard revamp) left the old
    check reporting "already installed" forever. Two real conditions instead:

    1. Every package declared in dependencies/devDependencies resolves to an
       installed node_modules/<name>/package.json — catches added packages.
    2. Neither manifest is newer than npm's own install receipt
       (node_modules/.package-lock.json, rewritten by every npm install) —
       catches version bumps, which condition 1 can't see.

    Returns a human-readable reason so the caller can say WHY it's installing.
    """
    node_modules = os.path.join(frontend_dir, "node_modules")
    if not os.path.isdir(node_modules):
        return "node_modules is missing"

    try:
        with open(os.path.join(frontend_dir, "package.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        # Unreadable manifest — run npm install and let npm report the
        # real problem loudly instead of silently skipping.
        return "package.json could not be read"

    declared = {
        **manifest.get("dependencies", {}),
        **manifest.get("devDependencies", {}),
    }
    for name in declared:
        # Scoped names ("@types/react") nest one directory deeper.
        pkg_json = os.path.join(node_modules, *name.split("/"), "package.json")
        if not os.path.isfile(pkg_json):
            return f"declared dependency '{name}' is not installed"

    receipt = os.path.join(node_modules, ".package-lock.json")
    if not os.path.isfile(receipt):
        return "npm's install receipt (node_modules/.package-lock.json) is missing"
    installed_at = os.path.getmtime(receipt)
    for filename in ("package.json", "package-lock.json"):
        path = os.path.join(frontend_dir, filename)
        if os.path.isfile(path) and os.path.getmtime(path) > installed_at:
            return f"{filename} changed after the last npm install"

    return None


def install_browser_frontend():
    """Install npm dependencies for the browser frontend."""
    frontend_dir = os.path.join(BASE_DIR, "app", "ui_layer", "browser", "frontend")

    if not os.path.exists(frontend_dir):
        print(f"\n⚠ Warning: Browser frontend directory not found at {frontend_dir}")
        print("   Browser interface will not work")
        return False

    # Try to install Node.js on Linux if not already installed
    npm_cmd = shutil.which("npm")
    if not npm_cmd and sys.platform != "win32":
        print("\n🔧 Node.js not detected. Attempting automatic installation...")
        if not install_nodejs_linux():
            # If auto-install failed, show manual instructions
            print("\n⚠ Warning: npm not found in PATH")
            print("   Browser interface requires Node.js and npm.")
            print("\n   📥 Install Node.js from: https://nodejs.org/")
            print("      (Choose LTS version)")
            print("\n   After installation:")
            print("   1. Restart your terminal")
            print("   2. Run: python install.py")
            print("\n   Or manually install frontend:")
            print("      cd app/ui_layer/browser/frontend")
            print("      npm install")
            return False
        # Refresh npm_cmd after installation
        npm_cmd = shutil.which("npm")

    # Final check for npm
    if not npm_cmd:
        print("\n⚠ Warning: npm not found in PATH")
        print("   Browser interface requires Node.js and npm.")
        print("\n   📥 Install Node.js from: https://nodejs.org/")
        print("      (Choose LTS version)")
        print("\n   After installation:")
        print("   1. Restart your terminal")
        print("   2. Run: python install.py")
        print("\n   Or manually install frontend:")
        print("      cd app/ui_layer/browser/frontend")
        print("      npm install")
        return False

    stale_reason = _frontend_deps_stale(frontend_dir)
    if stale_reason is None:
        print("\n✓ Browser frontend dependencies already installed")
        return True

    # Try to install
    print(f"\n🔧 Installing browser frontend dependencies ({stale_reason})...")
    try:
        result = run_command_with_progress(
            [npm_cmd, "install"],
            message="Installing npm packages",
            cwd=frontend_dir,
            check=False,
        )
        if result and hasattr(result, "returncode") and result.returncode == 0:
            print("✓ Browser frontend dependencies installed")
            return True
        else:
            print("\n⚠ Warning: npm install command failed")
            print("\n   Troubleshooting:")
            print("   1. Make sure Node.js is installed: node --version")
            print("   2. Check npm version: npm --version")
            print("   3. Try manually: cd app/ui_layer/browser/frontend && npm install")
            print("\n   If you still need help:")
            print("   - Check Node.js/npm documentation: https://nodejs.org/")
            print("   - Ensure internet connection is working")
            return False
    except Exception as e:
        print(f"\n⚠ Warning: Failed to install browser frontend: {e}")
        print("\n   You can manually install with:")
        print("   cd app/ui_layer/browser/frontend")
        print("   npm install")
        return False


def install_whatsapp_bridge():
    """Install npm dependencies for the WhatsApp bridge (Baileys).

    The bridge is a Node subprocess speaking WhatsApp's protocol via
    Baileys — no browser involved. Installing here (instead of lazily at
    the first bridge start) means the first QR link isn't blocked behind
    an npm download. Uses the same staleness check as the frontend, so a
    pulled branch that bumps the Baileys version reinstalls automatically.
    """
    bridge_dir = os.path.join(
        BASE_DIR, "craftos_integrations", "integrations", "whatsapp_web"
    )

    if not os.path.exists(os.path.join(bridge_dir, "package.json")):
        print(f"\n⚠ Warning: WhatsApp bridge directory not found at {bridge_dir}")
        print("   WhatsApp integration will not work")
        return False

    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        # install_browser_frontend (which runs after this on failure paths)
        # already walks the user through Node.js installation; keep this
        # message short.
        print("\n⚠ Warning: npm not found — WhatsApp bridge dependencies skipped")
        print("   After installing Node.js, run:")
        print("     cd craftos_integrations/integrations/whatsapp_web && npm install")
        return False

    stale_reason = _frontend_deps_stale(bridge_dir)
    if stale_reason is None:
        print("\n✓ WhatsApp bridge dependencies already installed")
        return True

    print(f"\n🔧 Installing WhatsApp bridge dependencies ({stale_reason})...")
    try:
        result = run_command_with_progress(
            [npm_cmd, "install"],
            message="Installing WhatsApp bridge (Baileys)",
            cwd=bridge_dir,
            check=False,
        )
        if result and hasattr(result, "returncode") and result.returncode == 0:
            print("✓ WhatsApp bridge dependencies installed")
            return True
        print("\n⚠ Warning: npm install for the WhatsApp bridge failed")
        print("   WhatsApp integration will not work until it succeeds:")
        print("     cd craftos_integrations/integrations/whatsapp_web && npm install")
        return False
    except Exception as e:
        print(f"\n⚠ Warning: Failed to install WhatsApp bridge deps: {e}")
        print("   You can manually install with:")
        print("     cd craftos_integrations/integrations/whatsapp_web && npm install")
        return False


def setup_pip_environment(requirements_file: str = REQUIREMENTS_FILE):
    try:
        if not os.path.exists(requirements_file):
            print(f"Error: {requirements_file} not found.")
            sys.exit(1)

        print("🔧 Installing core dependencies...")

        # Setup environment with TMPDIR for pip cache management
        # This helps on systems with limited space or PEP 668 issues
        my_env = os.environ.copy()
        tmp_dir = os.path.expanduser("~/pip-tmp")
        my_env["TMPDIR"] = tmp_dir
        # Disable pip's rich/colored output so it falls back to plain text.
        # This prevents pip's vendored rich library from crashing on Windows
        # terminals with encoding issues (common on Python 3.14+).
        my_env["NO_COLOR"] = "1"
        my_env["FORCE_COLOR"] = "0"
        my_env["PYTHONIOENCODING"] = "utf-8"

        # Create temp directory if it doesn't exist
        os.makedirs(tmp_dir, exist_ok=True)

        # First attempt with standard pip install
        # --no-color keeps output plain and avoids rich console crashes
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-color",
            "-r",
            requirements_file,
        ]
        result = run_command_with_progress(
            cmd,
            message="Installing core dependencies",
            check=False,
            env_extras={
                "TMPDIR": tmp_dir,
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
                "PYTHONIOENCODING": "utf-8",
            },
        )

        if result and hasattr(result, "returncode") and result.returncode != 0:
            # Check error output
            error_output = ""
            if hasattr(result, "stderr"):
                error_output = result.stderr
            elif hasattr(result, "stdout"):
                error_output = result.stdout

            # Check for disk space errors
            if (
                "no space left on device" in error_output.lower()
                or "disk full" in error_output.lower()
            ):
                print("\n❌ DISK SPACE ERROR - No space left on device\n")
                print(
                    "This is a common issue on Kali Linux when installing large packages.\n"
                )
                print("Immediate fixes:\n")
                print("1. Clear pip cache (usually frees 1-5 GB):")
                print("   pip cache purge\n")
                print("2. Clear npm cache (if installed):")
                print("   npm cache clean --force\n")
                print("3. Use alternate disk with more space:")
                mkdir_cmd = (
                    "/mnt/external/pip-tmp" if sys.platform != "win32" else "D:/pip-tmp"
                )
                print(f"   mkdir -p {mkdir_cmd}")
                print(f"   TMPDIR={mkdir_cmd} python install.py\n")
                print("4. Check disk usage:")
                check_cmd = "du -sh ~/*" if sys.platform != "win32" else "dir /-s C:\\"
                print(f"   {check_cmd}\n")
                suggest_cleanup_steps()
                sys.exit(1)

            # Check for PEP 668 error
            if (
                "externally-managed-environment" in error_output
                or "externally managed" in error_output
            ):
                print("\n⚠️  PEP 668 Error Detected (externally-managed-environment)\n")
                print(
                    "This usually happens on Kali Linux or other systems with managed Python."
                )
                print("\nOptions to fix:\n")
                print("Option 1 (Recommended): Use a virtual environment")
                print("  python3 -m venv craftbot-env")
                print("  source craftbot-env/bin/activate  # On Linux/macOS")
                print("  .\\craftbot-env\\Scripts\\activate  # On Windows")
                print("  python install.py\n")

                print("Option 2: Use conda (recommended for data science projects)")
                print("  python install.py --conda\n")

                print("Option 3: Break system packages (not recommended)")
                print("  Retrying with --break-system-packages flag...\n")

                # Retry with --break-system-packages
                cmd_with_flag = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-color",
                    "--break-system-packages",
                    "-r",
                    requirements_file,
                ]
                result = run_command_with_progress(
                    cmd_with_flag,
                    message="Retrying installation",
                    check=False,
                    env_extras={
                        "TMPDIR": tmp_dir,
                        "NO_COLOR": "1",
                        "FORCE_COLOR": "0",
                        "PYTHONIOENCODING": "utf-8",
                    },
                )

                if result and hasattr(result, "returncode") and result.returncode == 0:
                    print(
                        "✓ Core dependencies installed (with --break-system-packages)"
                    )
                else:
                    print("\n✗ Installation failed even with --break-system-packages")
                    if hasattr(result, "stderr") and result.stderr:
                        print(f"\nError: {result.stderr[:500]}")
                    print("\nPlease use Option 1 or Option 2 above.")
                    sys.exit(1)
            else:
                _pip_env = {
                    "TMPDIR": tmp_dir,
                    "NO_COLOR": "1",
                    "FORCE_COLOR": "0",
                    "PYTHONIOENCODING": "utf-8",
                }
                _ver = sys.version_info

                # On pre-release Python (3.14+), many packages only have wheels
                # under --pre.  Try that automatically before giving up.
                if _ver >= (3, 14):
                    print(
                        f"\n⚠  Python {_ver.major}.{_ver.minor} detected (pre-release)."
                    )
                    print("   Retrying with --pre to pick up pre-release wheels...")
                    cmd_pre = [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--no-color",
                        "--pre",
                        "-r",
                        requirements_file,
                    ]
                    result = run_command_with_progress(
                        cmd_pre,
                        message="Retrying (--pre)",
                        check=False,
                        env_extras=_pip_env,
                    )
                    if (
                        result
                        and hasattr(result, "returncode")
                        and result.returncode == 0
                    ):
                        print("✓ Core dependencies installed (--pre)")
                        return

                    # Second retry: prefer binary wheels, fall back to source only when needed.
                    # --prefer-binary is much safer than --only-binary=:all: because it still
                    # allows source builds for packages that genuinely have no wheel yet.
                    print(
                        "   Retrying with --prefer-binary to favour wheels over source builds..."
                    )
                    cmd_bin = [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--no-color",
                        "--pre",
                        "--prefer-binary",
                        "-r",
                        requirements_file,
                    ]
                    result = run_command_with_progress(
                        cmd_bin,
                        message="Retrying (prefer-binary)",
                        check=False,
                        env_extras=_pip_env,
                    )
                    if (
                        result
                        and hasattr(result, "returncode")
                        and result.returncode == 0
                    ):
                        print("✓ Core dependencies installed (prefer-binary)")
                        return

                # Show as much context as possible then give up
                print("\n✗ Error installing core dependencies:")
                err_text = ""
                if hasattr(result, "stderr") and result.stderr:
                    err_text = result.stderr.strip()
                if hasattr(result, "stdout") and result.stdout and not err_text:
                    err_text = result.stdout.strip()
                if err_text:
                    print(err_text[:2000])

                if _ver >= (3, 14):
                    print(
                        f"\n   Python {_ver.major}.{_ver.minor} is pre-release; some packages"
                    )
                    print(
                        "   may not yet ship wheels for it. The safest fix is to install"
                    )
                    print(
                        "   Python 3.11 or 3.12 from https://www.python.org/downloads/"
                    )
                    print("   and re-run: python install.py")

                print("\nTroubleshooting:")
                print(
                    "  1. Check for disk space: "
                    + ("df -h" if sys.platform != "win32" else "dir C:\\")
                )
                print("  2. Clear pip cache: pip cache purge")
                print("  3. Check your internet connection")
                print("  4. Try: pip install --upgrade pip")
                print("  5. Try with conda: python install.py --conda")
                sys.exit(1)
        else:
            print("✓ Core dependencies installed")

        # Quick import smoke-test: verify that the most critical packages are
        # actually importable with the current interpreter.  pip can report
        # returncode 0 yet leave some packages missing (e.g. version conflicts,
        # wrong interpreter, PEP 668 partial installs).
        _critical = ["openai", "anthropic", "requests", "aiohttp", "websockets"]
        _missing = []
        for _pkg in _critical:
            chk = subprocess.run(
                [sys.executable, "-c", f"import {_pkg}"],
                capture_output=True,
            )
            if chk.returncode != 0:
                _missing.append(_pkg)
        if _missing:
            print("\n  ✗ Import check failed — these packages are not importable:")
            for _m in _missing:
                print(f"    • {_m}")
            print("\n  This usually means pip installed them for a different Python")
            print(f"  interpreter. Current interpreter: {sys.executable}")
            print("\n  Fix: re-run with the correct Python:")
            print(f"    {sys.executable} install.py")
            sys.exit(1)
        print("  ✓ Import check passed")
    except Exception as e:
        print(f"\n✗ Exception during setup: {e}")
        raise


# ==========================================
# OMNIPARSER SETUP (GUI Mode)
# ==========================================
def setup_omniparser(force_cpu: bool, use_conda: bool):
    """Install OmniParser for GUI mode support."""

    if not shutil.which("git"):
        print("Error: 'git' is required to install GUI components.")
        print("Please install git: https://git-scm.com/downloads")
        sys.exit(1)

    # Get repo path from config or use default
    config = load_config()
    repo_path = config.get("omniparser_repo_path")
    if not repo_path:
        repo_path = os.path.abspath("OmniParser_CraftOS")
        save_config_value("omniparser_repo_path", repo_path)
    else:
        repo_path = os.path.abspath(repo_path)

    def run_omni_cmd(
        cmd_list: list[str],
        work_dir: str = repo_path,
        capture_output: bool = False,
        env_extras: Dict[str, str] = None,
    ):
        """Execute command in OmniParser environment (conda or direct pip)."""
        if use_conda:
            conda_cmd = get_conda_command()
            full_cmd = [conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME] + cmd_list
        else:
            full_cmd = cmd_list

        # Setup environment with TMPDIR for pip cache management
        local_env = env_extras.copy() if env_extras else {}
        tmp_dir = os.path.expanduser("~/pip-tmp")
        local_env["TMPDIR"] = tmp_dir
        os.makedirs(tmp_dir, exist_ok=True)

        run_command(
            full_cmd,
            cwd=work_dir,
            capture=capture_output,
            env_extras=local_env,
            quiet=capture_output,
        )

    # Step 1: Repository setup
    try:
        print("🔧 Setting up OmniParser repository...")
        if os.path.exists(repo_path):
            run_command(["git", "-C", repo_path, "pull"], quiet=True, check=False)
        else:
            run_command(
                [
                    "git",
                    "clone",
                    "-b",
                    OMNIPARSER_BRANCH,
                    OMNIPARSER_REPO_URL,
                    repo_path,
                ],
                quiet=False,
                show_error=True,
            )
    except Exception as e:
        print(f"✗ Error setting up repository: {e}")
        sys.exit(1)

    # Check marker file
    marker_path = os.path.join(repo_path, OMNIPARSER_MARKER_FILE)
    if not os.path.exists(marker_path):
        # Step 2: Create environment (only if using conda)
        if use_conda:
            conda_cmd = get_conda_command()
            print("🔧 Creating conda environment...")
            result = run_command(
                [conda_cmd, "create", "-n", OMNIPARSER_ENV_NAME, "python=3.10", "-y"],
                capture=True,
                check=False,
            )
            if result.returncode != 0:
                print("\n✗ Error creating conda environment 'omni'")
                sys.exit(1)

        print("🔧 Upgrading pip...")
        run_omni_cmd(["pip", "install", "--upgrade", "pip"])

        # Step 3: Install PyTorch
        print("🔧 Installing PyTorch...")
        pytorch_installed = False

        if use_conda:
            conda_cmd = get_conda_command()
            if force_cpu:
                print("   (CPU-only mode)")
                result = run_command(
                    [
                        conda_cmd,
                        "run",
                        "-n",
                        OMNIPARSER_ENV_NAME,
                        "conda",
                        "install",
                        "pytorch",
                        "torchvision",
                        "torchaudio",
                        "cpuonly",
                        "-c",
                        "pytorch",
                        "-y",
                    ],
                    capture=True,
                    check=False,
                )
                pytorch_installed = result.returncode == 0
            else:
                # Try GPU version first
                print("   (Attempting CUDA 12.1 GPU version)")
                result = run_command(
                    [
                        conda_cmd,
                        "run",
                        "-n",
                        OMNIPARSER_ENV_NAME,
                        "conda",
                        "install",
                        "pytorch",
                        "torchvision",
                        "torchaudio",
                        "pytorch-cuda=12.1",
                        "-c",
                        "pytorch",
                        "-c",
                        "nvidia",
                        "-y",
                    ],
                    capture=True,
                    check=False,
                )

                if result.returncode != 0:
                    print("   ⚠ GPU version failed. Falling back to CPU-only mode...")
                    result = run_command(
                        [
                            conda_cmd,
                            "run",
                            "-n",
                            OMNIPARSER_ENV_NAME,
                            "conda",
                            "install",
                            "pytorch",
                            "torchvision",
                            "torchaudio",
                            "cpuonly",
                            "-c",
                            "pytorch",
                            "-y",
                        ],
                        capture=True,
                        check=False,
                    )
                    pytorch_installed = result.returncode == 0
                    if pytorch_installed:
                        print("   ✓ CPU-only PyTorch installed successfully")
                else:
                    pytorch_installed = True
        else:
            # Use pip for non-conda installation
            if force_cpu:
                print("   (CPU-only mode)")
                result = run_command(
                    ["pip", "install", "torch", "torchvision", "torchaudio"],
                    capture=True,
                    check=False,
                    env_extras={"TMPDIR": os.path.expanduser("~/pip-tmp")},
                )
                pytorch_installed = result.returncode == 0
            else:
                # Try GPU version first
                print("   (Attempting CUDA 12.1 GPU version)")
                result = run_command(
                    [
                        "pip",
                        "install",
                        "torch",
                        "torchvision",
                        "torchaudio",
                        "torch-cuda==12.1",
                    ],
                    capture=True,
                    check=False,
                    env_extras={"TMPDIR": os.path.expanduser("~/pip-tmp")},
                )

                if result.returncode != 0:
                    print("   ⚠ GPU version failed. Falling back to CPU-only mode...")
                    result = run_command(
                        ["pip", "install", "torch", "torchvision", "torchaudio"],
                        capture=True,
                        check=False,
                        env_extras={"TMPDIR": os.path.expanduser("~/pip-tmp")},
                    )
                    pytorch_installed = result.returncode == 0
                    if pytorch_installed:
                        print("   ✓ CPU-only PyTorch installed successfully")
                else:
                    pytorch_installed = True

        if not pytorch_installed:
            print("\n✗ Error installing PyTorch")
            if hasattr(result, "stderr") and result.stderr:
                error_msg = result.stderr[:500]
                print(f"\n   Error details:\n   {error_msg}")

                # Check for specific errors
                if (
                    "no space left on device" in error_msg.lower()
                    or "disk" in error_msg.lower()
                ):
                    print("\n⚠️  DISK SPACE ERROR detected")
                    print("   PyTorch is very large (~5GB+). Your disk may be full.")
                    print("\n   Solutions:")
                    print("   1. Clear pip cache: pip cache purge")
                    print("   2. Clear npm cache: npm cache clean --force")
                    print(
                        "   3. Use alternate disk: TMPDIR=/mnt/large-disk/pip-tmp python install.py --gui"
                    )
                    print(
                        "   4. Use conda (more efficient): python install.py --gui --conda"
                    )

                elif (
                    "externally-managed-environment" in error_msg
                    or "externally managed" in error_msg
                ):
                    print("\n⚠️  PEP 668 Error: System-managed Python detected")
                    print("   Use virtual environment or conda for GUI mode")

                elif "cuda" in error_msg.lower() or "gpu" in error_msg.lower():
                    print("\n⚠️  CUDA/GPU Error detected")
                    print("   Try CPU-only: python install.py --gui --cpu-only")
                    print("   Or with conda: python install.py --gui --conda")

            print("\n⚠️  Troubleshooting:")
            print(
                "   1. Check disk space: "
                + ("df -h" if sys.platform != "win32" else "dir C:\\")
            )
            print("   2. Clear pip cache: pip cache purge")
            print(
                "   3. Try clearing system caches: "
                + ("sudo apt-get clean" if sys.platform != "win32" else "Disk Cleanup")
            )
            print(
                "   4. Try again with CPU-only mode: python install.py --gui --cpu-only"
            )
            print("   5. Use conda (recommended): python install.py --gui --conda")
            print(
                "   6. Check PyTorch documentation: https://pytorch.org/get-started/locally/"
            )
            sys.exit(1)

        # Step 4: Install dependencies
        print("🔧 Installing dependencies...")
        deps = [
            "mkl==2024.0",
            "sympy==1.13.1",
            "transformers==4.51.0",
            "huggingface_hub[cli]",
            "hf_transfer",
        ]
        tmp_dir = os.path.expanduser("~/pip-tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        if use_conda:
            conda_cmd = get_conda_command()
            result = run_command(
                [conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "pip", "install"] + deps,
                capture=True,
                check=False,
                env_extras={"TMPDIR": tmp_dir},
            )
        else:
            result = run_command(
                ["pip", "install"] + deps,
                capture=True,
                check=False,
                env_extras={"TMPDIR": tmp_dir},
            )
        if result.returncode != 0:
            print("⚠ Warning: Some dependencies may have failed to install")
            if (
                hasattr(result, "stderr")
                and result.stderr
                and "externally-managed" not in result.stderr
            ):
                error_snippet = result.stderr[:200].strip()
                if error_snippet:
                    print(f"  Details: {error_snippet}")

        req_txt = os.path.join(repo_path, "requirements.txt")
        if os.path.exists(req_txt):
            if use_conda:
                conda_cmd = get_conda_command()
                result = run_command(
                    [
                        conda_cmd,
                        "run",
                        "-n",
                        OMNIPARSER_ENV_NAME,
                        "pip",
                        "install",
                        "-r",
                        "requirements.txt",
                    ],
                    cwd=repo_path,
                    capture=True,
                    check=False,
                    env_extras={"TMPDIR": tmp_dir},
                )
            else:
                result = run_command(
                    ["pip", "install", "-r", "requirements.txt"],
                    cwd=repo_path,
                    capture=True,
                    check=False,
                    env_extras={"TMPDIR": tmp_dir},
                )
            if result.returncode != 0:
                print("⚠ Warning: Some requirements may have failed to install")

        # Create marker
        with open(marker_path, "w") as f:
            f.write(f"Installed on {time.ctime()}\n")
    else:
        print("🔧 Environment already set up, skipping setup steps...")

    # Step 5: Download model weights
    print("🔧 Downloading model weights (this may take a while)...")
    files_to_download = [
        {
            "file": "icon_detect/train_args.yaml",
            "local_path": "icon_detect/train_args.yaml",
        },
        {"file": "icon_detect/model.pt", "local_path": "icon_detect/model.pt"},
        {"file": "icon_detect/model.yaml", "local_path": "icon_detect/model.yaml"},
        {
            "file": "icon_caption/config.json",
            "local_path": "icon_caption_florence/config.json",
        },
        {
            "file": "icon_caption/generation_config.json",
            "local_path": "icon_caption_florence/generation_config.json",
        },
        {
            "file": "icon_caption/model.safetensors",
            "local_path": "icon_caption_florence/model.safetensors",
        },
    ]

    weights_dir = os.path.join(repo_path, "weights")
    os.makedirs(os.path.join(weights_dir, "icon_detect"), exist_ok=True)
    os.makedirs(os.path.join(weights_dir, "icon_caption_florence"), exist_ok=True)

    hf_env = {"HF_HUB_ENABLE_HF_TRANSFER": "1"}
    failed_downloads = []
    for i, file_info in enumerate(files_to_download, 1):
        local_dest = os.path.join(weights_dir, file_info["local_path"])
        if not os.path.exists(local_dest):
            print(
                f"  📦 ({i}/{len(files_to_download)}) Downloading: {file_info['local_path']}..."
            )
            if use_conda:
                conda_cmd = get_conda_command()
                result = run_command(
                    [
                        conda_cmd,
                        "run",
                        "-n",
                        OMNIPARSER_ENV_NAME,
                        "hf",
                        "download",
                        "microsoft/OmniParser-v2.0",
                        file_info["file"],
                        "--local-dir",
                        "weights",
                    ],
                    cwd=repo_path,
                    capture=True,
                    check=False,
                    env_extras=hf_env,
                )
            else:
                result = run_command(
                    [
                        "hf",
                        "download",
                        "microsoft/OmniParser-v2.0",
                        file_info["file"],
                        "--local-dir",
                        "weights",
                    ],
                    cwd=repo_path,
                    capture=True,
                    check=False,
                    env_extras=hf_env,
                )
            if result.returncode != 0:
                failed_downloads.append(file_info["local_path"])
        else:
            print(
                f"  ✓ ({i}/{len(files_to_download)}) Already have: {file_info['local_path']}"
            )

    if failed_downloads:
        print(f"\n⚠ Warning: {len(failed_downloads)} model files failed to download:")
        for f in failed_downloads:
            print(f"  - {f}")
        print("\n   You can retry downloading these later.")

    # Step 6: Reorganize files
    print("🔧 Organizing GUI components...")
    try:
        src_caption = os.path.join(weights_dir, "icon_caption")
        dst_caption = os.path.join(weights_dir, "icon_caption_florence")
        if os.path.exists(src_caption):
            if os.path.exists(dst_caption):
                shutil.rmtree(dst_caption)
            shutil.move(src_caption, dst_caption)
        print("✓ GUI components ready\n")
    except Exception as e:
        print(f"\n✗ Error organizing files: {e}")
        sys.exit(1)


# ==========================================
# MAIN
# ==========================================
def launch_agent_after_install(install_gui: bool, use_conda: bool):
    """Automatically launch CraftBot after installation."""
    main_script = os.path.abspath(os.path.join(BASE_DIR, "run.py"))
    if not os.path.exists(main_script):
        print(f"Error: {main_script} not found.")
        sys.exit(1)

    # Build command for run script
    args = []
    if install_gui:
        args.append("--gui")

    # Show launch message
    print("\n" + "=" * 60)
    print(" 🚀 Launching CraftBot (Browser Interface)...")
    print("=" * 60 + "\n")

    if use_conda:
        conda_cmd = get_conda_command()
        env_name = get_env_name_from_yml()
        cmd = [conda_cmd, "run", "-n", env_name, "python", "-u", main_script] + args
    else:
        cmd = [sys.executable, "-u", main_script] + args

    # Launch the agent
    try:
        subprocess.run(cmd, cwd=BASE_DIR)
    except KeyboardInterrupt:
        print("\n\n✓ CraftBot stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error launching CraftBot: {e}")

        # Show fallback instructions
        print("\nTo launch manually, run:")
        if use_conda:
            env_name = get_env_name_from_yml()
            conda_cmd = get_conda_command()
            cmd_args = " ".join(args) if args else ""
            print(
                f"  {conda_cmd} run -n {env_name} python run.py {cmd_args}".rstrip()
                + "\n"
            )
        else:
            cmd_args = " ".join(args) if args else ""
            print(f"  python run.py {cmd_args}".rstrip() + "\n")
        sys.exit(1)


# ==========================================
# API KEY SETUP
# ==========================================
def check_api_keys() -> bool:
    """Check if required API keys are set in settings.json."""
    settings_path = os.path.join(BASE_DIR, "app", "config", "settings.json")
    try:
        with open(settings_path, "r") as f:
            settings = json.load(f)
        api_keys = settings.get("api_keys", {})
        # Check if any API key is configured
        for key in ["openai", "anthropic", "google", "byteplus"]:
            if api_keys.get(key):
                return True
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return False


def show_api_setup_instructions():
    """Show instructions for setting up API keys."""
    print("\n" + "=" * 50)
    print(" ⚠ API Key Required")
    print("=" * 50)
    print("\nCraftBot needs an LLM API key to run.")
    print("\nSupported providers:")
    print("  1. OpenAI (fastest setup)")
    print("  2. Google Gemini")
    print("  3. Anthropic Claude")
    print("\nTo set up:")
    print("  1. Get an API key from your chosen provider")
    print("  2. Add it to app/config/settings.json:")
    print("     ")
    print('     "api_keys": {')
    print('       "openai": "your-key-here"')
    print("     }")
    print("     ")
    print("     OR")
    print("     ")
    print('     "api_keys": {')
    print('       "google": "your-key-here"')
    print("     }")
    print("     ")
    print("  3. Save and run again: python install.py")
    print("=" * 50 + "\n")


# ==========================================
# LINUX PYTHON COMPATIBILITY CHECK
# ==========================================
def _check_linux_python() -> None:
    """
    Warn Linux users who are running an old or system-managed Python.

    Common problem scenarios:
    - Python < 3.9  (Ubuntu 20.04 default is 3.8)
    - System Python used directly without a venv, which triggers PEP 668
      "externally-managed-environment" errors on newer distros
    """
    ver = sys.version_info

    # Already gated to >= 3.9 above, but warn hard about 3.9 since
    # it's the bare minimum — 3.10+ is recommended.
    if ver < (3, 10):
        print("\n" + "=" * 62)
        print(f" ⚠  Python {ver.major}.{ver.minor} detected — upgrade recommended")
        print("=" * 62)
        print(f"\n  You are running Python {ver.major}.{ver.minor}.{ver.micro}.")
        print("  CraftBot works on 3.9+ but runs best on Python 3.10 or newer.")
        print("\n  Recommended: use Python 3.10.17")
        print("=" * 62)
        print(
            f"\n  {ORANGE}[y]{RESET} Continue with Python {ver.major}.{ver.minor} anyway"
        )
        print(
            f"  {GREEN}[i]{RESET} Auto-install Python 3.10.17 and re-launch  {DIM}(recommended){RESET}"
        )
        print(f"  {RED}[n]{RESET} Cancel")
        choice = input("\n  Your choice (y/i/n): ").strip().lower()
        if choice == "i":
            _auto_install_python_310()
        elif choice != "y":
            print("\n  Installation cancelled. Please upgrade Python and try again.\n")
            sys.exit(1)
        print()


# ==========================================
# MAC PYTHON COMPATIBILITY CHECK
# ==========================================
def _check_mac_python() -> None:
    """
    Warn Mac users who are running a problematic Python interpreter.

    Common bad interpreters on macOS:
    - Xcode bundled Python  (/Applications/Xcode.app/...)
    - macOS system Python   (/usr/bin/python3)

    Both are difficult to install packages into and are intended as OS
    tooling, not for running user applications.  Homebrew or python.org
    Python is recommended instead.
    """
    exe = sys.executable or ""
    is_xcode = "Xcode.app" in exe or "Python3.framework" in exe
    is_system = exe.startswith("/usr/bin/python")

    if not (is_xcode or is_system):
        return  # Running a proper Python — nothing to warn about

    ver = sys.version_info
    label = "Xcode's built-in Python" if is_xcode else "macOS system Python"

    print("\n" + "=" * 62)
    print(" ⚠  WARNING: Wrong Python interpreter detected")
    print("=" * 62)
    print(f"\n  You are using {label}:")
    print(f"  {exe}")
    print(
        f"\n  This Python ({ver.major}.{ver.minor}.{ver.micro}) is reserved for macOS"
    )
    print("  system tools. Installing packages into it can be unreliable")
    print("  and may break system components.")
    print("\n  Recommended: use Python 3.10.17 (official python.org build)")
    print("=" * 62)
    print(f"\n  {ORANGE}[y]{RESET} Continue with the current interpreter anyway")
    print(
        f"  {GREEN}[i]{RESET} Auto-install Python 3.10.17 and re-launch  {DIM}(recommended){RESET}"
    )
    print(f"  {RED}[n]{RESET} Cancel")

    choice = input("\n  Your choice (y/i/n): ").strip().lower()
    if choice == "i":
        _auto_install_python_310()
    elif choice != "y":
        print("\n  Installation cancelled. Please use a python.org Python 3.10.\n")
        sys.exit(1)
    print()


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    # ── Python version gate ────────────────────────────────────────────────
    _ver = sys.version_info
    # --skip-python-check is passed by _auto_install_python_310 when it
    # re-launches install.py after installing Python 3.10, so we don't loop
    # back into the auto-install prompt again.
    _skip_python_check = "--skip-python-check" in sys.argv

    if _ver < (3, 9):
        print(f"\n❌ Python {_ver.major}.{_ver.minor} is not supported.")
        print("   CraftBot requires Python 3.9 or newer.")
        if sys.platform == "darwin":
            print("\n   Recommended fix:")
            print("   1. Install Homebrew: https://brew.sh")
            print("   2. Run: brew install python@3.11")
            print("   3. Re-run: /opt/homebrew/bin/python3.11 install.py")
        else:
            print(
                "\n   Please install Python 3.9+ from https://www.python.org/downloads/"
            )
        sys.exit(1)

    # ── Pre-release / wrong-version Python handling ───────────────────────
    if (_ver >= (3, 14) or _ver < (3, 10)) and not _skip_python_check:
        # Before prompting, check if Python 3.10 is already installed.
        # If it is, silently re-launch with it — no need to ask the user again.
        # EXCEPT inside an activated conda env: the user chose that env's
        # interpreter, so hijacking a different Python would install the
        # dependencies somewhere the service will never look. Fall through
        # to the prompt instead so they can continue with the env's Python.
        _in_conda_env = bool(os.environ.get("CONDA_PREFIX"))
        _python310 = None if _in_conda_env else _find_existing_python310()
        if _python310:
            print(
                f"\n  {GREEN}▸{RESET} {WHITE}Python 3.10 detected — re-launching automatically...{RESET}\n"
            )
            if _python310.lower().endswith("py.exe"):
                _relaunch_cmd = [_python310, "-3.10", __file__]
            else:
                _relaunch_cmd = [_python310, __file__]
            # Keep ALL flags (incl. --no-launch — craftbot.py relies on it)
            # and propagate the child's exit code so a failed install isn't
            # reported as success to the caller.
            _extra = list(sys.argv[1:])
            _result = subprocess.run(_relaunch_cmd + _extra + ["--skip-python-check"])
            sys.exit(_result.returncode)

        # Python 3.10 not found — show the prompt.
        if _ver >= (3, 14):
            _reason = f"Python {_ver.major}.{_ver.minor} is a pre-release version"
            _detail = (
                f"  You are running Python {_ver.major}.{_ver.minor}.{_ver.micro}.\n"
                "  Pre-release Python versions are not yet supported by all\n"
                "  packages CraftBot depends on and may cause install failures."
            )
        else:
            _reason = f"Python {_ver.major}.{_ver.minor} is older than recommended"
            _detail = (
                f"  You are running Python {_ver.major}.{_ver.minor}.{_ver.micro}.\n"
                "  CraftBot works best on Python 3.10 or newer."
            )
        print("\n" + "=" * 62)
        print(f" ⚠  {_reason}")
        print("=" * 62)
        print(f"\n{_detail}")
        print("\n  Recommended: use Python 3.10.17")
        print("=" * 62)
        print(
            f"\n  {ORANGE}[y]{RESET} Continue with Python {_ver.major}.{_ver.minor} anyway"
        )
        print(
            f"  {GREEN}[i]{RESET} Auto-install Python 3.10.17 and re-launch  {DIM}(recommended){RESET}"
        )
        print(f"  {RED}[n]{RESET} Cancel")
        _choice = input("\n  Your choice (y/i/n): ").strip().lower()
        if _choice == "i":
            _auto_install_python_310()
        elif _choice != "y":
            print("\n  Installation cancelled. Please use Python 3.10.17.\n")
            sys.exit(1)
        print()

    # ── platform-specific interpreter checks ──────────────────────────────
    if not _skip_python_check:
        if sys.platform == "darwin":
            _check_mac_python()
        elif sys.platform == "linux":
            _check_linux_python()

    args = set(sys.argv[1:])

    # Parse flags
    # [V1.2.2] GUI mode is temporarily disabled in this version.
    if "--gui" in args:
        print("\n[!] GUI mode is temporarily disabled in this version (V1.2.2).")
        print(
            "    This feature is experimental and will be re-enabled in a future release."
        )
        print("    Please run without --gui flag.\n")
        sys.exit(1)
    install_gui = False  # "--gui" in args  # [V1.2.2] disabled
    use_conda = "--conda" in args
    force_cpu = "--cpu-only" in args

    # Save installation configuration (silent)
    save_config_value("use_conda", use_conda)
    save_config_value("gui_mode_enabled", install_gui)
    os.environ["USE_CONDA"] = str(use_conda)

    # Print retro installation header
    _ART = [
        " ██████╗ ██████╗   █████╗  ███████╗ ████████╗██████╗   ██████╗ ████████╗",
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
    _sub = "░░░  INSTALLATION SYSTEM  ░░░"
    print(f"{ORANGE}║{RESET}{DIM}{_sub.center(_BW)}{RESET}{ORANGE}║{RESET}")
    _mode = "MODE: " + ("CONDA ENVIRONMENT" if use_conda else "GLOBAL PIP")
    print(f"{ORANGE}║{RESET}{ORANGE}{_mode.center(_BW)}{RESET}{ORANGE}║{RESET}")
    print(_BE)
    print(f"{_BB}\n")

    # Pre-flight check: Disk space (especially important for Kali)
    min_space_needed = (
        8.0 if install_gui else 5.0
    )  # GUI mode needs more space for torch
    if not check_disk_space_for_installation(min_free_gb=min_space_needed):
        sys.exit(1)

    # Step 1: Install core dependencies
    if use_conda:
        is_installed, reason, conda_base = is_conda_installed()
        if not is_installed:
            print("❌ Error: Conda not found")
            print("\nOptions:")
            print("  1. Auto-install Miniconda (recommended)")
            print("  2. Install manually from https://conda.io/")
            print("  3. Use without conda: python install.py\n")

            # Ask user if they want to auto-install
            choice = input("Select option (1-3): ").strip()
            if choice == "1":
                install_miniconda()
                # Refresh conda detection after installation
                is_installed, reason, conda_base = is_conda_installed()
                if not is_installed:
                    print("❌ Miniconda installation failed. Please install manually.")
                    sys.exit(1)
            elif choice == "3":
                print("✓ Proceeding with pip installation (no conda)\n")
                use_conda = False
                # Update config to reflect the user's choice
                save_config_value("use_conda", False)
            else:
                print(
                    "\n❌ Please install conda from https://conda.io/ or select option 3 to use pip\n"
                )
                sys.exit(1)

    # After user choice, setup the appropriate environment
    if use_conda:
        env_name = get_env_name_from_yml()
        setup_conda_environment(env_name)
        print("✓ Verifying conda environment...")
        verify_conda_env(env_name)
        print("✓ Environment verified\n")
    else:
        setup_pip_environment()
        print()

    # Install Playwright browser (needed for browser-automation actions)
    install_playwright_browser(use_conda=use_conda)

    # Install browser frontend dependencies — required for browser mode
    frontend_ok = install_browser_frontend()

    # Install the WhatsApp bridge's npm deps (Baileys) so the first QR
    # link isn't blocked behind an npm download.
    install_whatsapp_bridge()
    if not frontend_ok:
        print(f"\n  {RED}✗{RESET} {WHITE}Browser frontend setup failed.{RESET}")
        print(
            "  Browser mode (localhost:7925) will not work until Node.js is installed"
        )
        print("  and 'npm install' succeeds in app/ui_layer/browser/frontend/")
        print("\n  Fix:")
        print("    1. Install Node.js LTS from https://nodejs.org/")
        print("    2. Re-run: python install.py")
        sys.exit(1)

    # Step 2: Install GUI components (optional)
    if install_gui:
        print("\n" + "=" * 60)
        print(" 🎨 Installing GUI Components")
        print("=" * 60 + "\n")
        setup_omniparser(force_cpu=force_cpu, use_conda=use_conda)

    # Done — retro completion box
    _CW = 60
    _CT = f"{ORANGE}╔{'═' * _CW}╗{RESET}"
    _CB = f"{ORANGE}╚{'═' * _CW}╝{RESET}"
    _CE = f"{ORANGE}║{' ' * _CW}║{RESET}"
    _ok_vis = "  ██  INSTALLATION COMPLETE  ██  "
    print(f"\n{_CT}")
    print(_CE)
    print(f"{ORANGE}║{RESET}{GREEN}{_ok_vis.center(_CW)}{RESET}{ORANGE}║{RESET}")
    print(_CE)
    print(f"{_CB}\n")

    if "--no-launch" in args:
        print(
            f"  {GREEN}▸{RESET} {WHITE}DEPENDENCIES READY — SERVICE WILL START AUTOMATICALLY{RESET}\n"
        )
    else:
        print(f"  {ORANGE}▸{RESET} {WHITE}LOADING CRAFTBOT...{RESET}\n")
        launch_agent_after_install(install_gui, use_conda)
