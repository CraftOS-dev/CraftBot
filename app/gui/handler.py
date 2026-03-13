import subprocess
import json
import time
import io
from typing import Optional, Tuple, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.gui.gui_module import GUIModule
    
from app.state.agent_state import STATE

# Adjust import path as needed for your project structure
try:
    from app.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger("GUIHandler")
    logging.basicConfig(level=logging.DEBUG)

class GUIHandler:
    """
    Static handler for interacting with VM/Container GUIs via agent injection.
    Supports retrieving screenshots (bytes) and executing actions (dict).
    """

    # Class attribute that can be set externally to avoid circular dependency
    gui_module: Optional["GUIModule"] = None

    # Default container name (can be overridden per instance)
    TARGET_CONTAINER = "simple-agent-desktop"

    # Name of the Python packages required for Linux screen capture
    _LINUX_REQUIRED_PKG = "mss Pillow"
    
    # Magic exit code used by Linux screenshot payload to indicate missing package
    _EXIT_CODE_MISSING_PACKAGE = 10
    
    # PNG file signature (first 4 bytes of a PNG file)
    _PNG_SIGNATURE = b'\x89PNG'

    # --- Linux Screenshot Payload (Python) ---
    _LINUX_SCREENSHOT_PAYLOAD = """
import sys, io, os
if "DISPLAY" not in os.environ: os.environ["DISPLAY"] = ":1"
try:
    import mss
    from PIL import Image
except ImportError:
    sys.exit(10)  # Exit code 10 indicates missing package (handled by handler)
try:
    with mss.mss() as sct:
        # Capture the full virtual desktop (monitor 0 is the entire virtual screen)
        mon = sct.monitors[0]
        shot = sct.grab(mon)
        img = Image.frombytes('RGB', shot.size, shot.rgb)
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        sys.stdout.buffer.write(img_bytes.getvalue())
        sys.stdout.flush()
except Exception as e:
    sys.stderr.write(f"AGENT_ERROR: {e}")
    sys.exit(1)
"""

    # --- Windows Screenshot Payload (PowerShell) ---
    _WINDOWS_SCREENSHOT_PAYLOAD = r"""
try {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    Add-Type -AssemblyName System.Drawing | Out-Null
    # Get all screens to calculate the full virtual desktop bounds
    $screens = [System.Windows.Forms.Screen]::AllScreens
    $left = ($screens | Measure-Object -Property Bounds.Left -Minimum).Minimum
    $top = ($screens | Measure-Object -Property Bounds.Top -Minimum).Minimum
    $right = ($screens | Measure-Object -Property Bounds.Right -Maximum).Maximum
    $bottom = ($screens | Measure-Object -Property Bounds.Bottom -Maximum).Maximum
    $width = $right - $left
    $height = $bottom - $top
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    # Copy from the top-left of the virtual desktop
    $graphics.CopyFromScreen($left, $top, 0, 0, $bitmap.Size)
    $ms = New-Object System.IO.MemoryStream
    $bitmap.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    [Console]::OpenStandardOutput().Write($ms.ToArray(), 0, $ms.Length)
} catch {
    $host.ui.WriteErrorLine("AGENT_ERROR: " + $_.Exception.Message)
    exit 1
}
"""

    # ==========================
    # Public API
    # ==========================

    @classmethod
    def get_screen_state(cls, container_id: str, debug: bool = False) -> bytes:
        """
        Injects an agent script into the specified Docker container to take
        a screenshot and streams the raw PNG bytes back with a 10x10 pixel grid overlay.
        """
        logger.debug(f"[GUIHandler] Initiating screen capture for '{container_id}' (debug={debug})...")
        os_type = cls._detect_os(container_id)

        if os_type == "linux":
            img_bytes = cls._get_linux_screen_with_auto_install(container_id)
        elif os_type == "windows":
            img_bytes = cls._get_windows_screen(container_id)
        else:
            raise RuntimeError(f"Could not determine OS type for container '{container_id}'")

        if debug:
            try:
                timestamp = int(time.time())
                safe_container_id = container_id.replace("/", "_")
                debug_path = f"/tmp/{safe_container_id}_{timestamp}.png"
                with open(debug_path, "wb") as f:
                    f.write(img_bytes)
                logger.debug(f"[GUIHandler] Saved debug screenshot to '{debug_path}'")
            except Exception as e:
                logger.error(f"[GUIHandler] Failed to save debug screenshot: {e}")

        return img_bytes

    @classmethod
    def execute_action(cls, container_id: str, action_code: str, input_data: dict, mode: str) -> Dict[str, Any]:
        """
        Executes an action inside the container.
        Returns a dictionary parsed from the action's JSON stdout.
        """
        logger.debug(f"[GUIHandler] Executing action on container '{container_id}'...")
        if mode == "GUI" and not STATE.gui_mode:
            return {
                "status": "error",
                "message": f"{mode} mode is not enabled",
            }

        os_type = cls._detect_os(container_id)
        
        # We wrap the raw action code in a script that handles data injection,
        # execution, and JSON serialization of results.
        wrapper_script = cls._generate_python_action_wrapper(action_code, input_data)
        
        if os_type == "linux":
            # Assume 'python3' is available on Linux containers
            python_executable = ["python3"]
        elif os_type == "windows":
            # Assume 'python' is in the PATH on Windows containers. adjust if needed.
            python_executable = ["python"]
        else:
            raise RuntimeError(f"Unknown OS Type: {os_type}")

        logger.debug(f"[GUIHandler] Running action via {python_executable[0]} on {os_type}...")

        # Set X11 environment for Linux containers so pyautogui/Xlib can
        # connect without an XauthError.  XAUTHORITY is pointed at a
        # path we ensure exists, and DISPLAY at the KasmVNC virtual display.
        x11_env = None
        if os_type == "linux":
            x11_env = {"DISPLAY": ":1", "XAUTHORITY": "/config/.Xauthority"}
            # Ensure .Xauthority file exists (touch is idempotent)
            cls._run_docker_exec(
                container_id,
                ["/bin/sh", "-c", "touch /config/.Xauthority"],
            )

        stdout, stderr, code = cls._run_docker_exec(
            container_id,
            python_executable,
            wrapper_script.encode('utf-8'),
            env=x11_env,
        )
        
        return cls._validate_action_output(stdout, stderr, code)

    # ==========================
    # Internal OS-Specific Logic (Screenshots)
    # ==========================

    @classmethod
    def _get_linux_screen_with_auto_install(cls, container_id: str) -> bytes:
        """Handles Linux capture lifecycle, including auto-installing Pillow."""
        logger.debug("[GUIHandler] Attempting Linux capture...")
        x11_env = {"DISPLAY": ":1", "XAUTHORITY": "/config/.Xauthority"}
        # Ensure .Xauthority exists
        cls._run_docker_exec(container_id, ["/bin/sh", "-c", "touch /config/.Xauthority"])
        stdout, stderr, code = cls._run_docker_exec(
            container_id,
            ["python3"],
            cls._LINUX_SCREENSHOT_PAYLOAD.encode(),
            env=x11_env,
        )

        if code == cls._EXIT_CODE_MISSING_PACKAGE:
            logger.debug(f"[GUIHandler] Missing package(s): '{cls._LINUX_REQUIRED_PKG}'. Installing...")
            # Install all required packages at once
            cls._install_linux_package(container_id, cls._LINUX_REQUIRED_PKG)
            logger.debug("[GUIHandler] Retrying capture after installation...")
            stdout, stderr, code = cls._run_docker_exec(
                container_id,
                ["python3"],
                cls._LINUX_SCREENSHOT_PAYLOAD.encode(),
                env=x11_env,
            )

        return cls._validate_screenshot_output(stdout, stderr, code)

    @classmethod
    def _get_windows_screen(cls, container_id: str) -> bytes:
        """Handles Windows capture lifecycle via PowerShell."""
        logger.debug("[GUIHandler] Attempting Windows capture via PowerShell...")
        ps_cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "-"]
        stdout, stderr, code = cls._run_docker_exec(
            container_id, 
            ps_cmd, 
            cls._WINDOWS_SCREENSHOT_PAYLOAD.encode()
        )
        return cls._validate_screenshot_output(stdout, stderr, code)

    # ==========================
    # Internal Helpers & Validators
    # ==========================

    @classmethod
    def _generate_python_action_wrapper(cls, action_code: str, input_data: dict) -> str:
        """
        Generates a complete Python script to run inside the container.
        It injects data, defines the user function, calls it, and prints result as JSON.
        """
        try:
            # 1. Serialize input_data safely
            input_data_literal = repr(input_data)
            # 2. Serialize the action_code string itself safely. 
            #    This ensures that things like '\n' remain as literal backslash-n 
            #    characters in the generated script's string, rather than becoming real newlines.
            action_code_literal = repr(action_code)
        except Exception as e:
             # Fail early if host-side serialization fails
             raise ValueError(f"Failed to serialize data on host: {e}")

        # This script runs INSIDE the container
        wrapper = f"""
import json
import inspect
import sys
import os
import traceback

# --- 0. Ensure X11 env is set for pyautogui / Xlib ---
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":1"
if "XAUTHORITY" not in os.environ:
    os.environ["XAUTHORITY"] = "/config/.Xauthority"

# --- 1. Inject Input Data ---
try:
    input_data = {input_data_literal}
except Exception as e:
    # Use repr(str(e)) to ensure the error message itself doesn't break the JSON syntax
    print(json.dumps({{"status": "error", "message": f"Data injection failed: {{repr(str(e))}}"}}))
    sys.exit(1)

# Prepare namespace
local_ns = {{'input_data': input_data, 'json': json, 'inspect': inspect, 'sys': sys, 'os': os, 'traceback': traceback}}
pre_exec_keys = set(local_ns.keys())

# --- 2. Define User Function ---
# We assign the safely escaped string literal to the variable.
user_code_str = {action_code_literal}

try:
    # Execute the function definition
    exec(user_code_str, local_ns)

    # --- 3. Find the newly defined function ---
    function_to_call = None
    for key, value in local_ns.items():
        # Ensure we don't pick up imports like 'json' or 'sys' as the action function
        if key not in pre_exec_keys and key != '__builtins__' and inspect.isfunction(value) and value.__module__ == local_ns.get('__name__', None):
            function_to_call = value
            break

    if function_to_call is None:
         print(json.dumps({{"status": "error", "message": "No function definition found in action code."}}))
         sys.exit(1)

    # --- 4. Call Function & Capture Result ---
    # The action function is expected to return a dictionary
    result_dict = function_to_call(input_data)

    # Basic validation that it returned a dict
    if not isinstance(result_dict, dict):
         result_dict = {{"status": "success", "stdout": str(result_dict), "stderr": "", "note": "Action did not return a dict, wrapped output."}}

    # --- 5. Print Result as JSON to stdout ---
    # Ensure the entire dict is serialized safely
    print(json.dumps(result_dict))

except Exception as e:
    # Catch unexpected errors during execution (like syntax errors in user code)
    tb = traceback.format_exc()
    # Use repr() for message and stderr content to ensure valid JSON even if they contain weird chars
    err_response = {{"status": "error", "message": f"Execution error: {{repr(str(e))}}", "stderr": tb}}
    print(json.dumps(err_response))
    sys.exit(1)
"""
        return wrapper

    @classmethod
    def _validate_screenshot_output(cls, stdout: bytes, stderr: bytes, code: int) -> bytes:
        """Validator specifically for raw PNG data."""
        if code != 0:
            err_msg = stderr.decode(errors='replace').strip()
            raise RuntimeError(f"Screenshot failed (Exit {code}). Stderr: {err_msg}")
        
        if not stdout:
             raise RuntimeError("Agent finished successfully but returned zero data bytes.")

        if not stdout.startswith(cls._PNG_SIGNATURE):
             raise RuntimeError("Data returned by agent is not valid PNG format.")

        logger.debug(f"[GUIHandler] Successfully retrieved {len(stdout)} bytes of image data.")
        return stdout

    @classmethod
    def _validate_action_output(cls, stdout: bytes, stderr: bytes, code: int) -> Dict[str, Any]:
        """Validator specifically for JSON action output."""
        stdout_str = stdout.decode(errors='replace').strip()
        stderr_str = stderr.decode(errors='replace').strip()

        # 1. Attempt to parse stdout as JSON
        try:
            result_dict = json.loads(stdout_str) if stdout_str else {}
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from container. Raw stdout: {stdout_str}")
            # Return a structured error dict even if JSON parsing failed
            return {
                "status": "error",
                "message": "Container output was not valid JSON.",
                "stdout": stdout_str,
                "stderr": stderr_str or f"Exit code: {code}",
                "returncode": code
            }

        # 2. If the container exited with an error code, ensure the dict indicates error.
        # The wrapper script usually handles this, but this is a fallback safety check.
        if code != 0:
            logger.warning(f"Action container exited with non-zero code {code}.")
            if not result_dict.get("status") == "error":
                 # Augment existing dict or create new one if it doesn't look like an error report
                 result_dict["status"] = "error"
                 result_dict["message"] = result_dict.get("message", f"Process exited with code {code}")
                 result_dict["stderr"] = (result_dict.get("stderr", "") + "\n" + stderr_str).strip()

        # 3. Ensure returncode is included in the final result
        result_dict["returncode"] = code
        return result_dict


    # ==========================
    # General Helpers
    # ==========================

    @classmethod
    def _install_linux_package(cls, container_id: str, pkg_name: str):
        """Runs pip install inside the Linux container. Can handle space-separated package names."""
        packages = pkg_name.split()  # Split space-separated packages
        logger.debug(f"[GUIHandler] Installing '{pkg_name}' in container '{container_id}'...")
        cmd = ["python3", "-m", "pip", "install", "--quiet"] + packages
        # Note: Using _run_docker_exec without stdin_data
        stdout, stderr, code = cls._run_docker_exec(container_id, cmd, stdin_data=None)
        
        if code != 0:
                err_msg = stderr.decode(errors='replace').strip() or stdout.decode(errors='replace').strip()
                raise RuntimeError(f"Failed to install '{pkg_name}'. Exit {code}. Error: {err_msg}")

    @classmethod
    def _run_docker_exec(cls, container_id: str, shell_cmd: list, stdin_data: Optional[bytes] = None, env: Optional[Dict[str, str]] = None) -> Tuple[bytes, bytes, int]:
        """Helper to run docker exec piping data in and out."""
        try:
            cmd = ["docker", "exec", "-i"]
            if env:
                for k, v in env.items():
                    cmd += ["-e", f"{k}={v}"]
            cmd += [container_id] + shell_cmd
            # logger.debug(f"Executing command: {' '.join(cmd)}") # Optional verbose logging
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_data else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(input=stdin_data)
            return stdout, stderr, process.returncode
        except FileNotFoundError:
             raise FileNotFoundError("The 'docker' command was not found on the host system.")

    @classmethod
    def _detect_os(cls, container_id: str) -> str:
        """Probes container to guess OS type."""
        # Try Linux
        _, _, code_linux = cls._run_docker_exec(container_id, ["/bin/sh", "-c", "uname"])
        if code_linux == 0: return "linux"
        
        # Try Windows
        _, _, code_win = cls._run_docker_exec(container_id, ["cmd.exe", "/c", "ver"])
        if code_win == 0: return "windows"
        
        # Fallback/Testing assumption (Remove in production if detection is robust)
        logger.warning(f"Could not detect OS for {container_id}, defaulting to Linux based on previous examples.")
        return "linux" 

# ==========================================
# Example Usage (Testing the fix)
# ==========================================
if __name__ == "__main__":
    # --- Test 1: Screenshot (should still work) ---
    try:
        print("\n--- Testing Screenshot ---")
        # Note: Ensure TARGET_CONTAINER is running and is the correct OS type for this test.
        screenshot_bytes = GUIHandler.get_screen_state(GUIHandler.TARGET_CONTAINER)
        print(f"Successfully got screenshot: {len(screenshot_bytes)} bytes.")
    except Exception as e:
        print(f"Screenshot failed: {e}")

    # --- Test 2: Action Execution (The fix) ---
    print("\n--- Testing Action Execution ---")
    
    # This is the raw code body from your example action
    sample_action_code = """
def mouse_double_click(input_data: dict) -> dict:
    import json, sys, subprocess, importlib
    pkg = 'pyautogui'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])
    import pyautogui
    x = input_data.get('x')
    y = input_data.get('y')
    try:
        pos_x, pos_y = (x, y) if x is not None and y is not None else pyautogui.position()
        pyautogui.doubleClick(x=pos_x, y=pos_y, button='left')
        return {'status': 'success', 'message': ''}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
"""
    
    sample_input = {"code": "print('Hello from inside the container action!')"}

    try:
        # Execute the action and get a dict back
        result_dict = GUIHandler.execute_action(
            GUIHandler.TARGET_CONTAINER, 
            sample_action_code, 
            sample_input
        )
        
        print("Action Execution Result (Dictionary):")
        print(json.dumps(result_dict, indent=2))
        
        if result_dict.get("status") == "success":
            print("\nSUCCESS: Action executed and returned a dict correctly.")
        else:
            print("\nFAILURE: Action executed but reported an error.")

    except Exception as e:
        print(f"\nFATAL ERROR during action execution: {e}")