"""
Living UI Backend Test Runner

Auto-discovers and tests backend routes without agent involvement.
Four modes:
  --internal      : Pre-server validation (imports, models, route registration)
  --unit          : Auto-generated CRUD unit tests against temp DB
  --compatibility : Frontend-backend route compatibility check
  --external      : Post-server HTTP smoke tests (requires running server)

Usage:
  python test_runner.py --internal
  python test_runner.py --unit
  python test_runner.py --compatibility
  python test_runner.py --external --port 3101
"""

import argparse
import json
import logging
import re
import sys
import traceback
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("test_runner")

# Routes to skip during smoke tests (framework/template-provided, not agent code)
SKIP_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}
# Template-provided UI observation routes — complex payloads (base64 images, DOM), skip in smoke tests
SKIP_API_PREFIXES = (
    "/api/ui-snapshot",
    "/api/ui-screenshot",
)


# ============================================================================
# Auto-payload generation from OpenAPI schemas
# ============================================================================


def generate_payload_from_schema(
    schema: Dict[str, Any], definitions: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate a minimal valid payload from an OpenAPI/JSON Schema definition.

    Handles $ref resolution and generates test values for common types.
    Only includes required fields.
    """
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        schema = definitions.get(ref_name, {})

    if schema.get("type") != "object":
        return {}

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    # If no required fields specified, include all properties
    if not required:
        required = set(properties.keys())

    payload = {}
    for field_name, field_schema in properties.items():
        if field_name not in required:
            continue
        if field_name.startswith("_"):
            continue
        payload[field_name] = _generate_value(field_schema, definitions)

    return payload


def _generate_value(schema: Dict[str, Any], definitions: Dict[str, Any]) -> Any:
    """Generate a test value for a single field based on its schema."""
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        ref_schema = definitions.get(ref_name, {})
        return generate_payload_from_schema(ref_schema, definitions)

    field_type = schema.get("type", "string")

    if field_type == "string":
        if "enum" in schema:
            return schema["enum"][0]
        # Use format hints for better test values
        fmt = schema.get("format", "")
        if fmt == "date-time":
            return "2026-01-01T00:00:00"
        elif fmt == "date":
            return "2026-01-01"
        elif fmt == "email":
            return "test@test.com"
        elif fmt == "uri" or fmt == "url":
            return "http://test.com"
        return "test"
    elif field_type == "integer":
        return schema.get("minimum", 1)
    elif field_type == "number":
        return schema.get("minimum", 1.0)
    elif field_type == "boolean":
        return True
    elif field_type == "array":
        # Generate an array with one item of the correct type
        items_schema = schema.get("items", {})
        if items_schema:
            return [_generate_value(items_schema, definitions)]
        return []
    elif field_type == "object":
        # Check if it has properties (structured) or is a free-form dict
        if schema.get("properties"):
            return generate_payload_from_schema(schema, definitions)
        # Free-form object (e.g., Dict[str, Any])
        return {}
    elif field_type == "null":
        return None

    # anyOf / oneOf — pick the first non-null type
    for key in ("anyOf", "oneOf"):
        if key in schema:
            for variant in schema[key]:
                if variant.get("type") != "null":
                    return _generate_value(variant, definitions)

    return "test"


# ============================================================================
# Internal Tests (pre-server)
# ============================================================================


def run_internal_tests() -> Dict[str, Any]:
    """
    Run pre-server validation tests.

    - Import validation for main, routes, models, database
    - Route discovery from FastAPI app
    - Model verification (SQLAlchemy tables)

    Returns dict with status, errors, and discovered routes.
    """
    result = {
        "status": "pass",
        "errors": [],
        "routes": [],
        "timestamp": datetime.now().isoformat(),
        "mode": "internal",
    }

    # Test 1: Import validation
    modules_to_test = ["database", "models", "routes", "main"]
    for module_name in modules_to_test:
        try:
            __import__(module_name)
            logger.info(f"[IMPORT] {module_name} — OK")
        except Exception as e:
            error_msg = f"Failed to import {module_name}: {e}"
            logger.error(f"[IMPORT] {error_msg}")
            result["errors"].append(
                {
                    "test": "import",
                    "module": module_name,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
            result["status"] = "fail"

    if result["status"] == "fail":
        # No point continuing if imports fail
        _write_result(result, "test_discovery.json")
        return result

    # Test 2: Route discovery
    try:
        from main import app

        openapi_schema = app.openapi()
        definitions = openapi_schema.get("components", {}).get("schemas", {})
        paths = openapi_schema.get("paths", {})

        for path, methods in paths.items():
            for method, details in methods.items():
                if method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    # Check for request body schema
                    body_schema = None
                    has_request_body = False
                    request_body = details.get("requestBody", {})
                    if request_body:
                        has_request_body = True
                        content = request_body.get("content", {})
                        json_content = content.get("application/json", {})
                        body_schema = json_content.get("schema")

                    # Check for path parameters
                    path_params = []
                    for param in details.get("parameters", []):
                        if param.get("in") == "path":
                            path_params.append(param["name"])

                    route_info = {
                        "method": method.upper(),
                        "path": path,
                        "has_request_body": has_request_body,
                        "body_schema": body_schema,
                        "path_params": path_params,
                        "level": "light",
                    }
                    result["routes"].append(route_info)
                    logger.info(f"[ROUTE] {method.upper()} {path}")

        if not any(r["path"].startswith("/api") for r in result["routes"]):
            result["errors"].append(
                {
                    "test": "route_discovery",
                    "error": "No /api/* routes found — backend has no application routes registered",
                }
            )
            result["status"] = "fail"
        else:
            api_count = sum(1 for r in result["routes"] if r["path"].startswith("/api"))
            logger.info(f"[ROUTES] Discovered {api_count} API route(s)")

    except Exception as e:
        result["errors"].append(
            {
                "test": "route_discovery",
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
        )
        result["status"] = "fail"

    # Test 3: Model/table verification
    try:
        from models import Base

        # Verify tables can be created (uses in-memory check, doesn't modify real DB)
        table_names = list(Base.metadata.tables.keys())
        logger.info(f"[MODELS] Found {len(table_names)} table(s): {table_names}")

        if not table_names:
            result["errors"].append(
                {"test": "models", "error": "No SQLAlchemy models/tables defined"}
            )
            result["status"] = "fail"

    except Exception as e:
        result["errors"].append(
            {"test": "models", "error": str(e), "traceback": traceback.format_exc()}
        )
        result["status"] = "fail"

    # Test 4: System file integrity — verify critical system features weren't removed
    system_checks = _check_system_files()
    for check in system_checks:
        if check["status"] == "fail":
            result["errors"].append(
                {"test": "system_integrity", "error": check["error"]}
            )
            result["status"] = "fail"
            logger.error(f"[SYSTEM] {check['error']}")
        else:
            logger.info(f"[SYSTEM] {check['name']} — OK")

    _write_result(result, "test_discovery.json")
    return result


def _check_system_files() -> List[Dict[str, Any]]:
    """Check that critical system features haven't been removed from template files."""
    checks = []
    backend_dir = (
        Path(__file__).parent.parent / "backend"
        if (Path(__file__).parent.parent / "backend").exists()
        else Path(__file__).parent
    )
    project_root = Path(__file__).parent.parent

    # Check main.py has /health endpoint
    main_py = backend_dir / "main.py"
    if main_py.exists():
        content = main_py.read_text(encoding="utf-8")
        if "/health" not in content:
            checks.append(
                {
                    "name": "health_endpoint",
                    "status": "fail",
                    "error": "main.py is missing /health endpoint. Add: @app.get('/health') async def health_check(): return {'status': 'healthy'}",
                }
            )
        else:
            checks.append({"name": "health_endpoint", "status": "pass"})

        if "/api/logs" not in content:
            checks.append(
                {
                    "name": "logs_endpoint",
                    "status": "fail",
                    "error": "main.py is missing POST /api/logs endpoint for frontend console capture. Restore it from the template or add: @app.post('/api/logs') that accepts {entries: [{level, message, timestamp}]} and writes to logs/frontend_console.log",
                }
            )
        else:
            checks.append({"name": "logs_endpoint", "status": "pass"})

        if "setup_logging" not in content:
            checks.append(
                {
                    "name": "logging_setup",
                    "status": "fail",
                    "error": "main.py is missing setup_logging() call. Add: from logger import setup_logging, cleanup_old_logs; setup_logging(); cleanup_old_logs(keep=20)",
                }
            )
        else:
            checks.append({"name": "logging_setup", "status": "pass"})

        # Health checker is handled by the manager watchdog — no longer required in main.py
        checks.append({"name": "health_checker", "status": "pass"})
    else:
        checks.append(
            {"name": "main_py", "status": "fail", "error": "main.py not found"}
        )

    # Check index.html has console capture script
    index_html = project_root / "index.html"
    if index_html.exists():
        content = index_html.read_text(encoding="utf-8")
        if "ConsoleCapture" not in content and "/api/logs" not in content:
            checks.append(
                {
                    "name": "console_capture",
                    "status": "fail",
                    "error": "index.html is missing the ConsoleCapture script. Restore it from the template — it should be an inline <script> before the main.tsx module script",
                }
            )
        else:
            checks.append({"name": "console_capture", "status": "pass"})
    else:
        checks.append(
            {"name": "index_html", "status": "fail", "error": "index.html not found"}
        )

    # Check conftest.py uses correct imports (not package-style)
    conftest = backend_dir / "tests" / "conftest.py"
    if conftest.exists():
        content = conftest.read_text(encoding="utf-8")
        if "from backend." in content or "from backend import" in content:
            checks.append(
                {
                    "name": "conftest_imports",
                    "status": "fail",
                    "error": "tests/conftest.py has wrong imports. Use 'from models import Base', 'from database import get_db', 'from main import app' — NOT 'from backend.models' or 'from backend.main'. The conftest.py adds the backend dir to sys.path so absolute imports work.",
                }
            )
        else:
            checks.append({"name": "conftest_imports", "status": "pass"})

    return checks


# ============================================================================
# External Tests (post-server, HTTP smoke tests)
# ============================================================================


def run_external_tests(port: int) -> Dict[str, Any]:
    """
    Run HTTP smoke tests against the running backend.

    Reads discovered routes from test_discovery.json, then:
    1. POST endpoints — create test data, record IDs
    2. GET endpoints — verify they return 2xx
    3. PUT endpoints — modify test data
    4. DELETE endpoints — clean up test data

    Returns dict with status, errors, and test results.
    """
    result = {
        "status": "pass",
        "errors": [],
        "tests": [],
        "timestamp": datetime.now().isoformat(),
        "mode": "external",
    }

    # Load discovered routes from internal test phase
    discovery_file = LOG_DIR / "test_discovery.json"
    if not discovery_file.exists():
        result["errors"].append(
            {
                "test": "setup",
                "error": "test_discovery.json not found — run --internal first",
            }
        )
        result["status"] = "fail"
        _write_result(result, "test_results.json")
        return result

    discovery = json.loads(discovery_file.read_text(encoding="utf-8"))
    routes = discovery.get("routes", [])

    # Load OpenAPI schema from running server for payload generation
    definitions = {}
    try:
        openapi_url = f"http://localhost:{port}/openapi.json"
        resp = urllib.request.urlopen(openapi_url, timeout=5)
        openapi_schema = json.loads(resp.read().decode())
        definitions = openapi_schema.get("components", {}).get("schemas", {})
    except Exception as e:
        logger.warning(f"[EXTERNAL] Could not fetch OpenAPI schema: {e}")

    # Filter to only /api/* routes, skip framework/template routes
    api_routes = [
        r
        for r in routes
        if r["path"].startswith("/api")
        and r["path"] not in SKIP_PATHS
        and not any(r["path"].startswith(prefix) for prefix in SKIP_API_PREFIXES)
    ]

    # Group by base path (e.g., /api/sections, /api/cards)
    # Sort: POST first, then GET, then PUT, then DELETE
    method_order = {"POST": 0, "GET": 1, "PUT": 2, "PATCH": 3, "DELETE": 4}
    api_routes.sort(key=lambda r: (method_order.get(r["method"], 5), r["path"]))

    base_url = f"http://localhost:{port}"
    created_resources: Dict[str, List[int]] = {}  # path -> list of created IDs

    # Register a test user for auth (if auth routes exist)
    auth_token = None
    auth_routes_exist = any(r["path"].startswith("/api/auth") for r in api_routes)
    if auth_routes_exist:
        try:
            reg_data = json.dumps(
                {
                    "email": "smoketest@test.com",
                    "username": "smoketest",
                    "password": "testpass123",
                }
            ).encode()
            reg_req = urllib.request.Request(
                f"{base_url}/api/auth/register",
                data=reg_data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            reg_resp = urllib.request.urlopen(reg_req, timeout=10)
            reg_body = json.loads(reg_resp.read().decode())
            auth_token = reg_body.get("token")
            logger.info("[EXTERNAL] Registered smoke test user, token obtained")
        except Exception as e:
            try:
                login_data = json.dumps(
                    {"email": "smoketest@test.com", "password": "testpass123"}
                ).encode()
                login_req = urllib.request.Request(
                    f"{base_url}/api/auth/login",
                    data=login_data,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                login_resp = urllib.request.urlopen(login_req, timeout=10)
                login_body = json.loads(login_resp.read().decode())
                auth_token = login_body.get("token")
                logger.info("[EXTERNAL] Logged in as smoke test user")
            except Exception:
                logger.warning(
                    f"[EXTERNAL] Could not authenticate for smoke tests: {e}"
                )
        # Skip auth routes from generic testing (they need specific flows)
        api_routes = [r for r in api_routes if not r["path"].startswith("/api/auth")]

    for route in api_routes:
        method = route["method"]
        path = route["path"]
        path_params = route.get("path_params", [])

        # Skip parameterized paths if we don't have test data yet
        if path_params:
            # Try to find a matching created resource
            base_path = _get_base_path(path)
            ids = created_resources.get(base_path, [])
            # For action sub-paths like /api/bills/{id}/receive, try the parent path
            if not ids:
                parent_path = "/".join(base_path.split("/")[:-1])
                ids = created_resources.get(parent_path, [])
            if not ids:
                logger.info(f"[SKIP] {method} {path} — no test data available")
                result["tests"].append(
                    {
                        "method": method,
                        "path": path,
                        "status": "skipped",
                        "reason": "no test data",
                    }
                )
                continue
            # Substitute the first path param with a created ID
            resolved_path = path
            for param in path_params:
                resolved_path = resolved_path.replace(f"{{{param}}}", str(ids[0]))
            path = resolved_path

        test_result = _test_endpoint(
            base_url, method, path, route, definitions, auth_token=auth_token
        )
        result["tests"].append(test_result)

        if test_result["status"] == "fail":
            result["errors"].append(
                {
                    "test": f"{method} {route['path']}",
                    "error": test_result.get("error", "Unknown error"),
                }
            )
            result["status"] = "fail"
            logger.error(f"[FAIL] {method} {path} — {test_result.get('error')}")
        else:
            logger.info(f"[PASS] {method} {path} — {test_result.get('status_code')}")

            # Track created resources for later PUT/DELETE tests
            if method == "POST" and test_result.get("response_body"):
                body = test_result["response_body"]
                resource_id = body.get("id")
                if resource_id is not None:
                    base_path = _get_base_path(route["path"])
                    created_resources.setdefault(base_path, []).append(resource_id)

    # Cleanup: delete any remaining test data
    _cleanup_test_data(base_url, created_resources, result)

    _write_result(result, "test_results.json")
    return result


def _test_endpoint(
    base_url: str,
    method: str,
    path: str,
    route: Dict[str, Any],
    definitions: Dict[str, Any],
    auth_token: str = None,
) -> Dict[str, Any]:
    """Test a single endpoint and return the result."""
    url = f"{base_url}{path}"
    test_result: Dict[str, Any] = {
        "method": method,
        "path": path,
        "status": "pass",
    }

    try:
        payload = None
        if method in ("POST", "PUT", "PATCH") and route.get("body_schema"):
            payload = generate_payload_from_schema(route["body_schema"], definitions)

        data = json.dumps(payload).encode("utf-8") if payload else None
        headers = {"Content-Type": "application/json"} if data else {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )

        resp = urllib.request.urlopen(req, timeout=10)
        status_code = resp.status
        test_result["status_code"] = status_code

        try:
            response_body = json.loads(resp.read().decode())
            test_result["response_body"] = response_body
        except Exception:
            pass

        if status_code >= 400:
            test_result["status"] = "fail"
            test_result["error"] = f"HTTP {status_code}"

    except urllib.error.HTTPError as e:
        test_result["status"] = "fail"
        test_result["status_code"] = e.code
        # Read the response body for validation error details (FastAPI 422 includes them)
        error_detail = ""
        try:
            resp_body = json.loads(e.read().decode())
            test_result["response_body"] = resp_body
            # FastAPI 422 format: {"detail": [{"loc": [...], "msg": "...", "type": "..."}]}
            if "detail" in resp_body and isinstance(resp_body["detail"], list):
                details = [
                    f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg', '')}"
                    for d in resp_body["detail"]
                ]
                error_detail = "; ".join(details)
            elif "detail" in resp_body:
                error_detail = str(resp_body["detail"])
        except Exception:
            pass
        sent_info = f" (sent: {json.dumps(payload)})" if payload else ""
        test_result["error"] = f"HTTP {e.code}: {error_detail or e.reason}{sent_info}"
    except Exception as e:
        test_result["status"] = "fail"
        test_result["error"] = str(e)

    return test_result


def _get_base_path(path: str) -> str:
    """Extract base path without path parameters. e.g., /api/items/{item_id} -> /api/items"""
    parts = path.split("/")
    base_parts = [p for p in parts if not p.startswith("{")]
    return "/".join(base_parts)


def _cleanup_test_data(
    base_url: str,
    created_resources: Dict[str, List[int]],
    result: Dict[str, Any],
) -> None:
    """Delete all test data created during smoke tests."""
    for base_path, ids in created_resources.items():
        for resource_id in ids:
            delete_url = f"{base_url}{base_path}/{resource_id}"
            try:
                req = urllib.request.Request(delete_url, method="DELETE")
                urllib.request.urlopen(req, timeout=5)
                logger.info(f"[CLEANUP] Deleted {base_path}/{resource_id}")
            except Exception as e:
                logger.warning(
                    f"[CLEANUP] Failed to delete {base_path}/{resource_id}: {e}"
                )
                result["tests"].append(
                    {
                        "method": "DELETE",
                        "path": f"{base_path}/{resource_id}",
                        "status": "warning",
                        "error": f"Cleanup failed: {e}",
                    }
                )


# ============================================================================
# Frontend-Backend Compatibility Check
# ============================================================================

# TODO: Regex-based extraction is fragile and produces false positives.
# It cannot reliably parse template literals where the base URL contains /api
# (e.g., `${this.baseUrl}/items/${id}` where baseUrl='http://localhost:3101/api').
# Consider replacing with TypeScript AST parsing or a frontend API manifest.
#
# Regex patterns to extract fetch/API calls from TypeScript/JavaScript
# Matches: fetch(`${...}/api/something`, { method: 'POST' })
# Matches: fetch(`${this.baseUrl}/api/items/${id}`, { method: 'DELETE' })
# Matches: fetch(BASE_URL + '/api/items', { method: 'GET' })
_FETCH_PATTERNS = [
    # Template literal: fetch(`${...}/path/here`
    re.compile(r"""fetch\(\s*`[^`]*?(/(?:api|health)[^`]*?)`""", re.MULTILINE),
    # String concatenation or direct string: fetch(URL + '/path' or fetch('/path'
    re.compile(r"""fetch\([^,]*?['"](/(?:api|health)[^'"]*?)['"]""", re.MULTILINE),
]

# Extract HTTP method from fetch options: { method: 'POST' } or { method: "GET" }
_METHOD_PATTERN = re.compile(r"""method\s*:\s*['"](\w+)['"]""", re.MULTILINE)


def _scan_frontend_api_calls(frontend_dir: Path) -> List[Dict[str, str]]:
    """
    Scan all .ts/.tsx files in the frontend directory for fetch() calls.

    Returns list of {method, path, file, line} dicts.
    """
    api_calls: List[Dict[str, str]] = []

    if not frontend_dir.exists():
        return api_calls

    for ext in ("*.ts", "*.tsx"):
        for ts_file in frontend_dir.rglob(ext):
            # Skip node_modules and build output
            rel = str(ts_file.relative_to(frontend_dir))
            if "node_modules" in rel or "dist" in rel:
                continue

            try:
                content = ts_file.read_text(encoding="utf-8")
            except Exception:
                continue

            lines = content.split("\n")

            for line_num, line in enumerate(lines, 1):
                # Find fetch calls with API paths
                for pattern in _FETCH_PATTERNS:
                    for match in pattern.finditer(line):
                        raw_path = match.group(1)

                        # Normalize path: replace ${...} template vars with {param}
                        # e.g., /api/items/${id} -> /api/items/{id}
                        normalized_path = re.sub(r"\$\{[^}]+\}", "{id}", raw_path)

                        # Extract method from surrounding context (look ahead ~3 lines)
                        context = "\n".join(lines[line_num - 1 : line_num + 3])
                        method_match = _METHOD_PATTERN.search(context)
                        method = (
                            method_match.group(1).upper() if method_match else "GET"
                        )

                        api_calls.append(
                            {
                                "method": method,
                                "path": normalized_path,
                                "file": rel,
                                "line": line_num,
                            }
                        )

    return api_calls


def _normalize_route_path(path: str) -> str:
    """
    Normalize a backend route path for comparison.
    e.g., /api/items/{item_id} -> /api/items/{id}
    """
    return re.sub(r"\{[^}]+\}", "{id}", path)


def run_compatibility_tests() -> Dict[str, Any]:
    """
    Check that all frontend API calls have matching backend routes.

    Reads backend routes from test_discovery.json, scans frontend .ts/.tsx
    files for fetch() calls, and reports any mismatches.

    TODO: This test is currently non-blocking (required: false in manifest) because
    the regex-based frontend parsing produces false positives:
    - Cannot distinguish base URL from path in template literals
      (e.g., `${this.baseUrl}/${id}` extracts `/api{id}` instead of `/{id}`)
    - Flags template-provided routes (state, action) as missing when discovery
      doesn't include them
    - Cannot handle dynamic URL construction or string concatenation across lines
    To make this blocking, replace regex parsing with proper TypeScript AST parsing
    or require the frontend to declare its API calls in a manifest/config file.
    """
    result = {
        "status": "pass",
        "errors": [],
        "frontend_calls": [],
        "unmatched_calls": [],
        "timestamp": datetime.now().isoformat(),
        "mode": "compatibility",
    }

    # Load backend routes from discovery
    discovery_file = LOG_DIR / "test_discovery.json"
    if not discovery_file.exists():
        result["errors"].append(
            {
                "test": "setup",
                "error": "test_discovery.json not found — run --internal first",
            }
        )
        result["status"] = "fail"
        _write_result(result, "test_compatibility.json")
        return result

    discovery = json.loads(discovery_file.read_text(encoding="utf-8"))
    backend_routes = discovery.get("routes", [])

    # Build a set of normalized (method, path) tuples from backend
    backend_route_set: Set[Tuple[str, str]] = set()
    for route in backend_routes:
        normalized = _normalize_route_path(route["path"])
        backend_route_set.add((route["method"], normalized))

    # Scan frontend
    frontend_dir = Path(__file__).parent.parent / "frontend"
    frontend_calls = _scan_frontend_api_calls(frontend_dir)
    result["frontend_calls"] = frontend_calls

    if not frontend_calls:
        logger.info(
            "[COMPAT] No frontend API calls found (this may be OK for new projects)"
        )
        _write_result(result, "test_compatibility.json")
        return result

    logger.info(f"[COMPAT] Found {len(frontend_calls)} frontend API call(s)")

    # Compare: every frontend call should have a matching backend route
    seen: Set[Tuple[str, str]] = set()
    for call in frontend_calls:
        normalized_path = _normalize_route_path(call["path"])
        key = (call["method"], normalized_path)

        if key in seen:
            continue  # Already checked this method+path combo
        seen.add(key)

        # Skip /health — it's a framework route, always exists
        if normalized_path in SKIP_PATHS:
            continue

        if key not in backend_route_set:
            result["unmatched_calls"].append(
                {
                    "method": call["method"],
                    "path": call["path"],
                    "file": call["file"],
                    "line": call["line"],
                    "error": f"Frontend calls {call['method']} {call['path']} but no matching backend route exists",
                }
            )

    if result["unmatched_calls"]:
        result["status"] = "fail"
        for unmatched in result["unmatched_calls"]:
            result["errors"].append(
                {
                    "test": "compatibility",
                    "error": unmatched["error"],
                }
            )
            logger.error(
                f"[COMPAT] MISMATCH: {unmatched['method']} {unmatched['path']} "
                f"(called from {unmatched['file']}:{unmatched['line']})"
            )
    else:
        logger.info(
            f"[COMPAT] All {len(seen)} unique frontend API calls have matching backend routes"
        )

    _write_result(result, "test_compatibility.json")
    return result


# ============================================================================
# Auto-Generated Backend Unit Tests
# ============================================================================


def run_unit_tests() -> Dict[str, Any]:
    """
    Auto-generate and run CRUD unit tests for all SQLAlchemy models.

    Uses a temporary in-memory SQLite database so the real DB is untouched.
    Tests create, read, update, and delete for each model.
    """
    result = {
        "status": "pass",
        "errors": [],
        "tests": [],
        "timestamp": datetime.now().isoformat(),
        "mode": "unit",
    }

    try:
        from sqlalchemy import create_engine, inspect
        from sqlalchemy.orm import sessionmaker
        from models import Base
    except Exception as e:
        result["errors"].append({"test": "setup", "error": f"Failed to import: {e}"})
        result["status"] = "fail"
        _write_result(result, "test_unit.json")
        return result

    # Create temporary in-memory database
    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine)

    # Get all model classes from Base
    model_classes = []
    for mapper in Base.registry.mappers:
        model_cls = mapper.class_
        if hasattr(model_cls, "__tablename__"):
            model_classes.append(model_cls)

    if not model_classes:
        logger.warning("[UNIT] No model classes found")
        _write_result(result, "test_unit.json")
        return result

    logger.info(f"[UNIT] Testing {len(model_classes)} model(s)")

    for model_cls in model_classes:
        table_name = model_cls.__tablename__
        logger.info(f"[UNIT] Testing model: {model_cls.__name__} (table: {table_name})")

        # Get column info for auto-generating test data
        inspector = inspect(test_engine)
        columns = inspector.get_columns(table_name)

        # Generate test data
        test_data = _generate_model_test_data(columns)

        # Test CREATE
        test_name = f"{model_cls.__name__}.create"
        try:
            session = TestSession()
            instance = model_cls(**test_data)
            session.add(instance)
            session.commit()
            session.refresh(instance)
            instance_id = getattr(instance, "id", None)
            session.close()

            result["tests"].append({"test": test_name, "status": "pass"})
            logger.info(f"  [PASS] {test_name} (id={instance_id})")
        except Exception as e:
            result["tests"].append(
                {"test": test_name, "status": "fail", "error": str(e)}
            )
            result["errors"].append({"test": test_name, "error": str(e)})
            result["status"] = "fail"
            logger.error(f"  [FAIL] {test_name}: {e}")
            continue  # Skip remaining CRUD tests for this model

        # Test READ
        test_name = f"{model_cls.__name__}.read"
        try:
            session = TestSession()
            fetched = session.query(model_cls).first()
            assert fetched is not None, "No record found after create"
            session.close()

            result["tests"].append({"test": test_name, "status": "pass"})
            logger.info(f"  [PASS] {test_name}")
        except Exception as e:
            result["tests"].append(
                {"test": test_name, "status": "fail", "error": str(e)}
            )
            result["errors"].append({"test": test_name, "error": str(e)})
            result["status"] = "fail"
            logger.error(f"  [FAIL] {test_name}: {e}")

        # Test UPDATE
        test_name = f"{model_cls.__name__}.update"
        try:
            session = TestSession()
            fetched = session.query(model_cls).first()
            # Find a string column to update
            updated = False
            for col in columns:
                if (
                    str(col["type"]).startswith(("VARCHAR", "TEXT", "String"))
                    and col["name"] != "id"
                ):
                    setattr(fetched, col["name"], "updated_test")
                    updated = True
                    break
            if updated:
                session.commit()
                session.refresh(fetched)
            session.close()

            result["tests"].append({"test": test_name, "status": "pass"})
            logger.info(f"  [PASS] {test_name}")
        except Exception as e:
            result["tests"].append(
                {"test": test_name, "status": "fail", "error": str(e)}
            )
            result["errors"].append({"test": test_name, "error": str(e)})
            result["status"] = "fail"
            logger.error(f"  [FAIL] {test_name}: {e}")

        # Test DELETE
        test_name = f"{model_cls.__name__}.delete"
        try:
            session = TestSession()
            fetched = session.query(model_cls).first()
            if fetched:
                session.delete(fetched)
                session.commit()
                remaining = session.query(model_cls).count()
                assert remaining == 0, (
                    f"Record still exists after delete ({remaining} remaining)"
                )
            session.close()

            result["tests"].append({"test": test_name, "status": "pass"})
            logger.info(f"  [PASS] {test_name}")
        except Exception as e:
            result["tests"].append(
                {"test": test_name, "status": "fail", "error": str(e)}
            )
            result["errors"].append({"test": test_name, "error": str(e)})
            result["status"] = "fail"
            logger.error(f"  [FAIL] {test_name}: {e}")

    # Clean up
    test_engine.dispose()

    _write_result(result, "test_unit.json")
    return result


def _generate_model_test_data(columns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate test data for a SQLAlchemy model based on column definitions."""
    data = {}
    for col in columns:
        name = col["name"]
        col_type = str(col["type"]).upper()

        # Skip auto-generated columns
        if name == "id":
            continue
        if col.get("autoincrement"):
            continue
        # Skip columns with defaults (they'll be auto-populated)
        if col.get("default") is not None:
            continue

        if col.get("nullable", True) and col.get("default") is None:
            # Optional column with no default — skip unless it looks required
            pass

        if "VARCHAR" in col_type or "TEXT" in col_type or "STRING" in col_type:
            data[name] = "test"
        elif "INT" in col_type:
            data[name] = 1
        elif "FLOAT" in col_type or "REAL" in col_type or "NUMERIC" in col_type:
            data[name] = 1.0
        elif "BOOL" in col_type:
            data[name] = True
        elif "JSON" in col_type:
            data[name] = {}
        elif "DATE" in col_type or "TIME" in col_type:
            data[name] = datetime.now()

    return data


# ============================================================================
# Utilities
# ============================================================================


def _write_result(result: Dict[str, Any], filename: str) -> None:
    """Write test results to a JSON file in the logs directory."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    output_file = LOG_DIR / filename
    output_file.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    logger.info(f"[OUTPUT] Results written to {output_file}")


# ============================================================================
# CLI Entry Point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="Living UI Backend Test Runner")
    parser.add_argument(
        "--internal", action="store_true", help="Run internal pre-server tests"
    )
    parser.add_argument(
        "--unit", action="store_true", help="Run auto-generated CRUD unit tests"
    )
    parser.add_argument(
        "--compatibility",
        action="store_true",
        help="Run frontend-backend compatibility check",
    )
    parser.add_argument(
        "--external", action="store_true", help="Run external HTTP smoke tests"
    )
    parser.add_argument(
        "--port", type=int, default=3101, help="Backend port for external tests"
    )
    args = parser.parse_args()

    # Setup basic logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    if args.internal:
        logger.info("=" * 50)
        logger.info("Running INTERNAL tests (pre-server)")
        logger.info("=" * 50)
        result = run_internal_tests()
    elif args.unit:
        logger.info("=" * 50)
        logger.info("Running UNIT tests (auto-generated CRUD)")
        logger.info("=" * 50)
        result = run_unit_tests()
    elif args.compatibility:
        logger.info("=" * 50)
        logger.info("Running COMPATIBILITY tests (frontend-backend)")
        logger.info("=" * 50)
        result = run_compatibility_tests()
    elif args.external:
        logger.info("=" * 50)
        logger.info(f"Running EXTERNAL tests (port {args.port})")
        logger.info("=" * 50)
        result = run_external_tests(args.port)
    else:
        parser.print_help()
        sys.exit(1)

    # Print summary
    total_errors = len(result.get("errors", []))
    if result["status"] == "pass":
        logger.info("ALL TESTS PASSED")
        # Also print to stdout for subprocess capture
        print(json.dumps({"status": "pass", "errors": 0}))
        sys.exit(0)
    else:
        logger.error(f"TESTS FAILED ({total_errors} error(s))")
        for err in result["errors"]:
            logger.error(f"  - [{err.get('test')}] {err.get('error')}")
        print(json.dumps({"status": "fail", "errors": total_errors}))
        sys.exit(1)


if __name__ == "__main__":
    main()
