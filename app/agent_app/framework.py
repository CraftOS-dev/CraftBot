"""CraftBot entry points into the unchanged Agent-App framework CLI.

The pinned distribution is automatic; an explicit package override remains for
development. Framework state uses the shared A2APP_HOME (or ~/.a2app).
"""

from __future__ import annotations

import asyncio
import os
from itertools import count
from pathlib import Path
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

from app import agent_app_package
from app.agent_app.framework_cli import AgentAppCLI

# Only coordinates commands issued by this CraftBot process. The unchanged CLI
# retains its own filesystem locks; independent harnesses are outside this lock.
_lifecycle_locks: WeakValueDictionary = WeakValueDictionary()
_registry_observations = count(1)


def registry_observation() -> int:
    """Order host reads even on platforms whose clock ticks have equal values."""
    return next(_registry_observations)


def configured_cli() -> AgentAppCLI:
    """Select the built package and framework profile for this invocation."""
    package = os.environ.get("CRAFTBOT_AGENT_APP_PACKAGE", "").strip()
    package_dir = (
        Path(package).expanduser() if package else agent_app_package.ensure_package()
    )
    override = os.environ.get("A2APP_HOME", "")
    # Match the CLI: a nonblank override is resolved as supplied. Do not trim
    # meaningful spaces or expand a literal '~' in the framework's home path.
    home = Path(override) if override.strip() else Path.home() / ".a2app"
    return AgentAppCLI(package_dir, home=home)


async def list_apps() -> dict:
    """Run the framework's registry query and retain its data and diagnostics."""
    # First-use unpacking and cache verification must not block the server loop.
    cli = await asyncio.to_thread(configured_cli)
    return await _list_apps(cli)


async def _list_apps(cli: AgentAppCLI) -> dict:
    result = await cli.run(
        "agent-app", ["list", "--json"], cwd=cli.package_dir, timeout=30
    )
    data = result.json()
    response = {"exit_code": result.code, "stderr": result.stderr}
    if result.timed_out:
        message = "Agent-App registry listing timed out."
    elif not result.ok:
        message = f"Agent-App registry listing failed (exit code {result.code})."
    elif (
        not isinstance(data, dict)
        or data.get("ok") is not True
        or not isinstance(data.get("apps"), list)
        or not isinstance(data.get("connected"), list)
    ):
        message = "Agent-App returned an invalid registry response."
    else:
        return {"status": "success", "data": data, **response}
    return {
        "status": "error",
        "message": message,
        "stdout": result.stdout,
        **response,
    }


async def open_app_view(path: str, app_id: str) -> dict:
    """Resolve a registered local app's live view; never launch it or a browser."""

    def failure(code: str, message: str) -> dict:
        return {"status": "error", "code": code, "message": message}

    if (
        not isinstance(path, str)
        or not path
        or not isinstance(app_id, str)
        or not app_id
    ):
        return failure(
            "not_registered", "Select a local app from the framework registry."
        )
    cli = await asyncio.to_thread(configured_cli)
    snapshot = await _list_apps(cli)
    if snapshot["status"] != "success":
        return failure("query_failed", snapshot["message"])
    # A path disambiguates copied apps with the same ID. The refreshed ID must
    # also match the row the person selected; never silently open its replacement.
    app = next(
        (row for row in snapshot["data"]["apps"] if row.get("path") == path), None
    )
    if app is None:
        return failure(
            "not_registered", "This app is no longer in the framework registry."
        )
    if app.get("id") != app_id:
        return failure(
            "identity_changed",
            "The app at this location has changed.",
        )
    if app.get("status") != "running":
        status = app.get("status")
        return failure(
            status
            if status in {"stopped", "missing", "unreachable"}
            else "unreachable",
            "The selected app is not currently available.",
        )
    # The pinned sidecar blueprint serves protocol/account pages at this URL,
    # not the adopted UI. Its CLI has no separate view-address result yet.
    if await asyncio.to_thread((Path(path) / "sidecar.json").is_file):
        return failure(
            "separate_view",
            "This app's interface uses a separate address that the CLI does not expose.",
        )
    result = await cli.run(
        "agent-app", [path, "open", "--print-only"], cwd=cli.package_dir, timeout=10
    )
    data = result.json()
    if result.timed_out:
        return failure("query_failed", "Checking this app's view timed out.")
    if not result.ok:
        code = "stopped" if result.code == 3 else "unreachable"
        return failure(code, "Agent-App could not verify the running app.")
    if (
        not isinstance(data, dict)
        or data.get("ok") is not True
        or data.get("id") != app_id
    ):
        return failure(
            "identity_changed",
            "Agent-App returned a different or invalid app identity.",
        )
    url = data.get("url")
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        valid = (
            parsed is not None
            and parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None
            and parsed.port > 0
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        return failure(
            "unreachable", "Agent-App did not return a usable local view address."
        )
    return {
        "status": "success",
        "data": {"id": app_id, "path": path, "name": app["name"], "url": url},
    }


def lifecycle_lock(path: str):
    key = (asyncio.get_running_loop(), os.path.normcase(str(Path(path).resolve())))
    return _lifecycle_locks.setdefault(key, asyncio.Lock())


async def change_app_state(path: str, app_id: str, operation: str) -> dict:
    if not isinstance(path, str) or not path:
        return {
            "status": "error",
            "code": "not_registered",
            "message": "Select a local registry app.",
        }
    async with lifecycle_lock(path):
        return await change_app_state_locked(path, app_id, operation)


async def change_app_state_locked(
    path: str, app_id: str, operation: str, *, preserve_shares=False
) -> dict:
    """Start/stop a registered live app, then read its actual framework state."""

    def failure(code: str, message: str, **extra) -> dict:
        return {"status": "error", "code": code, "message": message, **extra}

    if operation not in ("start", "stop"):
        return failure("invalid_request", "Choose Start or Stop.")
    if (
        not isinstance(path, str)
        or not path
        or not isinstance(app_id, str)
        or not app_id
    ):
        return failure("not_registered", "Select a local registry app.")
    cli = await asyncio.to_thread(configured_cli)
    before = await _list_apps(cli)
    if before["status"] != "success":
        return failure("query_failed", before["message"])
    app = next((row for row in before["data"]["apps"] if row.get("path") == path), None)
    if app is None or app.get("id") != app_id:
        return failure(
            "identity_changed", "This registry entry no longer matches the selected app."
        )
    if app.get("status") not in ("running", "stopped"):
        return failure("unavailable", "This app is missing or its port is unavailable.")

    from app.agent_app.framework_host import get_host

    host = get_host()
    if host and operation == "start" and app["status"] == "stopped":
        await host.maintenance.before_start(cli, path, app_id)
    if host and operation == "stop" and not preserve_shares:
        await host.sharing.close_app(path, app_id)

    # No install, browser opener, dev-stop or bridge commands are implied.
    # The serve budget includes upstream's 600s build and 20s health wait.
    try:
        result = await cli.run(
            "agent-app",
            [path, "serve" if operation == "start" else "stop"],
            cwd=cli.package_dir,
            timeout=660 if operation == "start" else 30,
        )
        data = result.json()
        details = {"stderr": result.stderr, "exit_code": result.code}
        if result.timed_out:
            outcome = failure(
                "uncertain",
                "The command timed out. Check the refreshed app state before retrying.",
                **details,
            )
        elif not result.ok or not isinstance(data, dict) or data.get("ok") is not True:
            outcome = failure(
                "command_failed",
                "Agent-App could not complete the command.",
                **details,
            )
        elif operation == "start" and data.get("id") != app_id:
            outcome = failure(
                "identity_changed",
                "Agent-App reported a different app identity.",
                **details,
            )
        else:
            outcome = {"status": "success", **details}
    except Exception as exc:
        outcome = failure("uncertain", str(exc))

    # A stop can return ok with no recorded process while an independently
    # started instance is still running. Never synthesize state from exit 0.
    version = registry_observation()
    try:
        snapshot = await _list_apps(cli)
    except Exception as exc:
        snapshot = {"status": "error", "message": str(exc)}
    outcome.update(registry=snapshot, registry_version=version)
    if snapshot["status"] != "success":
        if outcome["status"] == "success":
            outcome.update(
                status="error",
                code="uncertain",
                message="The command finished but app status could not be checked.",
            )
        return outcome
    current = next(
        (
            row
            for row in snapshot["data"]["apps"]
            if row.get("path") == path and row.get("id") == app_id
        ),
        None,
    )
    expected = "running" if operation == "start" else "stopped"
    if outcome["status"] == "success" and (
        current is None or current.get("status") != expected
    ):
        outcome.update(
            status="error",
            code="state_mismatch",
            message=f"The app did not reach the {expected} state.",
        )
    if current:
        outcome["remaining"] = bool(
            current.get("bridge") or (current.get("dev") or {}).get("answering")
        )
    if outcome["status"] == "success":
        from app.agent_app.framework_host import get_host

        host = get_host()
        if host:
            await host.bridge.lifecycle_changed(path, app_id, operation)
    return outcome
