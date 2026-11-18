"""Resolve explicit native references and retired IDs using a fresh registry."""

import asyncio
import json
from pathlib import Path

from app.agent_app import framework


async def reference_app(target_id):
    from app.agent_app.framework_host import get_host

    host = get_host()
    if not target_id.startswith("framework:") and (
        not host
        or not any(m["legacyId"] == target_id for m in host.store.all("migration"))
    ):
        return None
    cli = await asyncio.to_thread(framework.configured_cli)
    identity = None
    if target_id.startswith("framework:"):
        try:
            identity = json.loads(target_id[len("framework:") :])
        except ValueError as error:
            raise ValueError("Invalid framework app reference.") from error
        if (
            not isinstance(identity, list)
            or len(identity) != 2
            or not all(isinstance(s, str) for s in identity)
        ):
            raise ValueError("Invalid framework app reference.")
    else:
        if host:
            for receipt in reversed(host.store.all("migration")):
                if receipt["legacyId"] == target_id and receipt["home"] == str(
                    cli.home
                ):
                    if receipt["phase"] == "complete":
                        identity = [receipt["target"], receipt["appId"]]
                    break
    if identity is None:
        return None
    snapshot = await framework._list_apps(cli)
    if snapshot["status"] != "success":
        raise ValueError("Could not refresh the referenced app's registry.")
    row = next(
        (r for r in snapshot["data"]["apps"] if [r["path"], r["id"]] == identity), None
    )
    if not row:
        raise ValueError(
            "The referenced framework app is no longer registered at this location."
        )
    return row


async def describe_reference(row):
    manifest = json.loads(
        await asyncio.to_thread(
            (Path(row["path"]) / "manifest.json").read_text, encoding="utf-8"
        )
    )
    return {
        "name": row["name"],
        "status": row["status"],
        "framework": "Agent-App",
        "modules": [
            {k: m[k] for k in ("name", "summary", "entities") if k in m}
            for m in manifest.get("modules", [])[:50]
            if isinstance(m, dict)
        ],
        "operationDiscovery": {
            "actionSet": "a2app",
            "action": "a2app_command",
            "args": [row["path"]],
        },
    }
