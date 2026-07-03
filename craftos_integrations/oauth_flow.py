"""OAuth localhost callback server + OAuthFlow composition helper.

This module is fully self-contained: it provides everything an OAuth
handler needs without reaching outside the package.

Two pieces:

  1. _run_localhost_callback(auth_url, *, use_https=False, ...) -> (code, error)
     Spins up a local HTTP/HTTPS server on port 8765, opens the browser,
     waits for the OAuth redirect, returns (code, error). Used as the
     default oauth_runner unless the host injects one via configure().

  2. OAuthFlow — class that handlers compose (not subclass). Wraps the
     full OAuth dance: build URL, run callback server, exchange tokens,
     optionally fetch userinfo. Returns a dict with tokens + userinfo.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import ipaddress
import os
import secrets
import ssl
import tempfile
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from .config import ConfigStore
from .helpers import request as http_request
from .logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════════
# Localhost callback server (ported from agent_core.oauth_server)
# ════════════════════════════════════════════════════════════════════════


def _generate_self_signed_cert() -> Tuple[str, str]:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_fd, cert_path = tempfile.mkstemp(suffix=".pem", prefix="oauth_cert_")
    key_fd, key_path = tempfile.mkstemp(suffix=".pem", prefix="oauth_key_")
    try:
        os.write(cert_fd, cert_pem)
        os.close(cert_fd)
        os.write(key_fd, key_pem)
        os.close(key_fd)
    except Exception:
        os.close(cert_fd)
        os.close(key_fd)
        _cleanup_files(cert_path, key_path)
        raise
    return cert_path, key_path


def _cleanup_files(*paths: str) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


def _make_callback_handler(result_holder: Dict[str, Any]):
    class _OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            params = parse_qs(parsed.query)

            # Ignore non-callback paths (favicon.ico, /, etc). Browsers fire
            # these automatically and they have no OAuth params — without
            # this filter they'd be misread as a failed callback and would
            # overwrite a successful result. Configured callback path is
            # stored on the holder; empty/"/" means "any path counts".
            expected_path = result_holder.get("expected_path") or "/"
            if expected_path and expected_path != "/" and path != expected_path:
                self.send_response(204)
                self.end_headers()
                return

            # If the result is already settled, treat any extra request as
            # noise — don't let it mutate state. Send a quiet 204.
            if result_holder.get("code") or result_holder.get("error"):
                self.send_response(204)
                self.end_headers()
                return

            returned_state = params.get("state", [None])[0]
            oauth_error = params.get("error", [None])[0]
            oauth_error_description = params.get("error_description", [""])[0]
            code = params.get("code", [None])[0]
            expected_state = result_holder.get("expected_state")

            # Decide what kind of response this is:
            #   1. Provider returned an error → preserve the real error text;
            #      do NOT rewrite it as "state mismatch" even if state is
            #      absent (providers commonly omit state on error responses).
            #   2. Otherwise, if state is present and doesn't match → real
            #      CSRF-style mismatch on a success response.
            #   3. Otherwise, success: extract the code.
            if oauth_error:
                result_holder["error"] = (
                    f"{oauth_error}: {oauth_error_description}"
                    if oauth_error_description
                    else oauth_error
                )
            elif expected_state and returned_state and returned_state != expected_state:
                result_holder["error"] = "OAuth state mismatch — possible CSRF attack"
            elif expected_state and not returned_state and not code:
                # Empty callback that's neither a success nor a declared
                # error — surface that as a distinct failure so we don't
                # mislabel it as CSRF.
                result_holder["error"] = (
                    "OAuth callback returned no code, no error, and no state"
                )
            else:
                result_holder["code"] = code
                if not code:
                    result_holder["error"] = "OAuth callback returned no code"

            # Log the raw callback path for debugging — redact `code` since
            # it's an authorization grant the agent can later exchange.
            try:
                from .logger import get_logger as _gl

                redacted_params = {
                    k: ("<redacted>" if k == "code" else v) for k, v in params.items()
                }
                _gl(__name__).info(
                    f"[OAUTH] callback received path={path} params={redacted_params}"
                )
            except Exception:
                pass

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if result_holder.get("code"):
                self.wfile.write(
                    b"<h2>Authorization successful!</h2><p>You can close this tab.</p>"
                )
            else:
                safe = html.escape(str(result_holder.get("error") or "Unknown error"))
                self.wfile.write(f"<h2>Failed</h2><p>{safe}</p>".encode())

        def log_message(self, format, *args):
            pass

    return _OAuthCallbackHandler


def _serve_until_code(
    server: HTTPServer,
    deadline: float,
    result_holder: Dict[str, Any],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    while time.time() < deadline:
        if cancel_event and cancel_event.is_set():
            break
        remaining = max(0.1, deadline - time.time())
        server.timeout = min(remaining, 0.5)
        try:
            server.handle_request()
        except Exception:
            pass
        if result_holder.get("code") or result_holder.get("error"):
            break


def _run_oauth_flow_sync(
    auth_url: str,
    port: int = 8765,
    timeout: int = 120,
    use_https: bool = False,
    cancel_event: Optional[threading.Event] = None,
    expected_path: str = "/",
) -> Tuple[Optional[str], Optional[str]]:
    if cancel_event and cancel_event.is_set():
        return None, "OAuth cancelled"

    expected_state = parse_qs(urlparse(auth_url).query).get("state", [None])[0]
    result_holder: Dict[str, Any] = {
        "code": None,
        "state": None,
        "error": None,
        "expected_state": expected_state,
        "expected_path": expected_path,
    }
    handler_class = _make_callback_handler(result_holder)

    try:
        server = HTTPServer(("127.0.0.1", port), handler_class)
    except OSError as e:
        return None, f"Failed to start OAuth server: {e}"

    if use_https:
        cert_path = key_path = None
        try:
            cert_path, key_path = _generate_self_signed_cert()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert_path, key_path)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
        except Exception as e:
            _cleanup_files(cert_path or "", key_path or "")
            server.server_close()
            return None, f"Failed to set up HTTPS for OAuth: {e}"
        finally:
            _cleanup_files(cert_path or "", key_path or "")

    scheme = "https" if use_https else "http"
    logger.info(
        f"[OAUTH] {scheme.upper()} server listening on {scheme}://127.0.0.1:{port}"
    )

    deadline = time.time() + timeout
    thread = threading.Thread(
        target=_serve_until_code,
        args=(server, deadline, result_holder, cancel_event),
        daemon=True,
    )
    thread.start()

    if cancel_event and cancel_event.is_set():
        server.server_close()
        return None, "OAuth cancelled"

    try:
        webbrowser.open(auth_url)
    except Exception:
        server.server_close()
        return None, f"Could not open browser. Visit manually:\n{auth_url}"

    while thread.is_alive():
        thread.join(timeout=0.5)
        if cancel_event and cancel_event.is_set():
            break

    server.server_close()

    if cancel_event and cancel_event.is_set():
        return None, "OAuth cancelled"
    if result_holder.get("error"):
        return None, result_holder["error"]
    if result_holder.get("code"):
        return result_holder["code"], None
    return None, "OAuth timed out."


async def run_localhost_callback(
    auth_url: str,
    *,
    port: int = 8765,
    timeout: int = 120,
    use_https: bool = False,
    expected_path: str = "/",
) -> Tuple[Optional[str], Optional[str]]:
    """Default OAuth runner. Returns (code, error)."""
    cancel_event = threading.Event()
    loop = asyncio.get_running_loop()

    def run_flow():
        return _run_oauth_flow_sync(
            auth_url=auth_url,
            port=port,
            timeout=timeout,
            use_https=use_https,
            cancel_event=cancel_event,
            expected_path=expected_path,
        )

    try:
        return await loop.run_in_executor(None, run_flow)
    except asyncio.CancelledError:
        cancel_event.set()
        raise


async def get_oauth_runner(
    auth_url: str,
    *,
    use_https: bool = False,
    port: int = 8765,
    expected_path: str = "/",
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve and call the configured oauth_runner (or the default).

    ``port`` and ``expected_path`` are forwarded only when the runner accepts
    them — older host-injected runners predate the kwargs, so we degrade to
    the older call shapes on ``TypeError``. Existing flows (port=8765,
    expected_path="/") hit the same code path as before.
    """
    runner = ConfigStore.oauth_runner or run_localhost_callback
    try:
        return await runner(
            auth_url, use_https=use_https, port=port, expected_path=expected_path
        )
    except TypeError:
        try:
            return await runner(auth_url, use_https=use_https, port=port)
        except TypeError:
            return await runner(auth_url, use_https=use_https)


# ════════════════════════════════════════════════════════════════════════
# OAuthFlow — composition helper for handlers
# ════════════════════════════════════════════════════════════════════════

REDIRECT_URI = "http://localhost:8765"
REDIRECT_URI_HTTPS = "https://localhost:8765"


class OAuthFlow:
    """Composition helper: handlers hold an OAuthFlow instance.

    Usage in a handler:
        oauth = OAuthFlow(
            client_id_key="GOOGLE_CLIENT_ID",
            client_secret_key="GOOGLE_CLIENT_SECRET",
            auth_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://www.googleapis.com/oauth2/v2/userinfo",
            scopes=GOOGLE_SCOPES,
            use_pkce=True,
        )

        result = await self.oauth.run()
        if result.get("error"):
            return False, result["error"]
        save_credential(self.spec.cred_file, MyCredential(
            access_token=result["access_token"],
            email=result["userinfo"]["email"],
        ))
    """

    def __init__(
        self,
        *,
        client_id_key: Optional[str] = None,
        client_secret_key: Optional[str] = None,
        auth_url: str,
        token_url: str,
        userinfo_url: Optional[str] = None,
        scopes: str = "",
        use_pkce: bool = False,
        use_https: bool = False,
        token_auth_basic: bool = False,
        token_request_json: bool = False,
        token_extra_headers: Optional[Dict[str, str]] = None,
        userinfo_extra_headers: Optional[Dict[str, str]] = None,
        extra_auth_params: Optional[Dict[str, str]] = None,
        scope_param: str = "scope",
        client_id_literal: Optional[str] = None,
        callback_port: int = 8765,
        callback_path: str = "",
        callback_host: str = "localhost",
    ):
        self.client_id_key = client_id_key
        self.client_secret_key = client_secret_key
        self.auth_url = auth_url
        self.token_url = token_url
        self.userinfo_url = userinfo_url
        self.scopes = scopes
        self.use_pkce = use_pkce
        self.use_https = use_https
        self.token_auth_basic = token_auth_basic
        self.token_request_json = token_request_json
        self.token_extra_headers = token_extra_headers or {}
        self.userinfo_extra_headers = userinfo_extra_headers or {}
        self.extra_auth_params = extra_auth_params or {}
        self.scope_param = scope_param
        self.client_id_literal = client_id_literal
        self.callback_port = callback_port
        self.callback_path = callback_path
        self.callback_host = callback_host

    @property
    def redirect_uri(self) -> str:
        scheme = "https" if self.use_https else "http"
        if (
            self.callback_port == 8765
            and self.callback_host == "localhost"
            and not self.callback_path
        ):
            return REDIRECT_URI_HTTPS if self.use_https else REDIRECT_URI
        return (
            f"{scheme}://{self.callback_host}:{self.callback_port}{self.callback_path}"
        )

    def _client_id(self) -> Optional[str]:
        if self.client_id_literal:
            return self.client_id_literal
        if not self.client_id_key:
            return None
        return ConfigStore.get_oauth(self.client_id_key) or None

    def _client_secret(self) -> Optional[str]:
        if not self.client_secret_key:
            return None
        return ConfigStore.get_oauth(self.client_secret_key) or None

    def _build_auth_url(self) -> Tuple[str, Dict[str, Any]]:
        client_id = self._client_id()
        if not client_id:
            raise RuntimeError(f"OAuth not configured: missing {self.client_id_key}")

        state = secrets.token_urlsafe(32)
        params: Dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if self.scopes:
            params[self.scope_param] = self.scopes

        ctx: Dict[str, Any] = {"state": state, "client_id": client_id}

        if self.use_pkce:
            verifier = secrets.token_urlsafe(64)[:128]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"
            ctx["code_verifier"] = verifier

        params.update(self.extra_auth_params)
        return f"{self.auth_url}?{urlencode(params)}", ctx

    def _exchange_token_sync(self, code: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Sync token exchange — runs in a worker thread via ``asyncio.to_thread``.

        Intentionally synchronous to side-step async-context detection issues
        that can occur after the OAuth callback executor returns control.
        """
        client_id = ctx["client_id"]
        client_secret = self._client_secret()

        token_data: Dict[str, str] = {
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        if "code_verifier" in ctx:
            token_data["code_verifier"] = ctx["code_verifier"]

        headers: Dict[str, str] = dict(self.token_extra_headers)
        if self.token_auth_basic and client_secret:
            basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {basic}"
        else:
            token_data["client_id"] = client_id
            if client_secret:
                token_data["client_secret"] = client_secret

        if self.token_request_json:
            headers.setdefault("Content-Type", "application/json")
            result = http_request(
                "POST",
                self.token_url,
                json=token_data,
                headers=headers,
                timeout=30.0,
                expected=(200,),
            )
        else:
            result = http_request(
                "POST",
                self.token_url,
                data=token_data,
                headers=headers,
                timeout=30.0,
                expected=(200,),
            )
        if "error" in result:
            return {
                "error": f"Token exchange failed: {result.get('details') or result['error']}"
            }
        return result["result"] or {}

    def _fetch_userinfo_sync(self, access_token: str) -> Dict[str, Any]:
        """Sync userinfo fetch — runs in a worker thread."""
        if not self.userinfo_url:
            return {}
        headers = {"Authorization": f"Bearer {access_token}"}
        headers.update(self.userinfo_extra_headers)
        result = http_request(
            "GET",
            self.userinfo_url,
            headers=headers,
            timeout=30.0,
            expected=(200,),
        )
        if "error" in result:
            logger.warning(f"[OAUTH] userinfo fetch failed: {result['error']}")
            return {}
        return result["result"] or {}

    async def run(self) -> Dict[str, Any]:
        """Run the full OAuth flow.

        Returns a dict:
            On success: {access_token, refresh_token, expires_in, userinfo, raw, ...}
            On failure: {error: "..."}
        """
        try:
            try:
                url, ctx = self._build_auth_url()
            except RuntimeError as e:
                return {"error": str(e)}

            code, error = await get_oauth_runner(
                url,
                use_https=self.use_https,
                port=self.callback_port,
                expected_path=self.callback_path or "/",
            )
            if error:
                return {"error": error}
            if not code:
                return {"error": "OAuth did not return a code"}

            tokens = await asyncio.to_thread(self._exchange_token_sync, code, ctx)
            if "error" in tokens and not tokens.get("access_token"):
                return tokens

            access_token = tokens.get("access_token", "")
            userinfo = (
                await asyncio.to_thread(self._fetch_userinfo_sync, access_token)
                if access_token
                else {}
            )

            return {
                "access_token": access_token,
                "refresh_token": tokens.get("refresh_token", ""),
                "expires_in": tokens.get("expires_in", 0),
                "userinfo": userinfo,
                "raw": tokens,
            }
        except Exception as e:
            logger.exception(f"[OAUTH] flow crashed: {e}")
            return {"error": f"OAuth flow error: {e}"}
