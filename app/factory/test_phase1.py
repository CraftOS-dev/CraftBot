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
import app.agent_app as agent_app_mod
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
    agent_app_mod.get_agent_app_manager = lambda: _Manager(tmp)  # monkeypatch
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

    assert "ATTEMPT LOG" not in DISPATCHED[0].description, (
        "a first round has no history; it must not read like a retry"
    )

    # Round 2, byte-identical cause. The log SAYS that and stops: what to do
    # about it is the agent's call, not a line the machine writes from a hash.
    d = host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 502 on /api/ops/x"],
        details="VERDICT: FAIL\n502 evidence line",
    )
    assert d.escalate and len(DISPATCHED) == 2
    brief = DISPATCHED[1].description
    assert "ATTEMPT LOG" in brief and "cause identical: verify.refresh" in brief
    for imperative in ("do something DIFFERENT", "DIAGNOSIS", "Stop fixing"):
        assert imperative not in brief, (
            f"the log reports, it does not instruct: found {imperative!r}"
        )

    # Round 3 on the same failure keeps working — repetition is not a verdict.
    d = host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 502 on /api/ops/x"],
        details="VERDICT: FAIL\n502 evidence line",
    )
    assert d.next_state == "fixing" and len(DISPATCHED) == 3, (
        "a third identical failure must not end the build"
    )
    assert not CHAT, "nothing is announced to the user while work continues"

    # A cause that MOVES on the same route is progress, and reads as progress.
    d = host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 401 unauthorized on /api/ops/x"],
        details="VERDICT: FAIL\n401 evidence line",
    )
    assert len(DISPATCHED) == 4
    assert "cause changed: verify.refresh" in DISPATCHED[3].description

    # What an agent proved innocent survives into every later brief.
    host.record_ruled_out("testproj", ["not the grant - dry run returns 200"])
    host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 401 unauthorized on /api/ops/x"],
        details="VERDICT: FAIL\n401 evidence line",
    )
    assert "RULED OUT BY EARLIER ROUNDS" in DISPATCHED[4].description
    assert "not the grant" in DISPATCHED[4].description
print("defects → mission → attempt log → work that keeps going: OK")

# ── the shape the whole redesign exists for: clearing gates one per round ───
# Live 2026-09-01: a Gmail status check failed three rounds on three different
# causes — one grant, then another grant, then the irreversible confirmation.
# Every round fixed something real and the build still ran out of road. A
# streak is invisible from inside one round, so the log MEASURES it. What it
# means — "read every precondition at once instead of one per round" — is the
# agent's inference to draw, and deliberately not a sentence the machine
# writes.
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.report_launch_success("testproj")
    for observed in (
        "403 create_gmail_draft not in capabilities.actions on /api/ops/integrations/status",
        "403 send_gmail not in capabilities.actions on /api/ops/integrations/status",
        "400 send_gmail requires confirm_irreversible on /api/ops/integrations/status",
    ):
        host.report_verify(
            "testproj",
            "defects",
            defects=[f"- Gmail status — FAIL — {observed}"],
            details=f"VERDICT: FAIL\n{observed}",
        )
    assert len(DISPATCHED) == 3, "three real causes are three rounds of progress"
    final = DISPATCHED[-1].description
    assert "3 rounds, a different cause each round" in final, final[:600]
    assert "/api/ops/integrations/status" in final  # measured, and where
    assert "cause changed: verify.gmail-status" in final
print("gate-clearing streak is measured, not interpreted: OK")

# ── the agent raises its hand instead of grinding ───────────────────────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.report_launch_success("testproj")
    d = host.report_blocked(
        "testproj",
        "Which calendar should new bookings write to?",
        ruled_out=["the API works - verified with the CLI"],
    )
    assert d.next_state == "blocked"
    assert CHAT and "Which calendar" in CHAT[-1]
    assert "could not be completed" not in CHAT[-1], "a question is not a failure"
    assert "the API works" in CHAT[-1], "what was established goes with the question"
    host.on_run_end("testproj", {})
    assert DISPATCHED == [], "a blocked build waits for the user, it does not retry"
    assert host.report_blocked("testproj", "another question?") is None, (
        "a terminal build has nothing in flight to pause"
    )
    assert len(CHAT) == 1, "and it must not announce a second time"
print("blocked: question to the user, no redispatch: OK")

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

# ── but a surrender LOOP still caps (chili3d, 2026-08-05: 37 in ~4 min) ─────
# The per-failure cap is gone; this one is not. Ending five runs without ever
# producing a verdict is not five attempts at the bug, it is an empty loop.
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    machine = host.machine_for("testproj")
    for _ in range(5):
        # Each resumed run ends the same way it began: nothing done, no
        # verdict. The mission id is what makes the next run-end count.
        last = DISPATCHED[-1].payload["factory_mission_id"] if DISPATCHED else None
        host.on_run_end("testproj", {"factory_mission_id": last} if last else {})
    assert len(DISPATCHED) == 2, f"stall cap 3 → 2 resumes, got {len(DISPATCHED)}"
    assert machine.terminal and machine.state == "stuck"
    assert CHAT and "could not be completed" in CHAT[-1]
print("surrender loop still caps: OK")

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
