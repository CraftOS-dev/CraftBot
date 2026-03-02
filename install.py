#!/usr/bin/env python3
"""
CraftBot Installation Script

Usage:
    python install.py           # Install core dependencies only
    python install.py --gui     # Install with GUI mode support (OmniParser)

Options:
    --gui           Install GUI components (OmniParser for screen automation)
    --no-conda      Use global pip instead of conda environments
    --cpu-only      Install CPU-only PyTorch (for OmniParser, requires --gui)
    --mamba         Use mamba instead of conda (faster but may have issues)
"""
import multiprocessing
import os
import sys
import json
import subprocess
import shutil
import time
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
            print(f"Updated config: {key} = {value}")
    except IOError as e:
        print(f"Warning: Could not save config file: {e}")

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
        print(f"$ {' '.join(cmd_list)}", flush=True)

    try:
        result = subprocess.run(cmd_list, cwd=cwd, check=check, env=my_env, **kwargs)
        return result
    except subprocess.CalledProcessError as e:
        if capture:
            print(f"\nError: {' '.join(cmd_list)}")
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
            print("Using mamba (faster resolver)")
            return "mamba"
        else:
            print("Warning: mamba not found, using conda")
    return "conda"

def setup_conda_environment(env_name: str, yml_path: str = YML_FILE):
    conda_cmd = get_conda_command()
    print(f"\nCreating/updating conda environment '{env_name}'...")
    run_command([conda_cmd, "env", "update", "-f", yml_path])
    print("Environment ready.")

def verify_conda_env(env_name: str) -> bool:
    print(f"Verifying environment '{env_name}'...")
    try:
        verification_cmd = ["conda", "run", "-n", env_name, "python", "-c", "print('OK')"]
        run_command(verification_cmd, capture=True)
        print(f"Environment '{env_name}' verified.")
        return True
    except:
        return False

def setup_pip_environment(requirements_file: str = REQUIREMENTS_FILE):
    print("\nInstalling dependencies with pip...")
    if not os.path.exists(requirements_file):
        print(f"Error: {requirements_file} not found.")
        sys.exit(1)
    run_command([sys.executable, "-m", "pip", "install", "-r", requirements_file])
    print("Dependencies installed.")

# ==========================================
# OMNIPARSER SETUP (GUI Mode)
# ==========================================
def setup_omniparser(force_cpu: bool, use_conda: bool):
    """Install OmniParser for GUI mode support."""
    print("\n" + "="*50)
    print(" Installing GUI Components (OmniParser)")
    print("="*50)

    mode_str = f"Conda Env '{OMNIPARSER_ENV_NAME}'" if use_conda else "Global Python"
    print(f"Mode: {mode_str}")

    if not shutil.which("git"):
        print("Error: 'git' is required. Please install git first.")
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
        if use_conda:
            full_cmd = ["conda", "run", "-n", OMNIPARSER_ENV_NAME] + cmd_list
            run_command(full_cmd, cwd=work_dir, capture=capture_output, env_extras=env_extras)
        else:
            final_cmd = []
            if cmd_list[0] == "python":
                final_cmd = [sys.executable] + cmd_list[1:]
            elif cmd_list[0] == "pip":
                final_cmd = [sys.executable, "-m", "pip"] + cmd_list[1:]
            else:
                final_cmd = cmd_list

            local_env = env_extras.copy() if env_extras else {}
            if sys.platform != "win32":
                user_base = subprocess.run([sys.executable, "-m", "site", "--user-base"], capture_output=True, text=True).stdout.strip()
                local_bin = os.path.join(user_base, 'bin')
                local_env["PATH"] = f"{local_bin}{os.pathsep}{os.environ.get('PATH', '')}"

            run_command(final_cmd, cwd=work_dir, capture=capture_output, env_extras=local_env)

    # Step 1: Clone/update repository
    print(f"\n[1/6] Repository setup...")
    if os.path.exists(repo_path):
        print(f"Updating existing repo at {repo_path}")
        run_command(["git", "-C", repo_path, "pull"])
    else:
        print(f"Cloning OmniParser...")
        run_command(["git", "clone", "-b", OMNIPARSER_BRANCH, OMNIPARSER_REPO_URL, repo_path])

    # Check marker file
    marker_path = os.path.join(repo_path, OMNIPARSER_MARKER_FILE)
    if os.path.exists(marker_path):
        print(f"\nOmniParser already installed (found marker file).")
        print("Skipping to model weights check...")
    else:
        # Step 2: Create environment (conda only)
        if use_conda:
            print(f"\n[2/6] Creating conda environment '{OMNIPARSER_ENV_NAME}'...")
            try:
                run_command(["conda", "create", "-n", OMNIPARSER_ENV_NAME, "python=3.10", "-y"], capture=True)
            except:
                print(f"Environment '{OMNIPARSER_ENV_NAME}' already exists.")
        else:
            print(f"\n[2/6] Using global Python: {sys.executable}")
            run_omni_cmd(["pip", "install", "--upgrade", "pip"])

        # Step 3: Install PyTorch
        print(f"\n[3/6] Installing PyTorch...")
        if use_conda:
            if force_cpu:
                run_omni_cmd(["conda", "install", "pytorch", "torchvision", "torchaudio", "cpuonly", "-c", "pytorch", "-y"])
            else:
                run_omni_cmd(["conda", "install", "pytorch", "torchvision", "torchaudio", "pytorch-cuda=12.1", "-c", "pytorch", "-c", "nvidia", "-y"])
        else:
            if force_cpu:
                run_omni_cmd(["pip", "install", "torch", "torchvision", "torchaudio", "--extra-index-url", "https://download.pytorch.org/whl/cpu"])
            else:
                run_omni_cmd(["pip", "install", "torch", "torchvision", "torchaudio", "--extra-index-url", "https://download.pytorch.org/whl/cu121"])

        # Step 4: Install other dependencies
        print(f"\n[4/6] Installing dependencies...")
        deps = ["mkl==2024.0", "sympy==1.13.1", "transformers==4.51.0", "huggingface_hub[cli]", "hf_transfer"]
        run_omni_cmd(["pip", "install"] + deps)

        req_txt = os.path.join(repo_path, "requirements.txt")
        if os.path.exists(req_txt):
            run_omni_cmd(["pip", "install", "-r", "requirements.txt"])

        # Create marker
        with open(marker_path, 'w') as f:
            f.write(f"Installed on {time.ctime()}\n")

    # Step 5: Download model weights
    print(f"\n[5/6] Checking model weights...")
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
    for file_info in files_to_download:
        local_dest = os.path.join(weights_dir, file_info['local_path'])
        if not os.path.exists(local_dest):
            print(f"Downloading {file_info['file']}...")
            run_omni_cmd(["hf", "download", "microsoft/OmniParser-v2.0", file_info['file'], "--local-dir", "weights"],
                        work_dir=repo_path, capture_output=True, env_extras=hf_env)

    # Step 6: Reorganize files
    print(f"\n[6/6] Finalizing...")
    src_caption = os.path.join(weights_dir, "icon_caption")
    dst_caption = os.path.join(weights_dir, "icon_caption_florence")
    if os.path.exists(src_caption):
        if os.path.exists(dst_caption):
            shutil.rmtree(dst_caption)
        shutil.move(src_caption, dst_caption)

    print("\nGUI components installed successfully!")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    print("="*50)
    print(" CraftBot Installation")
    print("="*50)

    args = set(sys.argv[1:])

    # Parse flags
    install_gui = "--gui" in args
    use_conda = "--no-conda" not in args
    force_cpu = "--cpu-only" in args

    # Save GUI mode preference
    save_config_value("gui_mode_enabled", install_gui)
    os.environ["USE_CONDA"] = str(use_conda)

    print(f"\nInstallation mode:")
    print(f"  - GUI support: {'Yes' if install_gui else 'No (use --gui to enable)'}")
    print(f"  - Using conda: {'Yes' if use_conda else 'No (global pip)'}")
    if install_gui and force_cpu:
        print(f"  - PyTorch: CPU only")

    # Step 1: Install core dependencies
    print("\n" + "-"*50)
    print(" Step 1: Core Dependencies")
    print("-"*50)

    if use_conda:
        is_installed, reason, conda_base = is_conda_installed()
        if not is_installed:
            print(f"Error: Conda not found ({reason})")
            print("Install conda or use --no-conda flag.")
            sys.exit(1)

        print(f"Conda: {reason}")
        env_name = get_env_name_from_yml()
        setup_conda_environment(env_name)
        verify_conda_env(env_name)
    else:
        setup_pip_environment()

    # Step 2: Install GUI components (optional)
    if install_gui:
        print("\n" + "-"*50)
        print(" Step 2: GUI Components")
        print("-"*50)
        setup_omniparser(force_cpu=force_cpu, use_conda=use_conda)
    else:
        print("\n" + "-"*50)
        print(" GUI components skipped (use --gui to install)")
        print("-"*50)

    # Done
    print("\n" + "="*50)
    print(" Installation Complete!")
    print("="*50)
    print("\nNext step: Run the agent with:")
    print("  python run.py")
    if not install_gui:
        print("\nTo add GUI support later, run:")
        print("  python install.py --gui")
