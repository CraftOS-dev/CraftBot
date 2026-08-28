"""External operations manifest: validation + helpers.

Spec: docs/design/external-app-a2app-adapter.md. An EXTERNAL (foreign,
run-as-is) app declares its A2App verb surface in the project's
operations.json — the same file and grammar native apps use (see
living-ui/tools/src/commands/validate.ts validateOps), with one extension:
an external `http` op carries `executor.upstream`, the data-not-code
mapping that tells the proxy how to translate an invocation onto the app's
own API. The gate rule is inherited from the protocol: a mapping that does
not validate (or, at verify time, does not work) is rejected, not shipped.

Pure module — no I/O beyond the explicit load helper, so the proxy, the
verifier and the tests all share one set of rules.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OP_NAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
PARAM_TYPES = ("string", "number", "boolean")
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def op_route(name: str) -> str:
    """The proxy route an external op is invoked at — the protocol's
    `/api/ops/{name}` surface, dots-to-slashes like native hook routes
    (`items.clear-done` -> `/api/ops/items/clear-done`)."""
    return "/api/ops/" + name.replace(".", "/")


def _check_params(at: str, params: Any, problems: List[str]) -> None:
    if not isinstance(params, dict):
        problems.append(f"{at}: 'params' must be an object keyed by param name")
        return
    for pname, spec in params.items():
        pat = f"{at}.params.{pname}"
        if not isinstance(spec, dict):
            problems.append(f"{pat}: must be an object with a 'type'")
            continue
        ptype = spec.get("type")
        if ptype not in PARAM_TYPES:
            problems.append(
                f"{pat}: 'type' must be one of {'|'.join(PARAM_TYPES)} "
                "(operations.json param shape)"
            )
        if "enum" in spec and not isinstance(spec["enum"], list):
            problems.append(f"{pat}: 'enum' must be an array")
        if "required" in spec and not isinstance(spec["required"], bool):
            problems.append(f"{pat}: 'required' must be a boolean")


def _check_upstream(
    at: str, upstream: Any, declared_params: Dict[str, Any], problems: List[str]
) -> None:
    if not isinstance(upstream, dict):
        problems.append(
            f"{at}: external http op needs 'executor.upstream' — the mapping "
            "{method, path, body?} onto the app's OWN API"
        )
        return
    method = upstream.get("method")
    if method not in HTTP_METHODS:
        problems.append(
            f"{at}.upstream: 'method' must be one of {'|'.join(HTTP_METHODS)}"
        )
    path = upstream.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        problems.append(f"{at}.upstream: 'path' must be a string starting with '/'")
    else:
        for ph in PLACEHOLDER_RE.findall(path):
            if ph not in declared_params:
                problems.append(
                    f"{at}.upstream.path: placeholder {{{{{ph}}}}} names no "
                    "declared param"
                )
    body = upstream.get("body")
    if body is not None:
        if not isinstance(body, dict):
            problems.append(f"{at}.upstream: 'body' template must be an object")
        else:
            for v in body.values():
                if isinstance(v, str):
                    for ph in PLACEHOLDER_RE.findall(v):
                        if ph not in declared_params:
                            problems.append(
                                f"{at}.upstream.body: placeholder "
                                f"{{{{{ph}}}}} names no declared param"
                            )
    timeout = upstream.get("timeoutSeconds")
    if timeout is not None and not (
        isinstance(timeout, (int, float)) and 1 <= timeout <= 600
    ):
        problems.append(f"{at}.upstream: 'timeoutSeconds' must be 1-600")
    unknown = set(upstream) - {"method", "path", "body", "timeoutSeconds"}
    for key in sorted(unknown):
        problems.append(f"{at}.upstream: unknown key '{key}'")


def validate_external_manifest(manifest: Any) -> List[str]:
    """Structural validation of an EXTERNAL project's operations.json.
    Returns a list of problems (empty = valid). Mirrors the native gate's
    rules (name grammar, unique names, description, typed params) and adds
    the external executor contract: type 'http', path pinned to the op's
    /api/ops/ route (so every client invokes through the guarded surface),
    plus the upstream mapping."""
    if not isinstance(manifest, dict):
        return ["operations.json must be a JSON object"]
    problems: List[str] = []
    if manifest.get("opsVersion") != 1:
        problems.append("opsVersion must be 1")
    ops = manifest.get("operations")
    if not isinstance(ops, list):
        problems.append("operations must be an array")
        return problems

    seen = set()
    for op in ops:
        if not isinstance(op, dict):
            problems.append("operations[]: each entry must be an object")
            continue
        name = op.get("name")
        at = f"operations[{name!r}]"
        if not isinstance(name, str) or not OP_NAME_RE.match(name):
            problems.append(f"invalid op name: {name!r}")
            continue
        if name in seen:
            problems.append(f"duplicate op name: {name}")
        seen.add(name)
        if not isinstance(op.get("description"), str) or not op["description"]:
            problems.append(f"{at}: description required")
        for flag in ("destructive", "system"):
            if flag in op and not isinstance(op[flag], bool):
                problems.append(f"{at}: '{flag}' must be a boolean")
        declared_params = op.get("params") or {}
        if "params" in op:
            _check_params(at, op["params"], problems)
            if not isinstance(declared_params, dict):
                declared_params = {}

        executor = op.get("executor")
        if not isinstance(executor, dict):
            problems.append(f"{at}: 'executor' object required")
            continue
        etype = executor.get("type")
        if etype != "http":
            problems.append(
                f"{at}: executor.type must be 'http' — 'crud' and 'job' are "
                "not supported for external apps yet"
            )
            continue
        if executor.get("method") not in HTTP_METHODS:
            problems.append(
                f"{at}: executor.method must be one of {'|'.join(HTTP_METHODS)}"
            )
        expected = op_route(name)
        if executor.get("path") != expected:
            problems.append(
                f"{at}: executor.path must be '{expected}' (the guarded "
                "/api/ops/ surface — the app's own endpoint belongs in "
                "executor.upstream.path)"
            )
        _check_upstream(at, executor.get("upstream"), declared_params, problems)
    return problems


def load_external_manifest(project_dir: Path) -> Tuple[Dict[str, Any], List[str]]:
    """Read + validate <project>/operations.json. Returns (manifest, problems);
    an unreadable or unparseable file returns ({}, [reason])."""
    path = Path(project_dir) / "operations.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        return {}, [f"operations.json unreadable: {e}"]
    try:
        manifest = json.loads(raw)
    except Exception as e:
        return {}, [f"operations.json is not valid JSON: {e}"]
    return manifest, validate_external_manifest(manifest)


def synthesize_params(op: Dict[str, Any]) -> Dict[str, Any]:
    """Sample values for live verification: declared defaults win; otherwise
    a per-type stand-in (enum -> first value). Optional params without a
    default are left out — the mapping must work with the minimal call."""
    out: Dict[str, Any] = {}
    for pname, spec in (op.get("params") or {}).items():
        if not isinstance(spec, dict):
            continue
        if "default" in spec:
            out[pname] = spec["default"]
        elif spec.get("required") is True:
            enum = spec.get("enum")
            if isinstance(enum, list) and enum:
                out[pname] = enum[0]
            elif spec.get("type") == "number":
                out[pname] = 1
            elif spec.get("type") == "boolean":
                out[pname] = False
            else:
                out[pname] = "a2app verify"
    return out
