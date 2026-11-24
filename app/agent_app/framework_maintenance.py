"""CraftBot preferences and schedules; Agent-App still owns app/data lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

from app.agent_app import framework
from app.agent_app.framework_cli import _terminate
from app.agent_app.framework_commands import command
from app.agent_app.framework_store import app_key

INTERVALS = {"hourly": 3600, "6h": 21600, "daily": 86400, "weekly": 604800}
FIRST_RETRY = 300


def retry_delay(failures, interval):
    """Back off after consecutive failures, never beyond the regular interval,
    so a backup that keeps failing is not retried every few minutes."""
    return min(FIRST_RETRY * 2 ** max(failures - 1, 0), INTERVALS[interval])


def record_failure(attachment, error, now):
    failures = attachment.get("backupFailures", 0) + 1
    attachment.update(
        backupError=error,
        backupFailures=failures,
        nextBackupAt=now
        + retry_delay(failures, attachment.get("backupInterval", "daily")),
    )


class BackupFailed(RuntimeError):
    """A backup failure that backup() already recorded on the attachment."""


APP_THEMES = frozenset(
    "craftbot modern normal ocean forest pastel glass classic velvet ink acid blueprint brutalist drafting clay atelier custom".split()
)


def validate_ui_theme(value):
    """CraftBot presentation preferences; never written into framework apps."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("themeId"), str)
        or value["themeId"] not in APP_THEMES
    ):
        raise ValueError("Choose a supported app theme.")
    result = {"themeId": value["themeId"]}
    if value["themeId"] == "custom":
        colors = value.get("customColors")
        if not isinstance(colors, dict) or any(
            not isinstance(colors.get(key), str)
            or not re.fullmatch(r"#[0-9a-fA-F]{6}", colors[key])
            for key in ("bg", "surface", "text", "accent")
        ):
            raise ValueError("Choose four valid hex colours for the custom theme.")
        result["customColors"] = {
            key: colors[key] for key in ("bg", "surface", "text", "accent")
        }
    return result


async def housekeeping(cli, path, app_id, operation, *args, timeout=120):
    argv, env = await asyncio.to_thread(cli._prepare, "agent-app", {})
    argv[1:] = [
        str(Path(__file__).with_suffix(".mjs")),
        str(cli.package_dir),
        path,
        app_id,
        operation,
        *args,
    ]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **(
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt"
            else {"start_new_session": True}
        ),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        await _terminate(proc)
        raise
    if proc.returncode:
        raise RuntimeError(
            stderr.decode("utf-8", errors="replace") or "App housekeeping failed."
        )
    return json.loads(stdout)


class FrameworkMaintenance:
    def __init__(self, host):
        self.host = host
        self.task = None

    def patch(self, attachment, data):
        values = {}
        if "uiTheme" in data:
            values["uiTheme"] = validate_ui_theme(data["uiTheme"])
            # Remember the custom palette when a preset is selected. The host
            # sends these overrides only while Custom is active.
            colors = (attachment.get("uiTheme") or {}).get("customColors")
            if colors and "customColors" not in values["uiTheme"]:
                values["uiTheme"]["customColors"] = colors
        for name in ("autoStart", "logCleanup", "backupsEnabled"):
            if name in data:
                if not isinstance(data[name], bool):
                    raise ValueError(f"{name} must be a boolean.")
                values[name] = data[name]
        if "backupInterval" in data:
            if data["backupInterval"] not in INTERVALS:
                raise ValueError("Choose hourly, 6h, daily or weekly backups.")
            values["backupInterval"] = data["backupInterval"]
        if "backupKeep" in data:
            if type(data["backupKeep"]) is not int or not 1 <= data["backupKeep"] <= 30:
                raise ValueError("Keep between 1 and 30 backups.")
            values["backupKeep"] = data["backupKeep"]
        if "backupsEnabled" in values or "backupInterval" in values:
            values["nextBackupAt"] = (
                time.time()
                + INTERVALS[
                    values.get(
                        "backupInterval", attachment.get("backupInterval", "daily")
                    )
                ]
            )
        attachment.update(values)
        if "nextBackupAt" in values:
            attachment.pop("backupFailures", None)  # a new schedule starts clean
        self.host.store.put("attachment", attachment["key"], attachment)
        return attachment

    async def before_start(self, cli, path, app_id):
        saved = self.host.store.get("attachment", app_key(cli.home, path, app_id)) or {}
        if saved.get("logCleanup"):
            await housekeeping(cli, path, app_id, "clean-logs")

    async def before_remove(self, path, app_id):
        cli = await asyncio.to_thread(framework.configured_cli)
        support = (await housekeeping(cli, path, app_id, "layout")).get(
            "backupSupport", {}
        )
        if support.get("mode") == "parent-toolkit":
            # Upstream remove archives snapshots, but cannot discover live data
            # through an absent custom toolkit. Capture the explicit parent's
            # data first; failure must leave the app and its registry intact.
            await self.backup(path, app_id, trigger="pre-remove")

    async def info(self, path, app_id):
        row = await self.host.selected(path, app_id)
        cli = await asyncio.to_thread(framework.configured_cli)
        key = app_key(cli.home, path, app_id)
        saved = self.host.store.get("attachment", key) or {}
        listing = await housekeeping(cli, path, app_id, "list")
        entries = listing["backups"]
        for entry in entries:
            receipt = self.host.store.get("backup", key + ":" + entry["filename"]) or {}
            entry["trigger"] = receipt.get("trigger", "manual")
        return {
            "port": row.get("port"),
            "backups": entries,
            "backupStatus": {
                "lastAt": entries[0]["ts"] / 1000 if entries else None,
                "count": len(entries),
                "totalSize": sum(e["size"] for e in entries),
                "lastError": saved.get("backupError"),
            },
            "links": self.host.sharing.links(path, app_id),
            "backupSupport": listing.get("backupSupport"),
        }

    async def backup(
        self, path, app_id, verb="backup", backup_id=None, trigger="manual"
    ):
        async with framework.lifecycle_lock(path):
            row = await self.host.selected(path, app_id)
            attachment = await self.host.attach(path, app_id)
            cli = await asyncio.to_thread(framework.configured_cli)
            if verb not in {"backup", "restore", "delete"}:
                raise ValueError("Unsupported backup action.")
            if verb != "backup":
                known = (await housekeeping(cli, path, app_id, "list"))["backups"]
                if not backup_id or backup_id not in {b["filename"] for b in known}:
                    raise ValueError("Choose an existing backup.")
            if verb == "delete":
                await housekeeping(cli, path, app_id, "delete", backup_id)
                return {"status": "success", "data": {"ok": True}}
            if row["status"] not in {"running", "stopped"}:
                raise ValueError("The app is unavailable. Refresh its status.")
            # A running app is backed up live, so its tasks, visitors and share
            # links carry on. Restore replaces the data the app has open, so it
            # still stops and restarts the app.
            live = verb == "backup" and row["status"] == "running"
            if not live and any(
                r["path"] == path and r["authority"].active
                for r in self.host.bridge.runs.values()
            ):
                raise ValueError(
                    "Wait for this app’s active tasks to finish before backing up or restoring."
                )
            support = (await housekeeping(cli, path, app_id, "layout")).get(
                "backupSupport", {"mode": "cli"}
            )
            if not support.get("mode"):
                raise ValueError(support["reason"])
            restarts = row["status"] == "running" and not live
            if restarts:
                attachment["maintenanceResume"] = True
                self.host.store.put("attachment", attachment["key"], attachment)
            result = None
            failure = None
            try:
                if restarts:
                    stopped = await framework.change_app_state_locked(
                        path, app_id, "stop", preserve_shares=True,
                        reason=f"{trigger} {verb}",
                    )
                    if stopped["status"] != "success":
                        raise RuntimeError(
                            stopped.get("message", "The app could not stop.")
                        )
                args = [path, verb] + ([backup_id] if backup_id else [])
                if live:
                    doc = await housekeeping(
                        cli, path, app_id, "backup-live", timeout=1200
                    )
                    result = {"status": "success", "data": doc}
                elif support["mode"] == "parent-toolkit":
                    doc = await housekeeping(
                        cli,
                        path,
                        app_id,
                        f"{verb}-parent",
                        *([backup_id] if backup_id else []),
                    )
                    result = {"status": "success", "data": doc}
                else:
                    result = await command("agent-app", args, _locked=True)
                if (
                    result["status"] != "success"
                    or (result.get("data") or {}).get("ok") is not True
                ):
                    raise RuntimeError(
                        result.get("stderr")
                        or "Agent-App could not complete the backup action."
                    )
                if verb == "backup":
                    backup_id = result["data"]["backup"]
                    self.host.store.put(
                        "backup",
                        attachment["key"] + ":" + backup_id,
                        {"trigger": trigger},
                    )
                    entries = (await housekeeping(cli, path, app_id, "list"))["backups"]
                    # Match Kanban: retention removes scheduled snapshots only.
                    # Manual, external and upstream safety backups are preserved.
                    owned = [
                        b["filename"]
                        for b in entries
                        if (
                            self.host.store.get(
                                "backup", attachment["key"] + ":" + b["filename"]
                            )
                            or {}
                        ).get("trigger")
                        == "scheduled"
                    ]
                    expired = owned[attachment.get("backupKeep", 7) :]
                    if expired:
                        await housekeeping(cli, path, app_id, "delete", *expired)
            except asyncio.CancelledError:
                failure = (
                    "Backup action interrupted. Check backup history before retrying."
                )
                raise
            except Exception as exc:
                failure = str(exc)
            finally:
                if restarts:
                    # Keep the resume receipt if restart fails or shutdown interrupts us.
                    try:
                        started = await framework.change_app_state_locked(
                            path, app_id, "start", reason=f"after {trigger} {verb}"
                        )
                        if started["status"] != "success":
                            raise RuntimeError(
                                started.get("message", "The app could not restart.")
                            )
                        attachment.pop("maintenanceResume", None)
                    except Exception as exc:
                        failure = f"{failure + '; ' if failure else ''}Restart: {exc}"
                # Merge with any preferences changed during a long-running command.
                saved = (
                    self.host.store.get("attachment", attachment["key"]) or attachment
                )
                if failure:
                    record_failure(saved, failure, time.time())
                else:
                    saved.update(
                        backupError=None,
                        nextBackupAt=time.time()
                        + INTERVALS[saved.get("backupInterval", "daily")],
                    )
                    saved.pop("backupFailures", None)
                if not attachment.get("maintenanceResume"):
                    saved.pop("maintenanceResume", None)
                self.host.store.put("attachment", saved["key"], saved)
                await self.host.changed()
            if failure:
                raise BackupFailed(failure)
            return result

    async def tick(self, now=None):
        now = time.time() if now is None else now
        cli = await asyncio.to_thread(framework.configured_cli)
        for saved in self.host.store.all("attachment"):
            if self.host.closing:
                return
            if (
                saved.get("home") != str(cli.home)
                or not saved.get("backupsEnabled")
                or saved.get("nextBackupAt", now + 1) > now
            ):
                continue
            try:
                await self.backup(saved["path"], saved["appId"], trigger="scheduled")
            except BackupFailed:
                pass  # backup() recorded it and scheduled the retry
            except Exception as exc:
                latest = self.host.store.get("attachment", saved["key"]) or saved
                record_failure(latest, str(exc), now)
                self.host.store.put("attachment", saved["key"], latest)
                await self.host.changed()

    async def run(self):
        while not self.host.closing:
            try:
                await self.tick()
            except Exception:
                pass  # Discovery reports unavailable CLI; retry next minute.
            await asyncio.sleep(60)

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
