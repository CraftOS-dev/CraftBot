"""Sanitized profile packages, using upstream export and install policies.

These are distribution packages, never a backup of live app data or grants.
Only apps attached to this CraftBot profile travel in a shared profile bundle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from app.agent_app import framework
from app.agent_app.framework_host import get_host
from app.agent_app.framework_store import HostStore
from app import paths


async def export_packages(staging: Path) -> list[dict]:
    host = get_host()
    store_path = paths.STATE_ROOT / "agent-app-host.sqlite3"
    if not host and not store_path.is_file():
        return []
    store = host.store if host else HostStore(store_path)
    cli = await asyncio.to_thread(framework.configured_cli)
    attachments = [a for a in store.all("attachment") if a.get("home") == str(cli.home)]
    if not attachments:
        return []
    snapshot = await framework._list_apps(cli)
    if snapshot["status"] != "success":
        raise ValueError(snapshot["message"])
    rows = snapshot["data"]["apps"]
    root = staging / "framework_apps"
    root.mkdir()
    entries = []
    for attachment in attachments:
        row = next(
            (
                r
                for r in rows
                if r["path"] == attachment["path"] and r["id"] == attachment["appId"]
            ),
            None,
        )
        if row is None:
            continue  # An attachment can outlive a removed registry entry.
        filename = f"{len(entries):04d}.zip"
        result = await cli.run(
            "agent-app",
            [row["path"], "export", "--out", str(root / filename)],
            cwd=cli.package_dir,
            timeout=600,
        )
        if not result.ok or not (root / filename).is_file():
            raise ValueError(f"Could not export {row['name']}: {result.stderr}")
        entries.append(
            {
                "file": filename,
                "name": row["name"],
                "sha256": hashlib.sha256((root / filename).read_bytes()).hexdigest(),
            }
        )
    (root / "index.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries


def stage_packages(bundle_root: Path) -> list[dict]:
    """Validate the complete index before copying packages to durable staging.

    Installing is a separate native job after the profile has been imported.
    Never merge a package into an existing app or copy the sender's registry.
    """
    root = bundle_root / "framework_apps"
    if not root.exists():
        return []
    entries = json.loads((root / "index.json").read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) > 500:
        raise ValueError("Invalid framework package index.")
    selected = []
    for entry in entries:
        filename = entry.get("file")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or not filename.endswith(".zip")
        ):
            raise ValueError("Invalid framework package filename.")
        source = root / filename
        if (
            source.is_symlink()
            or not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != entry.get("sha256")
        ):
            raise ValueError("Framework package checksum mismatch.")
        selected.append((source, entry))
    if not selected:
        return []
    destination = paths.STATE_ROOT / "framework-imports" / uuid.uuid4().hex
    destination.mkdir(parents=True)
    staged = []
    for source, entry in selected:
        target = destination / source.name
        shutil.copyfile(source, target)
        staged.append(
            {"from": str(target), "name": str(entry.get("name") or source.stem)}
        )
    return staged
