"""The frontend-only artifact contract. Browser isolation lives in the renderer."""

import re
import uuid
from html.parser import HTMLParser
from pathlib import Path

MAX_HTML_BYTES = 512_000
MAX_ORIGINS = 8
#: Libraries an output can preload. The frontend bundles them
#: (frontend/generativeUILibraries.ts, components/GenerativeUI/assets.ts).
LIBRARIES = frozenset({"chart", "leaflet", "lucide", "motion", "three"})
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8_000_000
MAX_TOTAL_IMAGE_BYTES = 16_000_000
IMAGE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,39}")


def persistence_contract(html: str, mode: object) -> str:
    """Validate a declared persistence strategy, without inspecting JS wording."""
    if mode not in ("controls", "manual", "none"):
        raise ValueError("persistence must be controls, manual or none.")
    if mode != "controls":
        return mode

    class Controls(HTMLParser):
        keys: dict[str, str] = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            kind = (attrs.get("type") or "text").lower()
            if tag not in ("input", "select", "textarea") or (
                tag == "input" and kind in ("button", "submit", "reset", "image")
            ):
                return
            if kind in ("password", "file", "hidden"):
                raise ValueError(
                    "Sensitive/file/hidden controls require manual persistence; never save secrets."
                )
            key = attrs.get("data-craftbot-state") or attrs.get("id")
            if (
                not key
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key)
                or key in ("__proto__", "constructor", "prototype")
            ):
                raise ValueError(
                    "Every persisted control needs a stable id or data-craftbot-state key."
                )
            if key in self.keys and not (kind == "radio" and self.keys[key] == "radio"):
                raise ValueError(f"Duplicate persistence key: {key}")
            self.keys[key] = kind

    parser = Controls()
    parser.feed(html)
    return mode


def normalize_origins(value: object, field: str) -> list[str]:
    """Accept exact public HTTPS origins, never CSP expressions or local hosts."""
    if not isinstance(value, list) or len(value) > MAX_ORIGINS:
        raise ValueError(f"{field} must be a list of at most 8 HTTPS origins.")
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
                f"{field} must contain exact public HTTPS origins, without paths, credentials or wildcards."
            )
        origins.add(f"https://{host}")
    return sorted(origins)


def normalize_libraries(value: object) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(name, str) or name not in LIBRARIES for name in value
    ):
        raise ValueError(
            f"libraries must be a list of: {', '.join(sorted(LIBRARIES))}."
        )
    return sorted(set(value))


def image_kind(data: bytes) -> str | None:
    """The file extension an image's own bytes declare, if it is one the
    output can show."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def read_images(value: object) -> dict[str, tuple[bytes, str]]:
    """Read the local image files an output shows: name -> (bytes, extension)."""
    if not isinstance(value, dict) or len(value) > MAX_IMAGES:
        raise ValueError("images must map at most 8 names to image file paths.")
    images: dict[str, tuple[bytes, str]] = {}
    total = 0
    for name, path in value.items():
        if not isinstance(name, str) or not IMAGE_NAME.fullmatch(name):
            raise ValueError(
                f"Image name {name!r} must be letters, digits or _ (a JS identifier)."
            )
        file = Path(path).expanduser() if isinstance(path, str) else None
        if file is None or not file.is_file():
            raise ValueError(f"Image {name!r}: {path!r} is not a file.")
        if file.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError(f"Image {name!r} exceeds {MAX_IMAGE_BYTES} bytes.")
        data = file.read_bytes()
        kind = image_kind(data)
        if kind is None:
            raise ValueError(f"Image {name!r} must be a PNG, JPEG, GIF or WebP file.")
        total += len(data)
        if total > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError(f"images exceed {MAX_TOTAL_IMAGE_BYTES} bytes in total.")
        images[name] = (data, kind)
    return images


def closed_artifact(artifact: dict) -> dict:
    """What remains of an artifact the user closed: who it was (so a later
    revision still numbers on), never its code or network permissions."""
    return {
        "id": artifact.get("id"),
        "title": artifact.get("title"),
        "revision": artifact.get("revision"),
        "closed": True,
    }


def make_artifact(data: dict, revision: int = 1) -> dict:
    title = data.get("title")
    html = data.get("html")
    artifact_id = data.get("artifact_id") or uuid.uuid4().hex
    connect_origins = normalize_origins(
        data.get("connect_origins", []), "connect_origins"
    )
    image_origins = normalize_origins(data.get("image_origins", []), "image_origins")
    libraries = normalize_libraries(data.get("libraries", []))
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
        "image_origins": image_origins,
        "libraries": libraries,
        "persistence": persistence_contract(html, data.get("persistence", "manual")),
    }
