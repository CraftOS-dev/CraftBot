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

The connection goes to the address that was checked (DNS pinning, as in
OpenClaw's pinned lookup): the request is sent to that IP while TLS still
verifies the certificate for the host name, so a name that changes its
address after the check (DNS rebinding) cannot redirect it. Through a
configured proxy the proxy connects, so only the checks apply there.
The Mini Browser applies the same rules to every page it loads
(app/mini_browser/netguard.py). The guard covers the web tools and the
browser, not commands the agent runs in a shell.
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
    return check_url(url, policy)[0]


def check_url(
    url: str, policy: Optional[SecurityPolicy] = None
) -> Tuple[Optional[str], Tuple[str, ...]]:
    """(refusal or None, the checked addresses the host resolves to)."""
    refusal, addresses = _check_url(url, policy or get_policy())
    return refusal, addresses


def _assess(url: str, policy: SecurityPolicy) -> Tuple[Optional[Tuple[str, str]], Tuple[str, ...]]:
    """((what is wrong, detail) or None, the checked addresses).

    What is wrong: scheme, host, domain, port, unresolved, empty, address.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return ("scheme", parts.scheme), ()
    host = parts.hostname
    if not host:
        return ("host", ""), ()
    if policy.allowed_domains and not _domain_allowed(host, policy.allowed_domains):
        return ("domain", host), ()
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return ("port", ""), ()
    try:
        addresses = _resolve(host, port)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        return ("unresolved", str(exc)), ()
    if not addresses:
        return ("empty", ""), ()
    for address in addresses:
        if address_refusal(address):
            return ("address", address), ()
    return None, addresses


def _check_url(url: str, policy: SecurityPolicy) -> Tuple[Optional[str], Tuple[str, ...]]:
    problem, addresses = _assess(url, policy)
    if problem is None:
        return None, addresses
    kind, detail = problem
    host = urlsplit(url).hostname or ""
    if kind == "scheme":
        return f"Only http and https URLs can be fetched, not {detail or 'this'}.", ()
    if kind == "host":
        return "The URL has no host.", ()
    if kind == "domain":
        return (
            f"{host} is not in the allowed domains (Settings > Security > Network)."
        ), ()
    if kind == "port":
        return "The URL has an invalid port.", ()
    if kind == "unresolved":
        return f"{host} could not be resolved ({detail}); not fetched.", ()
    if kind == "empty":
        return f"{host} has no address; not fetched.", ()
    return (
        f"Blocked: {host} resolves to {address_refusal(detail)}. The agent's web tools only "
        f"reach the public internet (Settings > Security > Network)."
    ), ()


def navigation_refusal(url: str, policy: Optional[SecurityPolicy] = None) -> Optional[str]:
    """Why the Mini Browser must not load ``url``, as a short clause, or None.

    The same rules as the web tools, for http and https; other schemes are
    the browser's own rules (app/mini_browser/urls.py). Does a DNS lookup.
    """
    problem, _ = _assess(url, policy or get_policy())
    if problem is None:
        return None
    kind, detail = problem
    host = urlsplit(url).hostname or ""
    if kind == "scheme":
        return None
    if kind == "host":
        return "the address has no host"
    if kind == "port":
        return "the address has an invalid port"
    if kind == "domain":
        return f"{host} is not in the allowed domains (Settings > Security > Network)"
    if kind in ("unresolved", "empty"):
        return (
            f"{host} could not be resolved, and Settings > Security > Network only "
            f"allows public addresses"
        )
    try:
        ip = ipaddress.ip_address(detail.split("%", 1)[0])
    except ValueError:
        ip = None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    where = "this computer" if ip is not None and ip.is_loopback else "the local network"
    subject = host if host.strip("[]") == detail else f"{host} ({detail})"
    return f"{subject} is on {where}, which Settings > Security > Network blocks"


def guard_active() -> bool:
    return get_policy().network_guard


def _without_credentials(headers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (headers or {}).items() if k.lower() not in _CREDENTIAL_HEADERS}


def _pinned_session(url: str, address: str):
    """A requests session whose connection for ``url`` goes to ``address``,
    the address the guard checked. TLS still verifies the host name."""
    import requests
    from requests.adapters import HTTPAdapter

    parts = urlsplit(url)
    host = parts.hostname

    class PinnedAdapter(HTTPAdapter):
        def build_connection_pool_key_attributes(self, request, verify, cert=None):
            host_params, pool_kwargs = super().build_connection_pool_key_attributes(
                request, verify, cert
            )
            host_params["host"] = address
            if host_params.get("scheme") == "https":
                pool_kwargs["server_hostname"] = host
                pool_kwargs["assert_hostname"] = host
            return host_params, pool_kwargs

        def send(self, request, **kwargs):
            # The connection is to the IP; the request still names the host,
            # or virtual-hosted servers answer for the wrong site.
            if urlsplit(request.url).hostname == host and "Host" not in request.headers:
                request.headers["Host"] = parts.netloc.rsplit("@", 1)[-1]
            return super().send(request, **kwargs)

    session = requests.Session()
    adapter = PinnedAdapter()
    session.mount(f"{parts.scheme}://", adapter)
    return session


def _uses_proxy(url: str) -> bool:
    from requests.utils import get_environ_proxies

    return bool(get_environ_proxies(url))


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
        refused, addresses = check_url(current_url)
        if refused:
            raise NetworkBlocked(refused)
        hop_client = client
        if session is None and not _uses_proxy(current_url):
            # Connect to the address just checked, not a fresh lookup.
            hop_client = _pinned_session(current_url, addresses[0])
        response = hop_client.request(
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
