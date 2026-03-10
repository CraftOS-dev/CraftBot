#!/usr/bin/env python3
import os
import sys
import subprocess
import platform
import time
import socket
import signal
import shutil # Needed for lsof check on Linux/macOS

# --- CONFIGURATION ---
# Path to the directory containing the docker-compose.yml file
VM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "app", "gui"))
# The main python command to run after setup (args added at runtime)
PYTHON_APP_BASE_CMD = [sys.executable, "-m", "app.main"]
# Service readiness check
READY_HOST = "localhost"
READY_PORT = 3001
MAX_WAIT_SECONDS = 60
# Port to clean up at the very end
CLEANUP_PORT = 7861
# ---------------------


# --- HELPER FUNCTIONS ---

def run_command(cmd: list, cwd: str = None, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Helper to run subprocess commands robustly."""
    try:
        use_shell = (platform.system() == "Windows")
        print(f"[*] Executing: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            shell=use_shell,
            stdout=subprocess.PIPE if capture else sys.stdout,
            stderr=subprocess.PIPE if capture else sys.stderr,
            text=True if capture else False
        )
        return result
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Command failed with exit code {e.returncode}: {' '.join(cmd)}")
        if capture:
            print(f"STDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")
        raise
    except FileNotFoundError:
         print(f"\n[ERROR] Command executable not found: {cmd[0]}")
         raise

def is_port_open(host: str, port: int, timeout: int = 1) -> bool:
    """Checks if a TCP port is open on a given host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def kill_process_on_port(port: int):
    """Finds and kills any process listening on the specified TCP port (Cross-platform)."""
    current_os = platform.system()
    port_str = str(port)
    print(f"[*] Checking for leftover processes on port {port}...")

    try:
        if current_os == "Windows":
            find_cmd = f"netstat -ano | findstr TCP | findstr :{port_str}"
            try:
                output = subprocess.check_output(find_cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
                pids_to_kill = set()
                for line in output.strip().split('\n'):
                    parts = line.strip().split()
                    if len(parts) >= 5 and parts[-2] == "LISTENING":
                        pid = parts[-1]
                        if pid.isdigit() and int(pid) > 0: pids_to_kill.add(pid)
                
                if not pids_to_kill:
                     print(f"[*] Port {port} is free.")
                     return

                for pid in pids_to_kill:
                    print(f"[!] Found stale process (PID: {pid}) on port {port}. Killing it...")
                    subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"[*] Port {port} cleared.")
                time.sleep(0.5)
            except subprocess.CalledProcessError:
                print(f"[*] Port {port} is free.")

        else: # Linux/macOS
            find_cmd = ["lsof", "-t", "-i", f"TCP:{port_str}"]
            if shutil.which("lsof"):
                try:
                    output = subprocess.check_output(find_cmd, text=True, stderr=subprocess.DEVNULL)
                    pids = [p for p in output.strip().split('\n') if p.isdigit() and int(p) > 0]
                    if not pids:
                        print(f"[*] Port {port} is free.")
                        return
                    for pid in pids:
                        print(f"[!] Found stale process (PID: {pid}) on port {port}. Killing it...")
                        subprocess.run(["kill", "-9", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"[*] Port {port} cleared.")
                    time.sleep(0.5)
                except subprocess.CalledProcessError:
                    print(f"[*] Port {port} is free.")
            else:
                 print(f"[!] Warning: 'lsof' not found. Cannot automatically clean port {port}.")

    except Exception as e:
        print(f"[!] Warning: Failed to clean up port {port}: {e}")

# --- MAIN LOGIC ---

def main():
    # === IGNORE CTRL+C ===
    # Tell this Python wrapper script to completely ignore SIGINT (Ctrl+C).
    # It will not raise KeyboardInterrupt. It will just keep doing what it's doing.
    # The child process will still receive the signal from the terminal driver.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # ------------------------------

    # Check if GUI mode is enabled
    gui_mode_enabled = os.getenv("GUI_MODE_ENABLED", "False").lower() == "true"
    docker_started = False

    print("--- Starting Launch Sequence ---")
    final_exit_code = 0

    # === TRY BLOCK: Setup and Run ===
    try:
        # 1. Start Docker VM (only if GUI mode is enabled)
        if gui_mode_enabled:
            print("\n[1/3] Launching VM Docker containers in background...")
            if not os.path.isdir(VM_DIR):
                 print(f"[ERROR] Docker directory not found: {VM_DIR}")
                 sys.exit(1)
            run_command(["docker", "compose", "up", "-d"], cwd=VM_DIR)
            docker_started = True

            # 2. Wait Loop
            print(f"\n[2/3] Waiting for VM service to be ready on port {READY_PORT}...")
            waited = 0
            while not is_port_open(READY_HOST, READY_PORT):
                if waited >= MAX_WAIT_SECONDS:
                    print(f"\n[ERROR] Timed out waiting for VM port {READY_PORT}.")
                    raise TimeoutError(f"Service on port {READY_PORT} did not become ready.")
                print(".", end="", flush=True)
                time.sleep(1)
                waited += 1
            print(f"\n[OK] VM Service is reachable after {waited}s!")

            # 3. Start Python Agent
            print(f"\n[3/3] Launching Python Agent...")
        else:
            print("\n[1/1] Launching Python Agent (CLI Mode)...")

        print("--------------------------------")
        print("Type '/exit' or use your defined quit hotkey to stop.")
        print("Ctrl+C is handled by the app logic (ignored by wrapper).")
        print("--------------------------------")

        # Run the main Python app in the foreground.
        # This call BLOCKS until the app exits.
        # Because we are ignoring signals, this wrapper will just sit here
        # until the child process decides to exit on its own.
        # Pass through command-line arguments (e.g., --cli, --provider)
        python_app_cmd = PYTHON_APP_BASE_CMD + sys.argv[1:]
        result = subprocess.run(
            python_app_cmd,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=False # We handle exit code manually
        )
        final_exit_code = result.returncode
        print(f"\n[i] Agent exited with code: {final_exit_code}")

    # Note: KeyboardInterrupt except block removed as it will never be caught.

    except (subprocess.CalledProcessError, TimeoutError, FileNotFoundError) as e:
        print(f"\n[!] Launch sequence aborted due to error.")
        final_exit_code = 1
        
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred: {e}")
        final_exit_code = 1


    # === FINALLY BLOCK: Guaranteed Cleanup ===
    # This block runs only when the 'try' block finishes naturally or hits a non-signal error.
    finally:
        print(f"\n\n--- Cleanup Initiated (Exit Status: {final_exit_code}) ---")
        
        # 1. Stop Docker containers (only if started)
        if docker_started:
            print("[*] Stopping Docker VM containers...")
            try:
                run_command(["docker", "compose", "down"], cwd=VM_DIR, check=False)
            except Exception as e:
                 print(f"[!] Warning: Error during docker shutdown: {e}")

            # 2. Clean up ports
            kill_process_on_port(CLEANUP_PORT)
        else:
            print("[*] Skipping Docker cleanup (not started in CLI mode).")

        print("Shutdown complete.")
        sys.exit(final_exit_code)

if __name__ == "__main__":
    main()