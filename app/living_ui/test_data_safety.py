"""Data-safety acceptance for the unified dev/live lifecycle.

The single invariant under test (docs/plans/living-ui-unified-lifecycle-plan.md):

    Nothing writes to a live environment's pb_data except PocketBase's
    migration replay during Promoter.promote().

Every code change — first build or modify — develops and verifies in a DEV
environment (code copy, hidden port, FRESH schema-only DB); a clean verify
promotes. There is no stored "delivered" flag: first-vs-update is derived
from live_db_exists().

Run:  python3 -m app.living_ui.test_data_safety

Style follows app/factory/test_phase*.py: a module-level assert script with
hand-rolled duck-typed stubs, no pytest. Action handlers are executed the
way production executes them — source extracted from the registry and
exec'd into a namespace holding ONLY input_data/json/asyncio (executor.py
_atomic_action_internal_async) — so a module-level name leaking into a
handler fails here the same way it fails live.
"""

import asyncio
import inspect
import os as _os
import json as _json
import sqlite3
import tempfile
import textwrap
import types
from pathlib import Path

from agent_core.core.action_framework.registry import _strip_decorator

from app.config import get_app_version

import app.factory.host_craftbot as host_mod
import app.living_ui as living_ui_mod
import app.living_ui.walk_verify as wv_mod
import app.living_ui.wizard as wizard_mod
from app.data.action import living_ui_actions as LA
from app.living_ui.manager import LivingUIManager, LivingUIProject
from app.living_ui.pb_data_io import restore_pb_data, snapshot_pb_data
from app.living_ui.lifecycle import DEV_PORT_RANGE, DevProvisioner, live_db_exists
from app.living_ui.runner import LivingUIRunner
from app.living_ui.wizard import _unwrap_document, adapt_chosen, fresh_build_chosen


# ── shared helpers ─────────────────────────────────────────────────────────
def _mkdb(path: Path, rows: int, table: str = "items") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(rows):
        conn.execute(f"INSERT INTO {table} (v) VALUES (?)", (f"row{i}",))
    conn.commit()
    conn.close()


def _count(path: Path, table: str = "items") -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _make_project_dir(living: Path, pid: str, port: int) -> Path:
    proj = living / f"app_{pid}"
    for d in (
        "pb/pb_hooks",
        "pb/pb_migrations",
        "pb/pb_public",
        "frontend/src",
        "frontend/node_modules/somepkg",
        ".lui",
        "reference",
        "logs",
    ):
        (proj / d).mkdir(parents=True)
    (proj / "manifest.json").write_text(
        _json.dumps(
            {
                "id": pid,
                "name": pid,
                "livingUIVersion": 2,
                "port": port,
                "pipeline": {
                    "start": f"pocketbase serve --http=127.0.0.1:{port} --dir pb/pb_data"
                },
            }
        )
    )
    (proj / "operations.json").write_text('{"opsVersion": 1, "operations": []}')
    (proj / "LIVING_UI.md").write_text("# plan\n")
    (proj / ".superuser").write_text("machine@local:pw\n")
    (proj / "frontend" / "package.json").write_text('{"name": "app"}')
    (proj / "frontend" / "src" / "App.tsx").write_text("export const A = 1\n")
    (proj / "pb" / "pb_hooks" / "ops.pb.js").write_text("// ops\n")
    (proj / "pb" / "pb_public" / "index.html").write_text("<html>built</html>")
    (proj / ".lui" / "system-hashes.json").write_text("{}")
    (proj / "reference" / "requirements.md").write_text("- feature one\n")
    _mkdb(proj / "pb" / "pb_data" / "data.db", rows=2)
    _mkdb(proj / "pb" / "pb_data" / "auxiliary.db", rows=0, table="aux")
    return proj


class _Project:
    def __init__(self, pid: str, path: Path, port: int):
        self.id, self.name, self.description = pid, pid, "test app"
        self.path, self.port, self.status = str(path), port, "running"
        self.backend_port = None
        self.url = f"http://127.0.0.1:{port}"
        self.backend_url = self.url
        self.bridge_token, self.process, self.session_id = "tok", None, None


def _extract(handler) -> str:
    return _strip_decorator(textwrap.dedent(inspect.getsource(handler)))


def _run_action(handler, input_data: dict) -> dict:
    """Execute a handler exactly like executor._atomic_action_internal_async."""
    local_ns = {"input_data": input_data, "json": _json, "asyncio": asyncio}
    pre = set(local_ns)
    exec(_extract(handler), local_ns, local_ns)
    fn = None
    for key, value in local_ns.items():
        if key not in pre and key != "__builtins__" and inspect.isfunction(value):
            fn = value
            break
    assert fn is not None, "handler source defined no function"
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(input_data))
    return fn(input_data)


# ── §1 pb_data_io round-trip ───────────────────────────────────────────────

with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "roundtrip1", 3123)
    pb_data = proj / "pb" / "pb_data"
    (pb_data / "storage").mkdir()
    (pb_data / "storage" / "upload.bin").write_bytes(b"file")

    baseline = proj / ".snapshots" / "baseline"
    snapshot_pb_data(pb_data, baseline, living)
    assert (baseline / "data.db").exists() and (baseline / "auxiliary.db").exists()
    assert (baseline / "storage" / "upload.bin").read_bytes() == b"file"

    _mkdb(pb_data / "data.db", rows=5)  # junk lands after the snapshot
    assert _count(pb_data / "data.db") == 7
    restore_pb_data(baseline, pb_data, living)
    assert _count(pb_data / "data.db") == 2, "restore must drop post-snapshot junk"
    assert _count(baseline / "data.db") == 2, "the baseline itself is untouched"
print("§1 pb_data_io round-trip: OK")


# ── §2 pb_data_io guards ───────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "guards1", 3124)
    baseline = proj / ".snapshots" / "baseline"
    snapshot_pb_data(proj / "pb" / "pb_data", baseline, living)

    outside = Path(tmp) / "outside" / "pb_data"
    outside.mkdir(parents=True)
    for fn_, args in (
        (restore_pb_data, (baseline, outside, living)),  # outside root
        (restore_pb_data, (baseline, proj / "pb" / "not_pb", living)),  # wrong name
        (snapshot_pb_data, (proj / "pb" / "missing", baseline, living)),  # no src
    ):
        try:
            fn_(*args)
            raise AssertionError(f"{fn_.__name__}{args} should have refused")
        except (ValueError, FileNotFoundError):
            pass
    empty = Path(tmp) / "empty_snapshot"
    empty.mkdir()
    try:
        restore_pb_data(empty, proj / "pb" / "pb_data", living)
        raise AssertionError("restore from a data.db-less snapshot must refuse")
    except FileNotFoundError:
        pass
print("§2 pb_data_io guards: OK")


# ── §3 DevProvisioner ──────────────────────────────────────────────────────


class _StubRunner:
    def __init__(self):
        self.kit_synced = []

    async def kit_sync(self, project_dir):
        self.kit_synced.append(Path(project_dir))


with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "dev00001", 3125)
    project = _Project("dev00001", proj, 3125)
    # Trigger declaration MUST travel to the dev copy: without it the copy's
    # guard declares nothing, every ⚡ fire 400s, and the walker fails an
    # unfixable "defect" (observed live 2026-08-06 — three identical STUCKs).
    (proj / "triggers.json").write_text(
        '{"triggers": {"ping": {"instruction": "reply", "description": "d"}}}'
    )
    runner = _StubRunner()
    sup = DevProvisioner(living, runner)

    inst = asyncio.run(sup.create_copy(project))
    sdir = inst.dir
    assert sdir == living / "_staging" / "project" / "dev00001"
    assert DEV_PORT_RANGE[0] <= inst.port <= DEV_PORT_RANGE[1]
    manifest = _json.loads((sdir / "manifest.json").read_text())
    assert manifest["port"] == inst.port, "manifest.port must be rewritten"
    assert manifest["env"] == "dev", "dev copies must be stamped env=dev (A2APP)"
    assert str(inst.port) in manifest["pipeline"]["start"], "pipeline keeps port inline"
    assert "3125" not in manifest["pipeline"]["start"], "old port must be gone"
    assert runner.kit_synced == [sdir], "hash canon must be re-recorded after rewrite"
    assert not (sdir / "pb" / "pb_public").exists(), (
        "gate rebuilds pb_public — never copy"
    )
    # THE POINT of the unified lifecycle: the dev copy has NO database at
    # all — PocketBase creates it at boot and replays the migration chain.
    # Live data is never cloned into an environment the agent writes to.
    assert not (sdir / "pb" / "pb_data").exists(), (
        "dev copy must NOT contain a database — schema comes from migrations"
    )
    assert (sdir / "frontend" / "node_modules" / "somepkg").exists(), (
        "node_modules rides along"
    )
    assert (sdir / ".superuser").exists() and (sdir / ".lui").exists()
    assert (sdir / "triggers.json").exists(), (
        "triggers.json must travel to the dev copy — its absence 400s every fire"
    )

    # sync_code: refreshes agent-owned paths, keeps the rewritten manifest.
    (proj / "frontend" / "src" / "App.tsx").write_text("export const A = 2\n")
    (proj / "frontend" / "package.json").write_text(
        '{"name": "app", "dependencies": {"x": "1.0.0"}}'
    )
    (proj / "triggers.json").write_text(
        '{"triggers": {"pong": {"instruction": "reply", "description": "d"}}}'
    )
    sup.sync_code(project, sdir)
    assert "A = 2" in (sdir / "frontend" / "src" / "App.tsx").read_text()
    assert "pong" in (sdir / "triggers.json").read_text(), (
        "fix-iteration edits to triggers.json must reach the dev copy"
    )
    assert not (sdir / "frontend" / "node_modules").exists(), (
        "changed package.json must clear node_modules so install runs"
    )
    assert _json.loads((sdir / "manifest.json").read_text())["port"] == inst.port

    # reset_db drops the dev DB (a booted dev instance leaves one behind);
    # the next boot replays migrations from empty.
    _mkdb(sdir / "pb" / "pb_data" / "data.db", rows=9)
    sup.reset_db(sdir)
    assert not (sdir / "pb" / "pb_data").exists(), "reset_db must drop the dev DB"
    assert _count(proj / "pb" / "pb_data" / "data.db") == 2, "original DB polluted!"

    # guarded rmtree refuses anything outside _staging
    try:
        sup._guarded_rmtree(proj)
        raise AssertionError("guarded rmtree left the dev root!")
    except ValueError:
        pass

    # destroy + reap
    sup.destroy("dev00001", inst.to_record())
    assert not sdir.exists()
    leftover = living / "_staging" / "project" / "leftover99"
    leftover.mkdir(parents=True)
    reaped = sup.reap_all({"gone12345": {"dir": str(leftover), "pid": 99999999}})
    assert reaped >= 1 and not leftover.exists()
print("§3 DevProvisioner: OK")


# ── §4 FactoryHost delivery bookkeeping + live_db_exists ───────────────────

with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "sidecar01", 3126)
    project = _Project("sidecar01", proj, 3126)

    class _MgrOne:
        def get_project(self, pid):
            return project if pid == "sidecar01" else None

    living_ui_mod.get_living_ui_manager = lambda: _MgrOne()
    host = host_mod.FactoryHost()
    # delivered_at is a cosmetic stamp, written once, never a control input.
    assert host.delivered_at("sidecar01") is None
    host.stamp_delivered("sidecar01")
    first_stamp = host.delivered_at("sidecar01")
    assert first_stamp is not None
    host.stamp_delivered("sidecar01")
    assert host.delivered_at("sidecar01") == first_stamp, "stamp is write-once"
    assert host.get_staging_record("sidecar01") is None
    host.set_staging_record("sidecar01", {"url": "http://127.0.0.1:3901", "port": 3901})
    assert host.get_staging_record("sidecar01")["port"] == 3901
    # stamp survives alongside the dev record
    side = _json.loads((proj / ".factory" / "host.json").read_text())
    assert side["delivered_at"] == first_stamp and side["staging"]["port"] == 3901
    host.clear_staging_record("sidecar01")
    assert host.get_staging_record("sidecar01") is None

    # live_db_exists: the structural first-vs-update predicate.
    assert live_db_exists(proj) is True
    (proj / "pb" / "pb_data" / "data.db").unlink()
    assert live_db_exists(proj) is False
    assert live_db_exists("") is False and live_db_exists(None) is False
    _mkdb(proj / "pb" / "pb_data" / "data.db", rows=2)  # restore for reuse
print("§4 FactoryHost bookkeeping + live_db_exists: OK")


# ── §5 manager.open_dev / promote — THE INVARIANT ──────────────────────────

with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    mgr = LivingUIManager(workspace_root=workspace)
    living = mgr.living_ui_dir
    proj_dir = _make_project_dir(living, "mgrtest01", 3127)
    project = LivingUIProject(
        id="mgrtest01",
        name="mgrtest01",
        description="t",
        path=str(proj_dir),
        status="running",
        port=3127,
    )
    project.bridge_token = "tok"
    mgr.projects["mgrtest01"] = project
    mgr.lifecycle.provisioner.runner = _StubRunner()  # no node in tests

    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None  # fresh singleton bound to this manager
    host = host_mod.get_factory_host()

    PIPELINE_RUNS = []

    class _FakeProc:
        pid = 4242

        def poll(self):
            return None

        def terminate(self):
            PIPELINE_RUNS.append("terminate")

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    async def _fake_pipeline(project_dir, port, bridge_token):
        PIPELINE_RUNS.append((Path(project_dir), port))
        return {"status": "success", "process": _FakeProc()}

    mgr._run_launch_pipeline = _fake_pipeline
    mgr.lifecycle._launch_pipeline = _fake_pipeline

    # Fingerprint the LIVE DB before the whole arc: the invariant is that
    # no lifecycle step below changes a single byte of it (the fake launch
    # stands in for the promote boot, whose migration replay is the one
    # sanctioned writer).
    _live_db = proj_dir / "pb" / "pb_data" / "data.db"
    _live_bytes_before = _live_db.read_bytes()

    result = asyncio.run(mgr.open_dev("mgrtest01"))
    assert result["status"] == "success" and result.get("dev") is True
    record = host.get_staging_record("mgrtest01")
    assert record and record["pid"] == 4242
    sdir = Path(record["dir"])
    assert sdir.exists() and PIPELINE_RUNS[-1][0] == sdir, (
        "pipeline must target the COPY"
    )
    assert PIPELINE_RUNS[-1][1] == record["port"] != 3127
    assert result.get("dir") == str(sdir), "agents need the dev dir for logs/CLI"
    assert not (sdir / "pb" / "pb_data").exists(), "dev copy must start with no DB"
    # live DB exists → open_dev re-armed the machine as a MODIFY
    machine = host.machine_for("mgrtest01")
    assert machine is not None and machine.state == "modifying", machine.state

    # a second open_dev (fix iteration) reuses the copy and resets its DB
    _mkdb(sdir / "pb" / "pb_data" / "data.db", rows=9)  # simulated boot junk
    result = asyncio.run(mgr.open_dev("mgrtest01"))
    assert result["status"] == "success"
    assert not (sdir / "pb" / "pb_data").exists(), (
        "each open_dev must reset the dev DB — migrations replay from empty"
    )

    # promote (update): relaunch real app, then destroy dev copy + record
    PROMOTED = []

    async def _fake_launch_and_verify(pid):
        PROMOTED.append(pid)
        return {"status": "success", "url": "http://127.0.0.1:3127", "port": 3127}

    mgr.lifecycle.promoter._launch_live = _fake_launch_and_verify
    up = asyncio.run(mgr.promote("mgrtest01"))
    assert up["status"] == "success" and PROMOTED == ["mgrtest01"]
    assert up["first"] is False, "live DB existed — this is an UPDATE promote"
    assert not sdir.exists(), "promote must destroy the dev copy"
    assert host.get_staging_record("mgrtest01") is None
    assert host.delivered_at("mgrtest01") is not None, "promote stamps delivery"
    assert _live_db.read_bytes() == _live_bytes_before, (
        "INVARIANT VIOLATED: the live DB changed outside the promote boot"
    )

    # failed promote keeps the copy and the record
    result = asyncio.run(mgr.open_dev("mgrtest01"))
    sdir = Path(host.get_staging_record("mgrtest01")["dir"])

    async def _failing_launch(pid):
        return {"status": "error", "step": "health", "errors": ["boom"]}

    mgr.lifecycle.promoter._launch_live = _failing_launch
    up = asyncio.run(mgr.promote("mgrtest01"))
    assert up["status"] == "error"
    assert sdir.exists() and host.get_staging_record("mgrtest01") is not None
    mgr.lifecycle.provisioner.destroy("mgrtest01", host.get_staging_record("mgrtest01"))
    host.clear_staging_record("mgrtest01")

    # FIRST promote: no live DB → first=True; nothing restores or wipes.
    proj2_dir = _make_project_dir(living, "firstdel01", 3128)
    import shutil as _shutil

    _shutil.rmtree(proj2_dir / "pb" / "pb_data")  # a never-delivered build
    project2 = LivingUIProject(
        id="firstdel01",
        name="firstdel01",
        description="t",
        path=str(proj2_dir),
        status="stopped",
        port=3128,
    )
    project2.bridge_token = "tok"
    mgr.projects["firstdel01"] = project2

    dev = asyncio.run(mgr.open_dev("firstdel01"))
    assert dev["status"] == "success"
    # no live DB → build era: the machine must NOT be re-armed into modify
    m2 = host.machine_for("firstdel01")
    assert m2 is not None and m2.state == "building", m2.state

    async def _first_launch(pid):
        # the promote boot creates the live DB from migrations — simulate it
        _mkdb(proj2_dir / "pb" / "pb_data" / "data.db", rows=0)
        return {"status": "success", "url": "http://127.0.0.1:3128", "port": 3128}

    mgr.lifecycle.promoter._launch_live = _first_launch
    up = asyncio.run(mgr.promote("firstdel01"))
    assert up["status"] == "success" and up["first"] is True
    assert live_db_exists(proj2_dir)
    assert host.get_staging_record("firstdel01") is None
print("§5 manager open_dev/promote invariant: OK")


# ── §6-8 action branching (bare-exec, like the real executor) ──────────────

EVENTS = []
WALK = {"report": None, "base_url": None, "project_path": None}


class _StubMgr:
    def __init__(self, project):
        self._p = project
        self.projects = {project.id: project}

    def get_project(self, pid):
        return self._p if pid == self._p.id else None

    async def launch_and_verify(self, pid):
        EVENTS.append("launch_and_verify")
        return {"status": "success", "url": self._p.url, "port": self._p.port}

    async def open_dev(self, pid):
        EVENTS.append("open_dev")
        return {
            "status": "success",
            "url": "http://127.0.0.1:3901",
            "port": 3901,
            "dir": "/tmp/devcopy",
            "dev": True,
        }

    async def stop_project(self, pid):
        EVENTS.append("stop_project")
        return True

    async def promote(self, pid):
        EVENTS.append("promote")
        return {
            "status": "success",
            "url": self._p.url,
            "port": self._p.port,
            "first": False,
        }


async def _b_ready(pid, url, port):
    EVENTS.append(("broadcast_ready", url))


async def _b_progress(pid, *a, **k):
    pass


async def _walk_stub(project, base_url=None, project_path=None):
    WALK.update(base_url=base_url, project_path=project_path)
    return WALK["report"]


def _wire(project, host):
    stub = _StubMgr(project)
    living_ui_mod.get_living_ui_manager = lambda: stub
    living_ui_mod.broadcast_living_ui_ready = _b_ready
    living_ui_mod.broadcast_living_ui_progress = _b_progress
    living_ui_mod.dispatch_living_ui_data_changed = lambda pid: EVENTS.append(
        "data_changed"
    )
    wv_mod.run_walk_verify = _walk_stub
    host.report_launch_success = lambda pid: None
    host.report_verify = lambda *a, **k: types.SimpleNamespace(
        next_state="fixing", payload={}
    )
    return stub


with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"

    # §6a no dev env: walk refuses; notify_ready boots the dev env
    proj = _make_project_dir(living, "actnostg01", 3132)
    project = _Project("actnostg01", proj, 3132)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    stub = _wire(project, host)
    EVENTS.clear()
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "actnostg01"})
    assert out["status"] == "error" and "dev" in out["message"].lower(), out
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "actnostg01"})
    assert out["status"] == "success" and "open_dev" in EVENTS
    assert "launch_and_verify" not in EVENTS, "native apps never launch live here"
    assert "DEV environment" in out["message"]
    assert "/tmp/devcopy" in out["message"], "message must name the dev dir"
    print("§6a dev-env gating: OK")

    # §6c dev defects: live app NOT stopped; dev log quoted
    sdir = living / "_staging" / "project" / "actnostg01"
    (sdir / "logs").mkdir(parents=True)
    (sdir / "logs" / "pocketbase.log").write_text(
        "ERROR hook exploded: dev-only-line\n"
    )
    host.set_staging_record(
        "actnostg01", {"url": "http://127.0.0.1:3905", "port": 3905, "dir": str(sdir)}
    )
    captured = {}
    host.report_verify = lambda *a, **k: (
        captured.update(k) or types.SimpleNamespace(next_state="fixing", payload={})
    )
    EVENTS.clear()
    WALK["report"] = {
        "kind": "defects",
        "passed": [],
        "defects": ["- add item — FAIL"],
        "raw": "VERDICT: FAIL",
    }
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "actnostg01"})
    assert out["status"] == "error"
    assert "stop_project" not in EVENTS, "native defects must not stop the live app"
    assert "previous working version" in out["message"]
    assert WALK["base_url"] == "http://127.0.0.1:3905", "verifier must drive the COPY"
    assert WALK["project_path"] == str(sdir)
    assert "dev-only-line" in captured.get("server_log", ""), (
        "evidence must come from the dev log"
    )
    print("§6c dev defects: OK")

    # §6d clean verdict: promote before announce; promote failure blocks it
    host.report_verify = lambda *a, **k: types.SimpleNamespace(
        next_state="done", payload={}
    )
    EVENTS.clear()
    WALK["report"] = {
        "kind": "pass",
        "passed": ["feature one"],
        "defects": [],
        "raw": "VERDICT: PASS",
    }
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "actnostg01"})
    assert out["status"] == "success", out
    promote_i = EVENTS.index("promote")
    ready_i = next(
        i
        for i, e in enumerate(EVENTS)
        if isinstance(e, tuple) and e[0] == "broadcast_ready"
    )
    assert promote_i < ready_i, "the promote must precede the announce"
    assert EVENTS[ready_i][1] == "http://127.0.0.1:3132", (
        "announce must carry the REAL url"
    )
    assert "finalize_first_delivery" not in EVENTS, (
        "the baseline-restore path must not exist"
    )

    class _PromoteFailMgr(_StubMgr):
        async def promote(self, pid):
            EVENTS.append("promote")
            return {
                "status": "error",
                "step": "health",
                "errors": ["real app did not boot"],
            }

    living_ui_mod.get_living_ui_manager = lambda: _PromoteFailMgr(project)
    EVENTS.clear()
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "actnostg01"})
    assert out["status"] == "error" and "deploy" in out["message"].lower()
    assert not any(
        isinstance(e, tuple) and e[0] == "broadcast_ready" for e in EVENTS
    ), "a failed promote must never announce"
    print("§6d clean verdict promotes: OK")

    # §7 notify_ready always routes native apps to the dev env — even a
    # first build with no live DB (the unified flow's whole point).
    proj = _make_project_dir(living, "actnr0001", 3133)
    import shutil as _sh

    _sh.rmtree(proj / "pb" / "pb_data")  # a never-delivered scaffold
    project = _Project("actnr0001", proj, 3133)
    _wire(project, host)
    EVENTS.clear()
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "actnr0001"})
    assert out["status"] == "success" and "open_dev" in EVENTS
    assert "launch_and_verify" not in EVENTS
    assert "DEV environment" in out["message"]
    print("§7 notify_ready first build → dev env: OK")

    # §8 living_ui_http: dev redirect, no iframe reload, mid-arc refusal
    import requests as _requests

    _orig_request = _requests.request
    HTTP = []

    def _fake_request(method, url, **kwargs):
        HTTP.append((method, url))
        return types.SimpleNamespace(
            ok=True,
            status_code=200,
            headers={},
            text="{}",
            url=url,
            json=lambda: {},
        )

    _requests.request = _fake_request
    try:
        proj = _make_project_dir(living, "acthttp01", 3134)
        project = _Project("acthttp01", proj, 3134)
        _wire(project, host)

        # mid-arc (machine non-terminal), no dev env → writes refused,
        # reads allowed. A virgin machine reads as mid-arc — that is the
        # safe direction: agent test writes belong in the dev env.
        out = _run_action(
            LA.living_ui_http,
            {"project_id": "acthttp01", "method": "POST", "path": "/api/x", "json": {}},
        )
        assert out["status"] == "error" and "dev" in out["message"], out
        out = _run_action(
            LA.living_ui_http,
            {"project_id": "acthttp01", "method": "GET", "path": "/api/x"},
        )
        assert out["status"] == "success"

        # dev env up → ALL agent HTTP redirected there, and NO iframe reload
        host.set_staging_record(
            "acthttp01", {"url": "http://127.0.0.1:3906", "port": 3906, "dir": "x"}
        )
        EVENTS.clear()
        out = _run_action(
            LA.living_ui_http,
            {"project_id": "acthttp01", "method": "POST", "path": "/api/x", "json": {}},
        )
        assert out["status"] == "success"
        assert HTTP[-1][1].startswith("http://127.0.0.1:3906"), (
            "write must hit the COPY"
        )
        assert "data_changed" not in EVENTS, (
            "dev writes must not reload the user's iframe"
        )

        # arc closed (machine terminal), no dev env → live writes are USER
        # data and flow to the real app + data_changed dispatch.
        host.clear_staging_record("acthttp01")
        host._machines["acthttp01"] = types.SimpleNamespace(terminal=True)
        EVENTS.clear()
        out = _run_action(
            LA.living_ui_http,
            {"project_id": "acthttp01", "method": "POST", "path": "/api/x", "json": {}},
        )
        assert out["status"] == "success" and HTTP[-1][1].startswith(
            "http://127.0.0.1:3134"
        )
        assert "data_changed" in EVENTS
        host._machines.pop("acthttp01", None)
    finally:
        _requests.request = _orig_request
    print("§8 living_ui_http redirect/refusal: OK")


# ── §9 requirements-document unwrap (wizard) ───────────────────────────────
_MD = "# app — Requirements\n\n## Features\n" + "The user can do a thing.\n" * 20
assert _unwrap_document(_MD) == _MD.strip(), "plain markdown must pass through"
assert _unwrap_document(f"```markdown\n{_MD}\n```") == _MD.strip()
# The observed failure: a {"document": "..."} JSON envelope (grok, 2026-08-04)
assert _unwrap_document(_json.dumps({"document": _MD})) == _MD.strip()
assert _unwrap_document(_json.dumps(_MD)) == _MD.strip(), "bare JSON string unwraps"
# 2026-08-05 live: a short-by-mandate decision doc arrived JSON-wrapped and
# slipped past the old >=200 unwrap heuristic — must unwrap regardless of length.
_SHORT_DECISION = (
    "MARKETPLACE DECISION: install kanban-board; adapt: no\n"
    "## Adaptations\n## User request\na simple kanban board"
)
assert _unwrap_document(_json.dumps({"document": _SHORT_DECISION})) == _SHORT_DECISION
# A dict with several long strings is ambiguous — leave untouched
_amb = _json.dumps({"a": _MD, "b": _MD})
assert _unwrap_document(_amb) == _amb
# Markdown that merely STARTS with "{" but isn't JSON is untouched
_brace = "{not json}\n" + _MD
assert _unwrap_document(_brace) == _brace.strip()
print("§9 requirements unwrap: OK")


# ── §10 wizard adapt-choice detection ──────────────────────────────────────
assert adapt_chosen(
    [{"question": "q", "answer": "Install kanban-board and adapt it to my needs"}]
)
assert not adapt_chosen(
    [{"question": "q", "answer": "Install kanban-board as-is (ready now)"}]
)
assert not adapt_chosen([{"question": "q", "answer": "Build a fresh app from scratch"}])
assert not adapt_chosen([])

# fresh-build detection + the round-2 interview it triggers (catalogue
# withheld so the marketplace question cannot recur — observed live
# 2026-08-05: round 1 was ONLY the marketplace question, so a fresh build
# synthesized from a one-line description)
assert fresh_build_chosen(
    [{"question": "q", "answer": "Build a fresh app from scratch"}]
)
assert not fresh_build_chosen(
    [{"question": "q", "answer": "Install kanban-board as-is (ready now)"}]
)

_R2_QUESTIONS = {
    "questions": [
        {
            "id": "q1",
            "question": "Which columns should the board start with?",
            "why": "seed data",
            "multiSelect": False,
            "options": ["To Do/Doing/Done", "Backlog/Active/Review/Done"],
        }
    ]
}


async def _fake_interview_llm(system_prompt, user_prompt, prompt_name):
    assert "BUILD FRESH FROM SCRATCH" in user_prompt, "round 2 must state the decision"
    assert "MARKETPLACE" not in user_prompt.split("BUILD FRESH")[0].upper() or (
        "marketplace was offered and declined" in user_prompt
    )
    return _json.dumps(_R2_QUESTIONS)


_orig_wllm = wizard_mod._llm
wizard_mod._llm = _fake_interview_llm
try:
    r2 = asyncio.run(
        wizard_mod.generate_interview(
            {"name": "kanban", "description": "a kanban board"},
            [],
            include_marketplace=False,
        )
    )
finally:
    wizard_mod._llm = _orig_wllm
assert r2 and r2[0]["question"].startswith("Which columns")
print("§10 adapt/fresh-choice detection + round 2: OK")

# Short-document guard vs marketplace-decision docs (observed live
# 2026-08-05: a VALID as-is decision doc is under 200 chars and failed the
# whole wizard finalize). Decision docs are exempt; garbage still refused.
_DECISION_DOC = (
    "MARKETPLACE DECISION: install kanban-board; adapt: no\n\n"
    "## Adaptations\n- none\n\n## User request\nkanban board\n"
)


async def _fake_syn_llm(system_prompt, user_prompt, prompt_name):
    return _SYN_REPLY[0]


_orig_sllm = wizard_mod._llm
wizard_mod._llm = _fake_syn_llm
try:
    _SYN_REPLY = [_json.dumps({"document": _DECISION_DOC})]  # grok-style envelope
    doc = asyncio.run(wizard_mod.synthesize_requirements({"name": "k"}, [], []))
    assert doc.startswith("MARKETPLACE DECISION: install kanban-board; adapt: no")

    _SYN_REPLY = [_DECISION_DOC]
    doc = asyncio.run(wizard_mod.synthesize_requirements({"name": "k"}, [], []))
    assert doc.startswith("MARKETPLACE DECISION: install kanban-board; adapt: no")

    _SYN_REPLY = ["MARKETPLACE DECISION: broken line"]
    try:
        asyncio.run(wizard_mod.synthesize_requirements({"name": "k"}, [], []))
        raise AssertionError("malformed decision line must refuse")
    except ValueError:
        pass

    _SYN_REPLY = ["too short"]
    try:
        asyncio.run(wizard_mod.synthesize_requirements({"name": "k"}, [], []))
        raise AssertionError("truncated non-decision doc must still refuse")
    except ValueError:
        pass
finally:
    wizard_mod._llm = _orig_sllm
print("§10b short-doc guard vs decision docs: OK")

# Adapt follow-ups must know WHAT the app is (else the model produces
# category options — "change the columns" — that teach the spec writer
# nothing; observed live 2026-08-05) and the target parses from the
# mandated option wording.
_ADAPT_ANSWERS = [
    {"question": "q", "answer": "Install kanban-board and adapt it to my needs"}
]
_orig_cat = wizard_mod._marketplace_catalogue
wizard_mod._marketplace_catalogue = lambda: [
    {
        "id": "kanban-board",
        "name": "Kanban Board",
        "description": "Drag-and-drop board with labels, priorities, checklists.",
        "tags": ["kanban"],
    }
]
try:
    _t = wizard_mod._adapt_target(_ADAPT_ANSWERS)
    assert _t and _t["id"] == "kanban-board"
    assert (
        wizard_mod._adapt_target([{"question": "q", "answer": "Build fresh"}]) is None
    )

    _FU_REPLY = _json.dumps(
        {
            "questions": [
                {
                    "id": "f1",
                    "question": "Which columns should the board use?",
                    "why": "stages",
                    "multiSelect": False,
                    "options": [
                        "Rename the columns to Backlog / In Progress / Done",
                        "Keep this as the marketplace version has it",
                    ],
                }
            ]
        }
    )

    async def _fake_fu_llm(system_prompt, user_prompt, prompt_name):
        assert "CONCRETE ADAPTATION" in system_prompt
        assert "labels, priorities, checklists" in user_prompt, (
            "the app's catalogue description must reach the prompt"
        )
        return _FU_REPLY

    _orig_fllm = wizard_mod._llm
    wizard_mod._llm = _fake_fu_llm
    try:
        fu = asyncio.run(
            wizard_mod.generate_followup_questions(
                {"name": "kanban", "description": "simple kanban"}, _ADAPT_ANSWERS, []
            )
        )
    finally:
        wizard_mod._llm = _orig_fllm
    assert fu and fu[0]["options"][0].startswith("Rename the columns")
finally:
    wizard_mod._marketplace_catalogue = _orig_cat
print("§10c adapt follow-ups grounded in the target app: OK")

# The interview prompt must never carry the whole catalogue — candidates are
# pre-ranked in-process (fine at 18 apps, unworkable at thousands).
_BIG_CAT = [
    {
        "id": f"app-{i}",
        "name": f"App {i}",
        "description": "unrelated tool",
        "tags": ["misc"],
    }
    for i in range(500)
] + [
    {
        "id": "kanban-board",
        "name": "Kanban Board",
        "description": "Drag-and-drop kanban board",
        "tags": ["kanban", "productivity"],
    },
    {
        "id": "kanban-online",
        "name": "Kanban Online",
        "description": "Multi-user kanban board",
        "tags": ["kanban", "multi-user"],
    },
]
_ranked = wizard_mod._rank_marketplace(_BIG_CAT, "a simple kanban board")
assert len(_ranked) <= 6
assert {a["id"] for a in _ranked} >= {"kanban-board", "kanban-online"}, _ranked
assert wizard_mod._rank_marketplace(_BIG_CAT, "quantum telescope alignment") == [], (
    "zero overlap must offer nothing"
)
assert len(wizard_mod._rank_marketplace(_BIG_CAT, "")) == 6, "empty query caps at k"
print("§10d marketplace candidate ranking: OK")


# ── §11 marketplace install adoption (bare-exec action) ────────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "adopt0001", 3141)
    import shutil as _sh11

    # A wizard scaffold mid-build has NO live DB (builds run in the dev env).
    _sh11.rmtree(proj / "pb" / "pb_data")
    project = _Project("adopt0001", proj, 3141)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    stub = _wire(project, host)

    INSTALLS = []

    async def _install(app_id, app_name, app_description, project_id=None):
        INSTALLS.append(project_id)
        pid = project_id or "fresh999"
        return {
            "status": "success",
            "project": {"id": pid, "url": "http://127.0.0.1:3141"},
            "url": "http://127.0.0.1:3141",
        }

    stub.install_from_marketplace = _install

    async def _b_created(p):
        pass

    living_ui_mod.broadcast_living_ui_created = _b_created

    VERDICTS = []
    host.report_verify = lambda pid, kind, **k: (
        VERDICTS.append((pid, kind))
        or types.SimpleNamespace(next_state="done", payload={})
    )

    # a) session project, never delivered, as-is → adopt + machine completes
    out = _run_action(
        LA.living_ui_marketplace_install,
        {"app_id": "kanban-board", "_session_id": "lui_adopt0001"},
    )
    assert out["status"] == "success" and out["project_id"] == "adopt0001"
    assert INSTALLS[-1] == "adopt0001", "install must ADOPT the session project"
    assert VERDICTS[-1] == ("adopt0001", "pass"), (
        "as-is adoption must close the factory arc"
    )
    assert "announced" in out["message"]

    # b) will_adapt → machine stays open, agent told to continue via modify flow
    VERDICTS.clear()
    out = _run_action(
        LA.living_ui_marketplace_install,
        {"app_id": "kanban-board", "_session_id": "lui_adopt0001", "will_adapt": True},
    )
    assert INSTALLS[-1] == "adopt0001" and not VERDICTS
    assert "notify_ready" in out["message"] and "adaptations" in out["message"].lower()

    # c) session project holding the SAME installed app → idempotent no-op
    # (the crash-resume path: redispatched "continue build" must not mint a
    # duplicate). "Installed" is structural: live DB + marketplaceAppId.
    _mkdb(proj / "pb" / "pb_data" / "data.db", rows=2)
    _mf = _json.loads((proj / "manifest.json").read_text())
    _mf["marketplaceAppId"] = "kanban-board"
    (proj / "manifest.json").write_text(_json.dumps(_mf))
    _n_installs = len(INSTALLS)
    out = _run_action(
        LA.living_ui_marketplace_install,
        {"app_id": "kanban-board", "_session_id": "lui_adopt0001"},
    )
    assert out["status"] == "success" and out.get("already_installed") is True
    assert len(INSTALLS) == _n_installs, "already-installed must not reinstall"
    assert "ALREADY" in out["message"]

    # c2) delivered session project, DIFFERENT app → separate fresh install
    out = _run_action(
        LA.living_ui_marketplace_install,
        {"app_id": "crm-system", "_session_id": "lui_adopt0001"},
    )
    assert INSTALLS[-1] is None, "a delivered session project means a NEW separate app"
    assert out["project_id"] == "fresh999"

    # d) not a project session → fresh install
    out = _run_action(
        LA.living_ui_marketplace_install,
        {"app_id": "kanban-board", "_session_id": "main"},
    )
    assert INSTALLS[-1] is None
print("§11 marketplace adoption: OK")


# ── §12 supervised modifies (LIFECYCLE-PLAN Phase 2) ───────────────────────
with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    mgr = LivingUIManager(workspace_root=workspace)
    living = mgr.living_ui_dir
    proj_dir = _make_project_dir(living, "modarc001", 3145)
    project = LivingUIProject(
        id="modarc001",
        name="modarc001",
        description="t",
        path=str(proj_dir),
        status="running",
        port=3145,
    )
    project.bridge_token = "tok"
    mgr.projects["modarc001"] = project
    mgr.lifecycle.provisioner.runner = _StubRunner()

    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    host.stamp_delivered("modarc001")
    assert isinstance(host.delivered_at("modarc001"), float)

    # Simulate the finished BUILD arc (wizard-built app): machine at DONE.
    machine = host.machine_for("modarc001")
    for s in ("building", "gating", "launching"):
        machine.advance(host_mod.Outcome(s, ok=True))
    machine.advance(host_mod.Outcome("verifying", ok=True))
    assert machine.terminal and machine.state == "done"

    MISSIONS = []
    host._emit_mission = lambda project, brief, mission_kind, machine: MISSIONS.append(
        (mission_kind, machine.generation, brief)
    )
    CHAT = []
    host._emit_chat = lambda pid, text: CHAT.append(text)

    class _ModProc:
        pid = 4243

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    async def _mod_pipeline(project_dir, port, bridge_token):
        return {"status": "success", "process": _ModProc()}

    mgr._run_launch_pipeline = _mod_pipeline
    mgr.lifecycle._launch_pipeline = _mod_pipeline

    # First modify: dev env up (live DB exists) → machine re-armed into
    # MODIFYING, gen 1
    result = asyncio.run(mgr.open_dev("modarc001"))
    assert result["status"] == "success"
    machine = host.machine_for("modarc001")
    assert machine.state == "modifying" and machine.generation == 1

    # notify_ready's report_launch_success no longer no-ops (non-terminal)
    host.report_launch_success("modarc001")
    assert machine.state == "verifying"

    # Defects now dispatch a REAL fix mission — the pre-Phase-2 hole
    decision = host.report_verify(
        "modarc001",
        "defects",
        defects=["- add deadline — FAIL"],
        details="- add deadline — FAIL",
        walk_report="VERDICT: FAIL",
        server_log="ERROR boom",
    )
    assert decision is not None, "modify verdicts must reach the machine"
    assert machine.state == "fixing"
    assert MISSIONS and MISSIONS[-1][0] == "fix" and MISSIONS[-1][1] == 1

    # Fix mission re-enters open_dev → begin_modify no-ops mid-arc
    result = asyncio.run(mgr.open_dev("modarc001"))
    assert result["status"] == "success"
    assert machine.state == "fixing" and machine.generation == 1

    # Fix passes → machine announces THE CHANGE (not a first build)
    host.report_launch_success("modarc001")
    decision = host.report_verify(
        "modarc001",
        "pass",
        url="http://127.0.0.1:3145",
        verified=["deadline"],
    )
    assert machine.terminal and machine.state == "done"
    assert CHAT and "change is live" in CHAT[-1], CHAT

    # Second modify: fresh generation, fresh budget
    result = asyncio.run(mgr.open_dev("modarc001"))
    assert machine.state == "modifying" and machine.generation == 2
    state_file = _json.loads((proj_dir / ".factory" / "state.json").read_text())
    assert state_file["total_missions"] == 0 and len(state_file["generations"]) == 2
print("§12 supervised modifies: OK")


# ── §13 requirements-staleness belt (LIFECYCLE-PLAN Phase 1) ───────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "specbelt01", 3146)
    project = _Project("specbelt01", proj, 3146)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    stub = _wire(project, host)
    host.stamp_delivered("specbelt01")
    host.set_staging_record(
        "specbelt01", {"url": "http://127.0.0.1:3907", "port": 3907, "dir": "x"}
    )

    req = proj / "reference" / "requirements.md"
    stale = host.delivered_at("specbelt01") - 1000
    _os.utime(req, (stale, stale))
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "specbelt01"})
    assert out["status"] == "success"
    assert "WARNING: reference/requirements.md" in out["message"], (
        "stale spec on a delivered app must warn"
    )

    req.write_text("- feature one\n\n## Changes\n- 2026-08-05: add deadline\n")
    _os.utime(req, (stale, stale))  # even with old mtime, ## Changes silences it
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "specbelt01"})
    assert "WARNING" not in out["message"]
print("§13 requirements-staleness belt: OK")


# ── §14 unified import (zip / folder / git) ────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    mgr = LivingUIManager(workspace_root=workspace)
    mgr.runner.kit_sync = _StubRunner().kit_sync
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    # detection
    src_dir = Path(tmp) / "exported_app"
    _make_project_dir(Path(tmp), "srcapp0001", 3151)
    (Path(tmp) / "app_srcapp0001").rename(src_dir)
    (src_dir / "frontend" / "node_modules" / "somepkg" / "x.js").parent.mkdir(
        parents=True, exist_ok=True
    )
    (src_dir / ".git").mkdir()
    (src_dir / ".git" / "config").write_text("[core]\n")
    assert mgr.detect_import_source(str(src_dir)) == "folder"
    assert mgr.detect_import_source("https://github.com/a/b") == "git"
    assert mgr.detect_import_source("git@github.com:a/b.git") == "git"
    assert mgr.detect_import_source("file:///tmp/x") == "git"
    for bad in ("", "/nonexistent/path", "/etc/hosts"):
        try:
            mgr.detect_import_source(bad)
            raise AssertionError(f"detect must refuse {bad!r}")
        except ValueError:
            pass

    # folder import: read-only source, junk skipped, delivered registration
    project = asyncio.run(mgr.import_project_source(str(src_dir), name="Folder App"))
    assert project.status == "stopped" and project.id != "srcapp0001"
    dest = Path(project.path)
    assert not (dest / ".superuser").exists(), "shipped credentials must strip"
    assert (
        not (dest / ".git").exists()
        and not (dest / "frontend" / "node_modules").exists()
    )
    _mf = _json.loads((dest / "manifest.json").read_text())
    assert _mf["id"] == project.id and _mf["port"] == project.port
    assert str(project.port) in _mf["pipeline"]["start"]
    assert host.delivered_at(project.id) is not None, (
        "imports are stamped delivered on arrival"
    )
    assert (src_dir / ".superuser").exists(), "the source folder is never modified"

    # zip import through the same core
    import zipfile as _zipfile

    zip_path = Path(tmp) / "export.zip"
    with _zipfile.ZipFile(zip_path, "w") as zf:
        for f in src_dir.rglob("*"):
            if f.is_file() and ".git" not in f.parts and "node_modules" not in f.parts:
                zf.write(f, Path("exported_app") / f.relative_to(src_dir))
    project2 = asyncio.run(mgr.import_project_source(str(zip_path)))
    assert project2.id != project.id and host.delivered_at(project2.id) is not None

    # git import via a real local repo (file:// clone path)
    import subprocess as _sub

    git_src = Path(tmp) / "gitrepo"
    import shutil as _shutil

    _shutil.copytree(
        src_dir, git_src, ignore=_shutil.ignore_patterns(".git", "node_modules")
    )
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
    ):
        _sub.run(cmd, cwd=git_src, check=True, capture_output=True)
    project3 = asyncio.run(mgr.import_project_source(f"file://{git_src}"))
    assert host.delivered_at(project3.id) is not None
    assert len({project.id, project2.id, project3.id}) == 3

    # A TEMPLATE tree (marketplace checkout imported by path) must have its
    # {{...}} tokens substituted or the app registers broken.
    tpl = Path(tmp) / "template_app"
    _shutil.copytree(
        src_dir, tpl, ignore=_shutil.ignore_patterns(".git", "node_modules")
    )
    _tm = _json.loads((tpl / "manifest.json").read_text())
    _tm["description"] = "{{PROJECT_DESCRIPTION}}"
    _tm["pipeline"]["start"] = (
        "pocketbase serve --http=127.0.0.1:{{PORT}} --dir pb/pb_data"
    )
    (tpl / "manifest.json").write_text(_json.dumps(_tm))
    (tpl / "LIVING_UI.md").write_text("# {{PROJECT_NAME}}\nid: {{PROJECT_ID}}\n")
    project4 = asyncio.run(mgr.import_project_source(str(tpl), name="Tpl App"))
    _lm = (Path(project4.path) / "LIVING_UI.md").read_text()
    assert "{{" not in _lm and "Tpl App" in _lm, _lm
    _mf4 = _json.loads((Path(project4.path) / "manifest.json").read_text())
    assert "{{" not in _json.dumps(_mf4), _mf4
print("§14 unified import: OK")


# ── §15 living_ui_import action dispatches the verify run ──────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "impact0001", 3152)
    project = _Project("impact0001", proj, 3152)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    stub = _wire(project, host)

    DISPATCHES = []

    async def _imp_source(source, name=None):
        return project

    async def _sdr(pid, **kwargs):
        DISPATCHES.append((pid, kwargs))
        return "lui_impact0001"

    stub.import_project_source = _imp_source
    stub.start_development_run = _sdr
    stub.post_import_brief = LivingUIManager.post_import_brief.__get__(stub)
    # post_import_brief now appends the trigger-consent ask (TRIGGERS-PLAN).
    stub.declared_triggers_brief = LivingUIManager.declared_triggers_brief.__get__(stub)

    out = _run_action(LA.living_ui_import, {"source": "/tmp/whatever.zip"})
    assert out["status"] == "success" and out["project_id"] == "impact0001"
    assert DISPATCHES, "import must queue the verify run"
    _pid, _kw = DISPATCHES[-1]
    assert _pid == "impact0001" and _kw["workflow_skill"] == "living-ui-modify"
    assert _kw["status"] is None and "IMPORT COMPLETE" in _kw["brief"]
    assert "queued" in out["message"]

    # EXTERNAL project → adoption brief + importer skill
    project.project_type = "external"
    project.app_runtime = "node"
    out = _run_action(LA.living_ui_import, {"source": "/tmp/foreign"})
    _pid, _kw = DISPATCHES[-1]
    assert _kw["workflow_skill"] == "living-ui-importer"
    assert "ADOPT EXTERNAL APP" in _kw["brief"] and "craftbot.json" in _kw["brief"]
    assert "adoption run has been queued" in out["message"]
    project.project_type = "native"

    async def _sdr_fail(pid, **kwargs):
        return None

    stub.start_development_run = _sdr_fail
    out = _run_action(LA.living_ui_import, {"source": "/tmp/whatever.zip"})
    assert "finish it yourself" in out["message"], "failed dispatch must fall back"
print("§15 living_ui_import action: OK")


# ── §16 foreign-source rendering (conversion evidence) ─────────────────────
def _make_foreign_app(base: Path) -> Path:
    src = base / "express-todo"
    (src / "routes").mkdir(parents=True)
    (src / "node_modules" / "junk").mkdir(parents=True)
    (src / "README.md").write_text("# Express Todo\nA todo list with boards.\n")
    (src / "package.json").write_text(
        '{"name": "express-todo", "dependencies": {"express": "^4"}}'
    )
    (src / "index.js").write_text("const app = require('express')();\n")
    (src / "routes" / "todos.js").write_text("router.post('/todos', createTodo)\n")
    (src / "node_modules" / "junk" / "big.js").write_text("x" * 100)
    (src / ".env").write_text("SECRET=hunter2\n")
    return src


with tempfile.TemporaryDirectory() as tmp:
    src = _make_foreign_app(Path(tmp))
    rendered = wizard_mod._render_source(src)
    assert "# Express Todo" in rendered, "README must lead the evidence"
    assert "routes/todos.js" in rendered and "createTodo" in rendered
    assert "hunter2" not in rendered, (
        ".env is not a route/model/readme — never rendered"
    )
    assert rendered.startswith("File tree:")
print("§16 foreign-source rendering: OK")


# ── §17 conversion (manager) — scaffold + ingest + synthesized spec ────────
with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    mgr = LivingUIManager(workspace_root=workspace)
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    src = _make_foreign_app(Path(tmp))

    class _ScaffoldStub:
        async def scaffold(
            self,
            name,
            description,
            parent_dir,
            port,
            project_id,
            auth_mode="none",
            folder=None,
            style=None,
        ):
            dest = Path(parent_dir) / (folder or f"x_{project_id}")
            (dest / "reference").mkdir(parents=True)
            (dest / "manifest.json").write_text(
                _json.dumps({"id": project_id, "livingUIVersion": 2, "port": port})
            )
            return types.SimpleNamespace(
                path=str(dest), id=project_id, slug="x", port=port
            )

        def ensure_available(self):
            pass

    mgr.runner.scaffold = _ScaffoldStub().scaffold

    _FAKE_DOC = (
        "# Express Todo — Requirements\n\n## Overview\nA todo app.\n\n## Features\n"
        + "The user can add a todo.\n" * 20
    )

    async def _fake_source_llm(system_prompt, user_prompt, prompt_name):
        assert "REBUILDING" in system_prompt and "Express Todo" in user_prompt
        return _FAKE_DOC

    _orig_llm = wizard_mod._llm
    wizard_mod._llm = _fake_source_llm
    try:
        project = asyncio.run(
            mgr.convert_foreign_source(str(src), description="keep the boards")
        )
    finally:
        wizard_mod._llm = _orig_llm

    dest = Path(project.path)
    assert (dest / "reference" / "source" / "README.md").exists()
    assert not (dest / "reference" / "source" / "node_modules").exists()
    assert not (dest / "reference" / "source" / ".env").exists(), "secrets never ingest"
    req_text = (dest / "reference" / "requirements.md").read_text()
    assert "The user can add a todo." in req_text
    assert "## Original source" in req_text and "reference/source/" in req_text
    assert host.delivered_at(project.id) is None, "a conversion is a pre-delivery BUILD"

    # A native Living UI source must be refused toward living_ui_import
    v2src = Path(tmp) / "v2app"
    v2src.mkdir()
    (v2src / "manifest.json").write_text(_json.dumps({"livingUIVersion": 2}))
    try:
        asyncio.run(mgr.convert_foreign_source(str(v2src)))
        raise AssertionError("Living UI source must be refused")
    except ValueError as e:
        assert "living_ui_import" in str(e)
print("§17 conversion (manager): OK")


# ── §18 living_ui_convert action dispatches the classic build ──────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "convact001", 3153)
    project = _Project("convact001", proj, 3153)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    stub = _wire(project, host)

    CONVERTS = []
    DISPATCHES2 = []

    async def _convert(source, name=None, description=""):
        CONVERTS.append((source, description))
        return project

    async def _sdr2(pid, **kwargs):
        DISPATCHES2.append((pid, kwargs))
        return "lui_convact001"

    stub.convert_foreign_source = _convert
    stub.start_development_run = _sdr2

    out = _run_action(
        LA.living_ui_convert,
        {"source": "https://github.com/a/b", "description": "keep the boards"},
    )
    assert out["status"] == "success" and CONVERTS[-1] == (
        "https://github.com/a/b",
        "keep the boards",
    )
    assert DISPATCHES2 and DISPATCHES2[-1][0] == "convact001"
    assert DISPATCHES2[-1][1] == {}, "conversion uses the CLASSIC build dispatch"
    assert "rebuild" in out["message"].lower()
print("§18 living_ui_convert action: OK")


# ── §19 external apps: run foreign sources AS-IS (EXTERNAL-APPS-PLAN A) ────
with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    mgr = LivingUIManager(workspace_root=workspace)
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    # runtime inference
    site = Path(tmp) / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>hello external</h1>")
    assert mgr.infer_app_runtime(site) == "static"
    nodeapp = Path(tmp) / "nodeapp"
    nodeapp.mkdir()
    (nodeapp / "package.json").write_text("{}")
    assert mgr.infer_app_runtime(nodeapp) == "node"
    assert mgr.infer_app_runtime(Path(tmp)) is None

    # foreign folder → EXTERNAL registration (not delivered, craftbot.json)
    project = asyncio.run(mgr.import_project_source(str(site), name="Ext Site"))
    assert project.project_type == "external" and project.app_runtime == "static"
    assert project.status == "stopped" and host.delivered_at(project.id) is None
    cfg = _json.loads((Path(project.path) / "craftbot.json").read_text())
    assert cfg["external"] is True and cfg["port"] == project.port
    assert cfg["pipeline"]["start"] == "", "adoption fills the verbs"
    _req19 = (Path(project.path) / "reference" / "requirements.md").read_text()
    assert "main screen" in _req19 and "NOT part of this verification" in _req19, (
        "adoption spec must scope verification to launchability"
    )
    assert "ADOPT EXTERNAL APP" in mgr.post_import_brief(project)

    # empty pipeline → adoption-needed error, not a crash
    res = asyncio.run(mgr.launch_and_verify(project.id))
    assert res["status"] == "error" and res["step"] == "adopt"
    assert "craftbot.json" in res["errors"][0]

    # write the verbs (what the adoption agent does) → real launch + health
    cfg["pipeline"]["start"] = "python3 -m http.server {{PORT}} --bind 127.0.0.1"
    (Path(project.path) / "craftbot.json").write_text(_json.dumps(cfg))
    res = asyncio.run(mgr.launch_and_verify(project.id))
    try:
        assert res["status"] == "success", res
        assert project.status == "running" and project.process is not None
        import urllib.request as _url

        body = (
            _url.urlopen(f"http://127.0.0.1:{project.port}/", timeout=5).read().decode()
        )
        assert "hello external" in body, "the ORIGINAL app must be serving"
        assert (Path(project.path) / "logs" / "app.log").exists()
        assert not (Path(project.path) / ".snapshots").exists(), (
            "externals never take a pb_data baseline"
        )
    finally:
        asyncio.run(mgr.stop_project(project.id))

    # open_dev refuses externals (changes run live)
    res = asyncio.run(mgr.open_dev(project.id))
    assert res["status"] == "error" and "no dev environment" in res["errors"][0]

    # broken start command → health failure with app.log evidence
    cfg["pipeline"]["start"] = "python3 -c 'import sys; sys.exit(3)'"
    (Path(project.path) / "craftbot.json").write_text(_json.dumps(cfg))
    res = asyncio.run(mgr.launch_and_verify(project.id))
    assert res["status"] == "error" and res["step"] == "health"
print("§19 external apps run as-is: OK")


# ── §20 EXTERNAL apps skip the dev env in the actions ──────────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "extact0001", 3154)
    project = _Project("extact0001", proj, 3154)
    project.project_type = "external"
    project.app_runtime = "static"
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    stub = _wire(project, host)

    EVENTS.clear()
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "extact0001"})
    assert out["status"] == "success"
    assert "launch_and_verify" in EVENTS and "open_dev" not in EVENTS, (
        "externals must relaunch LIVE, never open a dev env"
    )
    assert "EXTERNAL app runs live" in out["message"]

    # walk_verify: no dev-env requirement; a clean verdict promotes
    # (bookkeeping only for externals — the new code already runs live)
    EVENTS.clear()
    WALK["report"] = {
        "kind": "pass",
        "passed": ["serves"],
        "defects": [],
        "raw": "VERDICT: PASS",
    }
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "extact0001"})
    assert out["status"] == "success", out
    assert "promote" in EVENTS, "external clean verdict still promotes (bookkeeping)"
print("§20 external action branches: OK")


# ── §21 surrender loops are capped by the machine (chili3d incident) ───────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "loopcap001", 3155)
    project = _Project("loopcap001", proj, 3155)

    class _MgrLoop:
        def get_project(self, pid):
            return project if pid == "loopcap001" else None

    living_ui_mod.get_living_ui_manager = lambda: _MgrLoop()
    host_mod._HOST = None
    host_mod._REDISPATCH_MIN_INTERVAL_S = 0
    host = host_mod.get_factory_host()
    RESUMES = []
    host._emit_mission = lambda p, b, mission_kind, machine: RESUMES.append(
        mission_kind
    )
    CHAT21 = []
    host._emit_chat = lambda pid, text: CHAT21.append(text)

    machine = host.machine_for("loopcap001")
    assert machine.state == "building" and not machine.terminal

    # An agent that keeps surrendering: 5 run-ends with no progress.
    for _ in range(5):
        host.on_run_end("loopcap001", {})

    assert RESUMES.count("resume") == 2, (
        f"surrender must cap after the fingerprint limit, got {RESUMES}"
    )
    assert machine.terminal and machine.state == "stuck"
    assert CHAT21 and "could not be completed" in CHAT21[-1], (
        "the cap must produce an honest machine-composed stuck report"
    )
print("§21 surrender-loop cap: OK")


# ── §22 CraftBot version provenance ────────────────────────────────────────
_CB_V = get_app_version()
assert _CB_V and _CB_V != "0.0.0"

with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    mgr = LivingUIManager(workspace_root=workspace)
    mgr.runner.kit_sync = _StubRunner().kit_sync
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None

    # Import: registry stamped with the ACQUIRING version; manifest keeps
    # the original creator's version when the export carried one.
    src_dir = Path(tmp) / "exported22"
    _make_project_dir(Path(tmp), "prov220001", 3156)
    (Path(tmp) / "app_prov220001").rename(src_dir)
    _mf = _json.loads((src_dir / "manifest.json").read_text())
    _mf["craftbotVersion"] = "0.9.9"  # the original creator
    (src_dir / "manifest.json").write_text(_json.dumps(_mf))
    # donor lifecycle state must NOT travel with an import (a fresh sidecar
    # IS created by the import's own stamp_delivered — check donor CONTENT)
    (src_dir / ".factory").mkdir()
    (src_dir / ".factory" / "host.json").write_text(
        '{"delivered": true, "donor_marker": 1}'
    )
    (src_dir / ".factory" / "state.json").write_text('{"state": "stuck"}')

    project = asyncio.run(mgr.import_project_source(str(src_dir)))
    assert project.craftbot_version == _CB_V, "registry records the acquirer"
    _mf2 = _json.loads((Path(project.path) / "manifest.json").read_text())
    assert _mf2["craftbotVersion"] == "0.9.9", "manifest keeps the creator"
    _side = _json.loads((Path(project.path) / ".factory" / "host.json").read_text())
    assert "donor_marker" not in _side, "donor lifecycle state must not travel"
    assert not (Path(project.path) / ".factory" / "state.json").exists(), (
        "donor machine state must not travel"
    )
    assert project.to_dict()["craftbotVersion"] == _CB_V

    # manifest WITHOUT a version (older export) → stamped with the acquirer
    _mf.pop("craftbotVersion")
    (src_dir / "manifest.json").write_text(_json.dumps(_mf))
    project2 = asyncio.run(mgr.import_project_source(str(src_dir)))
    _mf3 = _json.loads((Path(project2.path) / "manifest.json").read_text())
    assert _mf3["craftbotVersion"] == _CB_V

    # external registration stamps craftbot.json + registry
    site = Path(tmp) / "site22"
    site.mkdir()
    (site / "index.html").write_text("<h1>x</h1>")
    ext = asyncio.run(mgr.import_project_source(str(site)))
    _cfg = _json.loads((Path(ext.path) / "craftbot.json").read_text())
    assert _cfg["craftbotVersion"] == _CB_V and ext.craftbot_version == _CB_V

    # persistence round-trip (the 3-site trap)
    mgr2 = LivingUIManager(workspace_root=workspace)
    assert mgr2.projects[project.id].craftbot_version == _CB_V
print("§22 craftbot version provenance: OK")


# ── §23 superuser upsert failure FAILS the launch (no installer popup) ─────
with tempfile.TemporaryDirectory() as tmp:
    runner23 = LivingUIRunner(Path(tmp))
    proj23 = Path(tmp) / "proj"
    proj23.mkdir()

    async def _fake_pb_binary():
        return Path("/usr/bin/false")

    async def _fake_run(cmd, timeout, cwd=None):
        return (1, "token=SECRET should never leak; some upsert error")

    runner23.pb_binary = _fake_pb_binary
    runner23._run = _fake_run
    try:
        asyncio.run(runner23.ensure_superuser(proj23))
        raise AssertionError("failed upsert must refuse to serve")
    except RuntimeError as e:
        assert "refusing to serve" in str(e) and "installer" in str(e)
print("§23 superuser fail-closed: OK")


# ── §24 thrash-guard suppression must NOT lose the wakeup (stale build) ────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "wakeup0001", 3157)
    project = _Project("wakeup0001", proj, 3157)

    class _MgrWake:
        def get_project(self, pid):
            return project if pid == "wakeup0001" else None

    living_ui_mod.get_living_ui_manager = lambda: _MgrWake()
    host_mod._HOST = None
    host_mod._REDISPATCH_MIN_INTERVAL_S = 2  # shrink the guard for the test
    host = host_mod.get_factory_host()
    WAKE_DISPATCHES = []
    host._emit_mission = lambda p, b, mission_kind, machine: WAKE_DISPATCHES.append(
        mission_kind
    )
    host._emit_chat = lambda pid, text: None

    async def _scenario():
        machine = host.machine_for("wakeup0001")
        # A run just ended and advanced the machine (fresh history entry),
        # then a 5s surrender ends another run — the guard trips.
        machine.advance(host_mod.Outcome("building", ok=True))  # fresh timestamp
        host.on_run_end("wakeup0001", {})  # guard trips → must DEFER, not drop
        assert WAKE_DISPATCHES == [], "guard should suppress the immediate dispatch"
        # The deferred re-check must fire on its own after the interval.
        await asyncio.sleep(3.5)
        assert WAKE_DISPATCHES, "the deferred wakeup was LOST — stale build bug"

    asyncio.run(_scenario())
    host_mod._REDISPATCH_MIN_INTERVAL_S = 20
print("§24 deferred redispatch wakeup: OK")

print("\nData-safety acceptance: ALL GREEN")
