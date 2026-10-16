"""Reviewed HTTPS form sign-in without putting source values in Playwright.

No universal form discovery, JavaScript execution, callback URLs or consumers'
browser/CDP handles. A host-installed descriptor fixes the form, destination,
success redirect and exact session-cookie names. Other flows need owner handoff.
"""

from dataclasses import dataclass
from html.parser import HTMLParser
import http.client
from http.cookies import SimpleCookie
import json
import re
import socket
import ssl
from threading import Timer
import time
from urllib.parse import urlencode, urljoin, urlsplit

from .contracts import CredentialKind
from .helpers import (
    HttpsCredentialCheck,
    JsonResult,
    _abort_socket,
    _address,
    _redact_response,
    _remaining,
)
from .secrets import Secret
from .use_errors import CredentialUseError, UseCode, use_boundary


@dataclass(frozen=True)
class HttpsFormLogin(HttpsCredentialCheck):
    login_page: str = ""
    success_url: str = ""
    username_field: str = "username"
    password_field: str = "password"
    csrf_field: str | None = None
    cookie_names: tuple[str, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        if self.kind is not CredentialKind.LOGIN:
            raise ValueError("invalid_browser_helper")
        if self.csrf_field is not None and (
            not isinstance(self.csrf_field, str) or not self.csrf_field
        ):
            raise ValueError("invalid_browser_fields")
        for endpoint in (self.login_page, self.success_url):
            candidate = HttpsCredentialCheck(self.operation, self.kind, endpoint)
            if candidate.origin != self.origin:
                raise ValueError("invalid_browser_origin")
        names = (self.username_field, self.password_field) + (
            (self.csrf_field,) if self.csrf_field else ()
        )
        if len(set(names)) != len(names) or any(
            not isinstance(n, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", n)
            for n in names
        ):
            raise ValueError("invalid_browser_fields")
        if (
            type(self.cookie_names) is not tuple
            or not 1 <= len(self.cookie_names) <= 8
            or len(set(self.cookie_names)) != len(self.cookie_names)
            or any(
                not re.fullmatch(r"[A-Za-z0-9_\-]{1,128}", n) for n in self.cookie_names
            )
        ):
            raise ValueError("invalid_browser_cookies")


class _Form(HTMLParser):
    def __init__(self, specification):
        super().__init__(convert_charrefs=True)
        self.spec = specification
        self.active = False
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "form":
            if self.active:
                raise ValueError("nested_form")
            self.active = (
                attrs.get("method", "get").lower() == "post"
                and urljoin(self.spec.login_page, attrs.get("action") or "")
                == self.spec.endpoint
            )
            self.current = {} if self.active else None
        elif tag == "input" and self.active:
            name = attrs.get("name")
            if name in (
                self.spec.username_field,
                self.spec.password_field,
                self.spec.csrf_field,
            ):
                if name in self.current or "disabled" in attrs:
                    raise ValueError("ambiguous_form")
                kind = (attrs.get("type") or "text").lower()
                if name == self.spec.password_field and (
                    kind != "password"
                    or "new-password" in (attrs.get("autocomplete") or "")
                ):
                    raise ValueError("not_login_form")
                if name == self.spec.username_field and kind not in ("text", "email"):
                    raise ValueError("not_login_form")
                if name == self.spec.csrf_field and kind != "hidden":
                    raise ValueError("invalid_csrf")
                self.current[name] = attrs.get("value") or ""

    def handle_endtag(self, tag):
        if tag == "form" and self.active:
            self.forms.append(self.current)
            self.active = False


def _roundtrip(spec, url, method, body, cookies, guard, deadline):
    parsed = urlsplit(url)
    family, socktype, protocol, sockaddr = _address(parsed.hostname, parsed.port or 443)
    guard()
    tls = ssl.create_default_context()
    tls.set_alpn_protocols(["http/1.1"])
    connection = http.client.HTTPSConnection(
        parsed.hostname, parsed.port or 443, context=tls
    )
    connection.auto_open = 0
    connection.set_debuglevel(0)
    timer = None
    try:
        with socket.socket(family, socktype, protocol) as transport:
            transport.settimeout(_remaining(deadline))
            transport.connect(sockaddr)
            transport.settimeout(_remaining(deadline))
            connection.sock = tls.wrap_socket(
                transport, server_hostname=parsed.hostname
            )
            timer = Timer(_remaining(deadline), _abort_socket, args=(connection.sock,))
            timer.daemon = True
            timer.start()
            guard()
            headers = {
                "User-Agent": "CraftBotCredentialHost/1",
                "Connection": "close",
                "Accept": "text/html",
            }
            if cookies.reveal():
                headers["Cookie"] = "; ".join(cookies.reveal())
            if method == "POST":
                headers.update(
                    {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": spec.origin,
                        "Referer": spec.login_page,
                    }
                )
            connection.request(
                method, parsed.path or "/", body.reveal() if body else None, headers
            )
            with connection.getresponse() as response:
                raw = Secret(response.read(512001))
                if len(raw.reveal()) > 512000:
                    raise CredentialUseError(UseCode.LIMIT)
                return response.status, Secret(response.getheaders()), raw
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def _cookies(headers, host):
    result = Secret({})
    for name, value in headers.reveal():
        if name.lower() != "set-cookie":
            continue
        parsed = SimpleCookie()
        parsed.load(value)
        for key, cookie in parsed.items():
            if (
                not cookie["secure"]
                or cookie["path"] not in ("", "/")
                or cookie["domain"]
                and cookie["domain"].lstrip(".").lower() != host.lower()
            ):
                continue
            if len(cookie.value) > 8192 or any(
                ord(c) < 33 or ord(c) > 126 for c in cookie.value
            ):
                raise CredentialUseError(UseCode.HELPER)
            result.reveal()[key] = {
                "value": cookie.value,
                "httpOnly": bool(cookie["httponly"]),
                "sameSite": {"strict": "Strict", "lax": "Lax", "none": "None"}.get(
                    cookie["samesite"].lower(), "Lax"
                ),
            }
            if cookie["max-age"] or cookie["expires"]:
                from email.utils import parsedate_to_datetime

                try:
                    expires = (
                        time.time() + int(cookie["max-age"])
                        if cookie["max-age"]
                        else parsedate_to_datetime(cookie["expires"]).timestamp()
                    )
                except (ValueError, TypeError, OverflowError):
                    raise CredentialUseError(UseCode.HELPER) from None
                if expires <= time.time():
                    result.reveal().pop(key)
                else:
                    result.reveal()[key]["expires"] = expires
    return result


@use_boundary
def _execute_form(specification, fields: Secret, guard, payload):
    if payload not in (None, {"body": None}):
        raise CredentialUseError(UseCode.DENIED)
    deadline = time.monotonic() + 25
    status, headers, raw = _roundtrip(
        specification,
        specification.login_page,
        "GET",
        None,
        Secret([]),
        guard,
        deadline,
    )
    if status != 200:
        raise CredentialUseError(UseCode.HELPER)
    form = _Form(specification)
    form.feed(raw.reveal().decode("utf-8"))
    required = {specification.username_field, specification.password_field}
    if specification.csrf_field:
        required.add(specification.csrf_field)
    if len(form.forms) != 1 or set(form.forms[0]) != required:
        raise CredentialUseError(UseCode.DENIED)
    data = Secret(
        {
            specification.username_field: fields.reveal()["username"],
            specification.password_field: fields.reveal()["password"],
        }
    )
    if specification.csrf_field:
        token = form.forms[0][specification.csrf_field]
        if not token or len(token) > 8192:
            raise CredentialUseError(UseCode.DENIED)
        data.reveal()[specification.csrf_field] = token
    host = urlsplit(specification.endpoint).hostname
    initial = _cookies(headers, host)
    jar = SimpleCookie()
    for name, item in initial.reveal().items():
        jar[name] = item["value"]
    cookies = Secret([cookie.OutputString(attrs=[]) for cookie in jar.values()])
    status, headers, _ = _roundtrip(
        specification,
        specification.endpoint,
        "POST",
        Secret(urlencode(data.reveal()).encode("utf-8")),
        cookies,
        guard,
        deadline,
    )
    locations = [v for k, v in headers.reveal() if k.lower() == "location"]
    if (
        status not in (302, 303)
        or len(locations) != 1
        or urljoin(specification.endpoint, locations[0]) != specification.success_url
    ):
        return JsonResult(
            409, '{"outcome":"owner_handoff_required"}', "application/json"
        )
    session = _cookies(headers, host)
    if not all(name in session.reveal() for name in specification.cookie_names):
        return JsonResult(
            409, '{"outcome":"owner_handoff_required"}', "application/json"
        )
    values = [
        {
            "name": name,
            **session.reveal()[name],
            "url": specification.origin + "/",
            "secure": True,
        }
        for name in specification.cookie_names
    ]
    output = json.dumps({"cookies": values, "continue_url": specification.success_url})
    if _redact_response(output, fields) != output:
        raise CredentialUseError(
            UseCode.HELPER
        )  # Never export a source echo as a cookie.
    return JsonResult(200, output, "application/json")
