"""Acceptance tests for Living UI backups — store, capture (both paths),
scheduler, pre-promote hook, restore, boot-cleaner/delete integration,
settings surface, and a real-PocketBase end-to-end (§8, skipped when the
pinned binary is not cached).

Spec: docs/plans/living-ui-backups-requirements.md / -plan.md.

Style follows test_data_safety.py: a module-level assert script with
section prints — run directly:

    PYTHONPATH=. python app/living_ui/test_backups.py
"""

import asyncio
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import app.factory.host_craftbot as host_mod
import app.living_ui as living_ui_mod
from app.living_ui.lifecycle.backups import (
    _NAME_RE,
    PRE_PROMOTE_KEEP,
    BackupService,
    BackupStore,
    _ts_name,
)
from app.living_ui.manager import LivingUIManager, LivingUIProject
from app.living_ui.pb_data_io import restore_pb_data


# ── shared helpers ─────────────────────────────────────────────────────────
def _mkdb(path: Path, rows: int, table: str = "items") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    with con:
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY)")
        con.execute(f"DELETE FROM {table}")
        con.executemany(
            f"INSERT INTO {table} (id) VALUES (?)", [(i,) for i in range(1, rows + 1)]
        )
    con.close()


def _count(path: Path, table: str = "items") -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


# Base epoch for fabricated archives: local-time filenames round-trip
# through mktime, which (on Windows) rejects near-epoch values — so the
# tests' relative offsets ride on a modern instant.
_T0 = 1_700_000_000.0


def _touch_archive(store: BackupStore, pid: str, ts: float, trigger: str) -> Path:
    ts += _T0
    p = store.project_dir(pid) / f"app__{_ts_name(ts)}__{trigger}.zip"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"zip" + bytes(int(ts) % 251))
    return p


def _make_project(living: Path, pid: str) -> SimpleNamespace:
    proj = living / f"app_{pid}"
    pb_data = proj / "pb" / "pb_data"
    _mkdb(pb_data / "data.db", 3)
    _mkdb(pb_data / "auxiliary.db", 1, table="aux")
    (pb_data / "types.d.ts").write_text("// generated\n")
    (pb_data / "data.db-wal").write_bytes(b"")
    (pb_data / "storage" / "rec1").mkdir(parents=True)
    (pb_data / "storage" / "rec1" / "upload.bin").write_bytes(b"file-bytes")
    (pb_data / "backups" / "old.zip").parent.mkdir(parents=True, exist_ok=True)
    (pb_data / "backups" / "old.zip").write_bytes(b"stale pb-native backup")
    return SimpleNamespace(id=pid, path=str(proj), status="stopped", port=0)


# ── §1 BackupStore: naming, pools, prune, guards ───────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    store = BackupStore(living)

    # canonical naming round-trips; claim_path bumps same-second collisions
    p1 = store.claim_path(
        "proj0001", "scheduled", ts=_T0 + 1000000.0, name="My CRM App!"
    )
    assert p1.name.startswith("my-crm-app__"), "filename must carry the app slug"
    p1.write_bytes(b"a")
    p2 = store.claim_path(
        "proj0001", "scheduled", ts=_T0 + 1000000.0, name="My CRM App!"
    )
    assert p1 != p2 and _NAME_RE.match(p2.name), "collision must bump, stay canonical"
    p2.write_bytes(b"b")
    # nameless captures still get a valid slug
    assert store.claim_path("proj0001", "manual", ts=_T0).name.startswith("app__")

    # unsafe ids refused before any path is built
    for bad in ("", "..", "a/b", "x" * 65):
        try:
            store.project_dir(bad)
            raise AssertionError(f"id {bad!r} must be refused")
        except ValueError:
            pass

    # listing: newest first, pools attributed, foreign files invisible
    _touch_archive(store, "proj0001", 2000.0, "pre_promote")
    _touch_archive(store, "proj0001", 3000.0, "manual")
    (store.project_dir("proj0001") / "README.txt").write_text("not a backup")
    (store.project_dir("proj0001") / "20990101T000000Z__evil.zip").write_bytes(b"x")
    entries = store.list_backups("proj0001")
    assert [e.trigger for e in entries] == [
        "scheduled",
        "scheduled",
        "manual",
        "pre_promote",
    ]
    assert entries[0].ts >= entries[1].ts
    assert store.total_size("proj0001") == sum(e.size for e in entries)

    # prune: only the named pool shrinks; foreign files untouched
    for ts in (10.0, 20.0, 30.0, 40.0):
        _touch_archive(store, "proj0002", ts, "scheduled")
    _touch_archive(store, "proj0002", 15.0, "manual")
    assert store.prune("proj0002", "scheduled", keep=2) == 2
    kept = store.list_backups("proj0002")
    assert [e.ts for e in kept if e.trigger == "scheduled"] == [_T0 + 40.0, _T0 + 30.0]
    assert [e.ts for e in kept if e.trigger == "manual"] == [_T0 + 15.0], (
        "other pools survive"
    )
    assert store.prune("proj0002", "scheduled", keep=2) == 0, "idempotent"

    # delete: canonical names only; guard refuses paths outside the root
    store.delete("proj0001", entries[-1].filename)
    for bad_name in ("../evil.zip", "README.txt", "x.zip", ""):
        try:
            store.delete("proj0001", bad_name)
            raise AssertionError(f"delete must refuse {bad_name!r}")
        except ValueError:
            pass
    outside = Path(tmp) / "outside.txt"
    outside.write_text("precious")
    try:
        store._guarded_delete(outside)
        raise AssertionError("guard must refuse targets outside _backups")
    except ValueError:
        pass
    assert outside.exists()
    assert (store.project_dir("proj0001") / "README.txt").exists()
    assert (store.project_dir("proj0001") / "20990101T000000Z__evil.zip").exists()

    # legacy-named archives (pre 2026-08-21) stay listed, attributed and
    # deletable — old backups must never become invisible
    legacy = store.project_dir("proj0001") / "20200101T000000Z__manual.zip"
    legacy.write_bytes(b"old-format")
    got = [e for e in store.list_backups("proj0001") if e.filename == legacy.name]
    assert got and got[0].trigger == "manual"
    store.delete("proj0001", legacy.name)
    assert not legacy.exists()

    # delete_project_backups removes the dir; orphans are reported, not reaped
    store.delete_project_backups("proj0002")
    assert not store.project_dir("proj0002").exists()
    assert store.orphan_dirs(registered_ids=[]) == ["proj0001"]
    assert store.orphan_dirs(registered_ids=["proj0001"]) == []
print("§1 BackupStore naming/pools/prune/guards: OK")


# ── §2 capture_stopped round-trip ──────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    living.mkdir()
    svc = BackupService(living)
    project = _make_project(living, "cap00001")
    pb_data = Path(project.path) / "pb" / "pb_data"

    entry = svc.capture_stopped(project, "manual")
    assert entry.path.exists() and entry.trigger == "manual" and entry.size > 0
    assert not (entry.path.parent / ".tmp").exists(), "capture temp must be cleaned"
    assert not list(entry.path.parent.glob("*.part")), "no partial archives"

    # archive carries DBs + storage, excludes PB-native backups/, WAL, types
    names = set(zipfile.ZipFile(entry.path).namelist())
    assert "data.db" in names and "auxiliary.db" in names
    assert "storage/rec1/upload.bin" in names
    assert not any(n.startswith("backups") for n in names)
    assert not any(n.endswith((".d.ts", "-wal")) for n in names)

    # post-backup junk rows vanish on restore; storage bytes survive
    _mkdb(pb_data / "data.db", 9)
    (pb_data / "storage" / "rec1" / "junk.bin").write_bytes(b"junk")
    unpack = living / "_backups" / "cap00001" / ".restore-tmp"
    with zipfile.ZipFile(entry.path) as zf:
        zf.extractall(unpack)
    restore_pb_data(unpack, pb_data, living)
    assert _count(pb_data / "data.db") == 3, "restore must drop post-backup junk"
    assert (pb_data / "storage" / "rec1" / "upload.bin").read_bytes() == b"file-bytes"
    assert not (pb_data / "storage" / "rec1" / "junk.bin").exists()

    # a second capture the same second lands beside the first, not over it
    entry2 = svc.capture_stopped(project, "manual")
    assert entry2.path != entry.path and len(svc.store.list_backups("cap00001")) == 2

    # capture with no data.db raises and leaves nothing behind
    bare = _make_project(living, "bare0001")
    (Path(bare.path) / "pb" / "pb_data" / "data.db").unlink()
    before = len(svc.store.list_backups("bare0001"))
    try:
        svc.capture_stopped(bare, "scheduled")
        raise AssertionError("capture without data.db must raise")
    except FileNotFoundError:
        pass
    assert len(svc.store.list_backups("bare0001")) == before
    assert not (svc.store.project_dir("bare0001") / ".tmp").exists()
print("§2 capture_stopped round-trip: OK")

# ── §3 scheduler due-logic ─────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    mgr = LivingUIManager(workspace_root=Path(tmp))
    project = _make_project(mgr.living_ui_dir, "sched001")
    lp = LivingUIProject(
        id="sched001", name="s", description="", path=project.path, status="stopped"
    )
    mgr.projects["sched001"] = lp
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    fired = []

    async def _fake_run(p):
        fired.append(p.id)
        mgr._backups_inflight.discard(p.id)

    mgr._run_scheduled_backup = _fake_run

    async def _t3():
        # absent last_at -> due now (first-enable and boot catch-up)
        mgr._maybe_schedule_backup(lp)
        await asyncio.sleep(0)
        assert fired == ["sched001"], "no last_at must mean due"

        # recent last_at -> not due; ancient -> due again
        host.record_backup_ok("sched001", time.time())
        mgr._maybe_schedule_backup(lp)
        assert len(fired) == 1, "fresh backup must not be due"
        host.record_backup_ok("sched001", time.time() - 86400 - 5)
        mgr._maybe_schedule_backup(lp)
        await asyncio.sleep(0)
        assert len(fired) == 2, "older than the interval must be due"

        # interval enum honored (hourly with a 2h-old stamp is due)
        lp.backup_interval = "hourly"
        host.record_backup_ok("sched001", time.time() - 7200)
        mgr._maybe_schedule_backup(lp)
        await asyncio.sleep(0)
        assert len(fired) == 3

        # gates: disabled / external / mid-op / inflight / no live DB
        host.record_backup_ok("sched001", time.time() - 7200)
        lp.backups_enabled = False
        mgr._maybe_schedule_backup(lp)
        lp.backups_enabled = True
        lp.project_type = "external"
        mgr._maybe_schedule_backup(lp)
        lp.project_type = "native"
        mgr._live_ops.add("sched001")
        mgr._maybe_schedule_backup(lp)
        mgr._live_ops.discard("sched001")
        mgr._backups_inflight.add("sched001")
        mgr._maybe_schedule_backup(lp)
        mgr._backups_inflight.discard("sched001")
        db = Path(lp.path) / "pb" / "pb_data" / "data.db"
        db.rename(db.with_name("data.db.away"))
        mgr._maybe_schedule_backup(lp)
        db.with_name("data.db.away").rename(db)
        await asyncio.sleep(0)
        assert len(fired) == 3, "every gate must hold"

        # the real runner: capture + prune-to-keep + sidecar ok (clears error)
        del mgr._run_scheduled_backup  # back to the bound method
        host.record_backup_error("sched001", "previous failure")
        lp.backup_keep = 1
        for ts in (100.0, 200.0):
            _touch_archive(mgr.backups.store, "sched001", ts, "scheduled")
        mgr._backups_inflight.add("sched001")
        await mgr._run_scheduled_backup(lp)
        pool = [
            e
            for e in mgr.backups.store.list_backups("sched001")
            if e.trigger == "scheduled"
        ]
        assert len(pool) == 1 and pool[0].ts > 200.0, "prune to keep=1, newest wins"
        state = host.backup_state("sched001")
        assert state["last_at"] is not None and state["last_error"] is None, (
            "success must stamp last_at and clear last_error"
        )
        assert "sched001" not in mgr._backups_inflight

        # a failing capture records the error and never raises out
        db.rename(db.with_name("data.db.away"))
        mgr._backups_inflight.add("sched001")
        await mgr._run_scheduled_backup(lp)
        db.with_name("data.db.away").rename(db)
        assert host.backup_state("sched001")["last_error"], "failure must be recorded"
        assert "sched001" not in mgr._backups_inflight

    asyncio.run(_t3())
print("§3 scheduler due-logic: OK")


# ── §4 pre-promote hook ────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    mgr = LivingUIManager(workspace_root=Path(tmp))
    project = _make_project(mgr.living_ui_dir, "promo001")
    lp = LivingUIProject(
        id="promo001", name="p", description="", path=project.path, status="stopped"
    )
    mgr.projects["promo001"] = lp
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    async def _fake_launch_live(pid):
        return {"status": "success", "url": "http://127.0.0.1:1", "port": 1}

    mgr.lifecycle.promoter._launch_live = _fake_launch_live

    # promote over a live DB captures pre_promote, prunes to the constant,
    # and resets the scheduled clock
    for ts in (10.0, 20.0, 30.0):
        _touch_archive(mgr.backups.store, "promo001", ts, "pre_promote")
    res = asyncio.run(mgr.promote("promo001"))
    assert res["status"] == "success" and res["first"] is False
    pool = [
        e
        for e in mgr.backups.store.list_backups("promo001")
        if e.trigger == "pre_promote"
    ]
    assert len(pool) == PRE_PROMOTE_KEEP and pool[0].ts > 30.0, (
        "hook must capture and prune to the constant"
    )
    assert host.backup_state("promo001")["last_at"] is not None
    assert "promo001" not in mgr._live_ops

    # first delivery (no live DB): the hook no-ops, promote proceeds
    db = Path(lp.path) / "pb" / "pb_data" / "data.db"
    db.unlink()
    n_before = len(mgr.backups.store.list_backups("promo001"))
    res = asyncio.run(mgr.promote("promo001"))
    assert res["status"] == "success" and res["first"] is True
    assert len(mgr.backups.store.list_backups("promo001")) == n_before, (
        "no live DB -> nothing to protect -> no archive"
    )
    _mkdb(db, 3)

    # a raising capture ABORTS the promote before the live boot
    def _boom(project, trigger):
        raise RuntimeError("disk full")

    mgr.backups.capture_stopped = _boom
    res = asyncio.run(mgr.promote("promo001"))
    assert res["status"] == "error" and res["step"] == "before_live_boot", (
        "failed pre-promote backup must abort the promote"
    )
    assert "promo001" not in mgr._live_ops, "mid-op marker must clear on abort"
print("§4 pre-promote hook: OK")

# ── §5 restore round-trip ──────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    mgr = LivingUIManager(workspace_root=Path(tmp))
    project = _make_project(mgr.living_ui_dir, "rest0001")
    lp = LivingUIProject(
        id="rest0001",
        name="r",
        description="",
        path=project.path,
        status="running",
        port=3131,
    )
    mgr.projects["rest0001"] = lp
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    RELAUNCHES = []

    async def _fake_relaunch(pid):
        RELAUNCHES.append(pid)
        lp.status = "running"
        return {"status": "success", "url": "http://127.0.0.1:3131"}

    mgr.launch_and_verify = _fake_relaunch
    db = Path(lp.path) / "pb" / "pb_data" / "data.db"

    async def _t5():
        # take a backup at 3 rows, then "life happens": 8 rows + a new file
        entry = await asyncio.to_thread(mgr.backups.capture_stopped, lp, "manual")
        _mkdb(db, 8)
        (db.parent / "storage" / "rec1" / "later.bin").write_bytes(b"post-backup")

        res = await mgr.restore_backup("rest0001", entry.filename)
        assert res["status"] == "success" and res["restored"] == entry.filename
        assert _count(db) == 3, "restore must return to the archived state"
        assert not (db.parent / "storage" / "rec1" / "later.bin").exists()
        assert RELAUNCHES == ["rest0001"], "restored app must relaunch"
        assert "rest0001" not in mgr._live_ops

        # ...and it is REVERSIBLE: the pre-restore capture holds the 8 rows
        pre_name = res["pre_restore_backup"]
        manual_pool = [
            e
            for e in mgr.backups.store.list_backups("rest0001")
            if e.trigger == "manual"
        ]
        assert any(e.filename == pre_name for e in manual_pool)
        res2 = await mgr.restore_backup("rest0001", pre_name)
        assert res2["status"] == "success"
        assert _count(db) == 8, "restoring the pre-restore backup must undo"
        assert not (mgr.backups.store.project_dir("rest0001") / ".restore-tmp").exists()

        # unknown archive / external app / mid-op are refused up front
        res = await mgr.restore_backup("rest0001", "20990101T000000Z__manual.zip")
        assert res["status"] == "error"
        lp.project_type = "external"
        assert (await mgr.restore_backup("rest0001", pre_name))["status"] == "error"
        lp.project_type = "native"
        mgr._live_ops.add("rest0001")
        res = await mgr.restore_backup("rest0001", pre_name)
        assert res["status"] == "error" and "in flight" in res["errors"][0]
        mgr._live_ops.discard("rest0001")

        # FR9 2a: failing pre-restore capture ABORTS with data untouched
        real_capture = mgr.backups.capture_stopped

        def _boom(project, trigger):
            raise RuntimeError("no space")

        mgr.backups.capture_stopped = _boom
        rows_before = _count(db)
        res = await mgr.restore_backup("rest0001", pre_name)
        assert res["status"] == "error" and res["step"] == "pre_restore_backup"
        assert _count(db) == rows_before, "aborted restore must not touch pb_data"
        mgr.backups.capture_stopped = real_capture
        assert "rest0001" not in mgr._live_ops

    asyncio.run(_t5())
print("§5 restore round-trip: OK")

# ── §6 boot cleaner + delete-project integration ───────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    mgr = LivingUIManager(workspace_root=Path(tmp))
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None

    project = _make_project(mgr.living_ui_dir, "keep0001")
    lp = LivingUIProject(
        id="keep0001", name="k", description="", path=project.path, status="stopped"
    )
    mgr.projects["keep0001"] = lp
    _touch_archive(mgr.backups.store, "keep0001", 100.0, "scheduled")
    _touch_archive(mgr.backups.store, "gone0001", 100.0, "manual")  # orphan's
    (mgr.living_ui_dir / "app_orphan_project").mkdir()

    # the boot cleaner LOGS unregistered dirs but NEVER deletes them, and
    # always skips _backups/_staging
    (mgr.living_ui_dir / "_staging").mkdir(exist_ok=True)
    found = mgr._log_orphan_folders()
    assert found == 1
    assert (mgr.living_ui_dir / "app_orphan_project").exists(), (
        "boot cleaner must NEVER delete orphan folders (only log them)"
    )
    assert (mgr.living_ui_dir / "_backups").exists(), (
        "boot cleaner must NEVER touch _backups"
    )
    assert mgr.backups.store.list_backups("keep0001"), "archives must survive boot"

    # delete_project default: a final pre_delete backup is captured, the
    # project dir dies, and the backups become a listed orphan
    asyncio.run(mgr.delete_project("keep0001"))
    assert "keep0001" not in mgr.projects and not Path(project.path).exists()
    assert mgr.backups.store.list_backups("keep0001"), (
        "default delete must KEEP backups (D5)"
    )
    assert any(
        e.trigger == "pre_delete" and e.size > 0
        for e in mgr.backups.store.list_backups("keep0001")
    ), "delete must capture the live data one last time first"
    assert mgr.backups.store.project_name("keep0001") == "k", (
        "capture must record the app's human name for the orphan listing"
    )
    assert set(mgr.backups.store.orphan_dirs(mgr.projects.keys())) == {
        "keep0001",
        "gone0001",
    }

    # delete_project with delete_backups=True removes the archives too
    project2 = _make_project(mgr.living_ui_dir, "kill0001")
    lp2 = LivingUIProject(
        id="kill0001", name="k2", description="", path=project2.path, status="stopped"
    )
    mgr.projects["kill0001"] = lp2
    _touch_archive(mgr.backups.store, "kill0001", 100.0, "scheduled")
    asyncio.run(mgr.delete_project("kill0001", delete_backups=True))
    assert not mgr.backups.store.project_dir("kill0001").exists()
print("§6 boot cleaner + delete-project: OK")


# ── §7 settings surface ────────────────────────────────────────────────────
from app.ui_layer.settings.living_ui_settings import (  # noqa: E402
    get_living_ui_projects,
    update_project_setting,
)

with tempfile.TemporaryDirectory() as tmp:
    mgr = LivingUIManager(workspace_root=Path(tmp))
    project = _make_project(mgr.living_ui_dir, "sett0001")
    lp = LivingUIProject(
        id="sett0001", name="s", description="", path=project.path, status="stopped"
    )
    mgr.projects["sett0001"] = lp
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None

    # DTO carries the backup settings + status + orphans (with human names
    # from the meta sidecar; id fallback when a dir predates the sidecar)
    _touch_archive(mgr.backups.store, "sett0001", 100.0, "manual")
    _touch_archive(mgr.backups.store, "olddead1", 100.0, "manual")
    out = get_living_ui_projects()
    assert out["success"] and out["backupOrphans"] == [
        {"id": "olddead1", "name": "olddead1"}
    ]
    mgr.backups.store.write_meta("olddead1", "Old Dead App")
    out = get_living_ui_projects()
    assert out["backupOrphans"] == [{"id": "olddead1", "name": "Old Dead App"}]
    dto = out["projects"][0]
    assert dto["backupsEnabled"] is True and dto["backupInterval"] == "daily"
    assert dto["backupKeep"] == 7 and dto["backupStatus"]["count"] == 1
    assert dto["projectType"] == "native"

    # validation branches
    assert update_project_setting("sett0001", "backupsEnabled", False)["success"]
    assert lp.backups_enabled is False
    assert update_project_setting("sett0001", "backupInterval", "weekly")["success"]
    assert not update_project_setting("sett0001", "backupInterval", "monthly")[
        "success"
    ]
    assert not update_project_setting("sett0001", "backupKeep", "abc")["success"]
    assert not update_project_setting("sett0001", "backupKeep", 0)["success"]
    assert not update_project_setting("sett0001", "backupKeep", 31)["success"]
    assert not update_project_setting("sett0001", "nope", 1)["success"]

    # prune-on-shrink: lowering keep applies immediately
    for ts in (10.0, 20.0, 30.0, 40.0):
        _touch_archive(mgr.backups.store, "sett0001", ts, "scheduled")
    assert update_project_setting("sett0001", "backupKeep", 2)["success"]
    pool = [
        e
        for e in mgr.backups.store.list_backups("sett0001")
        if e.trigger == "scheduled"
    ]
    assert [e.ts for e in pool] == [_T0 + 40.0, _T0 + 30.0], (
        "shrink must prune immediately"
    )
print("§7 settings surface: OK")

# ── §8 capture_running against a REAL PocketBase ───────────────────────────
# Uses the pinned binary from the lui cache (fetched by any prior Living UI
# build on this machine). Skipped when absent — §1-§7 stay deterministic.
import json as _json  # noqa: E402
import os as _os  # noqa: E402
import socket as _socket  # noqa: E402
import subprocess as _sp  # noqa: E402
import time as _time  # noqa: E402
import urllib.request as _url  # noqa: E402


def _pinned_pb_binary() -> Path:
    version = (
        (
            Path(__file__).resolve().parents[2]
            / "living-ui"
            / "spec"
            / "pocketbase.version"
        )
        .read_text(encoding="utf-8")
        .strip()
    )
    cache = _os.environ.get("LIVING_UI_PB_CACHE")
    if cache:
        root = Path(cache)
    elif _os.name == "nt":
        root = Path(_os.environ["LOCALAPPDATA"]) / "craftos-living-ui" / "pb"
    else:
        root = Path.home() / ".cache" / "craftos-living-ui" / "pb"
    exe = "pocketbase.exe" if _os.name == "nt" else "pocketbase"
    return root / version / exe


_pb_bin = _pinned_pb_binary()
if not _pb_bin.exists():
    print(f"§8 capture_running vs real PocketBase: SKIPPED (no binary at {_pb_bin})")
else:
    with tempfile.TemporaryDirectory() as tmp:
        living = Path(tmp) / "living_ui"
        proj_dir = living / "app_pbe2e001"
        pb_data = proj_dir / "pb" / "pb_data"
        pb_data.mkdir(parents=True)
        email, password = "agent@lui.local", "e2e-test-password-123"
        assert (
            _sp.run(
                [
                    str(_pb_bin),
                    "superuser",
                    "upsert",
                    email,
                    password,
                    "--dir",
                    str(pb_data),
                ],
                capture_output=True,
                timeout=60,
            ).returncode
            == 0
        ), "superuser upsert failed"
        (proj_dir / ".superuser").write_text(
            _json.dumps({"email": email, "password": password}) + "\n"
        )

        with _socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        proc = _sp.Popen(
            [str(_pb_bin), "serve", f"--http=127.0.0.1:{port}", "--dir", str(pb_data)],
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
        )
        try:
            for _ in range(100):  # wait_healthy, poor man's edition
                try:
                    _url.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
                    break
                except Exception:
                    _time.sleep(0.2)
            else:
                raise AssertionError("PocketBase never became healthy")

            svc = BackupService(living)
            project = SimpleNamespace(
                id="pbe2e001", path=str(proj_dir), status="running", port=port
            )
            entry = asyncio.run(svc.capture_running(project, "manual"))
            assert entry.path.exists() and entry.size > 0
            names = set(zipfile.ZipFile(entry.path).namelist())
            assert "data.db" in names, (
                f"PB archive missing data.db: {sorted(names)[:8]}"
            )
            assert not list((pb_data / "backups").glob("*.zip")), (
                "archive must be MOVED out of pb_data/backups"
            )

            # bad credentials fail loudly, never a silent raw-copy fallback
            (proj_dir / ".superuser").write_text(
                _json.dumps({"email": email, "password": "wrong"}) + "\n"
            )
            try:
                asyncio.run(svc.capture_running(project, "manual"))
                raise AssertionError("bad creds must raise")
            except RuntimeError as e:
                assert "auth failed" in str(e)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    print("§8 capture_running vs real PocketBase: OK")

print("\nBackup acceptance (Phases 1-4): ALL GREEN")
