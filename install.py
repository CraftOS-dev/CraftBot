#!/usr/bin/env python3
"""
CraftBot Installation Script

Usage:
    python install.py              # Install core dependencies with global pip
    python install.py --conda      # Install with conda environment
    python install.py --gui        # Install with GUI mode support (requires --conda)
    python install.py --gui --conda # Install with GUI and conda environment

Options:
    --gui           Install GUI components (OmniParser for screen automation)
    --conda         Use conda environment (required for --gui)
    --cpu-only      Install CPU-only PyTorch (for OmniParser, requires --gui)
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
            print(f"\nError during installation:")
            if stderr:
                print(stderr[:500])
            sys.exit(1)
        
        return subprocess.CompletedProcess(cmd_list, process.returncode, stdout, stderr)
    
    except FileNotFoundError as e:
        print(f"\nExecutable not found: {e.filename}")
        sys.exit(1)

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

def run_command(cmd_list: list[str], cwd: Optional[str] = None, check: bool = True, capture: bool = False, env_extras: Dict[str, str] = None, quiet: bool = False) -> subprocess.CompletedProcess:
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
        if capture or quiet:
            print(f"\nError: {' '.join(cmd_list)}")
            if not quiet:
                print(f"STDOUT: {e.stdout}")
                print(f"STDERR: {e.stderr}")
        else:
            print(f"\nCommand failed.")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"\nExecutable not found: {e.filename}")
        sys.exit(1)

# ==========================================
# ENVIRONMENT SETUP
# ==========================================
def is_conda_installed() -> Tuple[bool, str, Optional[str]]:
    conda_exe = shutil.which("conda")
    if conda_exe:
        conda_base_path = os.path.dirname(os.path.dirname(conda_exe))
        return True, f"Found at {conda_exe}", conda_base_path

    if sys.platform == "win32":
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

def get_conda_command() -> str:
    """Return conda command. Use --mamba flag to use mamba instead."""
    # Mamba can have compatibility issues, so use conda by default
    # Users can pass --mamba flag if they want to use mamba
    if "--mamba" in sys.argv:
        if shutil.which("mamba"):
            return "mamba"
    return "conda"

def setup_conda_environment(env_name: str, yml_path: str = YML_FILE):
    conda_cmd = get_conda_command()
    try:
        print(f"🔧 Setting up conda environment '{env_name}'...")
        run_command_with_progress([conda_cmd, "env", "update", "-f", yml_path], "Installing dependencies via conda")
        print("✓ Conda environment ready")
    except Exception as e:
        raise

def verify_conda_env(env_name: str) -> bool:
    try:
        verification_cmd = ["conda", "run", "-n", env_name, "python", "-c", "print('OK')"]
        run_command(verification_cmd, capture=True, quiet=True)
        return True
    except:
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
        full_cmd = ["conda", "run", "-n", OMNIPARSER_ENV_NAME] + cmd_list
        local_env = env_extras.copy() if env_extras else {}
        run_command(full_cmd, cwd=work_dir, capture=capture_output, env_extras=local_env, quiet=capture_output)

    # Step 1: Repository setup
    try:
        print("🔧 Setting up OmniParser repository...")
        if os.path.exists(repo_path):
            run_command(["git", "-C", repo_path, "pull"], quiet=True, check=False)
        else:
            run_command(["git", "clone", "-b", OMNIPARSER_BRANCH, OMNIPARSER_REPO_URL, repo_path], quiet=False)
    except Exception as e:
        progress.finish("Error")
        raise

    # Check marker file
    marker_path = os.path.join(repo_path, OMNIPARSER_MARKER_FILE)
    if not os.path.exists(marker_path):
        # Step 2: Create environment
        try:
            print("🔧 Creating conda environment...")
            run_command(["conda", "create", "-n", OMNIPARSER_ENV_NAME, "python=3.10", "-y"], capture=True, quiet=False, check=False)
            run_omni_cmd(["pip", "install", "--upgrade", "pip"])
        except Exception as e:
            print("\n✗ Error creating environment")
            raise
        
        # Step 3: Install PyTorch
        try:
            print("🔧 Installing PyTorch...")
            if force_cpu:
                run_omni_cmd(["conda", "install", "pytorch", "torchvision", "torchaudio", "cpuonly", "-c", "pytorch", "-y"])
            else:
                run_omni_cmd(["conda", "install", "pytorch", "torchvision", "torchaudio", "pytorch-cuda=12.1", "-c", "pytorch", "-c", "nvidia", "-y"])
        except Exception as e:
            print("\n✗ Error installing PyTorch")
            raise

        # Step 4: Install dependencies
        try:
            print("🔧 Installing dependencies...")
            deps = ["mkl==2024.0", "sympy==1.13.1", "transformers==4.51.0", "huggingface_hub[cli]", "hf_transfer"]
            run_omni_cmd(["pip", "install"] + deps)

            req_txt = os.path.join(repo_path, "requirements.txt")
            if os.path.exists(req_txt):
                run_omni_cmd(["pip", "install", "-r", "requirements.txt"])
        except Exception as e:
            print("\n✗ Error installing dependencies")
            raise

        # Create marker
        with open(marker_path, 'w') as f:
            f.write(f"Installed on {time.ctime()}\n")
    else:
        print("🔧 Environment already set up, skipping setup steps...")

    # Step 5: Download model weights
    try:
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
        for i, file_info in enumerate(files_to_download, 1):
            local_dest = os.path.join(weights_dir, file_info['local_path'])
            if not os.path.exists(local_dest):
                print(f"  📦 ({i}/{len(files_to_download)}) Downloading: {file_info['local_path']}...")
                run_omni_cmd(["hf", "download", "microsoft/OmniParser-v2.0", file_info['file'], "--local-dir", "weights"],
                            work_dir=repo_path, capture_output=True, env_extras=hf_env)
            else:
                print(f"  ✓ ({i}/{len(files_to_download)}) Already have: {file_info['local_path']}")
    except Exception as e:
        print("\n✗ Error downloading model weights")
        raise

    # Step 6: Reorganize files
    try:
        print("🔧 Organizing GUI components...")
        src_caption = os.path.join(weights_dir, "icon_caption")
        dst_caption = os.path.join(weights_dir, "icon_caption_florence")
        if os.path.exists(src_caption):
            if os.path.exists(dst_caption):
                shutil.rmtree(dst_caption)
            shutil.move(src_caption, dst_caption)
        print("✓ GUI components ready\n")
    except Exception as e:
        print("\n✗ Error organizing files")
        raise


# ==========================================
# MAIN
# ==========================================
def launch_agent_after_install(install_gui: bool, use_conda: bool):
    """Launch the agent automatically after installation."""
    main_script = os.path.abspath(os.path.join(BASE_DIR, "run.py"))
    if not os.path.exists(main_script):
        print(f"Error: {main_script} not found.")
        sys.exit(1)

    # Build args for run script
    args = []
    if install_gui:
        args.append("--gui")

    # Build command based on installation method
    if use_conda:
        env_name = get_env_name_from_yml()
        cmd = ["conda", "run", "-n", env_name, "python", "-u", main_script] + args
        
        # On Windows, wrap with cmd.exe if needed
        if sys.platform == "win32":
            conda_exe = shutil.which("conda") or "conda"
            if conda_exe.lower().endswith((".bat", ".cmd")):
                cmd = ["cmd.exe", "/d", "/c"] + cmd
    else:
        cmd = [sys.executable, "-u", main_script] + args

    # Launch the agent
    try:
        result = subprocess.run(cmd, cwd=BASE_DIR, env=os.environ.copy())
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"Error launching agent: {e}")
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

    # Validate flags
    if install_gui and not use_conda:
        print("Error: --gui requires --conda flag.")
        print("Use: python install.py --gui --conda\n")
        sys.exit(1)

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
            print("  1. Install Anaconda or Miniconda from https://conda.io/")
            print("  2. Or use without conda: python install.py\n")
            sys.exit(1)

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

