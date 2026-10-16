"""Bounded data encoders, never caller-provided HTTP transport or headers."""

import base64
import json
import re
import secrets
from urllib.parse import urlencode

MAX_INPUT = 32_000_000
MAX_OUTPUT = 96_000_000


def encode(body, format):
    if body is None:
        return None, "application/json"
    if type(body) is not dict and not (format == "json" and type(body) is list):
        raise ValueError("credential_request_invalid")
    if format == "json":
        result = json.dumps(body, allow_nan=False).encode("utf-8")
        mime = "application/json"
    elif format == "form":
        if any(
            type(v) not in (str, int, float, bool, type(None)) for v in body.values()
        ):
            raise ValueError("credential_request_invalid")
        result = urlencode({k: v for k, v in body.items() if v is not None}).encode()
        mime = "application/x-www-form-urlencoded"
    elif format == "image":
        if set(body) != {"data", "content_type"} or body["content_type"] not in (
            "image/png",
            "image/jpeg",
        ):
            raise ValueError("credential_request_invalid")
        result = base64.b64decode(body["data"], validate=True)
        mime = body["content_type"]
    elif format == "multipart":
        if (
            set(body) != {"fields", "files"}
            or type(body["fields"]) is not dict
            or type(body["files"]) is not list
            or not 1 <= len(body["files"]) <= 8
        ):
            raise ValueError("credential_request_invalid")
        boundary = "CraftBot" + secrets.token_hex(24)
        parts = []

        def name(value):
            if not isinstance(value, str) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_\[\]-]{0,63}", value
            ):
                raise ValueError("credential_request_invalid")
            return value

        for field, value in body["fields"].items():
            if type(value) not in (str, int, float, bool):
                raise ValueError("credential_request_invalid")
            parts.append(
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name(field)}"\r\n\r\n'
                    + str(value)
                    + "\r\n"
                ).encode()
            )
        for item in body["files"]:
            if (
                type(item) is not dict
                or not {"field", "data", "content_type"} <= set(item)
                or set(item) - {"field", "data", "content_type", "filename"}
                or item["content_type"]
                not in (
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                    "video/mp4",
                    "application/octet-stream",
                    "audio/wav",
                    "audio/x-wav",
                    "audio/mpeg",
                    "audio/mp4",
                    "audio/flac",
                    "audio/ogg",
                    "application/zip",
                    "text/plain",
                    "application/javascript",
                    "application/typescript",
                )
            ):
                raise ValueError("credential_request_invalid")
            filename = item.get("filename", "upload.bin")
            if not isinstance(filename, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", filename
            ):
                raise ValueError("credential_request_invalid")
            content = base64.b64decode(item["data"], validate=True)
            if len(content) > 24_000_000:
                raise ValueError("credential_use_limit")
            parts.extend(
                [
                    (
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{name(item["field"])}"; filename="{filename}"\r\nContent-Type: {item["content_type"]}\r\n\r\n'
                    ).encode(),
                    content,
                    b"\r\n",
                ]
            )
        parts.append(f"--{boundary}--\r\n".encode())
        result, mime = b"".join(parts), f"multipart/form-data; boundary={boundary}"
    else:
        raise ValueError("credential_request_invalid")
    if len(result) > MAX_INPUT:
        raise ValueError("credential_use_limit")
    return result, mime
