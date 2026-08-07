# -*- coding: utf-8 -*-
"""Phase 1 acceptance (FACTORY-PLAN §5 Phase 1): the CraftBot host adapter
drives the machine — fresh missions on defects, redispatch on surrender,
honest stuck at caps, announce only from the machine.

Runs with a STUBBED manager (no CraftBot runtime):
    python3 -m app.factory.test_phase1
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import app.factory.host_craftbot as host_mod
import app.living_ui as living_ui_mod
from app.factory.host_craftbot import FactoryHost

host_mod._REDISPATCH_MIN_INTERVAL_S = 0  # test: no thrash-guard waits

DISPATCHED = []  # captured TriggerSpecs
CHAT = []  # captured machine-composed chat lines


class _Session:
    id = "lui_test"


class _TriggerService:
    async def emit(self, spec):
        DISPATCHED.append(spec)


class _Project:
    def __init__(self, path):
        self.id = "testproj"
        self.name = "Test App"
        self.path = str(path)


class _Manager:
    def __init__(self, path):
        self._p = _Project(path)
        self._trigger_service = _TriggerService()

    def get_project(self, pid):
        return self._p if pid == "testproj" else None

    def ensure_project_session(self, project):
        return _Session()


def make_host(tmp) -> FactoryHost:
    living_ui_mod.get_living_ui_manager = lambda: _Manager(tmp)  # monkeypatch
    host = FactoryHost()
    host._emit_chat = lambda pid, text: CHAT.append(text)  # capture announcements
    return host


# ── defects → fresh mission with evidence; repeats → escalation → stuck ─────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.report_launch_success("testproj")
    d = host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 502 on /api/ops/x"],
        details="VERDICT: FAIL\n502 evidence line",
    )
    assert d is not None and d.next_state == "fixing"
    assert len(DISPATCHED) == 1, "first defect round must dispatch a fresh fix mission"
    assert "FIX MISSION" in DISPATCHED[0].description
    assert "DEFECT" in DISPATCHED[0].description  # card format (Phase 2)
    assert "502 on /api/ops/x" in DISPATCHED[0].description  # observed value travels
    assert DISPATCHED[0].payload["factory_mission_id"].startswith("fix-")

    d = host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 502 on /api/ops/x"],
        details="VERDICT: FAIL\n502 evidence line",
    )
    assert d.escalate and len(DISPATCHED) == 2
    assert "REPEATED" in DISPATCHED[1].description  # escalated brief

    d = host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 502 on /api/ops/x"],
        details="VERDICT: FAIL\n502 evidence line",
    )
    assert d.next_state == "stuck" and len(DISPATCHED) == 2  # cap: no 3rd mission
    assert CHAT and "could not be completed" in CHAT[-1]  # machine-composed stuck
print("defects → mission → escalate → honest stuck: OK")

# ── surrender → redispatch (I6 closed at the host level) ────────────────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    machine = host.machine_for("testproj")
    # Simulate: build run ends mid-work (machine exists, non-terminal, no mission)
    host.on_run_end("testproj", {})
    assert len(DISPATCHED) == 1, "surrendered run must redispatch"
    assert "CONTINUE BUILD" in DISPATCHED[0].description
    mission_id = DISPATCHED[0].payload["factory_mission_id"]
    # That mission's run ends without finishing either → redispatch again
    host.on_run_end("testproj", {"factory_mission_id": mission_id})
    assert len(DISPATCHED) == 2
print("surrender → auto-redispatch: OK")

# ── pass verdict → machine announces; done = no more redispatch ─────────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.report_launch_success("testproj")
    d = host.report_verify(
        "testproj",
        "pass",
        url="http://127.0.0.1:3100",
        verified=["feature a", "feature b"],
        caveat="",
    )
    assert d.next_state == "done"
    assert (
        CHAT
        and "ready at http://127.0.0.1:3100" in CHAT[-1]
        and "2 feature" in CHAT[-1]
    )
    host.on_run_end("testproj", {})
    assert DISPATCHED == [], "done build must never redispatch"
print("machine-composed ready + terminal stability: OK")

# ── unparseable verdict: retry once, then stuck — never announce ────────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.report_launch_success("testproj")
    d = host.report_verify("testproj", "unparseable")
    assert d.payload.get("redo") == "verify" and CHAT == []
    d = host.report_verify("testproj", "unparseable")
    assert d.next_state == "stuck"
    assert CHAT and "could not be completed" in CHAT[-1]
    assert all("ready at" not in c for c in CHAT)  # NEVER announced ready
print("unparseable verdicts fail closed: OK")


# ── surrender via CONTINUATION trigger (no mission id in final payload) ─────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    machine = host.machine_for("testproj")
    host.on_run_end("testproj", {})  # dispatch resume-1
    assert len(DISPATCHED) == 1
    mission_id = DISPATCHED[0].payload["factory_mission_id"]
    host.mission_run_started("testproj", mission_id)  # its run began
    # ...run ends on a run_continuation trigger: payload has NO mission id
    host.on_run_end("testproj", {})
    assert len(DISPATCHED) == 2, "continuation-ended surrender must still redispatch"
    # But a QUEUED (never-started) mission must NOT be clobbered:
    queued_id = DISPATCHED[1].payload["factory_mission_id"]
    host.on_run_end("testproj", {})  # e.g. stray old run ends
    assert len(DISPATCHED) == 2, (
        "queued mission must not be cleared by an unrelated run-end"
    )
print("continuation-trigger surrender + queued-mission safety: OK")

print("\nPhase 1 acceptance: ALL GREEN")
