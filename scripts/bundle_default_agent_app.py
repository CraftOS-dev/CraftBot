#!/usr/bin/env python3
"""Refresh the included Kanban from its pinned upstream revision.

Run from any directory with Python (stdlib only). This is a maintainer task;
installation reads the resulting bundle and never downloads marketplace code.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
DESTINATION = REPO_ROOT / "app" / "data" / "default_agent_app"
REPOSITORY = "CraftOS-dev/living-ui-marketplace"
REVISION = "b09584c6bb858237e8eaa6f2d4a0dc0d558a10eb"
APP_ID = "kanban-board"


def build_bundle(upstream: bytes) -> bytes:
    """Extract just the published app and its license into a repeatable ZIP."""
    files = {}
    with zipfile.ZipFile(io.BytesIO(upstream)) as source:
        for member in source.infolist():
            if member.is_dir():
                continue
            parts = member.filename.split("/")
            if len(parts) > 2 and parts[1] == APP_ID:
                relative = "/".join(parts[2:])
                if any(
                    part
                    in (
                        "..",
                        "node_modules",
                        "pb_data",
                        ".superuser",
                        ".git",
                        ".factory",
                        ".snapshots",
                        "logs",
                    )
                    for part in parts
                ):
                    raise ValueError(
                        f"Unexpected runtime state in upstream: {member.filename}"
                    )
                files[relative] = source.read(member)
            elif len(parts) == 2 and parts[1] == "LICENSE":
                files["LICENSE"] = source.read(member)
    if "LICENSE" not in files:
        raise ValueError("Upstream license missing")
    manifest = json.loads(files["manifest.json"])
    manifest["marketplaceAppId"] = APP_ID
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(2026, 10, 31, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            bundle.writestr(member, data)
    return output.getvalue()


def main() -> None:
    url = f"https://codeload.github.com/{REPOSITORY}/zip/{REVISION}"
    request = urllib.request.Request(url, headers={"User-Agent": "CraftBot"})
    with urllib.request.urlopen(request, timeout=120) as response:
        bundle = build_bundle(response.read())
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / "kanban-board.zip").write_bytes(bundle)
    provenance = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "appId": APP_ID,
        "sha256": hashlib.sha256(bundle).hexdigest(),
    }
    (DESTINATION / "source.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Bundled {APP_ID} at {REVISION}: {len(bundle):,} bytes")


if __name__ == "__main__":
    main()
