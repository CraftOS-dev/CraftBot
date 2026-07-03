from agent_core import action


@action(
    name="run_shell",
    description="Executes a shell command using the appropriate OS shell, capturing stdout, stderr, and exit code. Stdin is closed (EOF) by default. IMPORTANT: For long-running commands that don't terminate (e.g., 'npm run dev', 'npm start', 'python -m http.server', 'flask run', watch processes, dev servers), you MUST set background=true. Otherwise, the command will block the entire task until timeout and may not capture any output.",
    platforms=["linux"],
    default=True,
    action_sets=["core"],
    input_schema={
        "command": {
            "type": "string",
            "example": "dir C:\\\\Windows\\\\System32",
            "description": "The shell command to execute.",
        },
        "shell": {
            "type": "string",
            "example": "auto",
            "description": "Shell to use. Windows: 'cmd' (default), 'powershell', or 'pwsh' — bash/zsh are NOT available, and an unsupported value returns an error. macOS: 'bash' (default) or 'zsh'. Linux: ignored (runs via the system shell).",
        },
        "timeout": {
            "type": "integer",
            "example": 600,
            "description": "Optional timeout (seconds). If exceeded, the process is terminated.",
        },
        "cwd": {
            "type": "string",
            "example": "/home/user",
            "description": "Optional working directory for the command.",
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
            "description": "Set to true for long-running processes (dev servers, watchers, etc.). The command will start in the background and return immediately with the process ID. Required for commands like 'npm run dev', 'npm start', 'python -m http.server'.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "stdout": {"type": "string", "example": "Command output text"},
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
        "command": "dir C:\\\\Windows\\\\System32",
        "shell": "auto",
        "timeout": 600,
        "cwd": "/home/user",
        "env": {"MY_VAR": "123"},
        "background": False,
        "simulated_mode": True,
    },
)
def shell_exec(input_data: dict) -> dict:
    import os
    import subprocess
    import signal
    import time

    simulated_mode = input_data.get("simulated_mode", False)

    command = str(input_data.get("command", "")).strip()
    timeout_val = input_data.get("timeout")
    cwd = input_data.get("cwd")
    env_input = input_data.get("env") or {}
    background = input_data.get("background", False)

    if simulated_mode:
        # Return mock result for testing
        return {
            "status": "success",
            "stdout": "Simulated command output",
            "stderr": "",
            "return_code": 0,
            "message": "",
            "pid": None,
        }

    timeout_seconds = float(timeout_val) if timeout_val is not None else 600.0

    if not command:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
            "message": "command is required.",
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

    env = os.environ.copy()
    for k, v in env_input.items():
        env[str(k)] = str(v)

    # Background mode: start process and return immediately
    if background:
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                cwd=cwd if cwd else None,
                env=env,
                start_new_session=True,  # Detach from parent process group
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
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=cwd if cwd else None,
            env=env,
            text=True,
            errors="replace",
            start_new_session=True,  # Create new process group for proper cleanup
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            return {
                "status": "success" if process.returncode == 0 else "error",
                "stdout": stdout.strip() if stdout else "",
                "stderr": stderr.strip() if stderr else "",
                "return_code": process.returncode,
                "message": "",
                "pid": None,
            }
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            try:
                os.killpg(process.pid, signal.SIGTERM)
                time.sleep(0.5)
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
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
    except Exception as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "message": str(e),
            "pid": None,
        }


@action(
    name="run_shell",
    description="Executes a shell command using the appropriate OS shell, capturing stdout, stderr, and exit code. Stdin is closed (EOF) by default. IMPORTANT: For long-running commands that don't terminate (e.g., 'npm run dev', 'npm start', 'python -m http.server', 'flask run', watch processes, dev servers), you MUST set background=true. Otherwise, the command will block the entire task until timeout and may not capture any output.",
    platforms=["windows"],
    default=True,
    action_sets=["core"],
    input_schema={
        "command": {
            "type": "string",
            "example": "dir C:\\\\Windows\\\\System32",
            "description": "The shell command to execute.",
        },
        "shell": {
            "type": "string",
            "example": "auto",
            "description": "Shell to use. Windows: 'cmd' (default), 'powershell', or 'pwsh' — bash/zsh are NOT available, and an unsupported value returns an error. macOS: 'bash' (default) or 'zsh'. Linux: ignored (runs via the system shell).",
        },
        "timeout": {
            "type": "integer",
            "example": 600,
            "description": "Optional timeout (seconds). If exceeded, the process is terminated.",
        },
        "cwd": {
            "type": "string",
            "example": "/home/user",
            "description": "Optional working directory for the command.",
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
            "description": "Set to true for long-running processes (dev servers, watchers, etc.). The command will start in the background and return immediately with the process ID. Required for commands like 'npm run dev', 'npm start', 'python -m http.server'.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "stdout": {"type": "string", "example": "Command output text"},
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
        "command": "dir C:\\\\Windows\\\\System32",
        "shell": "auto",
        "timeout": 600,
        "cwd": "/home/user",
        "env": {"MY_VAR": "123"},
        "background": False,
        "simulated_mode": True,
    },
)
def shell_exec_windows(input_data: dict) -> dict:
    import os
    import subprocess

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        # Return mock result for testing
        return {
            "status": "success",
            "stdout": "Simulated command output",
            "stderr": "",
            "return_code": 0,
            "message": "",
            "pid": None,
        }

    command = str(input_data.get("command", "")).strip()
    shell_choice = str(input_data.get("shell", "cmd")).strip().lower()
    if shell_choice in ("", "auto"):
        shell_choice = "cmd"
    if shell_choice not in ("cmd", "powershell", "pwsh"):
        # Previously any unsupported value (e.g. "bash", "sh", "zsh") was
        # silently coerced to cmd, so a bash heredoc would run under cmd and
        # fail with a cryptic "<< was unexpected at this time." Return an
        # explicit error instead so the caller knows its shell choice was
        # rejected and why.
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
            "message": (
                f"Shell '{shell_choice}' is not available on Windows. "
                "Supported shells: cmd, powershell, pwsh. "
                "bash/zsh/sh syntax (e.g. heredocs) will NOT run here — "
                "use PowerShell for scripting, or write files via a file action "
                "rather than shell redirection."
            ),
            "pid": None,
        }
    timeout_val = input_data.get("timeout")
    cwd = input_data.get("cwd")
    env_input = input_data.get("env") or {}
    background = input_data.get("background", False)

    timeout_seconds = float(timeout_val) if timeout_val is not None else 600.0

    if not command:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
            "message": "command is required.",
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

    env = os.environ.copy()
    for k, v in env_input.items():
        env[str(k)] = str(v)

    if shell_choice == "powershell":
        args = [
            "powershell.exe",
            "-NoLogo",
            "-NonInteractive",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ]
    elif shell_choice == "pwsh":
        args = [
            "pwsh.exe",
            "-NoLogo",
            "-NonInteractive",
            "-NoProfile",
            "-Command",
            command,
        ]
    else:
        # Use /d and /s to ensure quoted commands (e.g., paths with spaces) are handled consistently.
        args = ["cmd.exe", "/d", "/s", "/c", command]

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

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
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
    except Exception as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "message": str(e),
            "pid": None,
        }


@action(
    name="run_shell",
    description="Executes a shell command using the appropriate OS shell, capturing stdout, stderr, and exit code. Stdin is closed (EOF) by default. IMPORTANT: For long-running commands that don't terminate (e.g., 'npm run dev', 'npm start', 'python -m http.server', 'flask run', watch processes, dev servers), you MUST set background=true. Otherwise, the command will block the entire task until timeout and may not capture any output.",
    platforms=["darwin"],
    default=True,
    action_sets=["core"],
    input_schema={
        "command": {
            "type": "string",
            "example": "dir C:\\\\Windows\\\\System32",
            "description": "The shell command to execute.",
        },
        "shell": {
            "type": "string",
            "example": "auto",
            "description": "Shell to use. Windows: 'cmd' (default), 'powershell', or 'pwsh' — bash/zsh are NOT available, and an unsupported value returns an error. macOS: 'bash' (default) or 'zsh'. Linux: ignored (runs via the system shell).",
        },
        "timeout": {
            "type": "integer",
            "example": 600,
            "description": "Optional timeout (seconds). If exceeded, the process is terminated.",
        },
        "cwd": {
            "type": "string",
            "example": "/home/user",
            "description": "Optional working directory for the command.",
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
            "description": "Set to true for long-running processes (dev servers, watchers, etc.). The command will start in the background and return immediately with the process ID. Required for commands like 'npm run dev', 'npm start', 'python -m http.server'.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "stdout": {"type": "string", "example": "Command output text"},
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
        "command": "dir C:\\\\Windows\\\\System32",
        "shell": "auto",
        "timeout": 600,
        "cwd": "/home/user",
        "env": {"MY_VAR": "123"},
        "background": False,
        "simulated_mode": True,
    },
)
def shell_exec_darwin(input_data: dict) -> dict:
    import os
    import subprocess
    import signal
    import time

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        # Return mock result for testing
        return {
            "status": "success",
            "stdout": "Simulated command output",
            "stderr": "",
            "return_code": 0,
            "message": "",
            "pid": None,
        }

    command = str(input_data.get("command", "")).strip()
    shell_choice = str(input_data.get("shell", "bash")).strip().lower()
    timeout_val = input_data.get("timeout")
    cwd = input_data.get("cwd")
    env_input = input_data.get("env") or {}
    background = input_data.get("background", False)

    timeout_seconds = float(timeout_val) if timeout_val is not None else 600.0

    if not command:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
            "message": "command is required.",
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

    env = os.environ.copy()
    for k, v in env_input.items():
        env[str(k)] = str(v)

    args = (
        ["/bin/zsh", "-c", command]
        if shell_choice == "zsh"
        else ["/bin/bash", "-c", command]
    )

    # Background mode: start process and return immediately
    if background:
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                cwd=cwd if cwd else None,
                env=env,
                start_new_session=True,  # Detach from parent process group
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
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=cwd if cwd else None,
            env=env,
            text=True,
            errors="replace",
            start_new_session=True,  # Create new process group for proper cleanup
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            return {
                "status": "success" if process.returncode == 0 else "error",
                "stdout": stdout.strip() if stdout else "",
                "stderr": stderr.strip() if stderr else "",
                "return_code": process.returncode,
                "message": "",
                "pid": None,
            }
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            try:
                os.killpg(process.pid, signal.SIGTERM)
                time.sleep(0.5)
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
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
    except Exception as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "message": str(e),
            "pid": None,
        }
