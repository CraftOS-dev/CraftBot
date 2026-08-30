"""
pb_data snapshot / restore utilities.

NO LIFECYCLE CODE CALLS THESE ANY MORE. The baseline-restore era (snapshot
at first launch, restore before the delivery announce) ended with the
unified dev/live lifecycle (docs/plans/agent-app-unified-lifecycle-plan.md)
after a stale delivered-flag made the restore wipe a live database
(2026-08-19). Dev environments boot with a FRESH pb_data instead — nothing
clones or restores over live data.

The functions stay for the deferred pre-promote backup
(Promoter.add_before_live_boot_hook is the reserved slot) and for tooling.

Copies go through sqlite's backup API, never shutil: PocketBase runs its DBs
in WAL mode, and a naive file copy of a live data.db loses every write still
sitting in the -wal sidecar. backup() produces a consistent, checkpointed
single file even while the server is running.

Every destructive path is guarded with the same predicate delete_project
adopted after rmtree wiped the CraftBot working tree twice (2026-07-25/26):
resolve, then require the target to be a strict descendant of the Agent App
workspace.
"""

import shutil
import sqlite3
from pathlib import Path

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

# PocketBase's own state that a snapshot must carry. Everything else in
# pb_data (types.d.ts, backups/, WAL/SHM sidecars) is regenerated or
# consolidated at the next boot.
_STORAGE_DIR = "storage"


def _assert_inside_living_root(target: Path, living_root: Path, verb: str) -> None:
    """Refuse to touch anything that is not strictly inside the Agent App
    workspace. Path("") resolves to the process CWD — the CraftBot repo
    root — which is exactly how the 2026-07-25/26 wipes happened."""
    if not str(target):
        raise ValueError(f"refusing to {verb} an empty path")
    resolved = target.resolve()
    root = living_root.resolve()
    if root not in resolved.parents:
        raise ValueError(
            f"refusing to {verb} {resolved} — outside the Agent App workspace {root}"
        )


def _backup_db(src_db: Path, dest_db: Path) -> None:
    """Consistent copy of one sqlite DB, safe against a live writer."""
    src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dest_db))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def snapshot_pb_data(src_pb_data: Path, dest: Path, living_root: Path) -> None:
    """Copy the meaningful state of a pb_data dir (every *.db + storage/)
    into dest, replacing whatever dest held. Safe while PocketBase is
    serving from src_pb_data. Raises on failure — callers decide whether a
    failed snapshot is fatal (staging: yes) or logged (baseline: no)."""
    src_pb_data = Path(src_pb_data)
    dest = Path(dest)
    if not src_pb_data.is_dir():
        raise FileNotFoundError(f"pb_data not found: {src_pb_data}")
    dbs = sorted(src_pb_data.glob("*.db"))
    if not any(db.name == "data.db" for db in dbs):
        raise FileNotFoundError(f"no data.db in {src_pb_data} — nothing to snapshot")

    if dest.exists():
        _assert_inside_living_root(dest, living_root, "overwrite snapshot at")
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for db in dbs:
        _backup_db(db, dest / db.name)
    storage = src_pb_data / _STORAGE_DIR
    if storage.is_dir():
        shutil.copytree(storage, dest / _STORAGE_DIR)
    logger.info(
        f"[AGENT_APP:PB_DATA] snapshot {src_pb_data} -> {dest} "
        f"({len(dbs)} db(s){', storage/' if storage.is_dir() else ''})"
    )


def restore_pb_data(snapshot_dir: Path, pb_data: Path, living_root: Path) -> None:
    """Replace pb_data with a snapshot taken by snapshot_pb_data. The server
    must be STOPPED first — restoring under a live writer corrupts both
    sides. Raises on failure; never call this on a delivered app's real
    pb_data unless the snapshot is its own pristine baseline."""
    snapshot_dir = Path(snapshot_dir)
    pb_data = Path(pb_data)
    if not (snapshot_dir / "data.db").exists():
        raise FileNotFoundError(
            f"snapshot at {snapshot_dir} has no data.db — refusing to restore from it"
        )
    if pb_data.name != "pb_data":
        raise ValueError(f"refusing to restore over {pb_data} — not a pb_data dir")
    _assert_inside_living_root(pb_data, living_root, "restore over")

    if pb_data.exists():
        shutil.rmtree(pb_data)
    shutil.copytree(snapshot_dir, pb_data)
    logger.info(f"[AGENT_APP:PB_DATA] restored {pb_data} from {snapshot_dir}")
