"""Explicit, journalled migration of legacy installations. No startup cutover.

Generic foreign runtimes remain deferred until their data mapping is supplied.
The automatic data path is deliberately restricted to a verified PocketBase
candidate with no live data. Source files, data, accounts and archives survive.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from app.agent_app import framework
from app.agent_app.framework_bridge import capability_fingerprint


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def data_inventory(directory: Path, columns=None):
    """Read-only counts and hashes, never values in the host receipt/UI."""
    database = directory / "data.db"
    if not database.is_file():
        raise ValueError("No PocketBase data.db found.")
    result = {"tables": {}, "files": {}, "collections": {}}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("The source database failed SQLite integrity checking.")
        all_names = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        names = [
            name
            for name in all_names
            if name == "_superusers" or not name.startswith(("_", "sqlite_"))
        ]
        if "_collections" in all_names:
            db.row_factory = sqlite3.Row
            for collection in db.execute('SELECT * FROM "_collections"'):
                if collection["name"] in names:
                    # Preserve collection IDs, relations, auth settings and access
                    # rules, not just SQLite values. Ignore timestamp churn only.
                    definition = {
                        key: collection[key]
                        for key in collection.keys()
                        if key not in {"created", "updated"}
                    }
                    result["collections"][collection["name"]] = hashlib.sha256(
                        json.dumps(definition, sort_keys=True).encode()
                    ).hexdigest()
            db.row_factory = None
        for name in names:
            schema = {
                r[1]: r[2] for r in db.execute(f"PRAGMA table_info({_quoted(name)})")
            }
            selected = (columns or {}).get(name, list(schema))
            if any(c not in schema for c in selected):
                raise ValueError(f"Migration dropped a column from {name}.")
            hashes = []
            for row in db.execute(
                f"SELECT {','.join(_quoted(c) for c in selected)} FROM {_quoted(name)}"
            ):
                value = [v.hex() if isinstance(v, bytes) else v for v in row]
                hashes.append(
                    hashlib.sha256(
                        json.dumps(
                            value, ensure_ascii=False, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
            result["tables"][name] = {
                "columns": {c: schema[c] for c in selected},
                "count": len(hashes),
                "sha256": hashlib.sha256(
                    "\n".join(sorted(hashes)).encode()
                ).hexdigest(),
            }
    storage = directory / "storage"
    for current, dirs, files in os.walk(storage, followlinks=False):
        if any((Path(current) / d).is_symlink() for d in dirs):
            raise ValueError("File-storage symlinks need a manual migration review.")
        for name in files:
            file = Path(current) / name
            if file.is_symlink():
                raise ValueError(
                    "File-storage symlinks need a manual migration review."
                )
            with file.open("rb") as stream:
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
            result["files"][file.relative_to(storage).as_posix()] = digest.hexdigest()
    return result


def verify_data(before, directory):
    columns = {name: list(table["columns"]) for name, table in before["tables"].items()}
    after = data_inventory(directory, columns)
    differences = [
        f"table:{name}"
        for name, table in before["tables"].items()
        if after["tables"].get(name) != table
    ]
    differences += [
        f"file:{name}"
        for name, digest in before["files"].items()
        if after["files"].get(name) != digest
    ]
    differences += [
        f"collection:{name}"
        for name, digest in before.get("collections", {}).items()
        if after["collections"].get(name) != digest
    ]
    if differences:
        raise ValueError(
            "Migration changed existing data; source retained. Review "
            + ", ".join(differences[:20])
        )
    return after


def source_snapshot(source: Path, destination: Path):
    """Private recovery copy, including config/credentials; never a share package."""
    ignored = {"node_modules", ".git", ".venv", "__pycache__", "pb_data", "pb_public"}
    for current, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if d not in ignored]
        if any((Path(current) / d).is_symlink() for d in dirs):
            raise ValueError("Source links need a manual migration review.")
        relative = Path(current).relative_to(source)
        for name in files:
            original = Path(current) / name
            if original.is_symlink():
                raise ValueError("Source links need a manual migration review.")
            target = destination / relative / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            target.chmod(0o600)


class FrameworkMigration:
    def __init__(self, host, manager):
        self.host, self.manager = host, manager
        self.lock = asyncio.Lock()
        # An interrupted transfer is a recovery item, never a retry instruction.
        for item in host.store.all("migration"):
            if item["phase"] in {
                "quiescing",
                "copying",
                "validating",
                "switching",
                "rolling_back",
            }:
                item.update(
                    phase="interrupted",
                    error="Inspect both installations and recovery artifacts before continuing. No migration was replayed.",
                )
                self.save(item)

    def save(self, item):
        item["updatedAt"] = time.time()
        self.host.store.put("migration", item["id"], item)
        return item

    def inventory(self):
        receipts = self.host.store.all("migration")
        rows = []
        for project in self.manager.list_projects():
            receipt = next(
                (r for r in reversed(receipts) if r["legacyId"] == project.id), None
            )
            row = {
                "id": project.id,
                "name": project.name,
                "path": project.path,
                "status": project.status,
                "migration": receipt,
            }
            row["reason"] = (
                "Requires a verified replacement before switching; the legacy installation remains usable."
            )
            if project.project_type == "external":
                row["reason"] = (
                    "External runtime: requires an app-specific data mapping. Automatic PocketBase transfer is unavailable."
                )
            rows.append(row)
        return {"legacy": rows, "migrations": receipts}

    async def conversion(self, project_id):
        project = self.manager.get_project(project_id)
        if not project or not project.path:
            raise ValueError("Select an existing legacy app.")
        return await self.host.workflow(
            "convert",
            f"Upgrade the existing app at {project.path} into a SEPARATE Agent-App candidate. Treat the source as read-only; preserve all behavior and its data schema. Never install, scaffold or sanitize over the source. Follow the unchanged importer/creator workflow, validate and independently verify. Keep migration filenames/identities for existing PocketBase collections. Do not transfer live data or cut over: the native migration control does that after verification. If schema changes cannot preserve all data, report the required mapping and leave migration deferred.",
        )

    def audit(self, project_id):
        """A live, read-only preview; cutover repeats data checks while stopped."""
        project = self.manager.get_project(project_id)
        if not project or not project.path:
            raise ValueError("Select an existing legacy app.")
        root = Path(project.path)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        result = {
            "id": project.id,
            "path": str(root),
            "runtime": project.project_type,
            "format": {
                k: manifest[k]
                for k in ("version", "a2app", "agentAppVersion", "blueprint")
                if k in manifest
            },
            "sessionId": project.session_id,
            "autoStart": project.auto_launch,
            "backupPolicy": {
                "enabled": project.backups_enabled,
                "transfer": "Existing archives stay with the original installation. Use the replacement's native backup controls; the legacy schedule is not copied.",
            },
            "pendingWork": {},
            "providerReferences": [],
            "operations": [],
            "note": "Preview only. No writer is stopped and no data is transferred. Interrupted work is retained for review, never replayed automatically.",
        }
        declarations = root / "operations.json"
        if declarations.is_file():
            result["operations"] = [
                op.get("name")
                for op in json.loads(declarations.read_text(encoding="utf-8")).get(
                    "operations", []
                )
            ]
        database = root / "pb/pb_data/data.db"
        if database.is_file():
            result["data"] = data_inventory(database.parent)
            with sqlite3.connect(
                database.resolve().as_uri() + "?mode=ro", uri=True
            ) as db:
                names = [
                    r[0]
                    for r in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ]
                for name in names:
                    if not any(term in name.lower() for term in ("request", "task")):
                        continue
                    columns = [
                        r[1] for r in db.execute(f"PRAGMA table_info({_quoted(name)})")
                    ]
                    if "status" in columns:
                        result["pendingWork"][name] = dict(
                            db.execute(
                                f"SELECT status, count(*) FROM {_quoted(name)} GROUP BY status"
                            )
                        )
        else:
            result["data"] = {"requiresMapping": True}
        ignored = {
            "node_modules",
            ".git",
            ".a2app",
            ".factory",
            "pb_data",
            "pb_public",
            ".venv",
            "__pycache__",
        }
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [
                d
                for d in dirs
                if d not in ignored and not (Path(current) / d).is_symlink()
            ]
            for name in files:
                file = Path(current) / name
                if (
                    file.suffix not in {".js", ".ts", ".tsx", ".jsx", ".py"}
                    or file.is_symlink()
                ):
                    continue
                text = file.read_text(encoding="utf-8", errors="replace")
                if any(
                    term in text
                    for term in (
                        "/api/llm",
                        "/api/vlm",
                        "/api/integration",
                        "CRAFTBOT_",
                        "agent_bridge",
                    )
                ):
                    result["providerReferences"].append(
                        file.relative_to(root).as_posix()
                    )
        result["providerReview"] = (
            "Source references are hints, not a complete dependency analysis. Preserve provider behavior in the replacement and verify it before cutover."
        )
        return result

    async def cutover(self, project_id, path, app_id, confirm):
        if confirm != project_id:
            raise ValueError(
                "Confirm the legacy app ID before stopping its runs and transferring data."
            )
        async with self.lock:
            project = self.manager.get_project(project_id)
            if not project or not project.path or project.project_type == "external":
                raise ValueError(
                    "Automatic transfer requires an existing PocketBase app."
                )
            if project_id in self.manager._live_ops or self.manager.instances.shadow(
                project_id
            ):
                raise ValueError(
                    "Finish the app's current build, restore or promotion first."
                )
            await self.host.selected(path, app_id)
            self.host.require_verified(path)
            source, target = Path(project.path).resolve(), Path(path).resolve()
            if source == target or source in target.parents or target in source.parents:
                raise ValueError(
                    "The verified candidate must be outside the original app directory."
                )
            if (target / "pb/pb_data").exists():
                raise ValueError(
                    "The candidate already has live data. Use a separate verified candidate; existing data is never overwritten."
                )
            manifest = json.loads(
                (target / "manifest.json").read_text(encoding="utf-8")
            )
            if "pb-serve.mjs" not in manifest.get("pipeline", {}).get("start", ""):
                raise ValueError("This candidate needs an app-specific data mapping.")
            cli = await asyncio.to_thread(framework.configured_cli)
            identifier = uuid.uuid4().hex
            recovery = self.host.store.path.parent / "agent-app-migrations" / identifier
            recovery.mkdir(parents=True, mode=0o700)
            omitted = {
                "process",
                "bridge_token",
                "internal_port",
                "status",
                "url",
                "backend_url",
            }
            original = {
                f.name: getattr(project, f.name)
                for f in dataclasses.fields(project)
                if f.name not in omitted
            }
            item = self.save(
                {
                    "id": identifier,
                    "legacyId": project.id,
                    "name": project.name,
                    "source": str(source),
                    "target": str(target),
                    "appId": app_id,
                    "home": str(cli.home),
                    "recovery": str(recovery),
                    "original": original,
                    "phase": "quiescing",
                    "wasRunning": project.status == "running",
                }
            )
            canonical = os.path.normcase(str(target))
            target_lock = framework._lifecycle_locks.setdefault(
                (asyncio.get_running_loop(), canonical), asyncio.Lock()
            )
            async with self.manager._launch_lock(project_id), target_lock:
                self.manager._live_ops.add(project_id)
                try:
                    project.auto_launch = False
                    self.manager._save_projects()
                    sessions = {
                        s.id
                        for s in self.host.agent.session_manager.sessions.values()
                        if getattr(s, "agent_app_project_id", None) == project_id
                    }
                    if project.session_id:
                        sessions.add(project.session_id)
                    if sessions:
                        await self.host.agent.trigger_service.cancel_sessions(
                            sorted(sessions)
                        )
                    if not await self.manager.stop_project(project_id):
                        raise ValueError("The original app could not be stopped.")
                    for args in ([path, "stop"], [path, "stop", "--dev"]):
                        stopped = await cli.run(
                            "agent-app", args, cwd=cli.package_dir, timeout=45
                        )
                        if not stopped.ok:
                            raise ValueError(
                                stopped.stderr or "Candidate could not be stopped."
                            )
                    from app.agent_app.pb_data_io import snapshot_pb_data

                    self.save({**item, "phase": "copying"})
                    await asyncio.to_thread(
                        source_snapshot, source, recovery / "source"
                    )
                    await asyncio.to_thread(
                        snapshot_pb_data,
                        source / "pb/pb_data",
                        recovery / "data",
                        recovery,
                    )
                    before = await asyncio.to_thread(data_inventory, recovery / "data")
                    item.update(
                        dataBefore=before,
                        sourceFingerprint=capability_fingerprint(str(source)),
                        phase="validating",
                    )
                    self.save(item)
                    await asyncio.to_thread(
                        shutil.copytree, recovery / "data", target / "pb/pb_data"
                    )
                    promoted = await cli.run(
                        "agent-app", [path, "promote"], cwd=cli.package_dir, timeout=600
                    )
                    if not promoted.ok:
                        raise ValueError(promoted.stderr or promoted.stdout)
                    item["dataAfter"] = await asyncio.to_thread(
                        verify_data, before, target / "pb/pb_data"
                    )
                    served = await cli.run(
                        "agent-app", [path, "serve"], cwd=cli.package_dir, timeout=600
                    )
                    if not served.ok:
                        raise ValueError(served.stderr or served.stdout)
                    opened = await framework.open_app_view(path, app_id)
                    if opened.get("status") != "success":
                        raise ValueError(
                            "The migrated app's live identity could not be verified."
                        )
                    item["phase"] = "switching"
                    self.save(item)
                    attached = await self.host.attach(path, app_id)
                    item["sessionId"] = attached["sessionId"]
                    # Persist intent first; keep the old tree/backups/chat intact.
                    self.manager.projects.pop(project_id)
                    self.manager._save_projects()
                    persisted = json.loads(
                        self.manager._projects_file.read_text(encoding="utf-8")
                    )
                    if any(p["id"] == project_id for p in persisted["projects"]):
                        self.manager.projects[project_id] = project
                        raise ValueError("Legacy registration could not be retired.")
                    item.update(phase="complete", error=None)
                    self.save(item)
                except BaseException as error:
                    item.update(
                        phase="interrupted", error=str(error) or "Migration interrupted"
                    )
                    self.save(item)
                    raise
                finally:
                    self.manager._live_ops.discard(project_id)
                    await self.host.changed()
            return item

    async def rollback(self, identifier, confirm):
        async with self.lock:
            item = self.host.store.get("migration", identifier)
            if (
                not item
                or confirm != item["legacyId"]
                or item["phase"] not in {"complete", "interrupted"}
            ):
                raise ValueError(
                    "Confirm the original app ID to restore its registration. New app data stays archived separately."
                )
            cli = await asyncio.to_thread(framework.configured_cli)
            if item["home"] != str(cli.home):
                raise ValueError(
                    "Select the Agent-App profile used for this migration."
                )
            if not Path(item["source"], "pb/pb_data/data.db").is_file():
                raise ValueError(
                    "The original data is missing. Recover it from the retained recovery directory before restoring registration."
                )
            if item.get("dataBefore"):
                await asyncio.to_thread(
                    verify_data, item["dataBefore"], Path(item["source"], "pb/pb_data")
                )
            if item.get("sourceFingerprint") and item[
                "sourceFingerprint"
            ] != await asyncio.to_thread(capability_fingerprint, item["source"]):
                raise ValueError(
                    "The original app's code changed after migration. Review its recovery copy before restoring registration."
                )
            item["phase"] = "rolling_back"
            self.save(item)
            try:
                from app.agent_app.framework_commands import command

                # Stop and preserve all writes to the new installation. Never
                # copy its data backwards into the old schema.
                stopped = await command("agent-app", [item["target"], "stop"])
                if stopped["status"] != "success":
                    raise ValueError(
                        "Stop the replacement before restoring the old app."
                    )
                if Path(item["target"], "pb/pb_data/data.db").is_file():
                    backup = await command("agent-app", [item["target"], "backup"])
                    if backup["status"] != "success":
                        raise ValueError(
                            "Could not preserve the replacement's current data."
                        )
                    item["rollbackBackup"] = backup.get("data")
                from app.agent_app.manager import AgentAppProject
                from app.agent_app.trigger_consent import reset

                original = AgentAppProject(**item["original"], status="stopped")
                # Old pending requests and grants must not silently replay.
                reset(original)
                original.auto_launch = False
                self.manager.projects[original.id] = original
                self.manager._save_projects()
                persisted = json.loads(
                    self.manager._projects_file.read_text(encoding="utf-8")
                )
                if not any(p["id"] == original.id for p in persisted["projects"]):
                    raise ValueError("Original registration could not be restored.")
                item.update(phase="rolled_back", error=None)
                self.save(item)
            except BaseException as error:
                item.update(
                    phase="interrupted", error=str(error) or "Rollback interrupted"
                )
                self.save(item)
                raise
            await self.host.changed()
            return item
