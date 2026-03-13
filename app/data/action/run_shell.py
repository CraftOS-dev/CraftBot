from agent_core import action

@action(
        name="run_shell",
        description="Executes a shell command using the appropriate OS shell, capturing stdout, stderr, and exit code. Stdin is closed (EOF) by default and no input can be provided by the agent when prompted by shell.",
        platforms=["linux"],
        default=True,
        action_sets=["core"],
        input_schema={
                "command": {
                        "type": "string",
                        "example": "dir C:\\\\Windows\\\\System32",
                        "description": "The shell command to execute."
                },
                "shell": {
                        "type": "string",
                        "example": "auto",
                        "description": "Shell to use. Default is platform's native shell (cmd, bash, or zsh)."
                },
                "timeout": {
                        "type": "integer",
                        "example": 60,
                        "description": "Optional timeout (seconds). If exceeded, the process is terminated."
                },
                "cwd": {
                        "type": "string",
                        "example": "/home/user",
                        "description": "Optional working directory for the command."
                },
                "env": {
                        "type": "object",
                        "additionalProperties": {
                                "type": "string"
                        },
                        "example": {
                                "MY_VAR": "123"
                        },
                        "description": "Optional environment variable overrides."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success"
                },
                "stdout": {
                        "type": "string",
                        "example": "Command output text"
                },
                "stderr": {
                        "type": "string",
                        "example": ""
                },
                "return_code": {
                        "type": "integer",
                        "example": 0
                },
                "message": {
                        "type": "string",
                        "example": "Timed out after 30s."
                }
        },
        test_payload={
                "command": "dir C:\\\\Windows\\\\System32",
                "shell": "auto",
                "timeout": 60,
                "cwd": "/home/user",
                "env": {
                        "MY_VAR": "123"
                },
                "simulated_mode": True
        }
)
def shell_exec(input_data: dict) -> dict:
    import os, json, subprocess

    simulated_mode = input_data.get('simulated_mode', False)
    
    command = str(input_data.get('command', '')).strip()
    shell_choice = str(input_data.get('shell', 'auto')).strip().lower()
    timeout_val = input_data.get('timeout')
    cwd = input_data.get('cwd')
    env_input = input_data.get('env') or {}

    if simulated_mode:
        # Return mock result for testing
        return {
            'status': 'success',
            'stdout': 'Simulated command output',
            'stderr': '',
            'return_code': 0,
            'message': ''
        }

    timeout_seconds = float(timeout_val) if timeout_val is not None else 30.0

    if not command:
        return {'status': 'error', 'stdout': '', 'stderr': '', 'return_code': -1, 'message': 'command is required.'}

    if cwd and not os.path.isdir(cwd):
        return {'status': 'error', 'stdout': '', 'stderr': '', 'return_code': -1, 'message': 'Working directory does not exist.'}

    env = os.environ.copy()
    for k, v in env_input.items():
        env[str(k)] = str(v)

    run_kwargs = {
        'capture_output': True,
        'text': True,
        'errors': 'replace',
        'cwd': cwd if cwd else None,
        'env': env,
        'timeout': timeout_seconds,
        'stdin': subprocess.DEVNULL,
        'shell': True,
    }

    try:
        # Default: use system shell (sh)
        result = subprocess.run(
            command,
            **run_kwargs
        )
        return {
            'status': 'success' if result.returncode == 0 else 'error',
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'return_code': result.returncode,
            'message': ''
        }
    except subprocess.TimeoutExpired as e:
        return {'status': 'error', 'stdout': (e.stdout or '').strip(), 'stderr': (e.stderr or '').strip(), 'return_code': -1, 'message': f'Timed out after {timeout_seconds}s.'}
    except Exception as e:
        return {'status': 'error', 'stdout': '', 'stderr': str(e), 'return_code': -1, 'message': str(e)}

@action(
        name="run_shell",
        description="Executes a shell command using the appropriate OS shell, capturing stdout, stderr, and exit code. Stdin is closed (EOF) by default and no input can be provided by the agent when prompted by shell.",
        platforms=["windows"],
        default=True,
        action_sets=["core"],
        input_schema={
                "command": {
                        "type": "string",
                        "example": "dir C:\\\\Windows\\\\System32",
                        "description": "The shell command to execute."
                },
                "shell": {
                        "type": "string",
                        "example": "auto",
                        "description": "Shell to use. Default is platform's native shell (cmd, bash, or zsh)."
                },
                "timeout": {
                        "type": "integer",
                        "example": 60,
                        "description": "Optional timeout (seconds). If exceeded, the process is terminated."
                },
                "cwd": {
                        "type": "string",
                        "example": "/home/user",
                        "description": "Optional working directory for the command."
                },
                "env": {
                        "type": "object",
                        "additionalProperties": {
                                "type": "string"
                        },
                        "example": {
                                "MY_VAR": "123"
                        },
                        "description": "Optional environment variable overrides."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success"
                },
                "stdout": {
                        "type": "string",
                        "example": "Command output text"
                },
                "stderr": {
                        "type": "string",
                        "example": ""
                },
                "return_code": {
                        "type": "integer",
                        "example": 0
                },
                "message": {
                        "type": "string",
                        "example": "Timed out after 30s."
                }
        },
        test_payload={
                "command": "dir C:\\\\Windows\\\\System32",
                "shell": "auto",
                "timeout": 60,
                "cwd": "/home/user",
                "env": {
                        "MY_VAR": "123"
                },
                "simulated_mode": True
        }
)
def shell_exec_windows(input_data: dict) -> dict:
    import os, json, subprocess

    simulated_mode = input_data.get('simulated_mode', False)

    if simulated_mode:
        # Return mock result for testing
        return {
            'status': 'success',
            'stdout': 'Simulated command output',
            'stderr': '',
            'return_code': 0,
            'message': ''
        }

    command = str(input_data.get('command', '')).strip()
    shell_choice = str(input_data.get('shell', 'cmd')).strip().lower()
    if shell_choice == 'auto':
        shell_choice = 'cmd'
    shell_choice = shell_choice if shell_choice in ('cmd', 'powershell', 'pwsh') else 'cmd'
    timeout_val = input_data.get('timeout')
    cwd = input_data.get('cwd')
    env_input = input_data.get('env') or {}

    timeout_seconds = float(timeout_val) if timeout_val is not None else 30.0

    if not command:
        return {'status': 'error', 'stdout': '', 'stderr': '', 'return_code': -1, 'message': 'command is required.'}

    if cwd and not os.path.isdir(cwd):
        return {'status': 'error', 'stdout': '', 'stderr': '', 'return_code': -1, 'message': 'Working directory does not exist.'}

    env = os.environ.copy()
    for k, v in env_input.items():
        env[str(k)] = str(v)

    if shell_choice == 'powershell':
        args = ['powershell.exe', '-NoLogo', '-NonInteractive', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command]
    elif shell_choice == 'pwsh':
        args = ['pwsh.exe', '-NoLogo', '-NonInteractive', '-NoProfile', '-Command', command]
    else:
        # Use /d and /s to ensure quoted commands (e.g., paths with spaces) are handled consistently.
        args = ['cmd.exe', '/d', '/s', '/c', command]

    run_kwargs = {
        'capture_output': True,
        'text': True,
        'errors': 'replace',
        'cwd': cwd if cwd else None,
        'env': env,
        'timeout': timeout_seconds,
        'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        'stdin': subprocess.DEVNULL,
    }

    try:
        result = subprocess.run(
            args,
            **run_kwargs
        )
        return {
            'status': 'success' if result.returncode == 0 else 'error',
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'return_code': result.returncode,
            'message': ''
        }
    except subprocess.TimeoutExpired as e:
        return {'status': 'error', 'stdout': (e.stdout or '').strip(), 'stderr': (e.stderr or '').strip(), 'return_code': -1, 'message': f'Timed out after {timeout_seconds}s.'}
    except Exception as e:
        return {'status': 'error', 'stdout': '', 'stderr': str(e), 'return_code': -1, 'message': str(e)}

@action(
        name="run_shell",
        description="Executes a shell command using the appropriate OS shell, capturing stdout, stderr, and exit code. Stdin is closed (EOF) by default and no input can be provided by the agent when prompted by shell.",
        platforms=["darwin"],
        default=True,
        action_sets=["core"],
        input_schema={
                "command": {
                        "type": "string",
                        "example": "dir C:\\\\Windows\\\\System32",
                        "description": "The shell command to execute."
                },
                "shell": {
                        "type": "string",
                        "example": "auto",
                        "description": "Shell to use. Default is platform's native shell (cmd, bash, or zsh)."
                },
                "timeout": {
                        "type": "integer",
                        "example": 60,
                        "description": "Optional timeout (seconds). If exceeded, the process is terminated."
                },
                "cwd": {
                        "type": "string",
                        "example": "/home/user",
                        "description": "Optional working directory for the command."
                },
                "env": {
                        "type": "object",
                        "additionalProperties": {
                                "type": "string"
                        },
                        "example": {
                                "MY_VAR": "123"
                        },
                        "description": "Optional environment variable overrides."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success"
                },
                "stdout": {
                        "type": "string",
                        "example": "Command output text"
                },
                "stderr": {
                        "type": "string",
                        "example": ""
                },
                "return_code": {
                        "type": "integer",
                        "example": 0
                },
                "message": {
                        "type": "string",
                        "example": "Timed out after 30s."
                }
        },
        test_payload={
                "command": "dir C:\\\\Windows\\\\System32",
                "shell": "auto",
                "timeout": 60,
                "cwd": "/home/user",
                "env": {
                        "MY_VAR": "123"
                },
                "simulated_mode": True
        }
)
def shell_exec_darwin(input_data: dict) -> dict:
    import os, json, subprocess

    simulated_mode = input_data.get('simulated_mode', False)

    if simulated_mode:
        # Return mock result for testing
        return {
            'status': 'success',
            'stdout': 'Simulated command output',
            'stderr': '',
            'return_code': 0,
            'message': ''
        }

    command = str(input_data.get('command', '')).strip()
    shell_choice = str(input_data.get('shell', 'bash')).strip().lower()
    timeout_val = input_data.get('timeout')
    cwd = input_data.get('cwd')
    env_input = input_data.get('env') or {}

    timeout_seconds = float(timeout_val) if timeout_val is not None else 30.0

    if not command:
        return {'status': 'error', 'stdout': '', 'stderr': '', 'return_code': -1, 'message': 'command is required.'}

    if cwd and not os.path.isdir(cwd):
        return {'status': 'error', 'stdout': '', 'stderr': '', 'return_code': -1, 'message': 'Working directory does not exist.'}

    env = os.environ.copy()
    for k, v in env_input.items():
        env[str(k)] = str(v)

    args = ['/bin/zsh', '-c', command] if shell_choice == 'zsh' else ['/bin/bash', '-c', command]

    run_kwargs = {
        'capture_output': True,
        'text': True,
        'errors': 'replace',
        'cwd': cwd if cwd else None,
        'env': env,
        'timeout': timeout_seconds,
        'stdin': subprocess.DEVNULL,
    }

    try:
        result = subprocess.run(
            args,
            **run_kwargs
        )
        return {
            'status': 'success' if result.returncode == 0 else 'error',
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'return_code': result.returncode,
            'message': ''
        }
    except subprocess.TimeoutExpired as e:
        return {'status': 'error', 'stdout': (e.stdout or '').strip(), 'stderr': (e.stderr or '').strip(), 'return_code': -1, 'message': f'Timed out after {timeout_seconds}s.'}
    except Exception as e:
        return {'status': 'error', 'stdout': '', 'stderr': str(e), 'return_code': -1, 'message': str(e)}