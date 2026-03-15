#!/usr/bin/env python3
"""
CraftBot Installation Script

Usage:
    python install.py              # Install core dependencies with global pip
    python install.py --conda      # Install with conda environment
    python install.py --gui        # Install with GUI mode support (with global pip)
    python install.py --gui --conda # Install with GUI and conda environment

Options:
    --gui           Install GUI components (OmniParser for screen automation)
    --conda         Use conda environment (optional)
    --cpu-only      Install CPU-only PyTorch (for OmniParser, with --gui)
    --mamba         Use mamba instead of conda (faster, optional with --conda)

After installation completes, CraftBot will automatically launch in browser mode.
To use TUI mode instead, run: python run.py --tui
"""
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
        bar = '=' * filled + '-' * (self.bar_length - filled)
        
        sys.stdout.write(f"\r[{bar}] {percent}%")
        sys.stdout.flush()
    
    def finish(self, message: str = "Complete"):
        """Finish with 100%."""
        self.current_step = self.total_steps
        bar = '=' * self.bar_length
        sys.stdout.write(f"\r[{bar}] 100% - {message}\n")
        sys.stdout.flush()

# ==========================================
# ANIMATED PROGRESS INDICATOR
# ==========================================
class AnimatedProgress:
    """Animated progress bar with percentage."""
    def __init__(self, message: str = "Installing"):
        self.message = message
        self.percent = 0
        self.bar_length = 30
    
    def update(self, percent: int):
        """Update progress with percentage."""
        self.percent = min(percent, 100)
        filled = int(self.bar_length * self.percent / 100)
        bar = "█" * filled + "░" * (self.bar_length - filled)
        sys.stdout.write(f"\r{self.message} [{bar}] {self.percent}%")
        sys.stdout.flush()
    
    def finish(self):
        """Complete the progress bar."""
        filled = self.bar_length
        bar = "█" * filled
        sys.stdout.write(f"\r{self.message} [{bar}] 100%\n")
        sys.stdout.flush()

def run_command_with_progress(cmd_list: list[str], message: str = "Processing", cwd: Optional[str] = None, check: bool = True, capture: bool = False, env_extras: Dict[str, str] = None) -> subprocess.CompletedProcess:
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
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'text': True,
    }

    try:
        # Start process
        process = subprocess.Popen(cmd_list, cwd=cwd, env=my_env, **kwargs)
        
        # Simulate progress updates while process runs
        import threading
        def update_progress():
            steps = [5, 10, 15, 25, 35, 45, 55, 65, 75, 85, 92, 98]
            step_idx = 0
            while process.poll() is None and step_idx < len(steps):
                progress.update(steps[step_idx])
                step_idx += 1
                time.sleep(0.1)  # Faster updates
            
            # Continue updating until process finishes
            while process.poll() is None:
                time.sleep(0.05)
        
        # Start progress thread
        progress_thread = threading.Thread(target=update_progress, daemon=True)
        progress_thread.start()
        
        # Wait for process to finish
        stdout, stderr = process.communicate()
        
        # Complete progress
        progress.finish()
        
        if process.returncode != 0 and check:
            print(f"\n✗ Error during installation:")
            if stderr:
                print(stderr[:500])
            sys.exit(1)
        
        return subprocess.CompletedProcess(cmd_list, process.returncode, stdout, stderr)
    
    except FileNotFoundError as e:
        exe_name = e.filename or cmd_list[0]
        print(f"\n✗ Executable not found: {exe_name}")
        print(f"   Command: {' '.join(cmd_list)}")
        print(f"   Make sure this program is installed and in your PATH")
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
            ctypes.windll.kernel32.GetDiskFreeSpaceEx(ctypes.c_wchar_p(path), None, None, ctypes.pointer(free_bytes))
            free_gb = free_bytes.value / (1024 ** 3)
            # For Windows, we'll estimate total as free + a reasonable amount
            total_gb = free_gb + 50  # Estimate
            used_gb = 0
        else:
            # Unix/Linux/Mac
            st = os.statvfs(path)
            free_gb = (st.f_bavail * st.f_frsize) / (1024 ** 3)
            total_gb = (st.f_blocks * st.f_frsize) / (1024 ** 3)
            used_gb = ((st.f_blocks - st.f_bfree) * st.f_frsize) / (1024 ** 3)
        
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
    
    print("\n" + "="*60)
    print(" 📊 Disk Space Check")
    print("="*60)
    print(f"Home directory: {os.path.expanduser('~')}")
    print(f"Total space:   {home_total_gb:.1f} GB")
    print(f"Used space:    {home_used_gb:.1f} GB ({percent_used:.1f}%)")
    print(f"Free space:    {home_free_gb:.1f} GB")
    
    if home_free_gb < min_free_gb:
        print(f"\n⚠️  WARNING: Low disk space ({home_free_gb:.1f} GB free, need {min_free_gb:.1f} GB)")
        print("\nRecommended fixes:")
        print("\n1. Clean up pip cache:")
        print("   pip cache purge")
        print("\n2. Clean up npm cache (if Node.js installed):")
        print("   npm cache clean --force")
        print("\n3. Remove old files/packages:")
        print(f"   rm -rf ~/.cache/*  # On Linux/Mac")
        print(f"   rmdir /s %LocalAppData%\\pip  # On Windows")
        print("\n4. Use a different disk with more space:")
        mkdir_path = "/mnt/large-disk/pip-tmp" if sys.platform != "win32" else "D:/pip-tmp"
        print(f"   mkdir -p {mkdir_path}")
        print(f"   TMPDIR={mkdir_path} python install.py")
        print(f"\n5. Or continue anyway (may fail): ", end="")
        
        choice = input("Continue? (y/n): ").strip().lower()
        if choice != 'y':
            print("Installation cancelled. Please free up disk space and try again.")
            return False
        else:
            print("\nAttempting installation anyway...\n")
    
    print("="*60 + "\n")
    return True

def suggest_cleanup_steps():
    """Show cleanup steps if disk is full."""
    print("\n" + "="*60)
    print(" 🧹 Disk Space Cleanup Guide (for Kali & other systems)")
    print("="*60)
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
    
    print("="*60 + "\n")

def load_config() -> Dict[str, Any]:
    """
    Load configuration from file safely.
    
    SECURITY FIX: Use try-except instead of check-then-use to prevent TOCTOU race conditions.
    This ensures atomic read operation.
    """
    try:
        with open(CONFIG_FILE, 'r') as f:
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
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except IOError as e:
        pass  # Silently fail if config can't be saved

def run_command(cmd_list: list[str], cwd: Optional[str] = None, check: bool = True, capture: bool = False, env_extras: Dict[str, str] = None, quiet: bool = False, show_error: bool = True) -> subprocess.CompletedProcess:
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
        kwargs['capture_output'] = True
        kwargs['text'] = True
    else:
        kwargs['stdout'] = subprocess.DEVNULL
        kwargs['stderr'] = subprocess.DEVNULL

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
            print(f"   Make sure this program is installed and in your PATH")
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
            os.path.dirname(os.path.dirname(current_python_dir))
        ]
        for base_path in potential_base_paths:
            activate_bat = os.path.join(base_path, "Scripts", "activate.bat")
            condabin_bat = os.path.join(base_path, "condabin", "conda.bat")
            if os.path.exists(activate_bat) or os.path.exists(condabin_bat):
                return True, f"Found at {base_path}", base_path

    return False, "Not found", None

def get_env_name_from_yml(yml_path: str = YML_FILE) -> str:
    try:
        with open(yml_path, 'r') as f:
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
            url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86.exe"
            installer = os.path.join(BASE_DIR, "Miniconda-installer.exe")
    elif sys.platform == "linux":
        # Linux
        if sys.maxsize > 2**32:
            url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
        else:
            url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86.sh"
        installer = os.path.join(BASE_DIR, "miniconda-installer.sh")
    elif sys.platform == "darwin":
        # macOS
        if sys.maxsize > 2**32:
            url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh"
        else:
            url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh"
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
            sp.run(["bash", installer, "-b", "-p", os.path.expanduser("~/miniconda3")], check=True)
            print("✓ Miniconda installed!")
            print("   Please add conda to PATH, then restart terminal and run installation again.\n")
            os.remove(installer)
            return True
    except Exception as e:
        print(f"❌ Miniconda installation failed: {e}")
        if os.path.exists(installer):
            try:
                os.remove(installer)
            except:
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
        result = run_command_with_progress([conda_cmd, "env", "update", "-f", yml_path, "-n", env_name], "Installing dependencies via conda", check=False)
        if result and hasattr(result, 'returncode') and result.returncode == 0:
            print("✓ Conda environment ready")
        else:
            print("\n✗ Failed to set up conda environment")
            if result and hasattr(result, 'stderr'):
                print(result.stderr[:500])
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error setting up conda environment: {e}")
        sys.exit(1)

def verify_conda_env(env_name: str) -> bool:
    try:
        conda_cmd = get_conda_command()
        verification_cmd = [conda_cmd, "run", "-n", env_name, "python", "-c", "print('OK')"]
        result = run_command(verification_cmd, capture=True, quiet=True, check=False, show_error=False)
        return result and hasattr(result, 'returncode') and result.returncode == 0
    except Exception as e:
        return False

def install_nodejs_linux():
    """
    Automatically install Node.js on Linux systems (including Kali).
    Detects the package manager (apt, pacman, yum) and installs accordingly.
    """
    if sys.platform == "win32":
        return True  # Windows users should install Node.js manually from nodejs.org
    
    # Check if node is already installed
    if shutil.which("node") and shutil.which("npm"):
        print("✓ Node.js and npm are already installed")
        return True
    
    print("\n🔧 Installing Node.js...")
    
    # Detect package manager and prepare install commands
    # Format: (package_manager, update_cmd, install_cmd)
    package_managers = [
        ("apt-get", ["sudo", "apt-get", "update"], ["sudo", "apt-get", "install", "-y", "nodejs", "npm"]),
        ("apt", ["sudo", "apt", "update"], ["sudo", "apt", "install", "-y", "nodejs", "npm"]),
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
                    update_result = run_command(update_cmd, check=False, capture=True, quiet=True, show_error=False)
                    if update_result and hasattr(update_result, 'returncode') and update_result.returncode != 0:
                        print(f"   ⚠ Package manager update failed, continuing anyway...")
                
                # Run install command
                install_result = run_command(install_cmd, check=False, capture=True, quiet=True, show_error=False)
                
                if install_result and hasattr(install_result, 'returncode') and install_result.returncode == 0:
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
            node_version = run_command([shutil.which("node"), "--version"], capture=True, quiet=True, show_error=False)
            npm_version = run_command([shutil.which("npm"), "--version"], capture=True, quiet=True, show_error=False)
            if node_version and hasattr(node_version, 'stdout'):
                print(f"   Node.js {node_version.stdout.strip()}")
            if npm_version and hasattr(npm_version, 'stdout'):
                print(f"   npm {npm_version.stdout.strip()}")
        except:
            pass
        return True
    else:
        print("⚠ Node.js verification failed - it may not be in PATH")
        print("  Please restart your terminal and verify: node --version")
        return False

def install_playwright_browser(use_conda: bool = False):
    """Install Playwright Chromium browser for WhatsApp Web support."""
    print("\nInstalling Playwright Chromium browser...")
    try:
        if use_conda:
            conda_cmd = get_conda_command()
            env_name = get_env_name_from_yml()
            result = run_command([conda_cmd, "run", "-n", env_name, "python", "-m", "playwright", "install", "chromium"], check=False, capture=True, show_error=False)
        else:
            result = run_command([sys.executable, "-m", "playwright", "install", "chromium"], check=False, capture=True, show_error=False)
        if result and hasattr(result, 'returncode') and result.returncode == 0:
            print("✓ Playwright Chromium installed")
            return True
        else:
            print("⚠ Warning: Playwright browser installation failed")
            if result and hasattr(result, 'stderr') and result.stderr:
                error_msg = result.stderr[:300].strip()
                if error_msg:
                    print(f"  Error details: {error_msg}")
            print("  WhatsApp Web integration may not work")
            print("  You can manually install later with: playwright install chromium")
            return False
    except Exception as e:
        print(f"⚠ Warning: Failed to install Playwright browser: {e}")
        print("  WhatsApp Web integration may not work")
        print("  You can manually install later with: playwright install chromium")
        return False

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

    # Check if node_modules already exists
    node_modules = os.path.join(frontend_dir, "node_modules")
    if os.path.exists(node_modules):
        print("\n✓ Browser frontend dependencies already installed")
        return True

    # Try to install
    print("\n🔧 Installing browser frontend dependencies...")
    try:
        result = run_command_with_progress([npm_cmd, "install"], message="Installing npm packages", cwd=frontend_dir, check=False)
        if result and hasattr(result, 'returncode') and result.returncode == 0:
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
        
        # Create temp directory if it doesn't exist
        os.makedirs(tmp_dir, exist_ok=True)
        
        # First attempt with standard pip install
        cmd = [sys.executable, "-m", "pip", "install", "-r", requirements_file]
        result = run_command(cmd, capture=True, check=False, env_extras={"TMPDIR": tmp_dir})
        
        if result and hasattr(result, 'returncode') and result.returncode != 0:
            # Check error output
            error_output = ""
            if hasattr(result, 'stderr'):
                error_output = result.stderr
            elif hasattr(result, 'stdout'):
                error_output = result.stdout
            
            # Check for disk space errors
            if "no space left on device" in error_output.lower() or "disk full" in error_output.lower():
                print("\n❌ DISK SPACE ERROR - No space left on device\n")
                print("This is a common issue on Kali Linux when installing large packages.\n")
                print("Immediate fixes:\n")
                print("1. Clear pip cache (usually frees 1-5 GB):")
                print("   pip cache purge\n")
                print("2. Clear npm cache (if installed):")
                print("   npm cache clean --force\n")
                print("3. Use alternate disk with more space:")
                mkdir_cmd = "/mnt/external/pip-tmp" if sys.platform != "win32" else "D:/pip-tmp"
                print(f"   mkdir -p {mkdir_cmd}")
                print(f"   TMPDIR={mkdir_cmd} python install.py\n")
                print("4. Check disk usage:")
                check_cmd = "du -sh ~/*" if sys.platform != "win32" else "dir /-s C:\\"
                print(f"   {check_cmd}\n")
                suggest_cleanup_steps()
                sys.exit(1)
            
            # Check for PEP 668 error
            if "externally-managed-environment" in error_output or "externally managed" in error_output:
                print("\n⚠️  PEP 668 Error Detected (externally-managed-environment)\n")
                print("This usually happens on Kali Linux or other systems with managed Python.")
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
                cmd_with_flag = [sys.executable, "-m", "pip", "install", "--break-system-packages", "-r", requirements_file]
                result = run_command(cmd_with_flag, capture=True, check=False, env_extras={"TMPDIR": tmp_dir})
                
                if result and hasattr(result, 'returncode') and result.returncode == 0:
                    print("✓ Core dependencies installed (with --break-system-packages)")
                else:
                    print("\n✗ Installation failed even with --break-system-packages")
                    if hasattr(result, 'stderr') and result.stderr:
                        print(f"\nError: {result.stderr[:500]}")
                    print("\nPlease use Option 1 or Option 2 above.")
                    sys.exit(1)
            else:
                # Different error
                print("\n✗ Error installing core dependencies:")
                if hasattr(result, 'stderr') and result.stderr:
                    print(result.stderr[:1000])
                print("\nTroubleshooting:")
                print("  1. Check for disk space: " + ("df -h" if sys.platform != "win32" else "dir C:\\"))
                print("  2. Clear pip cache: pip cache purge")
                print("  3. Check your internet connection")
                print("  4. Try: pip install --upgrade pip")
                print("  5. Try with conda: python install.py --conda")
                sys.exit(1)
        else:
            print("✓ Core dependencies installed")
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

    def run_omni_cmd(cmd_list: list[str], work_dir: str = repo_path, capture_output: bool = False, env_extras: Dict[str, str] = None):
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
        
        run_command(full_cmd, cwd=work_dir, capture=capture_output, env_extras=local_env, quiet=capture_output)

    # Step 1: Repository setup
    try:
        print("🔧 Setting up OmniParser repository...")
        if os.path.exists(repo_path):
            run_command(["git", "-C", repo_path, "pull"], quiet=True, check=False)
        else:
            run_command(["git", "clone", "-b", OMNIPARSER_BRANCH, OMNIPARSER_REPO_URL, repo_path], quiet=False, show_error=True)
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
            result = run_command([conda_cmd, "create", "-n", OMNIPARSER_ENV_NAME, "python=3.10", "-y"], capture=True, check=False)
            if result.returncode != 0:
                print(f"\n✗ Error creating conda environment 'omni'")
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
                result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "conda", "install", "pytorch", "torchvision", "torchaudio", "cpuonly", "-c", "pytorch", "-y"], capture=True, check=False)
                pytorch_installed = result.returncode == 0
            else:
                # Try GPU version first
                print("   (Attempting CUDA 12.1 GPU version)")
                result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "conda", "install", "pytorch", "torchvision", "torchaudio", "pytorch-cuda=12.1", "-c", "pytorch", "-c", "nvidia", "-y"], capture=True, check=False)
                
                if result.returncode != 0:
                    print("   ⚠ GPU version failed. Falling back to CPU-only mode...")
                    result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "conda", "install", "pytorch", "torchvision", "torchaudio", "cpuonly", "-c", "pytorch", "-y"], capture=True, check=False)
                    pytorch_installed = result.returncode == 0
                    if pytorch_installed:
                        print("   ✓ CPU-only PyTorch installed successfully")
                else:
                    pytorch_installed = True
        else:
            # Use pip for non-conda installation
            if force_cpu:
                print("   (CPU-only mode)")
                result = run_command(["pip", "install", "torch", "torchvision", "torchaudio"], capture=True, check=False, env_extras={"TMPDIR": os.path.expanduser("~/pip-tmp")})
                pytorch_installed = result.returncode == 0
            else:
                # Try GPU version first
                print("   (Attempting CUDA 12.1 GPU version)")
                result = run_command(["pip", "install", "torch", "torchvision", "torchaudio", "torch-cuda==12.1"], capture=True, check=False, env_extras={"TMPDIR": os.path.expanduser("~/pip-tmp")})
                
                if result.returncode != 0:
                    print("   ⚠ GPU version failed. Falling back to CPU-only mode...")
                    result = run_command(["pip", "install", "torch", "torchvision", "torchaudio"], capture=True, check=False, env_extras={"TMPDIR": os.path.expanduser("~/pip-tmp")})
                    pytorch_installed = result.returncode == 0
                    if pytorch_installed:
                        print("   ✓ CPU-only PyTorch installed successfully")
                else:
                    pytorch_installed = True
        
        if not pytorch_installed:
            print("\n✗ Error installing PyTorch")
            if hasattr(result, 'stderr') and result.stderr:
                error_msg = result.stderr[:500]
                print(f"\n   Error details:\n   {error_msg}")
                
                # Check for specific errors
                if "no space left on device" in error_msg.lower() or "disk" in error_msg.lower():
                    print("\n⚠️  DISK SPACE ERROR detected")
                    print("   PyTorch is very large (~5GB+). Your disk may be full.")
                    print("\n   Solutions:")
                    print("   1. Clear pip cache: pip cache purge")
                    print("   2. Clear npm cache: npm cache clean --force")
                    print("   3. Use alternate disk: TMPDIR=/mnt/large-disk/pip-tmp python install.py --gui")
                    print("   4. Use conda (more efficient): python install.py --gui --conda")
                
                elif "externally-managed-environment" in error_msg or "externally managed" in error_msg:
                    print("\n⚠️  PEP 668 Error: System-managed Python detected")
                    print("   Use virtual environment or conda for GUI mode")
                
                elif "cuda" in error_msg.lower() or "gpu" in error_msg.lower():
                    print("\n⚠️  CUDA/GPU Error detected")
                    print("   Try CPU-only: python install.py --gui --cpu-only")
                    print("   Or with conda: python install.py --gui --conda")
            
            print("\n⚠️  Troubleshooting:")
            print("   1. Check disk space: " + ("df -h" if sys.platform != "win32" else "dir C:\\"))
            print("   2. Clear pip cache: pip cache purge")
            print("   3. Try clearing system caches: " + ("sudo apt-get clean" if sys.platform != "win32" else "Disk Cleanup"))
            print("   4. Try again with CPU-only mode: python install.py --gui --cpu-only")
            print("   5. Use conda (recommended): python install.py --gui --conda")
            print("   6. Check PyTorch documentation: https://pytorch.org/get-started/locally/")
            sys.exit(1)

        # Step 4: Install dependencies
        print("🔧 Installing dependencies...")
        deps = ["mkl==2024.0", "sympy==1.13.1", "transformers==4.51.0", "huggingface_hub[cli]", "hf_transfer"]
        tmp_dir = os.path.expanduser("~/pip-tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        
        if use_conda:
            conda_cmd = get_conda_command()
            result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "pip", "install"] + deps, capture=True, check=False, env_extras={"TMPDIR": tmp_dir})
        else:
            result = run_command(["pip", "install"] + deps, capture=True, check=False, env_extras={"TMPDIR": tmp_dir})
        if result.returncode != 0:
            print("⚠ Warning: Some dependencies may have failed to install")
            if hasattr(result, 'stderr') and result.stderr and "externally-managed" not in result.stderr:
                error_snippet = result.stderr[:200].strip()
                if error_snippet:
                    print(f"  Details: {error_snippet}")

        req_txt = os.path.join(repo_path, "requirements.txt")
        if os.path.exists(req_txt):
            if use_conda:
                conda_cmd = get_conda_command()
                result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "pip", "install", "-r", "requirements.txt"], cwd=repo_path, capture=True, check=False, env_extras={"TMPDIR": tmp_dir})
            else:
                result = run_command(["pip", "install", "-r", "requirements.txt"], cwd=repo_path, capture=True, check=False, env_extras={"TMPDIR": tmp_dir})
            if result.returncode != 0:
                print("⚠ Warning: Some requirements may have failed to install")

        # Create marker
        with open(marker_path, 'w') as f:
            f.write(f"Installed on {time.ctime()}\n")
    else:
        print("🔧 Environment already set up, skipping setup steps...")

    # Step 5: Download model weights
    print("🔧 Downloading model weights (this may take a while)...")
    files_to_download = [
        {"file": "icon_detect/train_args.yaml", "local_path": "icon_detect/train_args.yaml"},
        {"file": "icon_detect/model.pt", "local_path": "icon_detect/model.pt"},
        {"file": "icon_detect/model.yaml", "local_path": "icon_detect/model.yaml"},
        {"file": "icon_caption/config.json", "local_path": "icon_caption_florence/config.json"},
        {"file": "icon_caption/generation_config.json", "local_path": "icon_caption_florence/generation_config.json"},
        {"file": "icon_caption/model.safetensors", "local_path": "icon_caption_florence/model.safetensors"}
    ]

    weights_dir = os.path.join(repo_path, "weights")
    os.makedirs(os.path.join(weights_dir, "icon_detect"), exist_ok=True)
    os.makedirs(os.path.join(weights_dir, "icon_caption_florence"), exist_ok=True)

    hf_env = {"HF_HUB_ENABLE_HF_TRANSFER": "1"}
    failed_downloads = []
    for i, file_info in enumerate(files_to_download, 1):
        local_dest = os.path.join(weights_dir, file_info['local_path'])
        if not os.path.exists(local_dest):
            print(f"  📦 ({i}/{len(files_to_download)}) Downloading: {file_info['local_path']}...")
            if use_conda:
                conda_cmd = get_conda_command()
                result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "hf", "download", "microsoft/OmniParser-v2.0", file_info['file'], "--local-dir", "weights"],
                            cwd=repo_path, capture=True, check=False, env_extras=hf_env)
            else:
                result = run_command(["hf", "download", "microsoft/OmniParser-v2.0", file_info['file'], "--local-dir", "weights"],
                            cwd=repo_path, capture=True, check=False, env_extras=hf_env)
            if result.returncode != 0:
                failed_downloads.append(file_info['local_path'])
        else:
            print(f"  ✓ ({i}/{len(files_to_download)}) Already have: {file_info['local_path']}")
    
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
    print("\n" + "="*60)
    print(" 🚀 Launching CraftBot (Browser Interface)...")
    print("="*60 + "\n")
    
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
            cmd_args = ' '.join(args) if args else ''
            print(f"  {conda_cmd} run -n {env_name} python run.py {cmd_args}".rstrip() + "\n")
        else:
            cmd_args = ' '.join(args) if args else ''
            print(f"  python run.py {cmd_args}".rstrip() + "\n")
        sys.exit(1)


# ==========================================
# API KEY SETUP
# ==========================================
def check_api_keys() -> bool:
    """Check if required API keys are set in settings.json."""
    settings_path = os.path.join(BASE_DIR, "app", "config", "settings.json")
    try:
        with open(settings_path, 'r') as f:
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
    print("\n" + "="*50)
    print(" ⚠ API Key Required")
    print("="*50)
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
    print('     }')
    print("     ")
    print("     OR")
    print("     ")
    print('     "api_keys": {')
    print('       "google": "your-key-here"')
    print('     }')
    print("     ")
    print("  3. Save and run again: python install.py")
    print("="*50 + "\n")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    args = set(sys.argv[1:])

    # Parse flags
    install_gui = "--gui" in args
    use_conda = "--conda" in args
    force_cpu = "--cpu-only" in args

    # Save installation configuration (silent)
    save_config_value("use_conda", use_conda)
    save_config_value("gui_mode_enabled", install_gui)
    os.environ["USE_CONDA"] = str(use_conda)

    # Print installation header
    print("\n" + "="*60)
    print(" 🚀 CraftBot Installation")
    print("="*60)
    if use_conda:
        print(" Mode: Conda environment")
    else:
        print(" Mode: Global pip")
    if install_gui:
        print(" GUI:  Enabled (OmniParser)")
    else:
        print(" GUI:  Disabled")
    print("="*60 + "\n")

    # Pre-flight check: Disk space (especially important for Kali)
    min_space_needed = 8.0 if install_gui else 5.0  # GUI mode needs more space for torch
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
                print("\n❌ Please install conda from https://conda.io/ or select option 3 to use pip\n")
                sys.exit(1)

    # After user choice, setup the appropriate environment
    if use_conda:
        env_name = get_env_name_from_yml()
        setup_conda_environment(env_name)
        print(f"✓ Verifying conda environment...")
        verify_conda_env(env_name)
        print("✓ Environment verified\n")
    else:
        setup_pip_environment()
        print()

    # Install Playwright browser (needed for WhatsApp Web)
    install_playwright_browser(use_conda=use_conda)

    # Install browser frontend dependencies
    install_browser_frontend()

    # Step 2: Install GUI components (optional)
    if install_gui:
        print("\n" + "="*60)
        print(" 🎨 Installing GUI Components")
        print("="*60 + "\n")
        setup_omniparser(force_cpu=force_cpu, use_conda=use_conda)

    # Done - launch the agent in browser mode (default)
    print("="*60)
    print(" ✅ Installation Complete!")
    print("="*60)
    print("\n🚀 Starting CraftBot Browser Interface...\n")
    launch_agent_after_install(install_gui, use_conda)

