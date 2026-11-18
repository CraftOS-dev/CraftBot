#!/usr/bin/env python3
"""Refresh bundled Kanban from source.json's repository/ref (main by default).

Use --ref for a one-off candidate; it records the resolved commit and sourceRef
without changing the configured update ref. App and toolkit files are unmodified.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
DESTINATION = REPO_ROOT / "app/data/default_agent_app"
APP_ID = "kanban-board"


def build_bundle(upstream: bytes) -> bytes:
    """Package a one-app offline catalogue with its separately resolved toolkit."""
    with zipfile.ZipFile(io.BytesIO(upstream)) as source:
        root = source.namelist()[0].split("/")[0] + "/"
        catalogue = json.loads(source.read(root + "catalogue.json"))
        app = next(row for row in catalogue["apps"] if row["id"] == APP_ID)
        if app.get("folder") != APP_ID:
            raise ValueError("Unexpected marketplace app folder")
        manifest = json.loads(source.read(root + APP_ID + "/manifest.json"))
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("agentAppVersion", ""))):
            raise ValueError("Kanban is still in the legacy format; await its framework release.")
        toolkit = json.loads(source.read(root + APP_ID + "/.a2app/toolkit.json"))["id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", toolkit):
            raise ValueError("Invalid marketplace toolkit ID")
        toolkit_prefix = f"toolkits/{toolkit}/"
        toolkit_manifest = json.loads(source.read(root + toolkit_prefix + "a2app.toolkit.json"))
        if toolkit_manifest["id"] != toolkit or app.get("toolkit") != toolkit:
            raise ValueError("Marketplace toolkit declarations disagree")
        files = {}
        for member in source.infolist():
            if member.is_dir() or not member.filename.startswith(root):
                continue
            name = member.filename[len(root):]
            if not name.startswith((APP_ID + "/", toolkit_prefix)):
                continue
            parts = PurePosixPath(name).parts
            if (".." in parts or "\\" in name or ":" in name
                    or (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe marketplace archive entry")
            if set(parts) & {
                "node_modules", "pb_data", "pb_public", ".superuser", ".git",
                ".factory", ".snapshots", "logs", "credentials.json", "live.json",
                "dev.json", "gate-pass.json",
            }:
                raise ValueError(f"Unexpected runtime state in upstream: {name}")
            if name in files:
                raise ValueError("Duplicate marketplace archive entry")
            files[name] = source.read(member)
        license_data = source.read(root + "LICENSE")
        files.setdefault(APP_ID + "/LICENSE", license_data)
        files.setdefault(toolkit_prefix + "LICENSE", license_data)
        files["catalogue.json"] = (json.dumps({"apps": [app]}, indent=2) + "\n").encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(2026, 10, 31, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            bundle.writestr(member, data)
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="One-off source ref; future refreshes still use source.json's ref")
    args = parser.parse_args()
    config = json.loads((DESTINATION / "source.json").read_text(encoding="utf-8"))
    repository = config["repository"]
    update_ref = config.get("ref", "main")
    selected_ref = args.ref or update_ref
    def download(url):
        with urlopen(Request(url, headers={"User-Agent": "CraftBot-bundle"}), timeout=120) as response:
            return response.read()

    commit = json.loads(download(
        f"https://api.github.com/repos/{repository}/commits/{quote(selected_ref, safe='')}",
    ))
    revision = commit["sha"]
    upstream = download(f"https://codeload.github.com/{repository}/zip/{revision}")
    bundle = build_bundle(upstream)
    provenance = {
        "repository": repository, "ref": update_ref, "sourceRef": selected_ref,
        "revision": revision, "appId": APP_ID,
        "sha256": hashlib.sha256(bundle).hexdigest(),
    }
    (DESTINATION / f"{APP_ID}.zip").write_bytes(bundle)
    (DESTINATION / "source.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Bundled {APP_ID} from {repository} at {revision}: {len(bundle):,} bytes")


if __name__ == "__main__":
    main()
