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

Auth mirrors _system.pb.js (see `guard_request`). Two independent checks:
the ORIGIN check refuses foreign-origin mutations outright, and the CALLER
check requires every mutation to carry a credential — X-A2App-Token from the
project's .agent-token (programs, the agent), or the UI session cookie the
app's own browser UI is issued. An allowed Origin is never a credential:
tunnel traffic arrives over loopback and can claim any Origin it likes.
Through a tunnel, every request needs the credential, reads included; the
UI session there is only issued in exchange for the share link's secret.
Ops are (re)read from operations.json on every request, like the native
describe, so the surface can never drift from the file on disk.
"""

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
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

# ── caller authentication (shared with the native guard in _a2app_lib.js) ──
#
# Local vs tunnel cannot be told apart by Origin (a tunnelled caller can send
# a loopback one) nor by peer address (cloudflared connects from loopback).
# It CAN be told apart by what Cloudflare adds to every request it forwards —
# headers a remote caller cannot strip. The test is fail-safe: a local caller
# that fakes one only demotes itself to tunnel rules.
TUNNEL_MARKER_HEADERS = (
    "cf-ray",
    "cf-connecting-ip",
    "cf-visitor",
    "cdn-loop",
    "x-forwarded-for",
    "x-forwarded-host",
    "forwarded",
)
LOOPBACK_HOST = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", re.I)
SHARE_PARAM = "a2app_share"
TOKEN_HEADERS = ("X-A2App-Token", "X-LUI-Token")  # TODO(lui-compat): legacy


def _hs256(secret: str, text: str) -> str:
    """HMAC-SHA256 hex — the same construction as PocketBase's
    $security.hs256(text, secret), so both adapters derive identical values."""
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def _read_secret(project_dir: Path, name: str) -> str:
    try:
        return (Path(project_dir) / name).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def origin_allowed(project_dir: Path, origin: str) -> bool:
    """Loopback, or the one public origin the host is currently sharing.

    AgentAppManager.start_tunnel writes `.tunnel-origin` and stop_tunnel
    deletes it, so the grant lasts exactly as long as the tunnel. Read per
    request for the same reason the native guard does: sharing starts and
    stops without restarting anything. Loopback-only was not a safe default
    for a shared app, it was a broken one — browsers send `Origin` on
    same-origin writes too, so through a tunnel every write was refused.
    This decides which browser pages may TALK to the app; it authenticates
    nobody (see guard_request).
    """
    if LOOPBACK_ORIGIN.match(origin):
        return True
    shared = _read_secret(project_dir, ".tunnel-origin")
    return bool(shared) and origin.lower() == shared.lower()


def is_tunnel_request(headers: Mapping[str, str]) -> bool:
    """True when the request came in through the share tunnel (or cannot be
    proven local). Local = no forwarding marker AND a loopback Host."""
    lowered = {k.lower() for k in headers.keys()}
    if any(h in lowered for h in TUNNEL_MARKER_HEADERS):
        return True
    host = next((v for k, v in headers.items() if k.lower() == "host"), "")
    return not LOOPBACK_HOST.match(host.strip())


def session_cookie_name(agent_token: str) -> str:
    """Per-app name: every app on 127.0.0.1 shares ONE cookie jar (cookies
    ignore ports), so a fixed name would have apps overwrite each other."""
    return "a2app_s_" + _hs256(agent_token, "a2app-ui:cookie-name:v1")[:12]


def session_value(project_dir: Path, agent_token: str, tunnel: bool) -> str:
    """The UI session credential for this ingress, or "" if none can exist.

    Stateless (derived, never stored): rotating the agent token ends every
    session. Local and tunnel values differ, so a local cookie is never a
    tunnel credential; the tunnel value folds in `.tunnel-secret`, which
    stop_tunnel deletes — every shared session dies with the tunnel."""
    if not agent_token:
        return ""
    if not tunnel:
        return _hs256(agent_token, "a2app-ui:local:v1")
    secret = _read_secret(project_dir, ".tunnel-secret")
    if not secret:
        return ""
    return _hs256(agent_token, "a2app-ui:share:v1:" + secret)


def session_cookie_header(name: str, value: str, tunnel: bool) -> str:
    # Lax, not Strict: a share link opened from chat is a cross-site
    # navigation, and Strict would withhold the cookie on the redirect that
    # follows the exchange. Writes do not lean on SameSite — the origin check
    # and the per-ingress value do that work.
    return (
        f"{name}={value}; Path=/; HttpOnly; SameSite=Lax"
        + ("; Secure" if tunnel else "")
    )


def guard_request(
    project_dir: Path,
    method: str,
    headers: Mapping[str, str],
    cookies: Mapping[str, str],
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """THE caller guard: None to proceed, else (status, error envelope).

    Two independent checks, in order:
      1. Origin — a foreign Origin on a mutation is refused (403). Reads pass:
         for those, withholding the CORS grant is the browser-side defence.
      2. Caller — a mutation, or ANY request through the tunnel, must carry
         a credential: the agent token (constant-time compare) or this
         ingress's UI session cookie. The Origin plays no part here.
    A project with no agent token provisioned is never locked out (native
    parity: the token is minted at launch, so this is a pre-launch edge).
    """
    method = method.upper()
    mutating = method in MUTATING
    origin = next((v for k, v in headers.items() if k.lower() == "origin"), "")
    if origin and mutating and not origin_allowed(project_dir, origin):
        return 403, {
            "a2app": True,
            "ok": False,
            "code": "forbidden_origin",
            "message": "Cross-origin writes are not allowed.",
        }

    tunnel = is_tunnel_request(headers)
    # Preflights never carry credentials (browsers strip them by spec).
    if method == "OPTIONS" or not (mutating or tunnel):
        return None
    expected = _read_secret(project_dir, ".agent-token")
    if not expected:
        return None

    lowered = {k.lower(): v for k, v in headers.items()}
    presented = next(
        (lowered[h.lower()] for h in TOKEN_HEADERS if lowered.get(h.lower())), ""
    ).strip()
    if presented and hmac.compare_digest(presented.encode(), expected.encode()):
        return None
    session = session_value(project_dir, expected, tunnel)
    cookie = cookies.get(session_cookie_name(expected), "")
    if session and cookie and hmac.compare_digest(cookie.encode(), session.encode()):
        return None

    if tunnel:
        return 401, {
            "a2app": True,
            "ok": False,
            "code": "share_session_required",
            "message": (
                "This app is shared by link. Open the full share link you "
                "were given (it carries ?a2app_share=...)."
            ),
        }
    return 401, {
        "a2app": True,
        "ok": False,
        "code": "unauthorized",
        "message": "agent token required",
        "hint": (
            "Send X-A2App-Token: <contents of the project .agent-token "
            "file> on writes."
        ),
    }


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
        "Send X-A2App-Agent: <your agent id> on writes; it is recorded in the "
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

    def _origin_allowed(self, origin: str) -> bool:
        return origin_allowed(self.project_dir, origin)

    def _deny(self, request):
        """guard_request as a response: None to proceed, else the refusal."""
        denied = guard_request(
            self.project_dir, request.method, request.headers, request.cookies
        )
        if denied is None:
            return None
        return self._json(request, denied[0], denied[1])

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
        if (
            request.method == "GET"
            and SHARE_PARAM in request.query
            and is_tunnel_request(request.headers)
        ):
            return self._share_exchange(request)
        own = (
            request.method == "GET"
            and path in ("/api/_a2app", "/api/_a2app/describe", "/api/_ops")
        ) or path == "/api/ops" or path.startswith("/api/ops/")
        if own:
            denied = self._deny(request)
            if denied is not None:
                return denied
        if request.method == "GET" and path == "/api/_a2app":
            return self._identity(request)
        if request.method == "GET" and path == "/api/_a2app/describe":
            return self._describe(request)
        if request.method == "GET" and path == "/api/_ops":
            return self._ops_manifest(request)
        if own:
            return await self._invoke(request)
        # TODO(passthrough-auth): the app's own surface is not guarded yet;
        # the follow-up applies guard_request here too.
        return await self._passthrough(request)

    def _share_exchange(self, request):
        """Trade the share link's secret for the tunnel UI session, then
        redirect to the same URL without it (out of the address bar, history
        and anything the visitor copies onward)."""
        from aiohttp import web

        secret = _read_secret(self.project_dir, ".tunnel-secret")
        presented = request.query.get(SHARE_PARAM, "")
        if not (
            secret
            and presented
            and hmac.compare_digest(presented.encode(), secret.encode())
        ):
            return self._json(
                request,
                403,
                {
                    "a2app": True,
                    "ok": False,
                    "code": "share_link_invalid",
                    "message": (
                        "This share link is invalid or has expired. Ask the "
                        "owner for a fresh one."
                    ),
                },
            )
        rest = [(k, v) for k, v in request.query.items() if k != SHARE_PARAM]
        resp = web.HTTPFound(str(request.rel_url.with_query(rest)))
        token = _read_secret(self.project_dir, ".agent-token")
        value = session_value(self.project_dir, token, tunnel=True)
        if value:
            resp.headers["Set-Cookie"] = session_cookie_header(
                session_cookie_name(token), value, tunnel=True
            )
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def _local_session_cookie(self, request) -> Optional[str]:
        """Set-Cookie for the app's own UI on local ingress, when it lacks a
        valid session. Anyone who can reach loopback gets one — which is
        everyone who could already read .agent-token, so it grants nothing
        new; what it replaces is trusting a forgeable Origin header."""
        if is_tunnel_request(request.headers):
            return None
        token = _read_secret(self.project_dir, ".agent-token")
        value = session_value(self.project_dir, token, tunnel=False)
        if not value:
            return None
        name = session_cookie_name(token)
        if request.cookies.get(name) == value:
            return None
        return session_cookie_header(name, value, tunnel=False)

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
        # Caller already cleared guard_request in _handle.
        # TODO(lui-compat): older clients/CLIs send the X-LUI-* header. Accept
        # either signature; drop the X-LUI-* fallback once every deployed app
        # and client speaks X-A2App-*.
        agent = (
            request.headers.get("X-A2App-Agent")
            or request.headers.get("X-LUI-Agent")
            or "unknown"
        )[:120]

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
                # The app's own UI gets its session with the page that boots
                # it; its same-origin fetches then carry it automatically.
                if request.method == "GET" and (up.content_type or "").startswith(
                    "text/html"
                ):
                    cookie = self._local_session_cookie(request)
                    if cookie:
                        resp.headers.add("Set-Cookie", cookie)
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
