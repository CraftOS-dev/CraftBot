"""
Operations manifest analyzer: generate and validate config/operations.json
from the backend's OpenAPI spec.

Everything in an op except its description is mechanically derivable —
FastAPI publishes exact paths, methods, param names/types/enums/defaults
(from the Pydantic schemas) and route docstrings (as summaries). Deriving
ops from the spec makes manifest correctness machine-guaranteed; the agent's
authoring job shrinks to curating descriptions. Used by:

- `livingui <project> ops-sync [--write]`  — generate/merge op skeletons
- `livingui <project> ops-check`           — validate + coverage lint
- the launch pipeline                      — structural errors block launch

Route classification:
- SYSTEM: template plumbing (/health, /api/state, /api/action, /api/logs,
  /api/ui-*, /api/items example) — never ops, never coverage gaps.
- CRUD: RESTful shapes covered by the CLI's built-in data commands
  (GET/POST /api/{res}, GET/PUT/PATCH/DELETE /api/{res}/{id},
  POST /api/{res}/bulk). POST on a single segment counts as CRUD-create
  only when a collection GET or /{id} sibling exists (so POST /api/search
  is a candidate, POST /api/boards is CRUD).
- CANDIDATE: everything else — verb segments (/move), computed reads
  (/stats, /dashboard), relationship paths — these should be declared ops
  or listed in the manifest's "ignore_routes".
"""

import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import operations

SYSTEM_PATHS = {
    "/health",
    "/api/logs",
    "/api/state",
    "/api/state/replace",
    "/api/action",
    "/api/ui-snapshot",
    "/api/ui-screenshot",
}
SYSTEM_PREFIXES = ("/api/items", "/api/files")

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

_TYPE_MAP = {
    "integer": "int",
    "number": "number",
    "boolean": "bool",
    "string": "string",
    "array": "array",
    "object": "object",
}


# Spec locations probed in order. FastAPI serves /openapi.json; the rest
# cover common conventions of imported third-party apps (Express/swagger,
# Spring, Rails/grape).
OPENAPI_CANDIDATE_PATHS = (
    "/openapi.json",
    "/swagger.json",
    "/api/openapi.json",
    "/api/swagger.json",
    "/v3/api-docs",
    "/api-docs",
)


def fetch_openapi(
    backend_url: str, timeout: float = 5.0, spec_url: str = ""
) -> Optional[Dict[str, Any]]:
    """Fetch an OpenAPI spec. None when unreachable.

    Probes the common spec locations on ``backend_url``; ``spec_url``
    (absolute) skips probing — for apps that serve their spec somewhere
    non-standard.
    """
    if spec_url:
        candidates = [spec_url]
    elif backend_url:
        candidates = [backend_url.rstrip("/") + p for p in OPENAPI_CANDIDATE_PATHS]
    else:
        return None
    for url in candidates:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                spec = json.loads(resp.read().decode("utf-8"))
            if isinstance(spec, dict) and isinstance(spec.get("paths"), dict):
                return spec
        except Exception:
            continue
    return None


def _resolve_ref(spec: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return spec.get("components", {}).get("schemas", {}).get(name, {})
    return schema


def _spec_type_to_param(
    spec: Dict[str, Any], schema: Dict[str, Any], required: bool
) -> Dict[str, Any]:
    """Convert an OpenAPI property schema to a manifest param spec."""
    schema = _resolve_ref(spec, schema)
    # Optional[T] arrives as anyOf: [T, null]
    if "anyOf" in schema:
        variants = [v for v in schema["anyOf"] if v.get("type") != "null"]
        if len(variants) < len(schema["anyOf"]):
            required = False
        schema = _resolve_ref(spec, variants[0]) if variants else {}
    out: Dict[str, Any] = {"type": _TYPE_MAP.get(schema.get("type", "string"), "string")}
    if "enum" in schema:
        out["enum"] = schema["enum"]
        out.pop("type", None)
    if "default" in schema:
        out["default"] = schema["default"]
    else:
        out["required"] = required
    description = schema.get("description") or schema.get("title")
    if description and str(description).lower() not in ("", "none"):
        out["description"] = str(description)
    return out


def _routes(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    routes = []
    for path, methods in (spec.get("paths") or {}).items():
        for method, meta in methods.items():
            if method.lower() not in HTTP_METHODS:
                continue
            routes.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "meta": meta or {},
                }
            )
    return routes


def _is_param_segment(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def classify_route(
    route: Dict[str, Any], all_paths: set
) -> str:
    """Return 'system' | 'crud' | 'candidate' for a route."""
    path, method = route["path"], route["method"]
    if path in SYSTEM_PATHS or any(path.startswith(p) for p in SYSTEM_PREFIXES):
        return "system"
    segments = [s for s in path.strip("/").split("/") if s]
    if not segments or segments[0] != "api":
        return "system"
    rest = segments[1:]

    # Engine-internal segments (e.g. /api/_meta/schema, /api/cards/_stats)
    # are infrastructure, not app verbs — never op candidates.
    if any(s.startswith("_") for s in rest):
        return "system"

    if len(rest) == 1 and not _is_param_segment(rest[0]):
        if method == "GET":
            # Collection GET is CRUD when an /{id} sibling exists, else a
            # computed read (e.g. GET /api/dashboard) — a candidate.
            has_item_sibling = any(
                p.startswith(f"/api/{rest[0]}/{{") for p in all_paths
            )
            return "crud" if has_item_sibling else "candidate"
        if method == "POST":
            # Create is CRUD only when it looks like a resource (collection
            # GET or /{id} sibling); POST /api/search|/api/stats are verbs.
            has_sibling = ("/api/" + rest[0]) in all_paths and any(
                r == "GET" for r in _methods_of(all_paths, "/api/" + rest[0])
            ) or any(p.startswith(f"/api/{rest[0]}/{{") for p in all_paths)
            return "crud" if has_sibling else "candidate"
        return "candidate"

    if len(rest) == 2 and _is_param_segment(rest[1]):
        if method in ("GET", "PUT", "PATCH", "DELETE"):
            return "crud"
        return "candidate"

    if len(rest) == 2 and rest[1] == "bulk" and method == "POST":
        return "crud"  # covered by the CLI's insert --file

    return "candidate"


# classify_route needs sibling METHOD lookups; we pass a path→methods map in
# practice. Kept simple: the analyzer builds `all_paths` as a set of paths
# and a parallel dict of methods.
_METHODS_BY_PATH: Dict[str, List[str]] = {}


def _methods_of(all_paths: set, path: str) -> List[str]:
    return _METHODS_BY_PATH.get(path, [])


def analyze_routes(spec: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Classify every route. Returns {system: [...], crud: [...], candidate: [...]}."""
    global _METHODS_BY_PATH
    routes = _routes(spec)
    all_paths = {r["path"] for r in routes}
    _METHODS_BY_PATH = {}
    for r in routes:
        _METHODS_BY_PATH.setdefault(r["path"], []).append(r["method"])
    buckets: Dict[str, List[Dict[str, Any]]] = {"system": [], "crud": [], "candidate": []}
    for route in routes:
        buckets[classify_route(route, all_paths)].append(route)
    return buckets


def _op_name_for(route: Dict[str, Any]) -> str:
    """Derive an op name — FastAPI operationIds embed the function name."""
    operation_id = route["meta"].get("operationId", "")
    if "_api_" in operation_id:
        name = operation_id.split("_api_")[0]
        if re.fullmatch(r"[a-z][a-z0-9_]*", name):
            return name
    # Fallback: verb-ish from path segments
    segments = [s for s in route["path"].strip("/").split("/") if not _is_param_segment(s)]
    segments = [s for s in segments if s != "api"]
    base = "_".join(segments) or "op"
    return f"{route['method'].lower()}_{base}"


def build_op_skeleton(
    spec: Dict[str, Any], route: Dict[str, Any]
) -> Tuple[str, Dict[str, Any]]:
    """Build a manifest op entry from a route, params exact from the schema."""
    meta = route["meta"]
    params: Dict[str, Any] = {}

    # Path + query parameters
    for parameter in meta.get("parameters", []) or []:
        name = parameter.get("name")
        if not name:
            continue
        params[name] = _spec_type_to_param(
            spec, parameter.get("schema", {}), parameter.get("required", False)
        )

    # JSON request body
    body_schema = (
        meta.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if body_schema:
        resolved = _resolve_ref(spec, body_schema)
        required_fields = set(resolved.get("required", []))
        for field, field_schema in (resolved.get("properties") or {}).items():
            params[field] = _spec_type_to_param(
                spec, field_schema, field in required_fields
            )

    # FastAPI puts the route docstring in `description` and auto-titles
    # `summary` from the function name — the docstring is the real content.
    docstring = (meta.get("description") or "").strip()
    first_line = docstring.splitlines()[0].strip() if docstring else ""
    description = first_line or (meta.get("summary") or "").strip()
    op = {
        "description": description or "TODO: describe when to use this",
        "params": params,
        "executor": {
            "type": "http",
            "method": route["method"],
            "path": route["path"],
        },
    }
    return _op_name_for(route), op


def generate_skeletons(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Generate op skeletons for every candidate route."""
    skeletons: Dict[str, Dict[str, Any]] = {}
    for route in analyze_routes(spec)["candidate"]:
        name, op = build_op_skeleton(spec, route)
        while name in skeletons:  # method collision on same fn name
            name = f"{name}_{route['method'].lower()}"
        skeletons[name] = op
    return skeletons


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def _load_manifest_raw(project_path: Path) -> Tuple[Optional[dict], Optional[str]]:
    manifest_path = Path(project_path) / operations.OPERATIONS_FILE
    if not manifest_path.exists():
        return None, None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, f"config/operations.json is invalid JSON: {e}"


def check_manifest(
    project_path: Path, spec: Optional[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """Validate the ops manifest. Returns findings:
    [{"level": "error"|"warning", "message": ..., "fix": ...}].

    Spec-dependent checks (dead routes, coverage) only run when a spec is
    provided (backend running); format checks always run.
    """
    findings: List[Dict[str, str]] = []

    raw, parse_error = _load_manifest_raw(project_path)
    if parse_error:
        return [{"level": "error", "message": parse_error, "fix": "fix the JSON syntax"}]
    if raw is None:
        if spec and analyze_routes(spec)["candidate"]:
            findings.append(
                {
                    "level": "warning",
                    "message": "no config/operations.json — the app has "
                    "non-CRUD routes but declares no operations",
                    "fix": "run: livingui <project> ops-sync --write",
                }
            )
        return findings

    ops = raw.get("operations") or {}
    ignore_routes = set(raw.get("ignore_routes") or [])

    spec_routes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if spec:
        for route in _routes(spec):
            spec_routes[(route["method"], route["path"])] = route

    for name, op_def in ops.items():
        if not isinstance(op_def, dict):
            findings.append(
                {"level": "error", "message": f"op '{name}' is not an object", "fix": "make it an object"}
            )
            continue
        if any(name.startswith(p) for p in operations.RESERVED_PREFIXES):
            findings.append(
                {
                    "level": "error",
                    "message": f"op '{name}' uses a reserved prefix",
                    "fix": "rename it (data./sql./http./job./ui./app. are built-ins)",
                }
            )
        description = (op_def.get("description") or "").strip()
        if len(description) < 15 or description.startswith("TODO"):
            findings.append(
                {
                    "level": "warning",
                    "message": f"op '{name}' has a missing/placeholder description",
                    "fix": "write one line saying what it does and when to use it "
                    "(agents choose ops by reading this)",
                }
            )
        params = op_def.get("params") or {}
        executor = op_def.get("executor") or {}
        executor_type = str(executor.get("type", "http")).lower()

        if executor_type == "http":
            path = executor.get("path", "")
            method = str(executor.get("method", "POST")).upper()
            path_params = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path))
            missing = path_params - set(params.keys())
            if missing:
                findings.append(
                    {
                        "level": "error",
                        "message": f"op '{name}': path params {sorted(missing)} not in declared params",
                        "fix": f"declare them, e.g. \"{next(iter(missing))}\": \"int\"",
                    }
                )
            if spec and (method, path) not in spec_routes:
                findings.append(
                    {
                        "level": "error",
                        "message": f"op '{name}': {method} {path} does not exist on the backend",
                        "fix": "fix the path/method or remove the op (run ops-sync to see real routes)",
                    }
                )
        elif executor_type == "shell":
            cmd = executor.get("cmd", "")
            placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", cmd))
            missing = placeholders - set(params.keys())
            if missing:
                findings.append(
                    {
                        "level": "error",
                        "message": f"op '{name}': shell placeholders {sorted(missing)} not in declared params",
                        "fix": "declare them or remove the placeholders",
                    }
                )
            if not cmd.strip():
                findings.append(
                    {"level": "error", "message": f"op '{name}': empty shell command", "fix": "set executor.cmd"}
                )
        elif executor_type == "sql":
            if not (executor.get("sql") or "").strip():
                findings.append(
                    {"level": "error", "message": f"op '{name}': empty sql", "fix": "set executor.sql"}
                )
        else:
            findings.append(
                {
                    "level": "error",
                    "message": f"op '{name}': unknown executor type '{executor_type}'",
                    "fix": "use http, sql, or shell",
                }
            )

    # Coverage lint: candidate routes with no op and not explicitly ignored
    if spec:
        covered = {
            (str((op.get("executor") or {}).get("method", "POST")).upper(),
             (op.get("executor") or {}).get("path", ""))
            for op in ops.values()
            if isinstance(op, dict)
            and str((op.get("executor") or {}).get("type", "http")).lower() == "http"
        }
        for route in analyze_routes(spec)["candidate"]:
            key = (route["method"], route["path"])
            tag = f"{route['method']} {route['path']}"
            if key not in covered and tag not in ignore_routes:
                findings.append(
                    {
                        "level": "warning",
                        "message": f"uncovered route: {tag} ({(route['meta'].get('summary') or 'no summary').strip()})",
                        "fix": "run `ops-sync --write` to declare it, or add "
                        f'"{tag}" to "ignore_routes" in operations.json',
                    }
                )
    return findings


def sync_manifest(
    project_path: Path, spec: Dict[str, Any], write: bool = False
) -> Dict[str, Any]:
    """Generate skeletons for uncovered candidate routes; merge on --write.

    Never modifies existing ops. Returns {new_ops, written, manifest_path}.
    """
    raw, parse_error = _load_manifest_raw(project_path)
    if parse_error:
        return {"error": parse_error}
    if raw is None:
        raw = {"operations": {}}
    ops = raw.setdefault("operations", {})
    ignore_routes = set(raw.get("ignore_routes") or [])

    covered = {
        (str((op.get("executor") or {}).get("method", "POST")).upper(),
         (op.get("executor") or {}).get("path", ""))
        for op in ops.values()
        if isinstance(op, dict)
    }
    new_ops: Dict[str, Dict[str, Any]] = {}
    for name, op in generate_skeletons(spec).items():
        key = (op["executor"]["method"], op["executor"]["path"])
        tag = f"{key[0]} {key[1]}"
        if key in covered or tag in ignore_routes:
            continue
        final_name = name
        suffix = 2
        while final_name in ops or final_name in new_ops:
            final_name = f"{name}_{suffix}"
            suffix += 1
        new_ops[final_name] = op

    manifest_path = Path(project_path) / operations.OPERATIONS_FILE
    written = False
    if write and new_ops:
        ops.update(new_ops)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written = True
    return {"new_ops": new_ops, "written": written, "manifest_path": str(manifest_path)}
