"""Private compatibility transport; no credential reaches prompts or receipts."""

import asyncio
import json
import os
import subprocess
from pathlib import Path

from app.agent_app.framework_cli import _terminate


async def _private_transport(cli, path, app_id, mode):
    argv, env = await asyncio.to_thread(cli._prepare, "agent-app", {})
    argv[1:] = [str(Path(__file__).with_suffix(".mjs")), str(cli.package_dir), path, app_id, mode]
    proc = await asyncio.create_subprocess_exec(
        *argv, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), 15)
    except BaseException:
        await _terminate(proc)
        raise
    if proc.returncode or not stdout or len(stdout) > 256 * 1024:
        raise PermissionError("The local app credential is unavailable. Restart the app and try again.")
    return stdout.decode("utf-8").strip()


async def local_owner_token(cli, path, app_id):
    return await _private_transport(cli, path, app_id, "credential")


async def pending_tasks(cli, path, app_id):
    return json.loads(await _private_transport(cli, path, app_id, "pending"))
