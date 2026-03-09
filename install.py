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

# Load .env if dotenv is available (optional, not required for fresh install)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed yet, that's fine

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

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Warning: {CONFIG_FILE} is corrupted. Starting with empty config.")
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

def setup_pip_environment(requirements_file: str = REQUIREMENTS_FILE):
    try:
        if not os.path.exists(requirements_file):
            print(f"Error: {requirements_file} not found.")
            sys.exit(1)
        print("🔧 Installing core dependencies...")
        run_command_with_progress([sys.executable, "-m", "pip", "install", "-r", requirements_file], 
                                 "Installing packages")
        print("✓ Core dependencies installed")
    except Exception as e:
        raise

# ==========================================
# OMNIPARSER SETUP (GUI Mode)
# ==========================================
def setup_omniparser(force_cpu: bool, use_conda: bool):
    """Install OmniParser for GUI mode support."""

    if not use_conda:
        print("Error: GUI installation requires --conda flag.")
        sys.exit(1)

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
        """Execute command in OmniParser conda environment."""
        conda_cmd = get_conda_command()
        full_cmd = [conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME] + cmd_list
        local_env = env_extras.copy() if env_extras else {}
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
        # Step 2: Create environment
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
        
        if not pytorch_installed:
            print("\n✗ Error installing PyTorch")
            if hasattr(result, 'stderr') and result.stderr:
                print(f"\n   Error details:\n   {result.stderr[:500]}")
            print("\n⚠️  Troubleshooting:")
            print("   1. Check your internet connection")
            print("   2. Try again with CPU-only mode: python install.py --gui --conda --cpu-only")
            print("   3. If issues persist, check conda/PyTorch documentation")
            sys.exit(1)

        # Step 4: Install dependencies
        print("🔧 Installing dependencies...")
        deps = ["mkl==2024.0", "sympy==1.13.1", "transformers==4.51.0", "huggingface_hub[cli]", "hf_transfer"]
        result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "pip", "install"] + deps, capture=True, check=False)
        if result.returncode != 0:
            print("⚠ Warning: Some dependencies may have failed to install")

        req_txt = os.path.join(repo_path, "requirements.txt")
        if os.path.exists(req_txt):
            result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "pip", "install", "-r", "requirements.txt"], cwd=repo_path, capture=True, check=False)
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
    conda_cmd = get_conda_command()
    for i, file_info in enumerate(files_to_download, 1):
        local_dest = os.path.join(weights_dir, file_info['local_path'])
        if not os.path.exists(local_dest):
            print(f"  📦 ({i}/{len(files_to_download)}) Downloading: {file_info['local_path']}...")
            result = run_command([conda_cmd, "run", "-n", OMNIPARSER_ENV_NAME, "hf", "download", "microsoft/OmniParser-v2.0", file_info['file'], "--local-dir", "weights"],
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
    print(" 🚀 Launching CraftBot...")
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
            print(f"  {conda_cmd} run -n {env_name} python run.py {' '.join(args)}\n")
        else:
            print(f"  python run.py {' '.join(args)}\n")
        sys.exit(1)


# ==========================================
# API KEY SETUP
# ==========================================
def check_api_keys() -> bool:
    """Check if required API keys are set."""
    required_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
    
    for key in required_keys:
        if os.getenv(key):
            return True
    
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
    print("  2. Create a .env file in this directory:")
    print("     ")
    print("     OPENAI_API_KEY=your-key-here")
    print("     ")
    print("     OR")
    print("     ")
    print("     GOOGLE_API_KEY=your-key-here")
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

    # Step 2: Install GUI components (optional)
    if install_gui:
        print("\n" + "="*60)
        print(" 🎨 Installing GUI Components")
        print("="*60 + "\n")
        setup_omniparser(force_cpu=force_cpu, use_conda=use_conda)

    # Done - silently launch the agent
    print("="*60)
    print(" ✅ Installation Complete!")
    print("="*60)
    print("\n🚀 Launching CraftBot...\n")
    launch_agent_after_install(install_gui, use_conda)

