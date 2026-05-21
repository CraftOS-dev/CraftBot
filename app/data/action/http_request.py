from agent_core import action


@action(
    name="http_request",
    description="Sends HTTP requests (GET, POST, PUT, PATCH, DELETE) with optional headers, params, and body.",
    mode="CLI",
    action_sets=["core"],
    input_schema={
        "method": {
            "type": "string",
            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "example": "GET",
            "description": "HTTP method to use.",
        },
        "url": {
            "type": "string",
            "example": "https://api.example.com/v1/items",
            "description": "Absolute URL to request. Must start with http or https.",
        },
        "headers": {
            "type": "object",
            "example": {
                "Authorization": "Bearer <token>",
                "Accept": "application/json",
            },
            "description": "Optional headers to send as key-value pairs.",
        },
        "params": {
            "type": "object",
            "example": {"q": "search", "limit": "10"},
            "description": "Optional query parameters.",
        },
        "json": {
            "type": "object",
            "example": {"name": "Widget", "price": 19.99},
            "description": "JSON body to send. Mutually exclusive with 'data'.",
        },
        "data": {
            "type": "string",
            "example": "field1=value1&field2=value2",
            "description": "Raw request body (e.g., form-encoded or plain text). Mutually exclusive with 'json'.",
        },
        "timeout": {
            "type": "number",
            "example": 30,
            "description": "Timeout in seconds. Defaults to 30.",
        },
        "allow_redirects": {
            "type": "boolean",
            "example": True,
            "description": "Whether to follow redirects. Defaults to true.",
        },
        "verify_tls": {
            "type": "boolean",
            "example": True,
            "description": "Verify TLS certificates. Defaults to true.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the request completed, 'error' otherwise.",
        },
        "status_code": {
            "type": "integer",
            "example": 200,
            "description": "HTTP status code from the response.",
        },
        "response_headers": {
            "type": "object",
            "example": {"Content-Type": "application/json"},
            "description": "Response headers returned by the server.",
        },
        "body": {
            "type": "string",
            "example": '{"ok":true}',
            "description": "Response body as text.",
        },
        "response_json": {
            "type": "object",
            "example": {"ok": True},
            "description": "Parsed JSON body if available; otherwise omitted.",
        },
        "final_url": {
            "type": "string",
            "example": "https://api.example.com/v1/items?limit=10",
            "description": "Final URL after redirects.",
        },
        "elapsed_ms": {
            "type": "number",
            "example": 123,
            "description": "Round-trip time in milliseconds.",
        },
        "message": {
            "type": "string",
            "example": "HTTP 404",
            "description": "Error message if applicable.",
        },
    },
    requirement=["requests"],
    test_payload={
        "method": "GET",
        "url": "https://api.example.com/v1/items",
        "headers": {"Authorization": "Bearer <token>", "Accept": "application/json"},
        "params": {"q": "search", "limit": "10"},
        "timeout": 30,
        "allow_redirects": True,
        "verify_tls": True,
        "simulated_mode": True,
    },
)
def send_http_requests(input_data: dict) -> dict:
    import sys
    import subprocess
    import importlib
    import time

    pkg = "requests"
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])
    import requests

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        # Return mock result for testing
        return {
            "status": "success",
            "status_code": 200,
            "response_headers": {"Content-Type": "application/json"},
            "body": '{"ok": true}',
            "final_url": input_data.get("url", ""),
            "elapsed_ms": 100,
            "message": "",
        }

    method = str(input_data.get("method", "GET")).upper()
    url = str(input_data.get("url", "")).strip()
    headers = input_data.get("headers") or {}
    params = input_data.get("params") or {}
    json_body = input_data.get("json") if "json" in input_data else None
    data_body = input_data.get("data") if "data" in input_data else None
    timeout = float(input_data.get("timeout", 30))
    allow_redirects = bool(input_data.get("allow_redirects", True))
    verify_tls = bool(input_data.get("verify_tls", True))
    allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    if method not in allowed:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "Unsupported method.",
        }
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "Invalid or missing URL.",
        }

    # SSRF protection: block requests to private/internal networks and cloud metadata.
    # Loopback is allowed only when the port belongs to a registered Living UI project,
    # so the agent can talk to its own apps without exposing arbitrary localhost services.
    try:
        from urllib.parse import urlparse as _urlparse
        import ipaddress as _ipaddress
        import socket as _socket

        _parsed = _urlparse(url)
        _hostname = _parsed.hostname or ""
        _port = _parsed.port
        # Block cloud metadata endpoints
        _BLOCKED_HOSTS = {
            "169.254.169.254",
            "metadata.google.internal",
            "metadata.internal",
        }
        if _hostname in _BLOCKED_HOSTS:
            return {
                "status": "error",
                "status_code": 0,
                "response_headers": {},
                "body": "",
                "final_url": "",
                "elapsed_ms": 0,
                "message": "Blocked: requests to cloud metadata endpoints are not allowed.",
            }

        def _living_ui_ports() -> set:
            try:
                from app.living_ui import get_living_ui_manager

                _mgr = get_living_ui_manager()
                if not _mgr:
                    return set()
                _ports = set()
                for _p in _mgr.projects.values():
                    if _p.port:
                        _ports.add(int(_p.port))
                    if _p.backend_port:
                        _ports.add(int(_p.backend_port))
                return _ports
            except Exception:
                return set()

        # Resolve hostname and check for private IPs
        try:
            _resolved = _socket.getaddrinfo(_hostname, None)
            for _family, _type, _proto, _canonname, _sockaddr in _resolved:
                _ip = _ipaddress.ip_address(_sockaddr[0])
                if _ip.is_loopback:
                    if _port and _port in _living_ui_ports():
                        continue  # Allowed: targeting a known Living UI port
                    return {
                        "status": "error",
                        "status_code": 0,
                        "response_headers": {},
                        "body": "",
                        "final_url": "",
                        "elapsed_ms": 0,
                        "message": f"Blocked: requests to loopback addresses ({_hostname}) are only allowed for registered Living UI ports. Use the living_ui_http action with project_id to talk to your Living UI.",
                    }
                if _ip.is_private or _ip.is_link_local:
                    return {
                        "status": "error",
                        "status_code": 0,
                        "response_headers": {},
                        "body": "",
                        "final_url": "",
                        "elapsed_ms": 0,
                        "message": f"Blocked: requests to private/internal addresses ({_hostname}) are not allowed.",
                    }
        except (_socket.gaierror, ValueError):
            pass  # Let the request library handle DNS resolution errors
    except Exception:
        pass  # Best-effort SSRF check; don't block on parsing failures
    if json_body is not None and data_body is not None:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "Provide either json or data, not both.",
        }
    if not isinstance(headers, dict) or not isinstance(params, dict):
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "headers and params must be objects.",
        }
    headers = {str(k): str(v) for k, v in headers.items()}
    params = {str(k): str(v) for k, v in params.items()}
    kwargs = {
        "headers": headers,
        "params": params,
        "timeout": timeout,
        "allow_redirects": allow_redirects,
        "verify": verify_tls,
    }
    if json_body is not None:
        kwargs["json"] = json_body
    elif data_body is not None:
        kwargs["data"] = data_body
    try:
        t0 = time.time()
        resp = requests.request(method, url, **kwargs)
        elapsed_ms = int((time.time() - t0) * 1000)
        resp_headers = {k: v for k, v in resp.headers.items()}
        parsed_json = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None
        out = {
            "status": "success" if resp.ok else "error",
            "status_code": resp.status_code,
            "response_headers": resp_headers,
            "body": resp.text,
            "final_url": resp.url,
            "elapsed_ms": elapsed_ms,
            "message": "" if resp.ok else f"HTTP {resp.status_code}",
        }
        if parsed_json is not None:
            out["response_json"] = parsed_json
        return out
    except Exception as e:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": str(e),
        }
