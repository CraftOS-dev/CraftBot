"""Agent API-key use: resolve and inject inside the app, return sanitized text.

No keys enter action inputs, event results, request URLs or response files.
Requests never follow redirects or use environment proxies/netrc credentials.
Failures deliberately omit exception text: HTTP exceptions can hold headers.
"""

from __future__ import annotations

import asyncio
import base64
import codecs
import html
import json
import math
import re
from email.message import Message
from urllib.parse import quote, quote_plus, urlsplit

import requests

from .vault import Secret, VaultError, get_vault

_MAX_BODY_BYTES = 256 * 1024
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,100}$")
_RESERVED_HEADERS = frozenset(
    {
        "host",
        "connection",
        "content-length",
        "transfer-encoding",
        "trailer",
        "upgrade",
        "proxy-authorization",
        "proxy-connection",
        "cookie",
        "accept-encoding",
        "te",
    }
)
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_INPUTS = frozenset(
    {
        "credential_id",
        "url",
        "method",
        "auth_type",
        "header_name",
        "headers",
        "params",
        "json",
        "data",
        "timeout",
        "simulated_mode",
        "_session_id",
    }
)


def _error(code: str, message: str) -> dict:
    return {"status": "error", "error_code": code, "message": message}


def _list_keys(data: dict) -> dict:
    try:
        query = data.get("query", "")
        if not isinstance(query, str) or len(query) > 200:
            return _error(
                "CREDENTIAL_INVALID_INPUT",
                "Use a search query of at most 200 characters.",
            )
        vault = get_vault()
        status = vault.status()
        if not status.get("ok"):
            return _error(
                "CREDENTIAL_VAULT_UNAVAILABLE",
                "Check the credential vault in Settings.",
            )
        query = query.strip().casefold()
        entries = [
            {
                key: entry.get(key, "other" if key == "group" else "")
                for key in ("id", "label", "site", "group")
            }
            for entry in vault.list_entries()
            if entry.get("kind") == "api_key"
            and (
                not query
                or query
                in " ".join(
                    str(entry.get(k, "")) for k in ("label", "site", "group")
                ).casefold()
            )
        ]
        return {"status": "success", "credentials": entries}
    except Exception:
        return _error(
            "CREDENTIAL_VAULT_UNAVAILABLE",
            "Saved API keys are unavailable. Check Settings > Credentials.",
        )


def _valid_header(name: object, value: object) -> bool:
    return (
        isinstance(name, str)
        and bool(_HEADER_NAME.fullmatch(name))
        and isinstance(value, str)
        and len(value) <= 8192
        and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    )


def _charset(content_type: str) -> str:
    """The charset the response declares, else UTF-8.

    requests assumes ISO-8859-1 for any text/* response without a charset,
    which garbles the UTF-8 that APIs send in practice.
    """
    message = Message()
    message["Content-Type"] = content_type
    charset = message.get_content_charset() or "utf-8"
    try:
        return codecs.lookup(charset).name
    except LookupError:
        return "utf-8"


def _redact(text: str, secret: Secret) -> str:
    # Known limitation: this is plain substring replacement, so a short key
    # also matches inside unrelated words and JSON field names (key "abc"
    # turns "tabcount" into "t[redacted]ount"). Accepted for now because
    # over-redacting is safer than leaking and real API keys are long. A fix
    # would replace only whole-token matches, or refuse keys below a minimum
    # length when they are saved.
    value = secret.reveal()
    raw = value.encode("utf-8")
    variants = {
        value,
        quote(value, safe=""),
        quote_plus(value, safe=""),
        html.escape(value),
        html.escape(value, quote=False),
        json.dumps(value, ensure_ascii=True)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
        base64.b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode(),
        raw.hex(),
        raw.hex().upper(),
    }
    variants |= {
        re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), value)
        for value in variants
        if "%" in value
    }
    # Also catch JSON unicode escapes, escaped slashes and response object keys.
    try:
        decoded = json.loads(text)
    except (ValueError, RecursionError):
        decoded = None

    ordered_variants = sorted(variants, key=len, reverse=True)

    def clean(item):
        if isinstance(item, str):
            for variant in ordered_variants:
                item = item.replace(variant, "[redacted]")
            return item
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, dict):
            return {clean(key): clean(child) for key, child in item.items()}
        return item

    return (
        clean(json.dumps(clean(decoded), ensure_ascii=False))
        if decoded is not None
        else clean(text)
    )


def _request(data: dict) -> dict:
    # Keep every operation involving a raw key inside this non-logging boundary.
    try:
        if not isinstance(data, dict) or set(data) - _INPUTS:
            return _error("CREDENTIAL_INVALID_INPUT", "Unsupported request options.")
        credential_id = data.get("credential_id")
        url = data.get("url")
        method = data.get("method", "GET")
        if (
            not isinstance(credential_id, str)
            or not credential_id
            or len(credential_id) > 100
        ):
            return _error(
                "CREDENTIAL_INVALID_INPUT",
                "Choose an ID from credential_list_api_keys.",
            )
        if (
            not isinstance(url, str)
            or len(url) > 8192
            or not url
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)
            or "\\" in url
        ):
            return _error(
                "CREDENTIAL_INVALID_INPUT",
                "Use an absolute HTTPS URL without whitespace or backslashes.",
            )
        parts = urlsplit(url)
        if (
            parts.scheme not in ("https", "http")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
        ):
            return _error(
                "CREDENTIAL_INVALID_INPUT",
                "URLs cannot contain user information or fragments.",
            )
        if not isinstance(method, str) or method not in _METHODS:
            return _error("CREDENTIAL_INVALID_INPUT", "Choose a supported HTTP method.")
        auth_type = data.get("auth_type", "bearer")
        header_name = data.get(
            "header_name", "Authorization" if auth_type == "bearer" else "X-API-Key"
        )
        if (
            auth_type not in ("bearer", "header")
            or not _valid_header(header_name, "")
            or header_name.lower() in _RESERVED_HEADERS
        ):
            return _error(
                "CREDENTIAL_INVALID_INPUT",
                "Use bearer authentication or a valid API-key header.",
            )
        headers = data.get("headers", {})
        if (
            not isinstance(headers, dict)
            or len(headers) > 50
            or any(
                not _valid_header(k, v)
                or k.lower()
                in _RESERVED_HEADERS | {"authorization", header_name.lower()}
                for k, v in headers.items()
            )
        ):
            return _error(
                "CREDENTIAL_INVALID_INPUT", "Invalid or conflicting request headers."
            )
        params = data.get("params", {})
        if not isinstance(params, dict) or len(params) > 100:
            return _error(
                "CREDENTIAL_INVALID_INPUT",
                "Query parameters must be an object of at most 100 fields.",
            )
        if "json" in data and "data" in data:
            return _error(
                "CREDENTIAL_INVALID_INPUT", "Send either a JSON body or a text body."
            )
        if "data" in data and not isinstance(data["data"], str):
            return _error("CREDENTIAL_INVALID_INPUT", "The raw body must be text.")
        if (
            len(
                json.dumps(
                    {k: data[k] for k in ("json", "data", "params") if k in data}
                ).encode()
            )
            > _MAX_BODY_BYTES
        ):
            return _error(
                "CREDENTIAL_INVALID_INPUT", "The request body or query is too large."
            )
        timeout = data.get("timeout", 30)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 1 <= timeout <= 60
        ):
            return _error(
                "CREDENTIAL_INVALID_INPUT", "Timeout must be between 1 and 60 seconds."
            )

        with requests.Session() as session:
            session.trust_env = False
            prepared = session.prepare_request(
                requests.Request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=data.get("json"),
                    data=data.get("data"),
                )
            )
            # Check the actual transport URL after requests has canonicalized it.
            secret = get_vault().api_key_for_url(credential_id, prepared.url)
            prepared.headers[header_name] = (
                "Bearer " if auth_type == "bearer" else ""
            ) + secret.reveal()
            with session.send(
                prepared,
                timeout=timeout,
                allow_redirects=False,
                verify=True,
                stream=True,
            ) as response:
                # Real redirects only (a Location to follow): a 304 Not
                # Modified is an ordinary answer to a conditional request.
                if response.is_redirect:
                    return _error(
                        "CREDENTIAL_REDIRECT_REFUSED",
                        "Redirect refused. Use a direct URL on the saved website.",
                    ) | {"status_code": response.status_code}
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > _MAX_BODY_BYTES:
                        # Never return a truncated value that could expose half a key.
                        return _error(
                            "CREDENTIAL_RESPONSE_TOO_LARGE",
                            "Response exceeded 256 KiB; no body was returned.",
                        )
                content_type_header = response.headers.get("Content-Type", "")
                content_type = content_type_header.split(";", 1)[0].lower()
                if content_type and not (
                    content_type.startswith("text/")
                    or content_type.endswith(("json", "+json", "xml", "+xml"))
                ):
                    return _error(
                        "CREDENTIAL_RESPONSE_TYPE",
                        "Only text and JSON API responses are returned.",
                    )
                text = _redact(
                    bytes(body).decode(_charset(content_type_header), errors="replace"),
                    secret,
                )
                return {
                    "status": "success" if response.status_code < 400 else "error",
                    "status_code": response.status_code,
                    "body": text,
                    "message": f"HTTP {response.status_code}",
                }
    except VaultError as exc:
        # Vault details are fixed validation messages, never a key or request.
        return _error(
            "CREDENTIAL_UNAVAILABLE", exc.detail or "Check Settings > Credentials."
        )
    except Exception:
        return _error(
            "CREDENTIAL_REQUEST_FAILED",
            "The authenticated request failed. Check the endpoint, connection and saved key.",
        )


async def list_api_keys(data: dict) -> dict:
    return await asyncio.to_thread(_list_keys, data)


async def request_with_api_key(data: dict) -> dict:
    return await asyncio.to_thread(_request, data)
