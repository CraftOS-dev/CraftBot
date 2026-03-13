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
"""

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
from typing import Optional, Tuple

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

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

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
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
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


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handler for OAuth callback requests."""

    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        """Handle GET request from OAuth callback."""
        params = parse_qs(urlparse(self.path).query)
        _OAuthCallbackHandler.code = params.get("code", [None])[0]
        _OAuthCallbackHandler.state = params.get("state", [None])[0]
        _OAuthCallbackHandler.error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if _OAuthCallbackHandler.code:
            self.wfile.write(
                b"<h2>Authorization successful!</h2><p>You can close this tab.</p>"
            )
        else:
            self.wfile.write(
                f"<h2>Failed</h2><p>{_OAuthCallbackHandler.error}</p>".encode()
            )

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass


def _serve_until_code(server: HTTPServer, deadline: float) -> None:
    """
    Handle requests in a loop until we capture the OAuth code/error or timeout.

    A single handle_request() can be consumed by TLS handshake failures,
    favicon requests, browser pre-connects, etc. Looping ensures the server
    stays alive for the actual callback.
    """
    while time.time() < deadline:
        remaining = max(0.5, deadline - time.time())
        server.timeout = min(remaining, 2.0)
        try:
            server.handle_request()
        except Exception as e:
            logger.debug(f"[OAUTH] handle_request error (will retry): {e}")
        if _OAuthCallbackHandler.code or _OAuthCallbackHandler.error:
            break


def run_oauth_flow(
    auth_url: str, port: int = 8765, timeout: int = 120, use_https: bool = False
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

    Returns:
        Tuple of (code, error_message):
        - On success: (authorization_code, None)
        - On failure: (None, error_message)
    """
    _OAuthCallbackHandler.code = None
    _OAuthCallbackHandler.state = None
    _OAuthCallbackHandler.error = None

    server = HTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)

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
    logger.info(f"[OAUTH] {scheme.upper()} server listening on {scheme}://127.0.0.1:{port}")

    deadline = time.time() + timeout
    thread = threading.Thread(
        target=_serve_until_code, args=(server, deadline), daemon=True
    )
    thread.start()

    try:
        webbrowser.open(auth_url)
    except Exception:
        server.server_close()
        return None, f"Could not open browser. Visit manually:\n{auth_url}"

    thread.join(timeout=timeout)
    server.server_close()

    if _OAuthCallbackHandler.error:
        return None, _OAuthCallbackHandler.error
    if _OAuthCallbackHandler.code:
        return _OAuthCallbackHandler.code, None
    return None, "OAuth timed out."
