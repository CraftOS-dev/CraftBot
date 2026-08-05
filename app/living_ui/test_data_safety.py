"""Data-safety acceptance: baseline restore (build era) + staging copies
(modify era) keep agent/verifier test junk out of the production DB.

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
from app.living_ui.staging import STAGING_PORT_RANGE, StagingSupervisor
from app.living_ui.v2_runner import V2Runner
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


# ── §3 StagingSupervisor ───────────────────────────────────────────────────


class _StubRunner:
    def __init__(self):
        self.kit_synced = []

    async def kit_sync(self, project_dir):
        self.kit_synced.append(Path(project_dir))


with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "stage0001", 3125)
    project = _Project("stage0001", proj, 3125)
    runner = _StubRunner()
    sup = StagingSupervisor(living, runner)

    inst = asyncio.run(sup.create_copy(project))
    sdir = inst.dir
    assert sdir == living / "_staging" / "project" / "stage0001"
    assert STAGING_PORT_RANGE[0] <= inst.port <= STAGING_PORT_RANGE[1]
    manifest = _json.loads((sdir / "manifest.json").read_text())
    assert manifest["port"] == inst.port, "manifest.port must be rewritten"
    assert str(inst.port) in manifest["pipeline"]["start"], "pipeline keeps port inline"
    assert "3125" not in manifest["pipeline"]["start"], "old port must be gone"
    assert runner.kit_synced == [sdir], "hash canon must be re-recorded after rewrite"
    assert not (sdir / "pb" / "pb_public").exists(), (
        "gate rebuilds pb_public — never copy"
    )
    assert (sdir / "frontend" / "node_modules" / "somepkg").exists(), (
        "node_modules rides along"
    )
    assert (sdir / ".superuser").exists() and (sdir / ".lui").exists()

    # DB isolation: staging writes never reach the original.
    assert _count(sdir / "pb" / "pb_data" / "data.db") == 2
    _mkdb(sdir / "pb" / "pb_data" / "data.db", rows=9)
    assert _count(proj / "pb" / "pb_data" / "data.db") == 2, "original DB polluted!"

    # sync_code: refreshes agent-owned paths, keeps staging pb_data + manifest.
    (proj / "frontend" / "src" / "App.tsx").write_text("export const A = 2\n")
    (proj / "frontend" / "package.json").write_text(
        '{"name": "app", "dependencies": {"x": "1.0.0"}}'
    )
    sup.sync_code(project, sdir)
    assert "A = 2" in (sdir / "frontend" / "src" / "App.tsx").read_text()
    assert not (sdir / "frontend" / "node_modules").exists(), (
        "changed package.json must clear node_modules so install runs"
    )
    assert _count(sdir / "pb" / "pb_data" / "data.db") == 11, (
        "sync_code must not touch staging data"
    )
    assert _json.loads((sdir / "manifest.json").read_text())["port"] == inst.port

    # guarded rmtree refuses anything outside _staging
    try:
        sup._guarded_rmtree(proj)
        raise AssertionError("guarded rmtree left the staging root!")
    except ValueError:
        pass

    # destroy + reap
    sup.destroy("stage0001", inst.to_record())
    assert not sdir.exists()
    leftover = living / "_staging" / "project" / "leftover99"
    leftover.mkdir(parents=True)
    reaped = sup.reap_all({"gone12345": {"dir": str(leftover), "pid": 99999999}})
    assert reaped >= 1 and not leftover.exists()
print("§3 StagingSupervisor: OK")


# ── §4 FactoryHost delivery helpers ────────────────────────────────────────

with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "sidecar01", 3126)
    project = _Project("sidecar01", proj, 3126)

    class _MgrOne:
        def get_project(self, pid):
            return project if pid == "sidecar01" else None

    living_ui_mod.get_living_ui_manager = lambda: _MgrOne()
    host = host_mod.FactoryHost()
    assert host.is_delivered("sidecar01") is False
    host.mark_delivered("sidecar01")
    assert host.is_delivered("sidecar01") is True
    assert host.get_staging_record("sidecar01") is None
    host.set_staging_record("sidecar01", {"url": "http://127.0.0.1:3901", "port": 3901})
    assert host.get_staging_record("sidecar01")["port"] == 3901
    # delivered flag survives alongside the staging record
    side = _json.loads((proj / ".factory" / "host.json").read_text())
    assert side["delivered"] is True and side["staging"]["port"] == 3901
    host.clear_staging_record("sidecar01")
    assert host.get_staging_record("sidecar01") is None
    assert host.is_delivered("sidecar01") is True
print("§4 FactoryHost delivery helpers: OK")


# ── §5 manager.launch_staging / finalize_modify / finalize_first_delivery ──

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
    mgr.staging.v2_runner = _StubRunner()  # no node in tests

    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None  # fresh singleton bound to this manager
    host = host_mod.get_factory_host()
    host.mark_delivered("mgrtest01")

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

    result = asyncio.run(mgr.launch_staging("mgrtest01"))
    assert result["status"] == "success" and result.get("staging") is True
    record = host.get_staging_record("mgrtest01")
    assert record and record["pid"] == 4242
    sdir = Path(record["dir"])
    assert sdir.exists() and PIPELINE_RUNS[-1][0] == sdir, (
        "pipeline must target the COPY"
    )
    assert PIPELINE_RUNS[-1][1] == record["port"] != 3127

    # flip: relaunch real app, then destroy staging + record
    FLIPPED = []

    async def _fake_launch_and_verify(pid):
        FLIPPED.append(pid)
        return {"status": "success", "url": "http://127.0.0.1:3127", "port": 3127}

    mgr.launch_and_verify = _fake_launch_and_verify
    flip = asyncio.run(mgr.finalize_modify("mgrtest01"))
    assert flip["status"] == "success" and FLIPPED == ["mgrtest01"]
    assert not sdir.exists(), "flip must destroy the staging copy"
    assert host.get_staging_record("mgrtest01") is None

    # failed flip keeps the copy and the record
    result = asyncio.run(mgr.launch_staging("mgrtest01"))
    sdir = Path(host.get_staging_record("mgrtest01")["dir"])

    async def _failing_launch(pid):
        return {"status": "error", "step": "health", "errors": ["boom"]}

    mgr.launch_and_verify = _failing_launch
    flip = asyncio.run(mgr.finalize_modify("mgrtest01"))
    assert flip["status"] == "error"
    assert sdir.exists() and host.get_staging_record("mgrtest01") is not None

    # finalize_first_delivery: junk after baseline → restored before announce
    proj2_dir = _make_project_dir(living, "firstdel01", 3128)
    project2 = LivingUIProject(
        id="firstdel01",
        name="firstdel01",
        description="t",
        path=str(proj2_dir),
        status="running",
        port=3128,
    )
    project2.bridge_token = "tok"
    mgr.projects["firstdel01"] = project2
    snapshot_pb_data(
        proj2_dir / "pb" / "pb_data", proj2_dir / ".snapshots" / "baseline", living
    )
    _mkdb(proj2_dir / "pb" / "pb_data" / "data.db", rows=6)  # verifier junk

    async def _fake_start(project_dir, port, bridge_token=""):
        return _FakeProc()

    async def _fake_healthy(port, timeout=None):
        return True

    mgr.v2_runner.start = _fake_start
    mgr.v2_runner.wait_healthy = _fake_healthy
    fin = asyncio.run(mgr.finalize_first_delivery("firstdel01"))
    assert fin["status"] == "success" and fin["restored"] is True
    assert _count(proj2_dir / "pb" / "pb_data" / "data.db") == 2, (
        "junk survived delivery!"
    )
    assert project2.status == "running"

    # no baseline → deliver as-is, never guess-wipe
    proj3_dir = _make_project_dir(living, "legacy0001", 3129)
    project3 = LivingUIProject(
        id="legacy0001",
        name="legacy0001",
        description="t",
        path=str(proj3_dir),
        status="running",
        port=3129,
    )
    mgr.projects["legacy0001"] = project3
    fin = asyncio.run(mgr.finalize_first_delivery("legacy0001"))
    assert fin["status"] == "success" and fin["restored"] is False
    assert _count(proj3_dir / "pb" / "pb_data" / "data.db") == 2
print("§5 manager staging/finalize: OK")


# ── §6-8 action branching (bare-exec, like the real executor) ──────────────

EVENTS = []
WALK = {"report": None, "base_url": None, "project_path": None}


class _StubMgr:
    def __init__(self, project):
        self._p = project

    def get_project(self, pid):
        return self._p if pid == self._p.id else None

    async def launch_and_verify(self, pid):
        EVENTS.append("launch_and_verify")
        return {"status": "success", "url": self._p.url, "port": self._p.port}

    async def launch_staging(self, pid):
        EVENTS.append("launch_staging")
        return {
            "status": "success",
            "url": "http://127.0.0.1:3901",
            "port": 3901,
            "staging": True,
        }

    async def stop_project(self, pid):
        EVENTS.append("stop_project")
        return True

    async def finalize_first_delivery(self, pid):
        EVENTS.append("finalize_first_delivery")
        return {"status": "success", "restored": True}

    async def finalize_modify(self, pid):
        EVENTS.append("finalize_modify")
        return {"status": "success"}


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

    # §6a build mode, clean verdict: finalize + mark_delivered BEFORE announce
    proj = _make_project_dir(living, "actbuild01", 3131)
    project = _Project("actbuild01", proj, 3131)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    _wire(project, host)
    EVENTS.clear()
    WALK["report"] = {
        "kind": "pass",
        "passed": ["feature one"],
        "defects": [],
        "raw": "VERDICT: PASS",
    }
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "actbuild01"})
    assert out["status"] == "success", out
    assert WALK["base_url"] == "http://127.0.0.1:3131" and WALK["project_path"] is None
    fin_i = EVENTS.index("finalize_first_delivery")
    ready_i = next(
        i
        for i, e in enumerate(EVENTS)
        if isinstance(e, tuple) and e[0] == "broadcast_ready"
    )
    assert fin_i < ready_i, "restore must precede the delivery announce"
    assert host.is_delivered("actbuild01") is True
    print("§6a build clean → finalize→mark→announce: OK")

    # §6b delivered but no staging: walk refuses, notify_ready boots staging
    proj = _make_project_dir(living, "actnostg01", 3132)
    project = _Project("actnostg01", proj, 3132)
    stub = _wire(project, host)
    host.mark_delivered("actnostg01")
    EVENTS.clear()
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "actnostg01"})
    assert out["status"] == "error" and "staging" in out["message"], out
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "actnostg01"})
    assert out["status"] == "success" and "launch_staging" in EVENTS
    assert "launch_and_verify" not in EVENTS
    assert "STAGING" in out["message"]
    print("§6b delivered gating: OK")

    # §6c staging defects: live app NOT stopped; staging log quoted
    sdir = living / "_staging" / "project" / "actnostg01"
    (sdir / "logs").mkdir(parents=True)
    (sdir / "logs" / "pocketbase.log").write_text(
        "ERROR hook exploded: staging-only-line\n"
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
    assert "stop_project" not in EVENTS, "modify defects must not stop the live app"
    assert "previous working version" in out["message"]
    assert WALK["base_url"] == "http://127.0.0.1:3905", "verifier must drive the COPY"
    assert WALK["project_path"] == str(sdir)
    assert "staging-only-line" in captured.get("server_log", ""), (
        "evidence must come from the staging log"
    )
    print("§6c staging defects: OK")

    # §6d staging clean: flip before announce; flip failure blocks announce
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
    flip_i = EVENTS.index("finalize_modify")
    ready_i = next(
        i
        for i, e in enumerate(EVENTS)
        if isinstance(e, tuple) and e[0] == "broadcast_ready"
    )
    assert flip_i < ready_i, "deploy must precede the announce"
    assert EVENTS[ready_i][1] == "http://127.0.0.1:3132", (
        "announce must carry the REAL url"
    )

    class _FlipFailMgr(_StubMgr):
        async def finalize_modify(self, pid):
            EVENTS.append("finalize_modify")
            return {
                "status": "error",
                "step": "health",
                "errors": ["real app did not boot"],
            }

    living_ui_mod.get_living_ui_manager = lambda: _FlipFailMgr(project)
    EVENTS.clear()
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "actnostg01"})
    assert out["status"] == "error" and "deploy" in out["message"].lower()
    assert not any(
        isinstance(e, tuple) and e[0] == "broadcast_ready" for e in EVENTS
    ), "a failed deploy must never announce"
    print("§6d staging clean/flip: OK")

    # §7 build mode notify_ready unchanged
    proj = _make_project_dir(living, "actnr0001", 3133)
    project = _Project("actnr0001", proj, 3133)
    _wire(project, host)
    EVENTS.clear()
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "actnr0001"})
    assert out["status"] == "success" and "launch_and_verify" in EVENTS
    assert "STAGING" not in out["message"]
    print("§7 notify_ready build mode: OK")

    # §8 living_ui_http: staging redirect, no iframe reload, write refusal
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

        # not delivered → real app + data_changed dispatch
        EVENTS.clear()
        out = _run_action(
            LA.living_ui_http,
            {"project_id": "acthttp01", "method": "POST", "path": "/api/x", "json": {}},
        )
        assert out["status"] == "success" and HTTP[-1][1].startswith(
            "http://127.0.0.1:3134"
        )
        assert "data_changed" in EVENTS

        # delivered, no staging → writes refused, reads allowed
        host.mark_delivered("acthttp01")
        out = _run_action(
            LA.living_ui_http,
            {"project_id": "acthttp01", "method": "POST", "path": "/api/x", "json": {}},
        )
        assert out["status"] == "error" and "staging" in out["message"], out
        out = _run_action(
            LA.living_ui_http,
            {"project_id": "acthttp01", "method": "GET", "path": "/api/x"},
        )
        assert out["status"] == "success"

        # delivered + staging → redirected, and NO iframe reload
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
            "staging writes must not reload the user's iframe"
        )
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

    # c) delivered session project holding the SAME app → idempotent no-op
    # (the crash-resume path: redispatched "continue build" must not mint a
    # duplicate)
    host.mark_delivered("adopt0001")
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
    mgr.staging.v2_runner = _StubRunner()

    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    host.mark_delivered("modarc001")
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

    # First modify: staging up → machine re-armed into MODIFYING, gen 1
    result = asyncio.run(mgr.launch_staging("modarc001"))
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

    # Fix mission re-enters launch_staging → begin_modify no-ops mid-arc
    result = asyncio.run(mgr.launch_staging("modarc001"))
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
    result = asyncio.run(mgr.launch_staging("modarc001"))
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
    host.mark_delivered("specbelt01")
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
    mgr.v2_runner.kit_sync = _StubRunner().kit_sync
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
    assert host.is_delivered(project.id), "imports are delivered on arrival"
    assert (src_dir / ".superuser").exists(), "the source folder is never modified"

    # zip import through the same core
    import zipfile as _zipfile

    zip_path = Path(tmp) / "export.zip"
    with _zipfile.ZipFile(zip_path, "w") as zf:
        for f in src_dir.rglob("*"):
            if f.is_file() and ".git" not in f.parts and "node_modules" not in f.parts:
                zf.write(f, Path("exported_app") / f.relative_to(src_dir))
    project2 = asyncio.run(mgr.import_project_source(str(zip_path)))
    assert project2.id != project.id and host.is_delivered(project2.id)

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
    assert host.is_delivered(project3.id)
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

    mgr.v2_runner.scaffold = _ScaffoldStub().scaffold

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
    assert not host.is_delivered(project.id), "a conversion is a pre-delivery BUILD"

    # A V2 source must be refused toward living_ui_import
    v2src = Path(tmp) / "v2app"
    v2src.mkdir()
    (v2src / "manifest.json").write_text(_json.dumps({"livingUIVersion": 2}))
    try:
        asyncio.run(mgr.convert_foreign_source(str(v2src)))
        raise AssertionError("V2 source must be refused")
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
    assert project.status == "stopped" and not host.is_delivered(project.id)
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

    # launch_staging refuses externals (changes run live)
    host.mark_delivered(project.id)
    res = asyncio.run(mgr.launch_staging(project.id))
    assert res["status"] == "error" and "no staging" in res["errors"][0]

    # broken start command → health failure with app.log evidence
    cfg["pipeline"]["start"] = "python3 -c 'import sys; sys.exit(3)'"
    (Path(project.path) / "craftbot.json").write_text(_json.dumps(cfg))
    res = asyncio.run(mgr.launch_and_verify(project.id))
    assert res["status"] == "error" and res["step"] == "health"
print("§19 external apps run as-is: OK")


# ── §20 delivered EXTERNAL app skips staging in the actions ────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    proj = _make_project_dir(living, "extact0001", 3154)
    project = _Project("extact0001", proj, 3154)
    project.project_type = "external"
    project.app_runtime = "static"
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    stub = _wire(project, host)
    host.mark_delivered("extact0001")

    EVENTS.clear()
    out = _run_action(LA.living_ui_notify_ready, {"project_id": "extact0001"})
    assert out["status"] == "success"
    assert "launch_and_verify" in EVENTS and "launch_staging" not in EVENTS, (
        "delivered externals must relaunch LIVE, never stage"
    )
    assert "EXTERNAL app runs live" in out["message"]

    # walk_verify: no staging requirement; build-mode branches apply
    EVENTS.clear()
    WALK["report"] = {
        "kind": "pass",
        "passed": ["serves"],
        "defects": [],
        "raw": "VERDICT: PASS",
    }
    out = _run_action(LA.living_ui_walk_verify, {"project_id": "extact0001"})
    assert out["status"] == "success", out
    assert "finalize_first_delivery" in EVENTS, (
        "external clean verdict follows the (no-op-safe) build finalize"
    )
    assert "finalize_modify" not in EVENTS
print("§20 delivered external action branches: OK")


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
    mgr.v2_runner.kit_sync = _StubRunner().kit_sync
    living_ui_mod.get_living_ui_manager = lambda: mgr
    host_mod._HOST = None

    # V2 import: registry stamped with the ACQUIRING version; manifest keeps
    # the original creator's version when the export carried one.
    src_dir = Path(tmp) / "exported22"
    _make_project_dir(Path(tmp), "prov220001", 3156)
    (Path(tmp) / "app_prov220001").rename(src_dir)
    _mf = _json.loads((src_dir / "manifest.json").read_text())
    _mf["craftbotVersion"] = "0.9.9"  # the original creator
    (src_dir / "manifest.json").write_text(_json.dumps(_mf))
    # donor lifecycle state must NOT travel with an import (a fresh sidecar
    # IS created by the import's own mark_delivered — check donor CONTENT)
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
    runner23 = V2Runner(Path(tmp))
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

print("\nData-safety acceptance: ALL GREEN")
