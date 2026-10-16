"""Fixed host helper implementation; no consumer URLs, code, headers or callbacks.

The host installs immutable check specifications, never from manifests/actions.
Browser filling, provider requests and token-producing login flows need separate
reviewed helpers. This check discards all response data except a coarse outcome.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
import http.client
import ipaddress
import json
import re
import socket
import ssl
from threading import Timer
import time
from types import MappingProxyType
from urllib.parse import urlsplit

from .contracts import CredentialKind, HelperOperation
from .records import CredentialDetails, origins
from .secrets import Secret
from .use_errors import CredentialUseError, UseCode, use_boundary


class HelperResult(str, Enum):
    ACCEPTED = "accepted"  # HTTP 2xx, not proof of a provider's account identity.
    REJECTED = "rejected"  # HTTP 401/403.
    UNAVAILABLE = "unavailable"  # Includes redirects; never followed.


@dataclass(frozen=True)
class HttpsCredentialCheck:
    """Host-reviewed, read-only GET with Basic or Bearer authorization.

    A service-secret field is explicitly selected by trusted configuration.
    No field-name inference, arbitrary requests, or generated token storage.
    """

    operation: HelperOperation
    kind: CredentialKind
    endpoint: str
    secret_field: str | None = None

    def __post_init__(self):
        if not isinstance(self.operation, HelperOperation) or not isinstance(
            self.kind, CredentialKind
        ):
            raise ValueError("invalid_helper")
        if (
            not isinstance(self.endpoint, str)
            or not self.endpoint.isascii()
            or len(self.endpoint) > 2048
            or any(ord(char) <= 32 or ord(char) == 127 for char in self.endpoint)
            or "\\" in self.endpoint
        ):
            raise ValueError("invalid_helper_endpoint")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in self.endpoint
            or "#" in self.endpoint
            or parsed.netloc.endswith(":")
            or not re.fullmatch(r"[A-Za-z0-9._~!$&'()*+,;=:@%/\-]*", parsed.path)
        ):
            raise ValueError("invalid_helper_endpoint")
        # Reuse the strict origin parser; no www folding or wildcard policy.
        origins((f"https://{parsed.netloc}",))
        if self.kind is CredentialKind.SERVICE_SECRET:
            if not isinstance(self.secret_field, str) or not re.fullmatch(
                r"[a-z][a-z0-9_]{0,63}", self.secret_field
            ):
                raise ValueError("invalid_helper_field")
        elif self.secret_field is not None:
            raise ValueError("invalid_helper_field")

    @property
    def origin(self) -> str:
        return origins((f"https://{urlsplit(self.endpoint).netloc}",))[0]


class HelperRegistry:
    """Sealed at host bootstrap. No runtime register/import/execute-code API."""

    def __init__(self, specifications: tuple[HttpsCredentialCheck, ...] = ()):
        from .browser_helper import HttpsFormLogin

        if type(specifications) is not tuple or len(specifications) > 1024:
            raise ValueError("invalid_helper_registry")
        entries = {}
        for specification in specifications:
            if (
                type(specification)
                not in (HttpsCredentialCheck, HttpsJsonOperation, HttpsFormLogin)
                or specification.operation in entries
            ):
                raise ValueError("invalid_helper_registry")
            entries[specification.operation] = specification
        self._entries = MappingProxyType(entries)

    def require(self, operation: HelperOperation) -> HttpsCredentialCheck:
        specification = self._entries.get(operation)
        if specification is None:
            raise CredentialUseError(UseCode.DENIED)
        return specification


@dataclass(frozen=True)
class HttpsJsonOperation(HttpsCredentialCheck):
    """One installed JSON API operation at one immutable HTTPS endpoint.

    Requesters supply JSON data, never a URL, path, method, headers or transport.
    Resource parameters are constrained by sealed templates. Streaming is
    filtered in the protected host before release. No response
    headers, cookies, redirects or provider error bodies leave this boundary.
    """

    method: str = "POST"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    protocol: str = "json"
    query_fields: tuple[str, ...] = ()
    path_fields: tuple[str, ...] = ()
    envelope: bool = False
    request_format: str = "json"
    response_format: str = "json"
    max_response_bytes: int = 2_000_000
    header_fields: tuple[str, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        if self.kind is CredentialKind.LOGIN or self.method not in (
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        ):
            raise ValueError("invalid_json_helper")
        if (
            type(self.query_fields) is not tuple
            or len(self.query_fields) > 128
            or len(json.dumps(self.query_fields)) > 4096
            or any(
                not isinstance(k, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,63}", k)
                for k in self.query_fields
            )
        ):
            raise ValueError("invalid_helper_query")
        from .route_policy import path_names

        if (
            type(self.path_fields) is not tuple
            or len(set(self.path_fields)) != len(self.path_fields)
            or path_names(self.endpoint) != self.path_fields
            or type(self.envelope) is not bool
            or self.request_format not in ("json", "form", "multipart", "image")
            or self.response_format not in ("json", "binary", "text")
        ):
            raise ValueError("invalid_helper_route")
        if (
            self.path_fields
            or self.request_format != "json"
            or self.response_format in ("binary", "text")
        ) and not self.envelope:
            raise ValueError("invalid_helper_route")
        if (
            type(self.max_response_bytes) is not int
            or not 1 <= self.max_response_bytes <= 64_000_000
        ):
            raise ValueError("invalid_helper_limit")
        if type(self.header_fields) is not tuple or set(self.header_fields) - {
            "Idempotency-Key",
            "Stripe-Account",
        }:
            raise ValueError("invalid_helper_headers")
        if (self.auth_header, self.auth_prefix) not in {
            ("Authorization", "Bearer "),
            ("Authorization", "Bot "),
            ("x-api-key", ""),
            ("x-goog-api-key", ""),
            ("X-Figma-Token", ""),
        } or self.protocol not in (
            "json",
            "openai",
            "anthropic",
            "aws_bedrock",
            "telegram",
            "basic",
            "oauth_form",
            "oauth_json",
            "oauth_basic",
            "discord_gateway",
            "twitter_oauth1",
            "lark_token",
            "lark_websocket",
            "telegram_mtproto",
        ):
            raise ValueError("invalid_json_helper")
        if self.protocol == "twitter_oauth1" and (
            not (
                self.origin == "https://api.twitter.com"
                and self.request_format == "json"
                or self.endpoint == "https://upload.twitter.com/1.1/media/upload.json"
                and self.method == "POST"
                and self.request_format == "multipart"
            )
            or self.kind is not CredentialKind.SERVICE_SECRET
            or self.secret_field != "api_secret"
            or not self.envelope
        ):
            raise ValueError("invalid_twitter_helper")
        if self.protocol in ("lark_token", "lark_websocket") and (
            self.endpoint
            != (
                "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
                if self.protocol == "lark_token"
                else "https://open.larksuite.com/callback/ws/endpoint"
            )
            or self.kind is not CredentialKind.API_KEY
            or self.method != "POST"
            or self.envelope
            or self.query_fields
            or self.path_fields
            or self.request_format != "json"
        ):
            raise ValueError("invalid_lark_helper")
        if self.protocol == "telegram_mtproto" and (
            self.endpoint
            != "https://api.telegram.org/mtproto/" + self.operation.operation
            or self.operation.operation
            not in ("send_code", "complete", "qr_login", "complete_password")
            or self.kind is not CredentialKind.SERVICE_SECRET
            or self.secret_field != "api_hash"
            or self.method != "POST"
            or self.envelope
            or self.query_fields
            or self.path_fields
        ):
            raise ValueError("invalid_mtproto_helper")
        if self.protocol == "discord_gateway" and (
            self.endpoint != "https://gateway.discord.gg/"
            or self.kind is not CredentialKind.API_KEY
            or self.method != "GET"
            or self.query_fields
            or self.path_fields
            or self.envelope
        ):
            raise ValueError("invalid_gateway_helper")
        if self.protocol.startswith("oauth_") and (
            self.kind is not CredentialKind.API_KEY
            or self.method != "POST"
            or self.path_fields
            or self.query_fields
            or not self.envelope
            or self.request_format not in ("json", "form")
        ):
            raise ValueError("invalid_oauth_helper")
        if self.protocol == "basic" and (
            self.kind is not CredentialKind.SERVICE_SECRET
            or self.secret_field != "api_token"
        ):
            raise ValueError("invalid_basic_helper")
        if self.protocol == "telegram" and (
            self.origin != "https://api.telegram.org"
            or not self.endpoint.startswith(
                (
                    "https://api.telegram.org/bot_TOKEN_/",
                    "https://api.telegram.org/file/bot_TOKEN_/",
                )
            )
            or "_TOKEN_" not in self.endpoint
        ):
            raise ValueError("invalid_telegram_helper")
        if self.protocol == "aws_bedrock":
            from .aws_helper import endpoint_region

            endpoint_region(self.endpoint)
            if (
                self.kind is not CredentialKind.SERVICE_SECRET
                or self.secret_field != "secret_access_key"
                or self.method != "POST"
                or self.query_fields
            ):
                raise ValueError("invalid_bedrock_helper")


@dataclass(frozen=True)
class JsonResult:
    status: int
    body: str
    content_type: str


def _response_variants(fields: Secret):
    """Scrub literal and common encoded echoes before any output is released."""
    import html
    from urllib.parse import quote

    variants = set()
    for raw in fields.reveal().values():
        if not raw:
            continue
        encoded = raw.encode("utf-8")
        unicode_units = raw.encode("utf-16-be")
        escaped = "".join(
            f"\\u{int.from_bytes(unicode_units[i : i + 2], 'big'):04x}"
            for i in range(0, len(unicode_units), 2)
        )
        variants.update(
            (
                raw,
                json.dumps(raw)[1:-1],
                html.escape(raw),
                quote(raw, safe=""),
                encoded.hex(),
                base64.b64encode(encoded).decode("ascii"),
                base64.urlsafe_b64encode(encoded).decode("ascii"),
                escaped,
                json.dumps(escaped)[1:-1],
                "".join(f"%{byte:02x}" for byte in encoded),
                "".join(f"%{byte:02X}" for byte in encoded),
            )
        )
    return Secret(tuple(sorted(variants, key=len, reverse=True)))


def _redact_response(value: str, fields: Secret) -> str:
    for variant in _response_variants(fields).reveal():
        value = value.replace(variant, "[redacted]")
    return value


def _sanitize_json_payloads(payloads, fields):
    """Validate redacted JSON and reject echoes split across semantic deltas.

    Network buffering alone misses a key split between SSE data records. Keep
    strings at the same JSON path together (including tool-call arguments), and
    also check concatenated leaves for array/object fragments. This is defence
    against accidental provider echoes, not permission to trust arbitrary URLs.
    Only fields actually sent to the reviewed service participate in filtering.
    """
    sanitized = []
    paths = {}
    leaves = []

    def collect(value, path=()):
        if type(value) is dict:
            for key, child in value.items():
                collect(child, (*path, key))
        elif type(value) is list:
            for index, child in enumerate(value):
                collect(child, (*path, index))
        elif isinstance(value, str):
            paths.setdefault(path, []).append(value)
            leaves.append(value)

    for payload in payloads:
        canonical = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        cleaned = _redact_response(canonical, fields)
        # Substitution must never return invalid JSON (e.g. a numeric key echo).
        collect(json.loads(cleaned))
        sanitized.append(cleaned)
    for fragments in (*paths.values(), leaves):
        joined = "".join(fragments)
        if _redact_response(joined, fields) != joined:
            raise CredentialUseError(UseCode.HELPER)
    return sanitized


@use_boundary
def _execute_json(
    specification: HttpsJsonOperation,
    fields: Secret,
    guard,
    payload,
    *,
    execution=None,
    after_send=None,
):
    if type(payload) is not dict or set(payload) != {"body"}:
        raise CredentialUseError(UseCode.DENIED)
    if specification.protocol == "discord_gateway":
        from .gateway_helper import execute

        return execute(specification, fields, guard, payload, execution, after_send)
    if specification.protocol == "telegram_mtproto":
        from .mtproto_helper import execute

        return execute(specification, fields, guard, payload, execution, after_send)
    body = payload["body"]
    session = None
    path = urlsplit(specification.endpoint).path or "/"
    query_data = body if specification.method == "GET" else None
    business_headers = {}
    if specification.envelope:
        from .route_policy import target

        if (
            type(body) is not dict
            or not {"path", "query", "data"} <= set(body)
            or set(body)
            - (
                {"path", "query", "data", "headers", "session"}
                if specification.protocol == "twitter_oauth1"
                else {"path", "query", "data", "headers"}
            )
        ):
            raise CredentialUseError(UseCode.DENIED)
        session = body.get("session")
        business_headers = body.get("headers", {})
        if (
            type(business_headers) is not dict
            or set(business_headers) - set(specification.header_fields)
            or any(
                not isinstance(v, str)
                or not 1 <= len(v) <= 256
                or any(ord(c) < 33 or ord(c) > 126 for c in v)
                for v in business_headers.values()
            )
        ):
            raise CredentialUseError(UseCode.DENIED)
        path = target(specification.endpoint, specification.path_fields, body["path"])
        query_data, body = body["query"], body["data"]
    query = ""
    if query_data is not None:
        from urllib.parse import urlencode

        if (
            type(query_data) is not dict
            or any(
                k.split("[", 1)[0] not in specification.query_fields
                or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_.]*(?:\[[A-Za-z0-9_.-]*\])*", k
                )
                for k in query_data
            )
            or any(
                type(v) not in (str, int, bool, type(None)) for v in query_data.values()
            )
        ):
            raise CredentialUseError(UseCode.DENIED)
        query = urlencode(
            {
                k: str(v).lower() if type(v) is bool else v
                for k, v in query_data.items()
                if v is not None
            }
        )
        if len(query) > 8192:
            raise CredentialUseError(UseCode.LIMIT)
    if specification.method == "GET":
        body = None
    if (
        body is not None
        and type(body) is not dict
        and not (
            specification.envelope
            and specification.request_format == "json"
            and type(body) is list
        )
    ):
        raise CredentialUseError(UseCode.DENIED)
    from .wire import encode, MAX_OUTPUT

    encoded, request_type = encode(body, specification.request_format)
    # Host-controlled timeout, immutable destination, no proxy or second DNS.
    deadline = time.monotonic() + (600 if execution is not None else 60)
    handshake_deadline = time.monotonic() + 20
    parsed = urlsplit(specification.endpoint)
    port = parsed.port or 443
    family, socktype, protocol, sockaddr = _address(parsed.hostname, port)
    guard()
    context = ssl.create_default_context()
    context.set_alpn_protocols(["http/1.1"])
    connection = http.client.HTTPSConnection(parsed.hostname, port, context=context)
    connection.auto_open = 0
    connection.set_debuglevel(0)
    timer = None
    finished = None
    try:
        with socket.socket(family, socktype, protocol) as transport:
            transport.settimeout(_remaining(handshake_deadline))
            transport.connect(sockaddr)
            transport.settimeout(_remaining(handshake_deadline))
            connection.sock = context.wrap_socket(
                transport, server_hostname=parsed.hostname
            )
            connection.sock.settimeout(_remaining(deadline))
            timer = Timer(_remaining(deadline), _abort_socket, args=(connection.sock,))
            timer.daemon = True
            timer.start()
            if execution is not None:
                from threading import Event, Thread

                finished = Event()

                def watch():
                    while not finished.wait(0.05):
                        if execution.cancelled.is_set():
                            _abort_socket(connection.sock)
                            return

                Thread(target=watch, daemon=True).start()
            guard()
            secret = Secret(
                fields.reveal()[
                    "api_key"
                    if specification.kind is CredentialKind.API_KEY
                    else specification.secret_field
                ]
            )
            if any(ord(c) < 33 or ord(c) > 126 for c in secret.reveal()):
                raise CredentialUseError(UseCode.DENIED)
            headers = {
                "Content-Type": request_type,
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "CraftBotCredentialHost/1",
                specification.auth_header: specification.auth_prefix + secret.reveal(),
            }
            if specification.protocol == "anthropic":
                headers["anthropic-version"] = "2023-06-01"
            if specification.operation.helper_id == "integration_notion":
                headers["Notion-Version"] = "2022-06-28"
            if specification.operation.helper_id == "integration_github":
                headers["Accept"] = "application/vnd.github+json"
                headers["X-GitHub-Api-Version"] = "2022-11-28"
            headers.update(business_headers)
            used_fields = Secret({"value": secret.reveal()})
            if specification.protocol == "twitter_oauth1":
                from .twitter_helper import authorization

                signed, used_fields = authorization(
                    specification.origin + path,
                    specification.method,
                    query,
                    fields,
                    session,
                )
                headers["Authorization"] = signed.reveal()
            if specification.protocol in ("lark_token", "lark_websocket"):
                if (
                    type(body) is not dict
                    or set(body) != {"app_id"}
                    or not isinstance(body["app_id"], str)
                    or not re.fullmatch(r"cli_[A-Za-z0-9_]{1,128}", body["app_id"])
                ):
                    raise CredentialUseError(UseCode.DENIED)
                private_body = Secret(
                    {"app_id": body["app_id"], "app_secret": secret.reveal()}
                    if specification.protocol == "lark_token"
                    else {"AppID": body["app_id"], "AppSecret": secret.reveal()}
                )
                headers.pop(specification.auth_header, None)
                encoded, headers["Content-Type"] = encode(private_body.reveal(), "json")
            if specification.protocol == "basic":
                username = Secret(fields.reveal()["username"])
                if ":" in username.reveal() or any(
                    ord(c) < 32 or ord(c) == 127 for c in username.reveal()
                ):
                    raise CredentialUseError(UseCode.DENIED)
                pair = Secret(username.reveal() + ":" + secret.reveal())
                headers["Authorization"] = (
                    "Basic " + base64.b64encode(pair.reveal().encode()).decode()
                )
                used_fields = Secret(
                    {
                        "username": username.reveal(),
                        "api_token": secret.reveal(),
                        "pair": pair.reveal(),
                    }
                )
            if specification.protocol.startswith("oauth_"):
                if type(body) is not dict or any(
                    type(v) not in (str, int, bool, type(None)) for v in body.values()
                ):
                    raise CredentialUseError(UseCode.DENIED)
                private_body = Secret(dict(body))
                private_body.reveal().pop("client_secret", None)
                headers.pop(specification.auth_header, None)
                if specification.protocol == "oauth_basic":
                    client_id = private_body.reveal().pop("client_id", None)
                    if (
                        not isinstance(client_id, str)
                        or not client_id
                        or ":" in client_id
                        or not client_id.isascii()
                        or any(ord(c) < 33 or ord(c) == 127 for c in client_id)
                    ):
                        raise CredentialUseError(UseCode.DENIED)
                    pair = Secret(client_id + ":" + secret.reveal())
                    headers["Authorization"] = (
                        "Basic " + base64.b64encode(pair.reveal().encode()).decode()
                    )
                    used_fields = Secret(
                        {"value": secret.reveal(), "pair": pair.reveal()}
                    )
                else:
                    private_body.reveal()["client_secret"] = secret.reveal()
                encoded, headers["Content-Type"] = encode(
                    private_body.reveal(), specification.request_format
                )
            if specification.protocol == "aws_bedrock":
                from .aws_helper import signing_headers

                signed, used_fields = signing_headers(
                    specification.endpoint, encoded, fields
                )
                headers.update(signed.reveal())
            if specification.protocol == "telegram":
                if not re.fullmatch(
                    r"[0-9]{5,20}:[A-Za-z0-9_-]{20,128}", secret.reveal()
                ):
                    raise CredentialUseError(UseCode.DENIED)
                path = path.replace("_TOKEN_", secret.reveal())
                headers.pop(specification.auth_header, None)
            if "Authorization" in headers:
                used_fields = Secret(
                    {**used_fields.reveal(), "authorization": headers["Authorization"]}
                )
            connection.request(
                specification.method,
                path + ("?" + query if query else ""),
                encoded,
                headers,
            )
            if after_send is not None:
                after_send()
            with connection.getresponse() as response:
                if not 200 <= response.status < 300:
                    status = (
                        response.status
                        if response.status
                        in (400, 401, 403, 404, 408, 409, 422, 429, 500, 502, 503, 504)
                        else 502
                    )
                    return JsonResult(
                        status,
                        '{"error":{"message":"Credential operation failed"}}',
                        "application/json",
                    )
                # SSE filtering retains potential source fragments across events.
                if response.status == 204:
                    return JsonResult(204, "{}", "application/json")
                response_type = (
                    response.getheader("Content-Type", "").split(";")[0].strip().lower()
                )
                if (
                    execution is not None
                    and response_type == "text/event-stream"
                    and specification.protocol in ("openai", "anthropic")
                ):
                    from .streaming import relay

                    execution.start(response.status, response_type)
                    relay(
                        response,
                        used_fields,
                        execution,
                        specification.max_response_bytes,
                    )
                    return JsonResult(response.status, "", response_type)
                raw = Secret(response.read(specification.max_response_bytes + 1))
                if len(raw.reveal()) > specification.max_response_bytes:
                    raise CredentialUseError(UseCode.LIMIT)
                content_type = (
                    response.getheader("Content-Type", "").split(";")[0].strip().lower()
                )
                if specification.response_format == "binary":
                    if content_type not in (
                        "video/mp4",
                        "image/png",
                        "image/jpeg",
                        "image/webp",
                        "application/octet-stream",
                        "application/pdf",
                        "application/zip",
                        "text/plain",
                        "audio/mpeg",
                        "audio/ogg",
                        "audio/wav",
                        "video/webm",
                        "image/gif",
                    ):
                        raise CredentialUseError(UseCode.HELPER)
                    inspection = Secret(raw.reveal().decode("latin-1"))
                    binary = Secret(base64.b64encode(raw.reveal()).decode("ascii"))
                    if (
                        _redact_response(inspection.reveal(), used_fields)
                        != inspection.reveal()
                        or _redact_response(binary.reveal(), used_fields)
                        != binary.reveal()
                        or any(
                            variant.encode("utf-8") in raw.reveal()
                            for variant in _response_variants(used_fields).reveal()
                        )
                    ):
                        raise CredentialUseError(UseCode.HELPER)
                    return JsonResult(
                        response.status,
                        json.dumps(
                            {"data": binary.reveal(), "media_type": content_type}
                        ),
                        "application/json",
                    )
                text = Secret(raw.reveal().decode("utf-8"))
                if specification.response_format == "text":
                    return JsonResult(
                        response.status,
                        _redact_response(text.reveal(), used_fields),
                        "text/plain",
                    )
                if content_type == "text/event-stream" and specification.protocol in (
                    "openai",
                    "anthropic",
                ):
                    # Only valid JSON data records and the standard terminator.
                    canonical = []
                    payloads = []
                    for line in text.reveal().splitlines():
                        if line.startswith("data:"):
                            if line[5:].strip() != "[DONE]":
                                payloads.append(json.loads(line[5:]))
                                line = len(payloads) - 1
                        elif line.startswith(":"):
                            continue  # Provider comments are not output data.
                        elif line.startswith("event:"):
                            if not re.fullmatch(r"event: ?[A-Za-z0-9_.-]{1,64}", line):
                                raise CredentialUseError(UseCode.HELPER)
                        elif line:
                            raise CredentialUseError(UseCode.HELPER)
                        canonical.append(line)
                    cleaned = _sanitize_json_payloads(payloads, used_fields)
                    text = Secret(
                        "\n".join(
                            "data: " + cleaned[line] if type(line) is int else line
                            for line in canonical
                        )
                        + "\n"
                    )
                elif content_type == "application/json":
                    text = Secret(
                        _sanitize_json_payloads(
                            [json.loads(text.reveal())], used_fields
                        )[0]
                    )
                else:
                    raise CredentialUseError(UseCode.HELPER)
                sanitized = _redact_response(text.reveal(), used_fields)
                if len(sanitized.encode("utf-8")) > MAX_OUTPUT:
                    raise CredentialUseError(UseCode.LIMIT)
                return JsonResult(response.status, sanitized, content_type)
    finally:
        if finished is not None:
            finished.set()
        if timer is not None:
            timer.cancel()
        connection.close()


def require_match(specification: HttpsCredentialCheck, details: CredentialDetails):
    if (
        specification.kind is not details.summary.kind
        or specification.origin not in details.allowed_origins
    ):
        raise CredentialUseError(UseCode.DENIED)


def _address(host: str, port: int):
    """Resolve once and connect to exactly a checked numeric address.

    Reject the entire answer on any private/special address, including mixed
    public/private answers. No proxy environment or second DNS lookup is used.
    """
    from .resolver import resolve

    addresses = resolve(host, port)
    if not addresses:
        raise CredentialUseError(UseCode.DENIED)
    for family, socktype, protocol, _, sockaddr in addresses:
        address = ipaddress.ip_address(sockaddr[0])
        if (
            family not in (socket.AF_INET, socket.AF_INET6)
            or socktype != socket.SOCK_STREAM
            or not address.is_global
            or address.is_multicast
            or address.is_reserved
            or getattr(address, "is_site_local", False)
            or getattr(address, "ipv4_mapped", None) is not None
            or getattr(address, "sixtofour", None) is not None
            or getattr(address, "teredo", None) is not None
            or "%" in sockaddr[0]
        ):
            raise CredentialUseError(UseCode.DENIED)
    family, socktype, protocol, _, sockaddr = addresses[0]
    return family, socktype, protocol, sockaddr


def _authorization(specification: HttpsCredentialCheck, fields: Secret) -> Secret:
    # All intermediates remain redacted in trusted frames; the public broker
    # boundary also discards inner frames on any exception.
    if specification.kind is CredentialKind.LOGIN:
        pair = Secret((fields.reveal()["username"], fields.reveal()["password"]))
        if ":" in pair.reveal()[0] or any(
            ord(char) < 32 or ord(char) == 127
            for value in pair.reveal()
            for char in value
        ):
            raise CredentialUseError(UseCode.DENIED)
        encoded = Secret(base64.b64encode(":".join(pair.reveal()).encode("utf-8")))
        return Secret("Basic " + encoded.reveal().decode("ascii"))
    value = Secret(
        fields.reveal()[
            "api_key"
            if specification.kind is CredentialKind.API_KEY
            else specification.secret_field
        ]
    )
    if not re.fullmatch(r"[A-Za-z0-9._~+/\-]+=*", value.reveal()):
        raise CredentialUseError(UseCode.DENIED)
    return Secret("Bearer " + value.reveal())


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    return remaining


def _abort_socket(transport):
    # A total request deadline must also stop trickled status/response headers;
    # a per-recv socket timeout alone does not bound that case.
    try:
        transport.shutdown(socket.SHUT_RDWR)
    except (OSError, AttributeError):
        pass


@use_boundary
def _execute_check(specification: HttpsCredentialCheck, fields: Secret, guard):
    """Private broker entry point. `guard` is host code, never a request value."""
    deadline = time.monotonic() + 10
    parsed = urlsplit(specification.endpoint)
    port = parsed.port or 443
    family, socktype, protocol, sockaddr = _address(parsed.hostname, port)
    guard()  # Slow DNS must not extend capability/owner-unlock lifetimes.
    _remaining(deadline)
    context = ssl.create_default_context()
    context.set_alpn_protocols(["http/1.1"])
    connection = http.client.HTTPSConnection(
        parsed.hostname, port, timeout=10, context=context
    )
    connection.auto_open = 0  # Never reconnect to an unchecked DNS address.
    connection.set_debuglevel(0)
    timer = None
    try:
        with socket.socket(family, socktype, protocol) as transport:
            transport.settimeout(_remaining(deadline))
            transport.connect(sockaddr)
            transport.settimeout(_remaining(deadline))
            connection.sock = context.wrap_socket(
                transport, server_hostname=parsed.hostname
            )
            connection.sock.settimeout(_remaining(deadline))
            timer = Timer(_remaining(deadline), _abort_socket, args=(connection.sock,))
            timer.daemon = True
            timer.start()
            guard()  # Recheck immediately before secrets enter the request.
            authorization = _authorization(specification, fields)
            connection.request(
                "GET",
                parsed.path or "/",
                headers={
                    "Authorization": authorization.reveal(),
                    "Connection": "close",
                    "Accept": "application/json",
                },
            )
            # Do not return/cache/log headers, URL, body, cookies or client objects.
            with connection.getresponse() as response:
                _remaining(deadline)
                if 200 <= response.status < 300:
                    return HelperResult.ACCEPTED
                if response.status in (401, 403):
                    return HelperResult.REJECTED
                return HelperResult.UNAVAILABLE
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()
