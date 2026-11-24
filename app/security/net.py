"""Network guard for the agent's web tools (Settings > Security > Network).

On at Enhanced and Strict. For ``http_request`` and ``web_fetch``:

- Every address a host name resolves to must be a public internet address.
  The ``ipaddress`` module classifies it (private, loopback, link-local,
  carrier-grade NAT, reserved, multicast, unspecified are refused), and an
  IPv4-mapped IPv6 address is judged as the IPv4 address it carries
  (OpenClaw CVE-2026-26324). Cloud metadata services sit on link-local
  addresses, so no list of their names is needed.
- A name that does not resolve is refused, not waved through (the old
  check failed open).
- Redirects are followed one hop at a time and every hop is checked again,
  so a public page cannot bounce the request into the local network.
  Credentials (Authorization, Cookie) are not carried to another host.
- With an allowlist set, only those domains and their subdomains are
  reachable.

Name resolution can change between the check and the connection (DNS
rebinding); checking every hop narrows that window but does not close it.
The guard covers the web tools, not commands the agent runs in a shell.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from app.security.policy import SecurityPolicy, get_policy

MAX_REDIRECTS = 10
_CREDENTIAL_HEADERS = ("authorization", "cookie", "proxy-authorization")


class NetworkBlocked(Exception):
    """The guard refused a request; the message says why, for the agent."""


def address_refusal(address: str) -> Optional[str]:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return f"{address} is not an IP address"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return f"{ip} is this computer (loopback)"
    if ip.is_unspecified or ip.is_multicast or not ip.is_global:
        return f"{ip} is not a public internet address"
    return None


def _domain_allowed(host: str, allowed: Iterable[str]) -> bool:
    labels = host.rstrip(".").lower().split(".")
    for entry in allowed:
        wanted = entry.strip().rstrip(".").lower().lstrip("*.").split(".")
        if wanted and labels[-len(wanted):] == wanted:
            return True
    return False


def _resolve(host: str, port: int) -> Tuple[str, ...]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(sorted({info[4][0] for info in infos}))


def url_refusal(url: str, policy: Optional[SecurityPolicy] = None) -> Optional[str]:
    """None when the guard lets the agent's web tools fetch ``url``."""
    policy = policy or get_policy()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"Only http and https URLs can be fetched, not {parts.scheme or 'this'}."
    host = parts.hostname
    if not host:
        return "The URL has no host."
    if policy.allowed_domains and not _domain_allowed(host, policy.allowed_domains):
        return (
            f"{host} is not in the allowed domains (Settings > Security > Network)."
        )
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return "The URL has an invalid port."
    try:
        addresses = _resolve(host, port)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        return f"{host} could not be resolved ({exc}); not fetched."
    if not addresses:
        return f"{host} has no address; not fetched."
    for address in addresses:
        why = address_refusal(address)
        if why:
            return (
                f"Blocked: {host} resolves to {why}. The agent's web tools only "
                f"reach the public internet (Settings > Security > Network)."
            )
    return None


def guard_active() -> bool:
    return get_policy().network_guard


def _without_credentials(headers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (headers or {}).items() if k.lower() not in _CREDENTIAL_HEADERS}


def guarded_request(method: str, url: str, *, allow_redirects: bool = True, session=None, **kwargs):
    """``requests`` call that checks the URL and every redirect hop.

    Raises NetworkBlocked when a hop is refused. Returns the final response,
    with ``response.url`` the last URL fetched.
    """
    import requests

    client = session or requests.Session()
    current_method, current_url = method.upper(), url
    origin_host = urlsplit(url).hostname
    for _ in range(MAX_REDIRECTS + 1):
        refused = url_refusal(current_url)
        if refused:
            raise NetworkBlocked(refused)
        response = client.request(
            current_method, current_url, allow_redirects=False, **kwargs
        )
        if not allow_redirects or not response.is_redirect:
            return response
        location = response.headers.get("location", "")
        next_url = urljoin(response.url, location)
        status = response.status_code
        response.close()
        if status == 303 or (status in (301, 302) and current_method == "POST"):
            # Browsers and requests turn these into a GET without a body.
            current_method = "GET"
            kwargs.pop("json", None)
            kwargs.pop("data", None)
        if urlsplit(next_url).hostname != origin_host:
            kwargs["headers"] = _without_credentials(kwargs.get("headers"))
        current_url = next_url
    raise NetworkBlocked(f"Stopped after {MAX_REDIRECTS} redirects.")
