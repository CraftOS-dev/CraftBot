from agent_core import action


@action(
    name="run_powershell",
    description="Runs a PowerShell script with Windows PowerShell, capturing stdout, stderr, and exit code. Stdin is closed (EOF) by default. IMPORTANT: For long-running scripts that don't terminate (e.g., dev servers, watch processes), you MUST set background=true. Otherwise, the script will block the entire task until timeout and may not capture any output.",
    platforms=["windows"],
    default=True,
    action_sets=["core"],
    input_schema={
        "script": {
            "type": "string",
            "example": "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID, FreeSpace, Size",
            "description": "The PowerShell script to run, exactly as typed at a PowerShell prompt. Can span multiple lines.",
        },
        "timeout": {
            "type": "integer",
            "example": 600,
            "description": "Optional timeout (seconds). If exceeded, the process is terminated.",
        },
        "cwd": {
            "type": "string",
            "example": "C:\\\\Users\\\\me",
            "description": "Optional working directory for the script.",
        },
        "env": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "example": {"MY_VAR": "123"},
            "description": "Optional environment variable overrides.",
        },
        "background": {
            "type": "boolean",
            "example": False,
            "description": "Set to true for long-running processes (dev servers, watchers, etc.). The script will start in the background and return immediately with the process ID. Required for commands like 'npm run dev', 'npm start', 'python -m http.server'.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "stdout": {"type": "string", "example": "Script output text"},
        "stderr": {"type": "string", "example": ""},
        "return_code": {"type": "integer", "example": 0},
        "message": {"type": "string", "example": "Timed out after 30s."},
        "pid": {
            "type": "integer",
            "example": 12345,
            "description": "Process ID when running in background mode.",
        },
    },
    test_payload={
        "script": "Get-ChildItem C:\\\\Windows\\\\System32",
        "timeout": 600,
        "cwd": "C:\\\\Users\\\\me",
        "env": {"MY_VAR": "123"},
        "background": False,
        "simulated_mode": True,
    },
)
def powershell_exec_windows(input_data: dict) -> dict:
    import os
    import subprocess

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        # Return mock result for testing
        return {
            "status": "success",
            "stdout": "Simulated script output",
            "stderr": "",
            "return_code": 0,
            "message": "",
            "pid": None,
        }

    script = str(input_data.get("script", "")).strip()
    timeout_val = input_data.get("timeout")
    cwd = input_data.get("cwd")
    env_input = input_data.get("env") or {}
    background = input_data.get("background", False)

    timeout_seconds = float(timeout_val) if timeout_val is not None else 600.0

    if not script:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
            "message": "script is required.",
            "pid": None,
        }

    if cwd and not os.path.isdir(cwd):
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
            "message": "Working directory does not exist.",
            "pid": None,
        }

    # Same environment as run_shell: the resolved Node runtime leads PATH, so
    # bare `node` is the major the agent-app CLI needs (app/node_runtime.py).
    from app import node_runtime

    env = node_runtime.child_env()
    for k, v in env_input.items():
        env[str(k)] = str(v)

    # Windows PowerShell ships with every Windows install, so the dialect a
    # script is written for is the same on every machine.
    args = [
        "powershell.exe",
        "-NoLogo",
        "-NonInteractive",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    # Background mode: start process and return immediately
    if background:
        try:
            # Use CREATE_NEW_PROCESS_GROUP to detach from parent
            bg_flags = creation_flags | subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                cwd=cwd if cwd else None,
                env=env,
                creationflags=bg_flags,
            )
            return {
                "status": "background",
                "stdout": "",
                "stderr": "",
                "return_code": 0,
                "message": f"Process started in background with PID {process.pid}",
                "pid": process.pid,
            }
        except Exception as e:
            return {
                "status": "error",
                "stdout": "",
                "stderr": str(e),
                "return_code": -1,
                "message": str(e),
                "pid": None,
            }

    # Foreground mode with proper timeout handling
    try:
        # Register with the run-cancel registry so a user force-stop can
        # kill this process tree while communicate() blocks the pool thread.
        from agent_core.core.impl.action.cancellation import (
            register_process,
            unregister_process,
            was_killed,
        )

        run_session_id = input_data.get("_session_id") or ""

        # Use CREATE_NEW_PROCESS_GROUP so we can kill the entire process tree
        fg_flags = creation_flags | subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=cwd if cwd else None,
            env=env,
            text=True,
            errors="replace",
            creationflags=fg_flags,
        )
        register_process(run_session_id, process)

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            if was_killed(process):
                # A user stop killed it; the exit code says nothing about
                # the script itself.
                return {
                    "status": "error",
                    "stdout": stdout.strip() if stdout else "",
                    "stderr": stderr.strip() if stderr else "",
                    "return_code": -1,
                    "message": "Stopped by the user before the script finished.",
                    "pid": None,
                }
            return {
                "status": "success" if process.returncode == 0 else "error",
                "stdout": stdout.strip() if stdout else "",
                "stderr": stderr.strip() if stderr else "",
                "return_code": process.returncode,
                "message": "",
                "pid": None,
            }
        except subprocess.TimeoutExpired:
            # Kill the entire process tree on Windows using taskkill
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    creationflags=creation_flags,
                )
            except Exception:
                pass
            process.kill()
            stdout, stderr = process.communicate()
            return {
                "status": "error",
                "stdout": (stdout or "").strip(),
                "stderr": (stderr or "").strip(),
                "return_code": -1,
                "message": f"Timed out after {timeout_seconds}s.",
                "pid": None,
            }
        finally:
            unregister_process(run_session_id, process)
    except Exception as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "message": str(e),
            "pid": None,
        }
