from agent_core import action


@action(
    name="run_python",
    description="Execute a Python code snippet in an isolated environment. Missing packages are auto-installed. Use print() to return results.",
    execution_mode="sandboxed",
    mode="CLI",
    default=True,
    action_sets=["core"],
    input_schema={
        "code": {
            "type": "string",
            "example": "print('Hello World')",
            "description": "Python code to execute. Use print() to output results.",
        }
    },
    output_schema={
        "status": {"type": "string", "description": "'success' or 'error'"},
        "stdout": {"type": "string", "description": "Output from print() statements"},
        "stderr": {"type": "string", "description": "Error output (if any)"},
        "message": {
            "type": "string",
            "description": "Error message (only if status is 'error')",
        },
    },
    requirement=[],
    test_payload={"code": "print('test')", "simulated_mode": True},
)
def create_and_run_python_script(input_data: dict) -> dict:
    import sys
    import io
    import traceback
    import subprocess
    import re

    code = input_data.get("code", "").strip()

    if not code:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "",
            "message": "No code provided",
        }

    # Capture stdout/stderr
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr

    def install_package(pkg):
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", pkg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            return True
        except Exception:
            return False

    try:
        sys.stdout, sys.stderr = stdout_buf, stderr_buf

        # Simple exec with retry for missing modules
        for attempt in range(3):
            try:
                exec(code, {"__builtins__": __builtins__})
                break
            except ModuleNotFoundError as e:
                match = re.search(r"No module named ['\"]([^'\"]+)['\"]", str(e))
                if match and attempt < 2:
                    pkg = match.group(1).split(".")[0]
                    if install_package(pkg):
                        continue
                raise

        sys.stdout, sys.stderr = old_stdout, old_stderr
        return {
            "status": "success",
            "stdout": stdout_buf.getvalue().strip(),
            "stderr": stderr_buf.getvalue().strip(),
        }

    except Exception:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        return {
            "status": "error",
            "stdout": stdout_buf.getvalue().strip(),
            "stderr": stderr_buf.getvalue().strip(),
            "message": traceback.format_exc(),
        }
