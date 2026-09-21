"""Handshake guard for the browser UI's /ws WebSocket.

Browsers apply no CORS to WebSocket handshakes, so without a check any page
the user opens could drive the agent through /ws. Two independent checks:

1. Origin (and Host) — the handshake must come from CraftBot's own UI origin,
   addressed by a loopback name. The Host check defeats DNS rebinding.
2. Session token — a random secret generated at startup. The UI reads it from
   GET /api/session-token (same-origin only: no CORS headers, so a foreign
   page can't read the response) and sends it in Sec-WebSocket-Protocol, which
   keeps it out of URLs and access logs.

Legitimate UI origins: the frontend port (Vite dev server, or run.py's static
server) and the backend port (aiohttp serving the built UI itself), each as
localhost / 127.0.0.1 / [::1]. Tunnels and LAN URLs only ever expose Agent App
ports, never this UI, so they are not allowed here.
"""

from __future__ import annotations

import hmac
import os
import secrets
from typing import Mapping, Optional, Set

# Subprotocol the server echoes back; the token rides alongside it as
# "craftbot-auth.<token>" in the client's protocol list.
WS_PROTOCOL = "craftbot"
WS_TOKEN_PROTOCOL_PREFIX = "craftbot-auth."

_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")
_DEFAULT_FRONTEND_PORT = 7925


def _ui_ports(backend_port: int) -> Set[int]:
    ports = {int(backend_port)}
    try:
        ports.add(int(os.environ.get("VITE_PORT", _DEFAULT_FRONTEND_PORT)))
    except ValueError:
        ports.add(_DEFAULT_FRONTEND_PORT)
    return ports


class WsAuth:
    """Origin/Host allowlist plus the per-process session token."""

    def __init__(self, backend_port: int, token: Optional[str] = None) -> None:
        ports = _ui_ports(backend_port)
        self.allowed_hosts: Set[str] = {
            f"{h}:{p}" for h in _LOOPBACK_HOSTS for p in ports
        }
        self.allowed_origins: Set[str] = {
            f"http://{hp}" for hp in self.allowed_hosts
        }
        self.token: str = token or secrets.token_hex(32)

    # -- individual checks -------------------------------------------------

    def host_ok(self, host: Optional[str]) -> bool:
        return bool(host) and host.lower() in self.allowed_hosts

    def origin_ok(self, origin: Optional[str]) -> bool:
        return bool(origin) and origin.lower().rstrip("/") in self.allowed_origins

    def token_ok(self, presented: Optional[str]) -> bool:
        if not presented:
            return False
        return hmac.compare_digest(presented.encode(), self.token.encode())

    @staticmethod
    def token_from_protocols(header: Optional[str]) -> Optional[str]:
        """Pull the token out of a Sec-WebSocket-Protocol header value."""
        for proto in (header or "").split(","):
            proto = proto.strip()
            if proto.startswith(WS_TOKEN_PROTOCOL_PREFIX):
                return proto[len(WS_TOKEN_PROTOCOL_PREFIX):]
        return None

    # -- request-level decisions ------------------------------------------

    def check_ws_handshake(self, headers: Mapping[str, str]) -> Optional[str]:
        """Return None if the handshake may proceed, else the rejection reason."""
        if not self.host_ok(headers.get("Host")):
            return "host"
        if not self.origin_ok(headers.get("Origin")):
            return "origin"
        if not self.token_ok(
            self.token_from_protocols(headers.get("Sec-WebSocket-Protocol"))
        ):
            return "token"
        return None

    def check_token_request(self, headers: Mapping[str, str]) -> Optional[str]:
        """Return None if GET /api/session-token may be served, else the reason.

        The main protection is that the response carries no CORS headers, so a
        cross-origin page can't read it. These checks add defense in depth:
        a rebinding Host, a foreign Origin, or a browser-labelled cross-site
        fetch are refused outright.
        """
        if not self.host_ok(headers.get("Host")):
            return "host"
        origin = headers.get("Origin")
        if origin is not None and not self.origin_ok(origin):
            return "origin"
        site = headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return "fetch-site"
        return None

