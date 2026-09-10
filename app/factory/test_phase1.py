# -*- coding: utf-8 -*-
"""Host acceptance: the CraftBot adapter drives the Arc — fix missions on
defects, ONE supervisor loop for every dormancy case, honest stuck at caps,
announce only from the record.

Runs with a STUBBED manager (no CraftBot runtime):
    python3 -m app.factory.test_phase1
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import app.agent_app as agent_app_mod
from app.factory.engine import ARC_BUILD, ARC_MODIFY, STALLS_CAP
from app.factory.host_craftbot import FactoryHost

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
        self.session_id = "lui_test"


class _Manager:
    def __init__(self, path):
        self._p = _Project(path)
        self._trigger_service = _TriggerService()
        self.projects = {"testproj": self._p}

    def get_project(self, pid):
        return self._p if pid == "testproj" else None

    def ensure_project_session(self, project):
        return _Session()


def make_host(tmp) -> FactoryHost:
    agent_app_mod.get_agent_app_manager = lambda: _Manager(tmp)  # monkeypatch
    host = FactoryHost()
    host._emit_chat = lambda pid, text: CHAT.append(text)  # capture announcements
    return host


def age(host, pid="testproj", seconds=3600.0):
    """Backdate the arc's activity so the supervisor's backoff passes."""
    arc = host.arc_for(pid)
    arc._d["last_activity_at"] = arc.last_activity_at - seconds
    arc.save()


# ── defects → fresh mission with evidence; the log reports, never orders ────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.open_arc("testproj", ARC_BUILD)
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
    assert "DEFECT" in DISPATCHED[0].description
    assert "502 on /api/ops/x" in DISPATCHED[0].description  # observed value travels
    assert DISPATCHED[0].payload["factory_mission_id"].startswith("fix-")
    assert DISPATCHED[0].payload["workflow_skills"] == ["agent-app-creator"]
    assert "ATTEMPT LOG" not in DISPATCHED[0].description, (
        "a first round has no history; it must not read like a retry"
    )

    # Round 2, byte-identical cause. The log SAYS that and stops.
    host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 502 on /api/ops/x"],
        details="VERDICT: FAIL\n502 evidence line",
    )
    assert len(DISPATCHED) == 2
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
    host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 401 unauthorized on /api/ops/x"],
        details="VERDICT: FAIL\n401 evidence line",
    )
    assert "cause changed: verify.refresh" in DISPATCHED[3].description

    # What an agent proved innocent survives into every later brief, and the
    # last defect round scopes the next verify.
    host.record_ruled_out("testproj", ["not the grant - dry run returns 200"])
    host.report_verify(
        "testproj",
        "defects",
        defects=["- Refresh — FAIL — 401 unauthorized on /api/ops/x"],
        details="VERDICT: FAIL\n401 evidence line",
    )
    assert "RULED OUT BY EARLIER ROUNDS" in DISPATCHED[4].description
    assert "not the grant" in DISPATCHED[4].description
    assert host.get_last_defects("testproj") == ["Refresh"]
print("defects → mission → attempt log → work that keeps going: OK")

# ── pass verdict → announce + arc closes; nothing ever dispatches again ─────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.open_arc("testproj", ARC_BUILD)
    host.report_launch_success("testproj")
    d = host.report_verify(
        "testproj",
        "pass",
        url="http://127.0.0.1:3100",
        verified=["feature a", "feature b"],
        caveat="",
    )
    assert d.next_state == "done"
    # User-facing announcement: friendly, no URL, no feature counts.
    assert CHAT and "Your app is ready" in CHAT[-1]
    assert "http" not in CHAT[-1] and "feature" not in CHAT[-1]
    assert not host.arc_for("testproj").is_open, "done = the arc is gone"
    age(host)
    assert host.supervise_once() == [], "a closed arc must never redispatch"
print("pass → announce + close, terminal stability: OK")

# ── a MODIFY arc announces as a change and briefs with the modify skill ─────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.begin_modify("testproj")
    host.report_verify(
        "testproj",
        "defects",
        defects=["- Board — FAIL — 500 on /api/ops/y"],
        details="VERDICT: FAIL\n500",
    )
    assert DISPATCHED[0].payload["workflow_skills"] == ["agent-app-modify"]
    host.report_verify(
        "testproj", "pass", url="http://127.0.0.1:3100", verified=["Board"]
    )
    assert "Your change is live" in CHAT[-1], "modify flavor comes from arc kind"
print("modify arc: modify skill + change-is-live flavor: OK")

# ── the supervisor: idle open arc → resume; stall cap → honest stuck ────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.open_arc("testproj", ARC_BUILD)
    assert host.supervise_once() == [], "fresh activity — backoff holds"
    for i in range(STALLS_CAP):
        age(host)
        acted = host.supervise_once()
        if i < STALLS_CAP - 1:
            assert acted == ["testproj"] and "CONTINUE BUILD" in DISPATCHED[-1].description
        else:
            assert acted == ["testproj"]
    assert len(DISPATCHED) == STALLS_CAP - 1, "cap 3 → 2 resumes, then stuck"
    assert CHAT and "try again" in CHAT[-1]
    assert not host.arc_for("testproj").is_open
    age(host)
    assert host.supervise_once() == [], "stuck closed the arc — quiet forever"
print("supervisor: resume then stall cap: OK")

# ── evidence between ticks resets the empty-loop counter ────────────────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.open_arc("testproj", ARC_BUILD)
    age(host)
    host.supervise_once()  # stall 1
    host.report_verify(
        "testproj",
        "defects",
        defects=["- X — FAIL — boom"],
        details="VERDICT: FAIL\nboom",
    )  # evidence → stalls reset
    for _ in range(2):
        age(host)
        host.supervise_once()
    assert host.arc_for("testproj").is_open, (
        "two empty rounds after real work must not hit the 3-stall cap"
    )
print("evidence resets the stall cap: OK")

# ── user stop = pause; supervisor respects it; re-ask = resume ──────────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.begin_modify("testproj")
    host.pause_by_user("testproj")
    assert CHAT and "paused" in CHAT[-1]
    age(host)
    assert host.supervise_once() == [], (
        "the stop button is a stop, not a deferral — no resurrection"
    )
    host.begin_modify("testproj")  # the user asked for the change again
    assert host.arc_for("testproj").paused is None
    age(host)
    assert host.supervise_once() == ["testproj"], "re-ask resumes supervision"
print("user stop pauses; re-ask resumes: OK")

# ── question park: run-end records it, the answer's run-end clears it ───────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.open_arc("testproj", ARC_BUILD)
    host.on_run_end("testproj", {}, awaiting_answer=True)
    assert host.arc_for("testproj").paused["by"] == "question"
    age(host)
    assert host.supervise_once() == [], "an open question is the user's move"
    host.on_run_end("testproj", {})  # the answer's run ended
    assert host.arc_for("testproj").paused is None
print("question park + answer unpark: OK")

# ── the agent raises its hand instead of grinding ───────────────────────────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.open_arc("testproj", ARC_BUILD)
    d = host.report_blocked(
        "testproj",
        "Which calendar should new bookings write to?",
        ruled_out=["the API works - verified with the CLI"],
    )
    assert d.next_state == "blocked"
    assert CHAT and "Which calendar" in CHAT[-1]
    assert "wasn't able to finish" not in CHAT[-1], "a question is not a failure"
    # The user gets the question and a plain lead only — no internal
    # ruled-out / "already established" developer notes.
    assert "decision from you" in CHAT[-1]
    assert "the API works" not in CHAT[-1]
    age(host)
    assert host.supervise_once() == [], "a blocked build waits for the user"
    assert host.report_blocked("testproj", "another question?") is None, (
        "no open arc — nothing in flight to pause"
    )
    assert len(CHAT) == 1, "and it must not announce a second time"
print("blocked: question to the user, arc closed, no retry: OK")

# ── unparseable verdict: retry once, then stuck — never announce ready ──────
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    host.open_arc("testproj", ARC_BUILD)
    d = host.report_verify("testproj", "unparseable")
    assert d.payload.get("redo") == "verify" and CHAT == []
    d = host.report_verify("testproj", "unparseable")
    assert d.next_state == "stuck"
    assert CHAT and "try again" in CHAT[-1]
    assert all("ready" not in c for c in CHAT)  # NEVER announced ready
print("unparseable verdicts fail closed: OK")

# ── an app that ARRIVED finished: no arc, no supervision, no ghost builds ───
with tempfile.TemporaryDirectory() as td:
    DISPATCHED.clear()
    CHAT.clear()
    host = make_host(Path(td))
    # Marketplace install opens nothing. "No work in flight" is stored truth.
    assert not host.arc_for("testproj").is_open
    host.on_run_end("testproj", {})  # first request to the installed app
    age(host, seconds=999999)
    assert host.supervise_once() == [], (
        "an app that arrived finished must never be dragged into a build"
    )
    assert host.report_verify("testproj", "pass", url="http://x") is None, (
        "a verdict with no arc is the caller's to announce"
    )
    assert CHAT == []
    # A later modify supervises normally.
    host.begin_modify("testproj")
    assert host.arc_for("testproj").kind == ARC_MODIFY
print("arrived-finished: quiet until a real modify: OK")

print("\nHost acceptance: ALL GREEN")
