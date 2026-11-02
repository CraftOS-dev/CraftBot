#!/usr/bin/env python3
"""Refresh the included Kanban from the configured marketplace ref.

Run with CraftBot's Python environment. Repository aliases and the ref come
from the existing marketplace configuration. source.json supplies the app ID
and records the resulting commit/checksum; installation uses the bundled ZIP.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.error
from urllib.parse import quote
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
DESTINATION = REPO_ROOT / "app" / "data" / "default_agent_app"
APP_ID = json.loads((DESTINATION / "source.json").read_text(encoding="utf-8"))["appId"]


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
    sys.path.insert(0, str(REPO_ROOT))
    from app.agent_app import marketplace_source

    selected_ref = quote(marketplace_source.ref(), safe="")
    for index, repository in enumerate(marketplace_source.REPOS):
        try:
            commit = json.loads(
                marketplace_source._read_url(
                    f"https://api.github.com/repos/{repository}/commits/{selected_ref}",
                    120,
                )
            )
            revision = commit["sha"]
            upstream = marketplace_source._read_url(
                f"https://codeload.github.com/{repository}/zip/{revision}", 120
            )
            break
        except (urllib.error.URLError, OSError):
            if index == len(marketplace_source.REPOS) - 1:
                raise
    bundle = build_bundle(upstream)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / f"{APP_ID}.zip").write_bytes(bundle)
    provenance = {
        "repository": repository,
        "revision": revision,
        "appId": APP_ID,
        "sha256": hashlib.sha256(bundle).hexdigest(),
    }
    (DESTINATION / "source.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Bundled {APP_ID} from {repository} at {revision}: {len(bundle):,} bytes")


if __name__ == "__main__":
    main()
