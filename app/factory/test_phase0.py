# -*- coding: utf-8 -*-
"""Phase 0 acceptance (FACTORY-PLAN §5 Phase 0). Plain asserts, no deps:
python3 -m app.factory.test_phase0
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.factory.engine import (
    ANNOUNCE_READY,
    ANNOUNCE_STUCK,
    DISPATCH_MISSION,
    DONE,
    STUCK,
    Caps,
    Machine,
    Outcome,
    card_from_dict,
    validate_card,
)
from app.factory.appfactory import (
    BUILDING,
    FIXING,
    GATING,
    LAUNCHING,
    MODIFYING,
    SPECIFYING,
    VERIFYING,
    transition,
)

# ── §3.5 example card validates ─────────────────────────────────────────────
EXAMPLE = {
    "key": "verify.feature.refresh-502",
    "where": "POST /api/ops/refresh-stories (ops.pb.js:41)",
    "observed": "502; pocketbase.log: 'hn-refresh failed: comment_count: cannot be blank'",
    "expected": "200 and stories rows created on click",
    "candidate_cause": "required number field rejects 0 (PB semantics)",
    "suggested_direction": "set a safe default before save OR relax required in a NEW migration",
    "repro": "node <cli> run <project> refresh_stories",
    "evidence": ["hn-refresh failed: GoError: comment_count: cannot be blank."],
}
assert validate_card(EXAMPLE) == [], validate_card(EXAMPLE)
card = card_from_dict(EXAMPLE)
assert card.fingerprint() and "DEFECT" in card.render()
assert validate_card({**EXAMPLE, "observed": ""}) != []  # empty required
assert validate_card({**EXAMPLE, "extra": "x"}) != []  # unknown field
print("card schema: OK")


# ── the arc: happy path ─────────────────────────────────────────────────────
def fresh_machine(tmp: Path, caps=None) -> Machine:
    return Machine(transition, tmp / "state.json", SPECIFYING, caps=caps)


with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td))
    d = m.advance(Outcome(SPECIFYING, ok=True))
    assert (m.state, d.action) == (BUILDING, DISPATCH_MISSION)
    m.mission_started("build-1")
    assert not m.needs_redispatch()
    m.mission_ended("build-1")
    assert m.needs_redispatch()  # I6: surrender is visible
    for s in (BUILDING, GATING, LAUNCHING):
        m.advance(Outcome(s, ok=True))
    d = m.advance(Outcome(VERIFYING, ok=True, payload={"verified": ["a", "b"]}))
    assert (m.state, d.action) == (DONE, ANNOUNCE_READY)
    assert not m.needs_redispatch()
print("happy path: OK")

# ── failure loop: caps + escalation ─────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_fingerprint=3, total_missions=12))
    fp = card.fingerprint()
    m.advance(Outcome(SPECIFYING, ok=True))  # → building (mission 1)
    m.advance(Outcome(BUILDING, ok=True))  # → gating
    d1 = m.advance(
        Outcome(GATING, ok=False, fingerprint=fp, payload={"cards": [EXAMPLE]})
    )
    assert (m.state, d1.action, d1.escalate) == (FIXING, DISPATCH_MISSION, False)
    m.advance(Outcome(FIXING, ok=True))  # fix ended → re-gate
    d2 = m.advance(Outcome(GATING, ok=False, fingerprint=fp))
    assert d2.escalate, "second identical failure must escalate the brief"
    m.advance(Outcome(FIXING, ok=True))
    d3 = m.advance(Outcome(GATING, ok=False, fingerprint=fp))
    assert (m.state, d3.action) == (STUCK, ANNOUNCE_STUCK)  # cap 3 → stuck
    assert "3×" in d3.reason or "cap" in d3.reason
    report = m.stuck_report()
    assert "could not be completed" in report and fp in report
print("caps + escalation + honest stuck report: OK")

# ── total mission budget ────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_fingerprint=99, total_missions=2))
    m.advance(Outcome(SPECIFYING, ok=True))  # mission 1 (build)
    m.advance(Outcome(BUILDING, ok=True))  # → gating
    d = m.advance(Outcome(GATING, ok=False, fingerprint="x1"))  # mission 2 (fix)
    assert d.action == DISPATCH_MISSION
    m.advance(Outcome(FIXING, ok=True))
    d = m.advance(Outcome(GATING, ok=False, fingerprint="x2"))  # would be 3 → stuck
    assert (m.state, d.action) == (STUCK, ANNOUNCE_STUCK)
print("mission budget: OK")

# ── fail-closed verdicts ────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td))
    for s in (SPECIFYING, BUILDING, GATING, LAUNCHING):
        m.advance(Outcome(s, ok=True))
    d = m.advance(Outcome(VERIFYING, ok=False, payload={"unknown_verdict": True}))
    assert m.state == VERIFYING and d.payload.get("redo") == "verify"
    d = m.advance(
        Outcome(
            VERIFYING,
            ok=False,
            payload={"unknown_verdict": True, "already_retried": True},
        )
    )
    assert (m.state, d.action) == (STUCK, ANNOUNCE_STUCK)  # NEVER announce
print("fail-closed verdicts: OK")

# ── persistence survives restart ────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td))
    m.advance(Outcome(SPECIFYING, ok=True))
    m.mission_started("build-1")
    m2 = fresh_machine(Path(td))  # reload from disk
    assert m2.state == BUILDING and m2.active_mission == "build-1"
print("persistence: OK")

# ── reopen (LIFECYCLE-PLAN Phase 2): terminal → new generation ──────────────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_fingerprint=3, total_missions=2))
    m.advance(Outcome(SPECIFYING, ok=True))  # mission 1 (build)
    for s in (BUILDING, GATING, LAUNCHING):
        m.advance(Outcome(s, ok=True))
    m.advance(Outcome(VERIFYING, ok=True))  # → done
    assert m.terminal and m.generation == 0

    m.reopen(MODIFYING)  # modify arc begins
    assert m.state == MODIFYING and not m.terminal
    assert m.generation == 1 and m.active_mission is None
    assert m.history() == [], "reopen must start a clean history"
    archived = m.generations()[-1]
    assert archived["final_state"] == DONE and archived["history"], (
        "the finished arc must be archived, not lost"
    )

    # Fresh caps budget: the build era consumed 1/2 missions; the modify era
    # gets 2 again (a third dispatch in THIS arc would exhaust, not the 2nd).
    m.advance(Outcome(MODIFYING, ok=True))  # → gating
    for s in (GATING, LAUNCHING):
        m.advance(Outcome(s, ok=True))
    d = m.advance(Outcome(VERIFYING, ok=False, fingerprint="m1"))  # fix 1
    assert d.action == DISPATCH_MISSION
    m.advance(Outcome(FIXING, ok=True))
    m.advance(Outcome(GATING, ok=True))
    m.advance(Outcome(LAUNCHING, ok=True))
    d = m.advance(Outcome(VERIFYING, ok=False, fingerprint="m2"))  # fix 2 (budget 2)
    assert d.action == DISPATCH_MISSION, "reopen must reset the mission budget"

    # Mid-arc reopen is refused — the invariant lives in the engine.
    try:
        m.reopen(MODIFYING)
        raise AssertionError("reopen mid-arc must refuse")
    except ValueError:
        pass

    # Persistence: generations survive a reload.
    m2 = fresh_machine(Path(td))
    assert m2.generation == 1 and m2.generations()[-1]["final_state"] == DONE
print("reopen/generations: OK")

# ── reopen: a VIRGIN machine (no history) may re-arm ────────────────────────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td))  # minted, never ran
    m.reopen(MODIFYING)  # e.g. installed app's first modify
    assert m.state == MODIFYING and m.generation == 1
    assert m.generations()[-1]["history"] == []
print("reopen virgin: OK")

print("\nPhase 0 acceptance: ALL GREEN")
