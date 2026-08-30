"""A2App adapter for EXTERNAL apps: a per-project reverse proxy.

Spec: docs/design/external-app-a2app-adapter.md. A foreign codebase runs
AS-IS and cannot host the PocketBase adapter hooks, so the A2App surface
sits in FRONT of it: the app binds a hidden internal loopback port, this
proxy binds the project's assigned port, answers the protocol endpoints
itself, and passes every other request through untouched (the app's own UI
keeps working). Because the proxy is system code running inside CraftBot,
"adapter stamped at every launch" holds for externals with no sync step.

Served surface (mirrors the native pb_hooks adapter):
  GET /api/_a2app            identity (+ flavor:"external")
  GET /api/_a2app/describe   operations + conventions (entities: {} — the
                             foreign data model is not mapped; ops only)
  GET /api/_ops              operations.json verbatim
  *   /api/ops/{name}        guarded invocation, mapped onto the app's API
  *   anything else          transparent passthrough (HTTP + WebSocket)

Auth mirrors _system.pb.js: browser writes are constrained to loopback
origins; programmatic writes (no Origin) present X-LUI-Token from the
project's .agent-token; foreign-origin mutations are refused outright.
Ops are (re)read from operations.json on every request, like the native
describe, so the surface can never drift from the file on disk.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from app.agent_app.ops_manifest import (
    PLACEHOLDER_RE,
    load_external_manifest,
)

EXTERNAL_ADAPTER_VERSION = "0.1.0"
LOOPBACK_ORIGIN = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Hop-by-hop headers never forwarded in either direction (RFC 9110 §7.6.1).
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}
UPSTREAM_BODY_CAP = 10 * 1024 * 1024  # ops responses are read whole; cap them
EXCERPT = 2000


def _server_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _tz_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


def _schema_version(raw: bytes) -> str:
    """Fingerprint of the ops manifest (djb2, same shape as the native
    adapter's sv_ hash) so clients can cache describe against it."""
    h = 5381
    for b in raw:
        h = ((h * 33) ^ b) & 0xFFFFFFFF
    return f"sv_{h:x}"


EXTERNAL_CONVENTIONS = {
    "operations": (
        "This is an ADOPTED third-party app: declared operations are the "
        "only guarded write path. Check `operations` and invoke via "
        "POST/GET /api/ops/{name}; there are no protocol-typed entities to "
        "write directly (entities is empty by design, not omission)."
    ),
    "read": (
        "The app's own HTTP API remains reachable through this same port; "
        "anything outside /api/_a2app*, /api/_ops and /api/ops/* is the "
        "app's native surface, passed through unmodified."
    ),
    "destructive": (
        "An operation marked `destructive` changes or deletes data "
        "irreversibly. Confirm with the user before running it."
    ),
    "agent": (
        "Send X-LUI-Agent: <your agent id> on writes; it is recorded in the "
        "app's action log."
    ),
    "errors": (
        "Rejections carry a machine `code` and a full `violations` list; "
        "branch on `code`, never on prose. `upstream_error` relays the "
        "app's own failure status and body excerpt."
    ),
    "limits": (
        "If no declared operation expresses what was asked, say so plainly. "
        "Do not drive undeclared app endpoints to work around a limitation."
    ),
}


class ExternalA2AppProxy:
    """One instance per running external project. start()/stop() are the
    whole lifecycle; the manager owns both."""

    def __init__(
        self,
        project_dir: Path,
        listen_port: int,
        upstream_port: int,
        app_id: str,
        app_name: str,
        app_runtime: Optional[str] = None,
    ):
        self.project_dir = Path(project_dir)
        self.listen_port = int(listen_port)
        self.upstream_port = int(upstream_port)
        self.app_id = app_id
        self.app_name = app_name
        self.app_runtime = app_runtime
        self._runner = None
        self._session = None
        self._thread_loop = None
        self._thread = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        import sys
        import aiohttp
        from aiohttp import web

        if sys.platform == "win32":
            import asyncio
            import threading

            self._thread_loop = asyncio.SelectorEventLoop()
            ready = threading.Event()
            error_holder: list = [None]

            async def _setup() -> None:
                try:
                    self._session = aiohttp.ClientSession(
                        auto_decompress=False,
                        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
                    )
                    _app = web.Application(client_max_size=UPSTREAM_BODY_CAP)
                    _app.router.add_route("*", "/{tail:.*}", self._handle)
                    self._runner = web.AppRunner(_app, access_log=None)
                    await self._runner.setup()
                    site = web.TCPSite(self._runner, "127.0.0.1", self.listen_port)
                    await site.start()
                except Exception as exc:
                    error_holder[0] = exc
                finally:
                    ready.set()

            def _run_loop() -> None:
                self._thread_loop.run_until_complete(_setup())
                self._thread_loop.run_forever()

            self._thread = threading.Thread(
                target=_run_loop,
                daemon=True,
                name=f"a2app-proxy-{self.app_id}",
            )
            self._thread.start()
            ready.wait(timeout=10)
            if error_holder[0] is not None:
                raise error_holder[0]
        else:
            self._session = aiohttp.ClientSession(
                auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
            )
            app = web.Application(client_max_size=UPSTREAM_BODY_CAP)
            app.router.add_route("*", "/{tail:.*}", self._handle)
            self._runner = web.AppRunner(app, access_log=None)
            await self._runner.setup()
            site = web.TCPSite(self._runner, "127.0.0.1", self.listen_port)
            await site.start()

        logger.info(
            f"[AGENT_APP:A2APP] external adapter for {self.app_id} on "
            f":{self.listen_port} -> app on :{self.upstream_port}"
        )

    async def stop(self) -> None:
        if self._thread_loop is not None:
            # Windows: cleanup must run in the background SelectorEventLoop.
            import asyncio

            async def _cleanup() -> None:
                if self._runner is not None:
                    try:
                        await self._runner.cleanup()
                    except Exception:
                        pass
                    self._runner = None
                if self._session is not None:
                    try:
                        await self._session.close()
                    except Exception:
                        pass
                    self._session = None

            fut = asyncio.run_coroutine_threadsafe(_cleanup(), self._thread_loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
            try:
                self._thread_loop.call_soon_threadsafe(self._thread_loop.stop)
            except Exception:
                pass
            self._thread_loop = None
            self._thread = None
        else:
            if self._runner is not None:
                try:
                    await self._runner.cleanup()
                except Exception:
                    pass
                self._runner = None
            if self._session is not None:
                try:
                    await self._session.close()
                except Exception:
                    pass
                self._session = None

    # ── shared helpers ─────────────────────────────────────────────────────

    def _upstream_base(self) -> str:
        return f"http://127.0.0.1:{self.upstream_port}"

    def _ops_raw(self) -> bytes:
        try:
            return (self.project_dir / "operations.json").read_bytes()
        except Exception:
            return b"{}"

    def _agent_token(self) -> str:
        try:
            return (
                (self.project_dir / ".agent-token").read_text(encoding="utf-8").strip()
            )
        except Exception:
            return ""

    def _origin_allowed(self, origin: str) -> bool:
        """Loopback, or the one public origin the host is currently sharing.

        AgentAppManager.start_tunnel writes `.tunnel-origin` and stop_tunnel
        deletes it, so the grant lasts exactly as long as the tunnel. Read per
        request for the same reason the native guard does: sharing starts and
        stops without restarting anything. Loopback-only was not a safe
        default for a shared app, it was a broken one — browsers send `Origin`
        on same-origin writes too, so through a tunnel every write was refused.
        """
        if LOOPBACK_ORIGIN.match(origin):
            return True
        try:
            shared = (
                (self.project_dir / ".tunnel-origin")
                .read_text(encoding="utf-8")
                .strip()
            )
        except Exception:
            return False  # no file = not sharing = loopback only
        return bool(shared) and origin.lower() == shared.lower()

    def _json(self, request, status: int, payload: Dict[str, Any]):
        from aiohttp import web

        resp = web.json_response(payload, status=status)
        self._reflect_cors(request, resp)
        return resp

    def _reflect_cors(self, request, resp) -> None:
        """Loopback and the shared origin get the grant reflected; foreign
        origins get nothing, so the browser refuses to expose the response —
        the same posture as the native origin guard."""
        origin = request.headers.get("Origin", "")
        if origin and self._origin_allowed(origin):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"

    def _log_action(self, entry: Dict[str, Any]) -> None:
        try:
            logs = self.project_dir / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            with open(logs / "agent-actions.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # logging must never break a write

    # ── routing ────────────────────────────────────────────────────────────

    async def _handle(self, request):
        path = request.path
        if request.method == "GET" and path == "/api/_a2app":
            return self._identity(request)
        if request.method == "GET" and path == "/api/_a2app/describe":
            return self._describe(request)
        if request.method == "GET" and path == "/api/_ops":
            return self._ops_manifest(request)
        if path == "/api/ops" or path.startswith("/api/ops/"):
            return await self._invoke(request)
        return await self._passthrough(request)

    # ── A2App endpoints ────────────────────────────────────────────────────

    def _identity(self, request):
        return self._json(
            request,
            200,
            {
                "a2app": True,
                "protocol": "1.0",
                "adapterVersion": EXTERNAL_ADAPTER_VERSION,
                "flavor": "external",
                "app": {
                    "id": self.app_id,
                    "name": self.app_name,
                    "runtime": self.app_runtime,
                },
                # Externals have no dev/promote lifecycle: this IS the app.
                "env": "live",
                "schemaVersion": _schema_version(self._ops_raw()),
                "serverNow": _server_now(),
                "serverTzOffsetMinutes": _tz_offset_minutes(),
            },
        )

    def _describe(self, request):
        manifest, problems = load_external_manifest(self.project_dir)
        operations = manifest.get("operations") if not problems else []
        return self._json(
            request,
            200,
            {
                "a2app": True,
                "protocol": "1.0",
                "adapterVersion": EXTERNAL_ADAPTER_VERSION,
                "flavor": "external",
                "schemaVersion": _schema_version(self._ops_raw()),
                "serverNow": _server_now(),
                # Externals are the operations slice: the foreign data model is
                # not mapped into protocol entities (see the design doc's
                # Non-goals). Empty means "no guarded collection surface",
                # not "unknown".
                "entities": {},
                "operations": operations if isinstance(operations, list) else [],
                "conventions": EXTERNAL_CONVENTIONS,
            },
        )

    def _ops_manifest(self, request):
        from aiohttp import web

        resp = web.Response(body=self._ops_raw(), content_type="application/json")
        self._reflect_cors(request, resp)
        return resp

    # ── operation invocation ───────────────────────────────────────────────

    async def _invoke(self, request):
        origin = request.headers.get("Origin", "")
        agent = request.headers.get("X-LUI-Agent", "unknown")[:120]

        # Check 1 (browser): mutations from foreign origins are refused
        # outright; loopback origins are the app's own UI and pass free, as
        # does the shared origin while the user is tunnelling this app.
        if origin and not self._origin_allowed(origin):
            if request.method in MUTATING:
                return self._json(
                    request,
                    403,
                    {
                        "a2app": True,
                        "ok": False,
                        "code": "forbidden_origin",
                        "message": "Cross-origin writes are not allowed.",
                    },
                )
        # Check 2 (programs): no Origin means a programmatic caller — a
        # mutation must present the project's agent token. A project with no
        # token provisioned is never locked out (native parity).
        elif not origin and request.method in MUTATING:
            expected = self._agent_token()
            presented = request.headers.get("X-LUI-Token", "").strip()
            if expected and presented != expected:
                return self._json(
                    request,
                    401,
                    {
                        "a2app": True,
                        "ok": False,
                        "code": "unauthorized",
                        "message": "agent token required",
                        "hint": (
                            "Send X-LUI-Token: <contents of the project "
                            ".agent-token file> on writes."
                        ),
                    },
                )

        manifest, problems = load_external_manifest(self.project_dir)
        if problems:
            return self._json(
                request,
                500,
                {
                    "a2app": True,
                    "ok": False,
                    "code": "invalid_manifest",
                    "message": "operations.json failed validation.",
                    "violations": problems[:20],
                },
            )
        op = None
        for candidate in manifest.get("operations", []):
            executor = candidate.get("executor") or {}
            if (
                executor.get("path") == request.path
                and executor.get("method") == request.method
            ):
                op = candidate
                break
        if op is None:
            declared = [
                f"{(o.get('executor') or {}).get('method')} "
                f"{(o.get('executor') or {}).get('path')}"
                for o in manifest.get("operations", [])
            ]
            return self._json(
                request,
                404,
                {
                    "a2app": True,
                    "ok": False,
                    "code": "unknown_operation",
                    "message": (
                        f"No declared operation matches {request.method} "
                        f"{request.path}. Declared: {declared or 'none'}"
                    ),
                },
            )

        params, violation = await self._extract_params(request)
        if violation is not None:
            return self._json(request, 400, violation)
        values, violations = _validate_params(op, params)
        if violations:
            first = violations[0]
            return self._json(
                request,
                400,
                {
                    "a2app": True,
                    "ok": False,
                    "code": first["code"],
                    "param": first.get("param"),
                    "expected": first.get("expected"),
                    "got": first.get("got"),
                    "serverNow": _server_now(),
                    "message": (
                        f"Rejected by a2app ({first['code']}"
                        + (f": {first['param']}" if first.get("param") else "")
                        + "). All violations listed — one round trip fixes "
                        "them all."
                    ),
                    "violations": violations,
                },
            )

        status, body, ctype, err_code = await self._call_upstream(op, values)
        self._log_action(
            {
                "ts": _server_now(),
                "agent": agent,
                "op": op["name"],
                "params": sorted(values.keys()),
                "upstreamStatus": status,
                "verdict": "ok" if err_code is None and status < 400 else "error",
            }
        )
        if err_code is not None:
            return self._json(
                request,
                502,
                {
                    "a2app": True,
                    "ok": False,
                    "code": err_code,
                    "message": (
                        f"The app did not answer on its internal port "
                        f"({self.upstream_port}): {body[:EXCERPT]}"
                    ),
                },
            )
        if status >= 400:
            return self._json(
                request,
                status,
                {
                    "a2app": True,
                    "ok": False,
                    "code": "upstream_error",
                    "upstreamStatus": status,
                    "upstreamBody": body[:EXCERPT],
                    "message": (
                        f"The app rejected the mapped call for "
                        f"'{op['name']}' with HTTP {status}."
                    ),
                },
            )
        from aiohttp import web

        resp = web.Response(
            status=status,
            body=body.encode("utf-8"),
            content_type=ctype or "application/json",
        )
        self._reflect_cors(request, resp)
        return resp

    async def _extract_params(
        self, request
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        if request.method in ("GET", "DELETE"):
            return {k: request.query[k] for k in request.query.keys()}, None
        raw = await request.read()
        if not raw:
            return {}, None
        try:
            body = json.loads(raw)
        except Exception:
            return {}, {
                "a2app": True,
                "ok": False,
                "code": "invalid_body",
                "message": "Request body must be a JSON object of parameters.",
            }
        if not isinstance(body, dict):
            return {}, {
                "a2app": True,
                "ok": False,
                "code": "invalid_body",
                "message": "Request body must be a JSON object of parameters.",
            }
        return body, None

    async def _call_upstream(
        self, op: Dict[str, Any], values: Dict[str, Any]
    ) -> Tuple[int, str, Optional[str], Optional[str]]:
        """Execute the mapped call. Returns (status, body, content_type,
        error_code) — error_code is set only when the app was unreachable."""
        import aiohttp

        upstream = op["executor"]["upstream"]
        method = upstream["method"]
        path = upstream["path"]
        used_in_path = set()
        for ph in PLACEHOLDER_RE.findall(path):
            used_in_path.add(ph)
            path = path.replace(
                "{{" + ph + "}}", quote(str(values.get(ph, "")), safe="")
            )
        leftover = {k: v for k, v in values.items() if k not in used_in_path}

        url = self._upstream_base() + path
        kwargs: Dict[str, Any] = {
            "timeout": aiohttp.ClientTimeout(
                total=float(upstream.get("timeoutSeconds", 60))
            )
        }
        template = upstream.get("body")
        if template is not None:
            kwargs["json"] = _fill_template(template, values)
        elif leftover:
            if method in ("GET", "DELETE"):
                url += ("&" if "?" in url else "?") + urlencode(
                    {k: str(v) for k, v in leftover.items()}
                )
            else:
                kwargs["json"] = leftover

        try:
            async with self._session.request(method, url, **kwargs) as up:
                body = (await up.content.read(UPSTREAM_BODY_CAP)).decode(
                    "utf-8", errors="replace"
                )
                return up.status, body, up.content_type, None
        except Exception as e:
            return 0, str(e), None, "upstream_unreachable"

    # ── passthrough ────────────────────────────────────────────────────────

    async def _passthrough(self, request):
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._ws_passthrough(request)

        from aiohttp import web

        url = self._upstream_base() + str(request.rel_url)
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS
        }
        try:
            async with self._session.request(
                request.method,
                url,
                headers=headers,
                data=request.content if request.body_exists else None,
                allow_redirects=False,
            ) as up:
                resp = web.StreamResponse(status=up.status)
                for k, v in up.headers.items():
                    if k.lower() not in HOP_HEADERS:
                        resp.headers[k] = v
                await resp.prepare(request)
                async for chunk in up.content.iter_chunked(64 * 1024):
                    await resp.write(chunk)
                await resp.write_eof()
                return resp
        except (ConnectionResetError, ConnectionAbortedError):
            raise
        except Exception as e:
            return self._json(
                request,
                502,
                {
                    "a2app": True,
                    "ok": False,
                    "code": "upstream_unreachable",
                    "message": (
                        f"The app is not answering on its internal port "
                        f"({self.upstream_port}): {str(e)[:300]}"
                    ),
                },
            )

    async def _ws_passthrough(self, request):
        import asyncio

        import aiohttp
        from aiohttp import web

        protocols = tuple(
            p.strip()
            for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
            if p.strip()
        )
        server_ws = web.WebSocketResponse(protocols=protocols)
        await server_ws.prepare(request)
        url = self._upstream_base() + str(request.rel_url)
        try:
            client_ws = await self._session.ws_connect(url, protocols=protocols)
        except Exception:
            await server_ws.close()
            return server_ws

        async def pump(src, dst):
            async for msg in src:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await dst.send_str(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await dst.send_bytes(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break

        try:
            await asyncio.wait(
                [
                    asyncio.ensure_future(pump(server_ws, client_ws)),
                    asyncio.ensure_future(pump(client_ws, server_ws)),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            try:
                await client_ws.close()
            except Exception:
                pass
            try:
                await server_ws.close()
            except Exception:
                pass
        return server_ws


# ── param validation (pure, shared with tests) ─────────────────────────────


def _validate_params(
    op: Dict[str, Any], supplied: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Coerce + validate supplied params against the op's declarations.
    Returns (typed values with defaults applied, violations). Strict on
    unknown params — silently dropping input is how silent-200 bugs start."""
    declared: Dict[str, Any] = op.get("params") or {}
    violations: List[Dict[str, Any]] = []
    values: Dict[str, Any] = {}

    for key in supplied:
        if key not in declared:
            violations.append(
                {
                    "code": "unknown_param",
                    "param": key,
                    "expected": f"one of: {sorted(declared) or 'none'}",
                }
            )
    for pname, spec in declared.items():
        if pname in supplied:
            raw = supplied[pname]
        elif "default" in spec:
            raw = spec["default"]
        elif spec.get("required") is True:
            violations.append(
                {
                    "code": "missing_param",
                    "param": pname,
                    "expected": spec.get("type", "string"),
                }
            )
            continue
        else:
            continue

        ptype = spec.get("type", "string")
        value: Any = raw
        if ptype == "number":
            if isinstance(raw, bool) or (
                not isinstance(raw, (int, float)) and not _is_numeric_string(raw)
            ):
                violations.append(
                    {
                        "code": "invalid_number",
                        "param": pname,
                        "expected": "a number",
                        "got": repr(raw),
                    }
                )
                continue
            value = float(raw) if not isinstance(raw, (int, float)) else raw
            if isinstance(value, float) and value.is_integer():
                value = int(value)
        elif ptype == "boolean":
            if isinstance(raw, bool):
                value = raw
            elif isinstance(raw, str) and raw.lower() in ("true", "false"):
                value = raw.lower() == "true"
            else:
                violations.append(
                    {
                        "code": "invalid_boolean",
                        "param": pname,
                        "expected": "true or false",
                        "got": repr(raw),
                    }
                )
                continue
        else:
            if not isinstance(raw, str):
                violations.append(
                    {
                        "code": "invalid_string",
                        "param": pname,
                        "expected": "a string",
                        "got": repr(raw),
                    }
                )
                continue
            value = raw
        enum = spec.get("enum")
        if isinstance(enum, list) and enum and value not in enum:
            violations.append(
                {
                    "code": "invalid_enum",
                    "param": pname,
                    "expected": f"one of {enum}",
                    "got": repr(value),
                }
            )
            continue
        values[pname] = value
    return values, violations


def _is_numeric_string(raw: Any) -> bool:
    if not isinstance(raw, str):
        return False
    try:
        float(raw)
        return True
    except ValueError:
        return False


def _fill_template(template: Dict[str, Any], values: Dict[str, Any]) -> Any:
    """Build an upstream body from the declared template. A value that IS a
    single placeholder gets the typed param (numbers stay numbers); embedded
    placeholders interpolate as strings; nested objects recurse."""

    def fill(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v) for v in node]
        if isinstance(node, str):
            exact = PLACEHOLDER_RE.fullmatch(node)
            if exact:
                return values.get(exact.group(1))
            return PLACEHOLDER_RE.sub(lambda m: str(values.get(m.group(1), "")), node)
        return node

    return fill(template)
