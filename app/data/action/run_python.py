from agent_core import action


@action(
    name="run_python",
    description=(
        "Execute a Python code snippet in an isolated environment. Missing "
        "packages are auto-installed. Use print() to return results.\n\n"
        "PASSING PRIOR DATA: any additional parameters you supply alongside "
        "`code` are exposed in the script as Python variables of the same "
        "name. Use a `$ref` parameter to pull a slice of an earlier action's "
        "output without pasting it into `code`. Example:\n"
        "  parameters = {\n"
        '    "code": "for c in channels: print(c[\'name\'])",\n'
        '    "channels": {"$ref": "get_discord_channels#a3f1c2", '
        '"path": "result.result.all_channels"}\n'
        "  }\n"
        "The manager resolves the ref before the script runs; inside the "
        "script `channels` is already a Python list. Never paste prior tool "
        "output as a string literal into `code` — it triggers JSON "
        "truncation and parsing failures."
    ),
    execution_mode="sandboxed",
    mode="CLI",
    default=True,
    action_sets=["core"],
    input_schema={
        "code": {
            "type": "string",
            "example": "print('Hello World')",
            "description": (
                "Python code to execute. Use print() to output results. "
                "Reference any sibling parameters by name inside the code; "
                "they are pre-populated (including any `$ref`-resolved "
                "values) before execution."
            ),
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

    # Every sibling parameter (anything besides ``code`` and the ``_``-prefixed
    # plumbing keys the ActionManager injects) becomes a Python variable of
    # the same name inside the script. ``$ref`` markers are already resolved
    # by the manager, so the values seen here are real data.
    exec_globals = {"__builtins__": __builtins__}
    for k, v in input_data.items():
        if k == "code" or k.startswith("_"):
            continue
        if not isinstance(k, str) or not k.isidentifier():
            continue
        exec_globals[k] = v

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
                exec(code, exec_globals)
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
