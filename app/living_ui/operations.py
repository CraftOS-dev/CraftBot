"""
Living UI Operations Plane

App-declared verbs for Living UI projects. Each project may ship a
``config/operations.json`` manifest declaring named, typed operations —
"render_timeline", "make_move", "rebuild_site" — with an executor binding:

    {
      "operations": {
        "render": {
          "description": "Render the scene to PNG frames",
          "params": {
            "scene":  "string",
            "preset": {"enum": ["draft", "final"], "default": "draft"}
          },
          "executor": {"type": "shell", "cmd": "blender -b {scene} -o renders/ -a"},
          "mode": "job"
        }
      }
    }

Executor types:
    http  — {"type": "http", "method": "POST", "path": "/api/render", "target": "backend"}
            params become the JSON body (or query params for GET/DELETE).
    sql   — {"type": "sql", "sql": "UPDATE ... WHERE id = :id", "mode": "write"}
            params bind as named parameters; never string-substituted.
    shell — {"type": "shell", "cmd": "cmd with {param} placeholders",
             "cwd": "relative/dir", "timeout": 300, "env": {"K": "V"}}
            Substituted values are validated (no shell metacharacters) and
            quoted; the command runs caged in the project directory.

Modes:
    sync (default) — run to completion, return the result.
    job            — shell only: spawn detached with logged output, return a
                     job id; poll with `livingui <project> job <id>`.

Param specs: shorthand ("string", "int?", ...) or full objects
({"type": ..., "required": ..., "default": ..., "enum": [...]}).
Validation happens BEFORE anything executes, and errors name the exact
parameter — retry-friendly for the model.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

OPERATIONS_FILE = Path("config") / "operations.json"

# Namespaces owned by the built-in controller — manifests may not shadow them.
RESERVED_PREFIXES = ("data.", "sql.", "http.", "job.", "ui.", "app.")

_SHORTHAND_RE = re.compile(
    r"^(string|str|int|integer|number|float|bool|boolean|object|array|list)(\?)?$"
)

# Characters that could break a substituted value out of its quotes in a
# declared shell command (covers cmd.exe, PowerShell and POSIX shells).
_SHELL_UNSAFE_RE = re.compile(r"[\"'`;&|<>$%\n\r\x00]")

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}
_TYPE_ALIASES = {
    "str": "string",
    "integer": "int",
    "float": "number",
    "boolean": "bool",
    "list": "array",
}


class OperationError(Exception):
    """A user-facing operations plane failure."""


# ---------------------------------------------------------------------------
# Manifest loading & param validation
# ---------------------------------------------------------------------------


def load_operations(project: Any) -> Dict[str, Any]:
    """Load a project's declared operations. Missing manifest → {}."""
    if not project or not getattr(project, "path", None):
        return {}
    manifest_path = Path(project.path) / OPERATIONS_FILE
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise OperationError(f"config/operations.json is invalid JSON: {e}")
    ops = data.get("operations")
    if not isinstance(ops, dict):
        return {}
    valid: Dict[str, Any] = {}
    for name, op_def in ops.items():
        if not isinstance(op_def, dict):
            continue
        if any(name.startswith(p) for p in RESERVED_PREFIXES):
            logger.warning(
                f"[LIVING_UI:OPS] Ignoring op '{name}': reserved namespace prefix"
            )
            continue
        valid[name] = op_def
    return valid


def _normalize_param_spec(spec: Any) -> Dict[str, Any]:
    """Normalize shorthand ('string', 'int?') to the full object form."""
    if isinstance(spec, str):
        m = _SHORTHAND_RE.match(spec.strip())
        if not m:
            return {"type": "string", "required": True}
        base = _TYPE_ALIASES.get(m.group(1), m.group(1))
        return {"type": base, "required": m.group(2) != "?"}
    if isinstance(spec, dict):
        out = dict(spec)
        raw_type = str(out.get("type", "string")).lower()
        out["type"] = _TYPE_ALIASES.get(raw_type, raw_type)
        if "required" not in out:
            # A param with a default is implicitly optional
            out["required"] = "default" not in out
        return out
    return {"type": "string", "required": True}


def validate_and_fill_params(
    op_name: str, op_def: Dict[str, Any], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate params against the op's spec; apply defaults.

    Raises OperationError with a precise, retryable message on mismatch.
    """
    params = dict(params or {})
    specs = op_def.get("params") or {}
    if not isinstance(specs, dict):
        specs = {}

    errors: List[str] = []
    filled: Dict[str, Any] = {}

    for name, raw_spec in specs.items():
        spec = _normalize_param_spec(raw_spec)
        if name not in params or params[name] is None:
            if "default" in spec:
                filled[name] = spec["default"]
            elif spec.get("required", True):
                errors.append(f"missing required param '{name}' ({spec.get('type')})")
            continue
        value = params.pop(name)
        enum = spec.get("enum")
        if enum:
            if value not in enum:
                errors.append(f"param '{name}' must be one of {enum}, got {value!r}")
                continue
        else:
            check = _TYPE_CHECKS.get(spec.get("type", "string"))
            if check and not check(value):
                errors.append(
                    f"param '{name}' must be of type {spec.get('type')}, got {type(value).__name__}"
                )
                continue
        filled[name] = value

    unknown = [k for k in params.keys()]
    if unknown:
        errors.append(
            f"unknown param(s) {unknown}; declared params: {sorted(specs.keys()) or '(none)'}"
        )
    if errors:
        raise OperationError(f"Invalid params for op '{op_name}': " + "; ".join(errors))
    return filled


# ---------------------------------------------------------------------------
# Shell command templating (caged)
# ---------------------------------------------------------------------------


def render_shell_command(cmd_template: str, params: Dict[str, Any]) -> str:
    """Substitute {param} placeholders with validated, quoted values.

    Values may not contain shell metacharacters — the declared command is
    the cage; params can only fill blanks inside it, never extend it.
    """

    def substitute(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            raise OperationError(
                f"shell command references undeclared param '{{{key}}}'"
            )
        value = params[key]
        if isinstance(value, bool):
            value = "true" if value else "false"
        value = str(value)
        if _SHELL_UNSAFE_RE.search(value):
            raise OperationError(
                f"param '{key}' contains characters not allowed in shell "
                f"operations (quotes, $, %, ;, &, |, <, >, backtick, newline)"
            )
        return f'"{value}"' if (" " in value or value == "") else value

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", substitute, cmd_template)


def render_http_path(
    path_template: str, params: Dict[str, Any]
) -> "tuple[str, Dict[str, Any]]":
    """Substitute {param} placeholders in an http executor path.

    Returns (rendered_path, remaining_params) — consumed params are removed
    so they don't also land in the body/query. Values are URL-quoted and
    restricted to scalars.
    """
    import urllib.parse

    remaining = dict(params)

    def substitute(match: re.Match) -> str:
        key = match.group(1)
        if key not in remaining:
            raise OperationError(f"http path references undeclared param '{{{key}}}'")
        value = remaining.pop(key)
        if isinstance(value, bool):
            value = "true" if value else "false"
        if not isinstance(value, (str, int, float)):
            raise OperationError(
                f"param '{key}' must be a scalar to appear in a URL path"
            )
        return urllib.parse.quote(str(value), safe="")

    rendered = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", substitute, path_template)
    return rendered, remaining


def resolve_op_cwd(project_path: Path, executor: Dict[str, Any]) -> Path:
    """Resolve the executor cwd, refusing paths that escape the project."""
    cwd = project_path
    rel = executor.get("cwd")
    if rel:
        candidate = (project_path / rel).resolve()
        try:
            candidate.relative_to(project_path.resolve())
        except ValueError:
            raise OperationError(f"executor cwd '{rel}' escapes the project directory")
        cwd = candidate
    if not cwd.is_dir():
        raise OperationError(f"executor cwd does not exist: {cwd}")
    return cwd


# ---------------------------------------------------------------------------
# Sync shell execution
# ---------------------------------------------------------------------------


def run_shell_sync(
    command: str,
    cwd: Path,
    timeout: float = 300.0,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run a declared shell op to completion (sync mode)."""
    import os

    env = os.environ.copy()
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired:
        raise OperationError(
            f"Shell op timed out after {timeout}s. For long-running work, "
            f'declare the op with "mode": "job" and poll with job.status.'
        )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    return {
        "return_code": completed.returncode,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
    }
