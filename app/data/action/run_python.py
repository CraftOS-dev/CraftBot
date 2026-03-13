from agent_core import action

@action(
    name="run_python",
    description="This action takes a single Python code snippet as input and executes it in a fresh environment. Missing packages are automatically detected and installed when ImportError occurs. This action is intended for cases when the AI agent needs to create a one-off solution dynamically.",
    execution_mode="sandboxed",
    mode="CLI",
    default=True,
    action_sets=["core"],
    input_schema={
        "code": {
            "type": "string",
            "example": "import requests\nprint(requests.get('https://example.com').text)",
            "description": "The Python code snippet to execute. Missing packages will be automatically installed on ImportError. The input code MUST NOT have any malicious code, the code MUST BE SANDBOXED. The code must be production code with the highest level of quality. DO NOT give any placeholder code or fabricated data. You MUST NOT handle exception with system exit. The result of the code return to the agent can only be returned with 'print'."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the script ran without errors; otherwise 'error'."
        },
        "stdout": {
            "type": "string",
            "example": "Hello, World!",
            "description": "Captured standard output from the script execution."
        },
        "stderr": {
            "type": "string",
            "example": "Traceback (most recent call last): ...",
            "description": "Captured standard error from the script execution (empty if no error)."
        },
        "message": {
            "type": "string",
            "example": "Script executed successfully.",
            "description": "A short message indicating the result of the script execution. Only present if status is 'error'."
        }
    },
    requirement=["traceback"],
    test_payload={
        "code": "import subprocess, sys\nsubprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'requests'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\nimport requests\nprint(requests.get('https://example.com').text)",
        "simulated_mode": True
    }
)
def create_and_run_python_script(input_data: dict) -> dict:
    import json
    import sys
    import subprocess
    import io
    import traceback
    import re
    import importlib

    code_snippet = input_data.get("code", "")
    
    def _ensure_utf8_stdio() -> None:
        """Force stdout/stderr to UTF-8 so Unicode output doesn't break on Windows consoles."""
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name, None)
            if hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    return {
                        "status": "error",
                        "stdout": "",
                        "stderr": "",
                        "message": "The 'utf-8' not supported."
                    }

    _ensure_utf8_stdio()    

    if not code_snippet.strip():
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "message": "The 'code' field is required."
        }

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    def _install_package(pkg_name: str) -> bool:
        try:
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', '--quiet', pkg_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60
            )
            return True
        except Exception:
            return False

    def _extract_imports(code: str) -> set:
        imports = set()
        # Match: import module, import module as alias, from module import ...
        patterns = [
            r'^import\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)',
            r'^from\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s+import',
        ]
        for line in code.split('\n'):
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            for pattern in patterns:
                match = re.match(pattern, line)
                if match:
                    module = match.group(1).split('.')[0]  # Get top-level module
                    # Skip stdlib modules
                    if module not in ['json', 'sys', 'os', 'io', 'subprocess', 'traceback', 're', 'importlib', 
                                      'urllib', 'collections', 'datetime', 'time', 'pathlib', 'tempfile']:
                        imports.add(module)
        return imports

    try:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        # Pre-install packages detected from imports (optional optimization)
        # This helps but we'll also handle ImportError at runtime
        detected_imports = _extract_imports(code_snippet)
        for pkg in detected_imports:
            try:
                importlib.import_module(pkg)
            except ImportError:
                _install_package(pkg)

        exec_globals = {}
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                exec(code_snippet, exec_globals)
                break  # Success, exit retry loop
            except ModuleNotFoundError as e:
                # Extract module name from error message
                module_match = re.search(r"No module named ['\"]([^'\"]+)['\"]", str(e))
                if module_match:
                    missing_module = module_match.group(1).split('.')[0]  # Get top-level module
                    if retry_count < max_retries - 1:
                        # Try to install the missing module
                        if _install_package(missing_module):
                            retry_count += 1
                            continue  # Retry execution
                # If we can't install or max retries reached, raise the original error
                raise
            except Exception:
                # For non-ImportError exceptions, don't retry
                raise

        sys.stdout = original_stdout
        sys.stderr = original_stderr

        return {
            "status": "success",
            "stdout": stdout_capture.getvalue().strip(),
            "stderr": stderr_capture.getvalue().strip()
        }

    except Exception:
        sys.stdout = original_stdout
        sys.stderr = original_stderr

        return {
            "status": "error",
            "stdout": stdout_capture.getvalue().strip(),
            "stderr": stderr_capture.getvalue().strip(),
            "message": traceback.format_exc()
        }