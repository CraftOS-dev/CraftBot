"""Private compatibility transport; no credential reaches prompts or receipts."""

import asyncio
import json
import os
import subprocess
from pathlib import Path

from app.agent_app.framework_cli import _terminate


async def _private_transport(cli, path, app_id, mode, *, endpoint="", token=""):
    from app.agent_app.framework_connections import is_connection
    remote = is_connection(path)
    argv, env = await asyncio.to_thread(cli._prepare, "agent-app", {})
    script = Path(__file__).with_name("framework_connections.mjs") if remote else Path(__file__).with_suffix(".mjs")
    argv[1:] = [str(script), str(cli.package_dir), path, app_id, mode, endpoint]
    if token:
        env["CRAFTBOT_BRIDGE_TOKEN"] = token
    proc = await asyncio.create_subprocess_exec(
        *argv, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), None if mode == "pump" else 25 if remote else 15)
    except BaseException:
        await _terminate(proc)
        raise
    if proc.returncode or (not stdout and mode != "pump") or len(stdout) > 256 * 1024:
        raise PermissionError("The app connection is unavailable or its access has changed. Reconnect to the app." if remote else "The local app credential is unavailable. Restart the app and try again.")
    return stdout.decode("utf-8").strip()


async def local_owner_token(cli, path, app_id):
    return await _private_transport(cli, path, app_id, "credential")


async def pending_tasks(cli, path, app_id):
    return json.loads(await _private_transport(cli, path, app_id, "pending"))
