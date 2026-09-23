"""BackupStore + BackupService — backups of a Agent App app's live pb_data.

Spec: docs/plans/agent-app-backups-requirements.md (+ -plan.md). One archive
format for every trigger: a ZIP of the snapshot layout snapshot_pb_data
produces (every *.db consistent via sqlite's backup API + storage/), named
<app-slug>__<local-ts>__<trigger>.zip under agent_app/_backups/<project_id>/
— OUTSIDE the project dir, so it survives anything that deletes or restores
the project's own pb_data (the 2026-08-19 incident class this feature
answers). The app slug + local timestamp make the file self-describing to a
human browsing the folder; a meta.json sidecar carries the app's full name
so a backup dir stays identifiable after its project is deleted (orphan
listing). Archives in the pre-2026-08-21 name <utc-ts>__<trigger>.zip are
still listed, restored, pruned and deleted — just never produced.

Two capture paths, one output:
  - capture_stopped: sync, snapshot_pb_data + zip. Also correct while the
    app RUNS for the DB half (sqlite backup API tolerates a live writer) —
    it is the pre-promote / pre-restore path, where a fs-level skew between
    DB and storage/ is acceptable and no event loop is guaranteed.
  - capture_running: PocketBase's own POST /api/backups (superuser-authed) —
    the only DB+files-ATOMIC option (PB goes read-only for the duration) —
    then the finished zip is MOVED out of pb_data/backups/ into the store.

Deletion discipline: everything goes through _guarded_delete, which requires
a strict descendant of the _backups root (same predicate as
DevProvisioner._guarded_rmtree / pb_data_io). prune()/delete() additionally
touch only filenames matching the canonical pattern — files we cannot
attribute to a pool are never deleted (FR5).
"""

import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from app.agent_app.pb_data_io import snapshot_pb_data

TRIGGERS = ("scheduled", "pre_promote", "manual", "pre_delete", "pre_restore")

# pre_promote-pool retention — a deliberate constant, not a setting (resolved
# question §7.2 in the requirements: a second retention knob on the card
# requires understanding what a promote is; the scheduled pool owns depth).
PRE_PROMOTE_KEEP = 3
# pre_restore-pool retention — same reasoning: each restore captures the
# then-current state as its own undo; only the last few matter.
PRE_RESTORE_KEEP = 3

# <app-slug>__<local-ts>__<trigger>.zip — the trigger token doubles as the
# retention pool; the slug exists purely for humans browsing the folder
# (the dir name is the opaque project id). Slug charset excludes "_", so
# the "__" separators stay unambiguous.
_NAME_RE = re.compile(
    r"^(?P<slug>[a-z0-9][a-z0-9-]{0,39})__"
    r"(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})__"
    r"(?P<trigger>scheduled|pre_promote|manual|pre_delete|pre_restore)\.zip$"
)
# Pre-2026-08-21 archives: <utc-ts>__<trigger>.zip. Recognized forever so
# existing backups keep listing/restoring/pruning; never produced any more.
_LEGACY_NAME_RE = re.compile(
    r"^(?P<ts>\d{8}T\d{6}Z)__"
    r"(?P<trigger>scheduled|pre_promote|manual|pre_delete|pre_restore)\.zip$"
)
# Same guard the provisioner/wizard use: nothing outside this pattern ever
# becomes part of a deleted path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


@dataclass
class BackupEntry:
    project_id: str
    path: Path
    ts: float  # epoch, UTC
    trigger: str
    size: int

    @property
    def filename(self) -> str:
        return self.path.name


def _ts_name(ts: float) -> str:
    """LOCAL wall-clock time — the filename exists for the user's eyes, and
    a backup made at 12:29 must say 12:29. Retention only needs ordering,
    so the (at most one-hour, DST-only) parse ambiguity is harmless."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d_%H-%M-%S")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:40].rstrip("-") or "app"


def _parse_name(filename: str):
    """(epoch_ts, trigger) for a canonical or legacy archive name, else None
    — the single authority on what counts as one of our archives."""
    m = _NAME_RE.match(filename or "")
    if m:
        dt = datetime.strptime(m.group("ts"), "%Y-%m-%d_%H-%M-%S")
        try:
            ts = dt.timestamp()
        except (OSError, OverflowError, ValueError):
            # Windows mktime rejects near-epoch local times; a slightly-off
            # ts beats an archive going invisible.
            ts = dt.replace(tzinfo=timezone.utc).timestamp()
        return ts, m.group("trigger")
    m = _LEGACY_NAME_RE.match(filename or "")
    if m:
        return (
            datetime.strptime(m.group("ts"), "%Y%m%dT%H%M%SZ")
            .replace(tzinfo=timezone.utc)
            .timestamp(),
            m.group("trigger"),
        )
    return None


class BackupStore:
    """Layout, listing and pool-aware pruning under agent_app/_backups/.
    Pure filesystem — knows nothing about projects beyond their id."""

    def __init__(self, agent_app_dir: Path) -> None:
        self.agent_app_dir = Path(agent_app_dir)
        self.root = self.agent_app_dir / "_backups"

    # ── layout ─────────────────────────────────────────────────────────────
    def project_dir(self, project_id: str) -> Path:
        if not _ID_RE.match(project_id or ""):
            raise ValueError(f"unsafe project id for backups: {project_id!r}")
        return self.root / project_id

    def claim_path(
        self,
        project_id: str,
        trigger: str,
        ts: Optional[float] = None,
        name: str = "",
    ) -> Path:
        """Reserve a canonical archive path (parent created, name unique —
        same-second collisions bump the timestamp forward). `name` is the
        app's human name; it becomes the filename's slug."""
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown backup trigger: {trigger!r}")
        pdir = self.project_dir(project_id)
        pdir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(name)
        ts = time.time() if ts is None else ts
        path = pdir / f"{slug}__{_ts_name(ts)}__{trigger}.zip"
        while path.exists():
            ts += 1
            path = pdir / f"{slug}__{_ts_name(ts)}__{trigger}.zip"
        return path

    # ── listing ────────────────────────────────────────────────────────────
    def list_backups(self, project_id: str) -> List[BackupEntry]:
        """All attributable archives for the project, newest first. Files
        not matching the canonical name are invisible here (and therefore
        untouchable by prune/delete)."""
        pdir = self.project_dir(project_id)
        entries: List[BackupEntry] = []
        if not pdir.is_dir():
            return entries
        for f in pdir.iterdir():
            parsed = _parse_name(f.name)
            if not parsed or not f.is_file():
                continue
            ts, trigger = parsed
            entries.append(
                BackupEntry(
                    project_id=project_id,
                    path=f,
                    ts=ts,
                    trigger=trigger,
                    size=f.stat().st_size,
                )
            )
        entries.sort(key=lambda e: e.ts, reverse=True)
        return entries

    def total_size(self, project_id: str) -> int:
        return sum(e.size for e in self.list_backups(project_id))

    def orphan_dirs(self, registered_ids) -> List[str]:
        """Backup dirs whose project no longer exists (D5: listed for manual
        cleanup, never auto-reaped)."""
        if not self.root.is_dir():
            return []
        known = set(registered_ids)
        return sorted(
            d.name for d in self.root.iterdir() if d.is_dir() and d.name not in known
        )

    def orphan_info(self, registered_ids) -> List[dict]:
        """orphan_dirs + the app's human name from meta.json — the id alone
        means nothing to a user once the project is gone."""
        return [
            {"id": oid, "name": self.project_name(oid) or oid}
            for oid in self.orphan_dirs(registered_ids)
        ]

    # ── meta sidecar ───────────────────────────────────────────────────────
    def write_meta(self, project_id: str, name: str) -> None:
        """Refresh the human-name sidecar. Cosmetic — never fails a capture."""
        try:
            pdir = self.project_dir(project_id)
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "meta.json").write_text(
                json.dumps({"id": project_id, "name": name}), encoding="utf-8"
            )
        except Exception:
            pass

    def project_name(self, project_id: str) -> str:
        try:
            raw = (self.project_dir(project_id) / "meta.json").read_text(
                encoding="utf-8"
            )
            return str(json.loads(raw).get("name") or "")
        except Exception:
            return ""

    # ── deletion ───────────────────────────────────────────────────────────
    def prune(self, project_id: str, trigger: str, keep: int) -> int:
        """Delete the oldest archives of one pool beyond `keep`. Other pools
        and unattributable files are untouched."""
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown backup trigger: {trigger!r}")
        keep = max(0, int(keep))
        pool = [e for e in self.list_backups(project_id) if e.trigger == trigger]
        doomed = pool[keep:]  # list is newest-first
        for entry in doomed:
            self._guarded_delete(entry.path)
        if doomed:
            logger.info(
                f"[AGENT_APP:BACKUP] pruned {len(doomed)} {trigger} backup(s) "
                f"of {project_id} (keep {keep})"
            )
        return len(doomed)

    def delete(self, project_id: str, filename: str) -> None:
        """Delete one archive by its canonical/legacy filename (user-driven)."""
        if _parse_name(filename) is None:
            raise ValueError(f"not a backup archive name: {filename!r}")
        self._guarded_delete(self.project_dir(project_id) / filename)

    def delete_project_backups(self, project_id: str) -> None:
        """Remove the project's whole backup dir (delete-project opt-in, D5)."""
        pdir = self.project_dir(project_id)
        if pdir.exists():
            self._guarded_delete(pdir)

    def _guarded_delete(self, target: Path) -> None:
        """Only ever delete strictly inside the _backups root."""
        resolved = Path(target).resolve()
        root = self.root.resolve()
        if root not in resolved.parents:
            raise ValueError(f"refusing to delete {resolved} — outside {root}")
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()


class BackupService:
    """Capture orchestration. Composed by the manager (like the lifecycle);
    never reaches back into registry, sessions or broadcasting."""

    def __init__(self, agent_app_dir: Path) -> None:
        self.agent_app_dir = Path(agent_app_dir)
        self.store = BackupStore(agent_app_dir)

    # ── stopped / hook path ────────────────────────────────────────────────
    def capture_stopped(self, project, trigger: str) -> BackupEntry:
        """snapshot_pb_data + zip. Correct with the app stopped (consistent
        by absence of writers) and acceptable while it runs (DBs consistent
        via the sqlite backup API; storage/ may skew by the copy window) —
        the pre-promote and pre-restore path. Raises on failure; callers
        decide fatality (scheduler: log+retry; pre-promote hook: abort)."""
        final = self.store.claim_path(
            project.id, trigger, name=getattr(project, "name", "")
        )
        tmp_root = final.parent / ".tmp"
        if tmp_root.exists():
            self.store._guarded_delete(tmp_root)  # crashed prior capture
        snapshot = tmp_root / "pb_data"
        try:
            snapshot_pb_data(
                Path(project.path) / "pb" / "pb_data", snapshot, self.agent_app_dir
            )
            self._zip_dir(snapshot, final)
        finally:
            if tmp_root.exists():
                self.store._guarded_delete(tmp_root)
        self.store.write_meta(project.id, getattr(project, "name", ""))
        entry = BackupEntry(
            project_id=project.id,
            path=final,
            ts=_parse_name(final.name)[0],
            trigger=trigger,
            size=final.stat().st_size,
        )
        logger.info(
            f"[AGENT_APP:BACKUP] {project.id} {trigger} backup (stopped path) "
            f"-> {final.name} ({entry.size} bytes)"
        )
        return entry

    # ── running path ───────────────────────────────────────────────────────
    async def capture_running(self, project, trigger: str) -> BackupEntry:
        """PocketBase's own backup API: one ATOMIC zip of pb_data (DB +
        storage; PB goes read-only for the duration), moved out of
        pb_data/backups/ into the store. Raises on any failure — never
        falls back to a raw copy of a live DB (FR2)."""
        from app.agent_app.runner import read_superuser_creds

        creds = read_superuser_creds(Path(project.path))
        if creds is None:
            raise RuntimeError(
                f"no .superuser credentials for {project.id} — cannot call "
                "the PocketBase backup API"
            )
        email, password = creds
        base = f"http://127.0.0.1:{project.port}"
        # PB restricts backup names to [a-z0-9_-].zip — use a throwaway name
        # and let the store rename impose the canonical one.
        pb_name = f"craftbot_{int(time.time())}.zip"

        import aiohttp

        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base}/api/collections/_superusers/auth-with-password",
                json={"identity": email, "password": password},
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"superuser auth failed ({resp.status})")
                token = (await resp.json()).get("token") or ""
            async with session.post(
                f"{base}/api/backups",
                json={"name": pb_name},
                headers={"Authorization": token},
            ) as resp:
                if resp.status not in (200, 204):
                    body = (await resp.text())[:300]
                    raise RuntimeError(
                        f"PocketBase backup failed ({resp.status}): {body}"
                    )

        produced = Path(project.path) / "pb" / "pb_data" / "backups" / pb_name
        if not produced.exists():
            raise RuntimeError(f"PocketBase reported success but {pb_name} is missing")
        final = self.store.claim_path(
            project.id, trigger, name=getattr(project, "name", "")
        )
        shutil.move(str(produced), str(final))
        self.store.write_meta(project.id, getattr(project, "name", ""))
        entry = BackupEntry(
            project_id=project.id,
            path=final,
            ts=_parse_name(final.name)[0],
            trigger=trigger,
            size=final.stat().st_size,
        )
        logger.info(
            f"[AGENT_APP:BACKUP] {project.id} {trigger} backup (PB API) "
            f"-> {final.name} ({entry.size} bytes)"
        )
        return entry

    # ── restore support ────────────────────────────────────────────────────
    def prepare_restore(self, entry: BackupEntry) -> Path:
        """Unzip an archive to a temp dir under the guard root and validate
        it — the snapshot-layout dir restore_pb_data expects. The caller
        (manager.restore_backup) owns stop/replace/relaunch; this keeps all
        archive handling in one module. Caller must remove the returned dir
        (it lives under _backups/<id>/.restore-tmp, so the next prepare also
        sweeps a leftover)."""
        target = self.store.project_dir(entry.project_id) / ".restore-tmp"
        if target.exists():
            self.store._guarded_delete(target)
        with zipfile.ZipFile(entry.path) as zf:
            for name in zf.namelist():
                # Belt against hostile archives: no absolute paths, no
                # parent-dir escapes (the store only holds files we wrote,
                # but an uploaded/copied-in zip costs one loop to distrust).
                p = Path(name)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError(f"unsafe path in archive: {name!r}")
            zf.extractall(target)
        if not (target / "data.db").exists():
            self.store._guarded_delete(target)
            raise ValueError(f"{entry.filename} has no data.db — not a pb_data backup")
        return target

    def cleanup_restore(self, entry: BackupEntry) -> None:
        target = self.store.project_dir(entry.project_id) / ".restore-tmp"
        if target.exists():
            self.store._guarded_delete(target)

    # ── internals ──────────────────────────────────────────────────────────
    def _zip_dir(self, src_dir: Path, final: Path) -> None:
        """Zip src_dir's CONTENTS to `final` — written as a sibling .tmp and
        renamed into place, so a partial archive is never listable."""
        tmp = final.with_name(final.name + ".part")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(src_dir.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(src_dir))
            tmp.replace(final)
        finally:
            if tmp.exists():
                tmp.unlink()
