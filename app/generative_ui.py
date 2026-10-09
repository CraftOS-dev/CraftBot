"""The frontend-only artifact contract. Browser isolation lives in the renderer."""

import re
import uuid

MAX_HTML_BYTES = 512_000
MAX_CONNECT_ORIGINS = 8


def normalize_connect_origins(value: object) -> list[str]:
    """Accept exact public HTTPS origins, never CSP expressions or local hosts."""
    if not isinstance(value, list) or len(value) > MAX_CONNECT_ORIGINS:
        raise ValueError("connect_origins must be a list of at most 8 HTTPS origins.")
    origins = set()
    for origin in value:
        match = (
            re.fullmatch(r"https://([A-Za-z0-9.-]+)(?::443)?/?", origin)
            if isinstance(origin, str)
            else None
        )
        host = match[1].lower() if match else ""
        labels = host.split(".")
        if (
            len(host) > 253
            or len(labels) < 2
            or not re.fullmatch(r"[a-z]{2,63}", labels[-1])
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
            or labels[-1]
            in {
                "localhost",
                "local",
                "internal",
                "lan",
                "home",
                "corp",
                "arpa",
                "onion",
                "test",
                "invalid",
            }
        ):
            raise ValueError(
                "connect_origins must contain exact public HTTPS origins, without paths, credentials or wildcards."
            )
        origins.add(f"https://{host}")
    return sorted(origins)


def make_artifact(data: dict, revision: int = 1) -> dict:
    title = data.get("title")
    html = data.get("html")
    artifact_id = data.get("artifact_id") or uuid.uuid4().hex
    connect_origins = normalize_connect_origins(data.get("connect_origins", []))
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        raise ValueError("title must contain 1–120 characters.")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("html must be a complete HTML document.")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError(f"html exceeds {MAX_HTML_BYTES} bytes.")
    if not isinstance(artifact_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,80}", artifact_id
    ):
        raise ValueError("artifact_id must contain 1–80 letters, digits, _ or -.")
    return {
        "id": artifact_id,
        "title": title.strip(),
        "html": html,
        "revision": revision,
        "connect_origins": connect_origins,
    }
