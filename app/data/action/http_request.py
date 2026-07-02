from agent_core import action


@action(
    name="http_request",
    description=(
        "Sends HTTP requests (GET, POST, PUT, PATCH, DELETE) with optional headers, "
        "params, and body. To DOWNLOAD A FILE (zip, exe, pdf, image, any binary), set "
        "'save_to' to a destination path — the raw bytes are streamed to disk intact and "
        "'saved_path' is returned instead of 'body'. Binary responses are auto-saved to "
        "the workspace 'downloads/' folder even without 'save_to'; only text/JSON is ever "
        "returned inline in 'body'. Never expect binary file content inside 'body'."
    ),
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
        "save_to": {
            "type": "string",
            "example": "D:/Work/CraftOS/CraftBot/agent_file_system/workspace/tcc.zip",
            "description": (
                "Optional destination path to save the response body to as raw "
                "bytes (binary-safe). Use this to download files. Absolute paths "
                "are used as-is; relative paths resolve under the workspace. If it "
                "names an existing directory, the filename is derived from the URL "
                "or Content-Disposition. When set, 'saved_path' is returned and "
                "'body' is omitted."
            ),
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
            "description": "Response body as text. Omitted for binary/saved responses.",
        },
        "saved_path": {
            "type": "string",
            "example": "D:/Work/CraftOS/CraftBot/agent_file_system/workspace/downloads/tcc.zip",
            "description": "Absolute path the response was saved to (downloads / binary / save_to).",
        },
        "bytes_written": {
            "type": "integer",
            "example": 314159,
            "description": "Number of bytes written to 'saved_path'.",
        },
        "content_type": {
            "type": "string",
            "example": "application/zip",
            "description": "Response Content-Type (bare media type, no parameters).",
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
    save_to = input_data.get("save_to")
    save_to = str(save_to).strip() if save_to else ""
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

    import os
    import re
    import mimetypes
    from urllib.parse import urlparse, unquote

    def _bare_content_type(resp) -> str:
        # "application/zip; charset=..." -> "application/zip"
        return (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()

    def _is_textual(content_type: str):
        """True/False for known types, None when unknown (caller should sniff)."""
        if not content_type:
            return None
        if content_type.startswith("text/"):
            return True
        if content_type in {
            "application/json",
            "application/xml",
            "application/javascript",
            "application/ld+json",
            "application/x-www-form-urlencoded",
            "image/svg+xml",
        }:
            return True
        if content_type.endswith("+json") or content_type.endswith("+xml"):
            return True
        return False

    def _sanitize_filename(name: str) -> str:
        name = os.path.basename(unquote(name or "")).strip().strip('"')
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-")
        return name

    def _derive_filename(resp, content_type: str) -> str:
        # 1) Content-Disposition filename*=UTF-8''... or filename="..."
        cd = resp.headers.get("Content-Disposition", "") or ""
        m = re.search(r"filename\*=(?:[^']*'')?([^;]+)", cd) or re.search(
            r'filename="?([^";]+)"?', cd
        )
        if m:
            fn = _sanitize_filename(m.group(1))
            if fn:
                return fn
        # 2) Basename from the final URL path
        fn = _sanitize_filename(urlparse(resp.url).path)
        if fn:
            return fn
        # 3) Fallback: timestamped name with an extension guessed from the type
        ext = mimetypes.guess_extension(content_type) if content_type else None
        return f"download_{int(time.time() * 1000)}{ext or '.bin'}"

    def _resolve_save_path(save_to: str, resp, content_type: str) -> str:
        # Absolute paths are honored; relative paths resolve under the workspace.
        if os.path.isabs(save_to):
            base = save_to
        else:
            try:
                from agent_core.core.config import get_workspace_root

                base = os.path.join(get_workspace_root(), save_to)
            except Exception:
                base = os.path.abspath(save_to)
        # If the target is (or looks like) a directory, derive the filename.
        if os.path.isdir(base) or save_to.endswith(("/", "\\")):
            base = os.path.join(base, _derive_filename(resp, content_type))
        return base

    def _auto_download_path(resp, content_type: str) -> str:
        try:
            from agent_core.core.config import get_workspace_root

            root = get_workspace_root()
        except Exception:
            root = os.getcwd()
        return os.path.join(root, "downloads", _derive_filename(resp, content_type))

    def _stream_to_file(resp, path: str) -> int:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        written = 0
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
                    written += len(chunk)
        return written

    try:
        t0 = time.time()
        # stream=True lets us inspect headers before pulling the body, and keeps
        # large downloads out of memory (we write them straight to disk).
        resp = requests.request(method, url, stream=True, **kwargs)
        resp_headers = {k: v for k, v in resp.headers.items()}
        content_type = _bare_content_type(resp)

        # Decide whether this response is a file to save (binary-safe) or text
        # to return inline. Explicit save_to always saves; otherwise auto-save
        # anything that isn't recognizably textual so binary bytes are never
        # decoded through resp.text (which corrupts them).
        textual = _is_textual(content_type)
        should_save = bool(save_to) or textual is False

        if not should_save and textual is None:
            # Unknown content type — sniff the leading bytes for NUL to tell
            # binary from text without committing to a decode.
            peek = resp.raw.read(2048, decode_content=True) or b""
            is_binary = b"\x00" in peek
            # Re-expose the peeked bytes so the body remains complete.
            resp._content = peek + resp.raw.read(decode_content=True)
            resp._content_consumed = True
            should_save = is_binary

        if should_save:
            dest = (
                _resolve_save_path(save_to, resp, content_type)
                if save_to
                else _auto_download_path(resp, content_type)
            )
            written = _stream_to_file(resp, dest)
            elapsed_ms = int((time.time() - t0) * 1000)
            note = (
                ""
                if save_to
                else " (binary response auto-saved; not returned inline)"
            )
            return {
                "status": "success" if resp.ok else "error",
                "status_code": resp.status_code,
                "response_headers": resp_headers,
                "saved_path": os.path.abspath(dest),
                "bytes_written": written,
                "content_type": content_type,
                "final_url": resp.url,
                "elapsed_ms": elapsed_ms,
                "message": (f"Saved {written} bytes to {os.path.abspath(dest)}{note}")
                if resp.ok
                else f"HTTP {resp.status_code}",
            }

        # Textual response — return inline as before.
        body_text = resp.text
        elapsed_ms = int((time.time() - t0) * 1000)
        parsed_json = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None
        out = {
            "status": "success" if resp.ok else "error",
            "status_code": resp.status_code,
            "response_headers": resp_headers,
            "body": body_text,
            "content_type": content_type,
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
