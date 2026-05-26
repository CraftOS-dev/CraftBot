# -*- coding: utf-8 -*-
"""
Temporary local HTTP/HTTPS server for OAuth callbacks.

This module provides a simple OAuth callback server that can be used
to capture authorization codes from OAuth flows. Supports both HTTP
(for providers like Google that allow http://localhost) and HTTPS with
an auto-generated self-signed certificate (for providers like Slack
that require https://).

Usage:
    from agent_core.core.credentials.oauth_server import run_oauth_flow

    # HTTP (default — works with Google, Notion, LinkedIn, etc.)
    code, error = run_oauth_flow("https://provider.com/oauth/authorize?...")

    # HTTPS (for Slack and other providers requiring https redirect URIs)
    code, error = run_oauth_flow("https://slack.com/oauth/...", use_https=True)

    # Async version with cancellation support (recommended for UI contexts)
    code, error = await run_oauth_flow_async("https://provider.com/oauth/...")
"""

import asyncio
import html
import ipaddress
import logging
import os
import ssl
import tempfile
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _generate_self_signed_cert() -> Tuple[str, str]:
    """
    Generate a temporary self-signed certificate for localhost.

    Returns:
        Tuple of (cert_path, key_path) — temporary PEM files.
        Caller is responsible for cleanup.
    """
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

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

    # Write to temp files (needed by ssl.SSLContext.load_cert_chain)
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
    """
    Create a callback handler class that stores results in the provided dict.

    This avoids class-level state that would be shared across OAuth flows.
    """

    class _OAuthCallbackHandler(BaseHTTPRequestHandler):
        """Handler for OAuth callback requests."""

        def do_GET(self):
            """Handle GET request from OAuth callback."""
            params = parse_qs(urlparse(self.path).query)
            returned_state = params.get("state", [None])[0]
            result_holder["error"] = params.get("error", [None])[0]

            # Validate OAuth state parameter to prevent CSRF
            expected_state = result_holder.get("expected_state")
            if expected_state and returned_state != expected_state:
                result_holder["error"] = "OAuth state mismatch — possible CSRF attack"
                result_holder["code"] = None
                logger.warning(
                    "[OAUTH] State mismatch: expected %s, got %s",
                    expected_state,
                    returned_state,
                )
            else:
                result_holder["code"] = params.get("code", [None])[0]

            result_holder["state"] = returned_state

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if result_holder["code"]:
                self.wfile.write(
                    b"<h2>Authorization successful!</h2><p>You can close this tab.</p>"
                )
            else:
                safe_error = html.escape(
                    str(result_holder.get("error") or "Unknown error")
                )
                self.wfile.write(f"<h2>Failed</h2><p>{safe_error}</p>".encode())

        def log_message(self, format, *args):
            """Suppress default HTTP server logging."""
            pass

    return _OAuthCallbackHandler


def _serve_until_code(
    server: HTTPServer,
    deadline: float,
    result_holder: Dict[str, Any],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    """
    Handle requests in a loop until we capture the OAuth code/error, timeout, or cancelled.

    A single handle_request() can be consumed by TLS handshake failures,
    favicon requests, browser pre-connects, etc. Looping ensures the server
    stays alive for the actual callback.
    """
    while time.time() < deadline:
        # Check for cancellation
        if cancel_event and cancel_event.is_set():
            logger.debug("[OAUTH] Cancellation requested, stopping server")
            break

        remaining = max(0.1, deadline - time.time())
        # Use shorter timeout (0.5s) for responsive cancellation checking
        server.timeout = min(remaining, 0.5)
        try:
            server.handle_request()
        except Exception as e:
            logger.debug(f"[OAUTH] handle_request error (will retry): {e}")

        if result_holder.get("code") or result_holder.get("error"):
            break


def run_oauth_flow(
    auth_url: str,
    port: int = 8765,
    timeout: int = 120,
    use_https: bool = False,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Open browser for OAuth, wait for callback.

    Args:
        auth_url: The full OAuth authorization URL to open.
        port: Local port for callback server (default: 8765).
        timeout: Seconds to wait for callback (default: 120).
        use_https: If True, serve HTTPS with a self-signed cert.
                   Required for providers like Slack that reject http:// redirect URIs.
                   Default False (plain HTTP — works with Google, Notion, etc.).
        cancel_event: Optional threading.Event to signal cancellation.
                      When set, the OAuth flow will stop and return a cancellation error.

    Returns:
        Tuple of (code, error_message):
        - On success: (authorization_code, None)
        - On failure: (None, error_message)
    """
    # Check for early cancellation
    if cancel_event and cancel_event.is_set():
        return None, "OAuth cancelled"

    # Extract the state parameter from the auth URL for CSRF validation
    auth_params = parse_qs(urlparse(auth_url).query)
    expected_state = auth_params.get("state", [None])[0]

    # Use instance-level result holder instead of class-level state
    result_holder: Dict[str, Any] = {
        "code": None,
        "state": None,
        "error": None,
        "expected_state": expected_state,
    }
    handler_class = _make_callback_handler(result_holder)

    try:
        server = HTTPServer(("127.0.0.1", port), handler_class)
    except OSError as e:
        # Port already in use
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

    # Check cancellation before opening browser
    if cancel_event and cancel_event.is_set():
        server.server_close()
        return None, "OAuth cancelled"

    try:
        webbrowser.open(auth_url)
    except Exception:
        server.server_close()
        return None, f"Could not open browser. Visit manually:\n{auth_url}"

    # Wait for thread with periodic cancellation checks
    while thread.is_alive():
        thread.join(timeout=0.5)
        if cancel_event and cancel_event.is_set():
            logger.debug("[OAUTH] Cancellation detected during wait")
            break

    server.server_close()

    # Check cancellation first
    if cancel_event and cancel_event.is_set():
        return None, "OAuth cancelled"

    if result_holder.get("error"):
        return None, result_holder["error"]
    if result_holder.get("code"):
        return result_holder["code"], None
    return None, "OAuth timed out."


async def run_oauth_flow_async(
    auth_url: str,
    port: int = 8765,
    timeout: int = 120,
    use_https: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Async version of run_oauth_flow with proper cancellation support.

    This function runs the OAuth flow in a thread executor and properly handles
    asyncio task cancellation by signaling the OAuth server to stop.

    Args:
        auth_url: The full OAuth authorization URL to open.
        port: Local port for callback server (default: 8765).
        timeout: Seconds to wait for callback (default: 120).
        use_https: If True, serve HTTPS with a self-signed cert.

    Returns:
        Tuple of (code, error_message):
        - On success: (authorization_code, None)
        - On failure: (None, error_message)

    Raises:
        asyncio.CancelledError: If the task is cancelled (after signaling OAuth to stop)
    """
    cancel_event = threading.Event()
    loop = asyncio.get_event_loop()

    def run_flow():
        return run_oauth_flow(
            auth_url=auth_url,
            port=port,
            timeout=timeout,
            use_https=use_https,
            cancel_event=cancel_event,
        )

    try:
        return await loop.run_in_executor(None, run_flow)
    except asyncio.CancelledError:
        # Signal the OAuth server to stop
        cancel_event.set()
        logger.debug("[OAUTH] Async task cancelled, signaled OAuth server to stop")
        raise
