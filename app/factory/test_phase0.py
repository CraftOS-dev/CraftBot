# -*- coding: utf-8 -*-
"""Phase 0 acceptance (FACTORY-PLAN §5 Phase 0). Plain asserts, no deps:
python3 -m app.factory.test_phase0
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.factory.engine import (
    ANNOUNCE_BLOCKED,
    ANNOUNCE_READY,
    ANNOUNCE_STUCK,
    BLOCKED,
    DISPATCH_MISSION,
    DONE,
    STUCK,
    Caps,
    Machine,
    Outcome,
    card_from_dict,
    validate_card,
)
from app.factory.engine.cards import fingerprint_all
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

# ── the fingerprint tracks the CAUSE, not the wording ───────────────────────
# Both halves matter and they pull against each other. Too coarse (hashing the
# feature title, as it first did) and a loop clearing one gate per round looks
# identical every round: the Gmail status check below burned its whole budget
# one gate from done. Too fine (harvesting quoted strings, as it did next) and
# the same failure reworded by the verifier hashes differently every round,
# which makes the stall signal unreachable.
_C = dict(expected="x", candidate_cause="y", suggested_direction="z", repro="r")
_R = "/api/ops/integrations/status"


def _card(observed: str, key: str = "verify.gmail-status"):
    return card_from_dict({"key": key, "where": _R, "observed": observed, **_C})


# Three rounds, three real causes: each fix cleared one gate and exposed the
# next. The discriminating tokens are all machine-written identifiers.
causes = [
    _card(f"POST {_R} 403 - action create_gmail_draft not in capabilities.actions"),
    _card(f"POST {_R} 403 - action send_gmail not in capabilities.actions"),
    _card(f"POST {_R} 400 - send_gmail requires confirm_irreversible"),
]
assert len({c.fingerprint() for c in causes}) == 3, [c.cause_signature() for c in causes]

# One round, three ways the verifier might write it up — including the route
# ending a sentence, where the full stop rides along on the token.
rewordings = [
    _card(f'POST {_R} returned 400 {{"error":"Invalid payload"}}'),
    _card(f'The check failed: POST {_R} gave a 400 with "Invalid payload".'),
    _card(f'Clicking "Check Gmail" shows "Gmail not connected"; 400 on {_R}.'),
    _card(f"Still failing - {_R}, HTTP 400."),
]
assert len({c.fingerprint() for c in rewordings}) == 1, [
    c.cause_signature() for c in rewordings
]

# A defect with no machine-written token left falls back to the feature key
# rather than to an empty signature every card would share.
assert _card("the timeline never renders", key="verify.timeline").cause_signature()

# The SET's identity ignores card order (ordering is the distiller's, not the
# failure's) and moves when any member's cause moves — that is the whole
# progress signal: two defects, fix one, the set reads as different.
assert fingerprint_all(causes[:2]) == fingerprint_all(list(reversed(causes[:2])))
assert fingerprint_all(causes[:2]) != fingerprint_all(causes[1:])
assert fingerprint_all([]) == ""
print("defect fingerprints: cause-sensitive, wording-blind: OK")


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

# ── a repeating FAILURE escalates and keeps working ─────────────────────────
# It used to end the build at three. That is a judgement about whether the
# approach is working, made from a hash: the Gmail loop that cleared one gate
# per round was killed one gate short. Repetition now buys a harder brief and
# nothing else; only the budget stops the work.
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_stall=3, total_missions=12))
    fp = card.fingerprint()
    m.advance(Outcome(SPECIFYING, ok=True))  # → building (mission 1)
    m.advance(Outcome(BUILDING, ok=True))  # → gating
    d1 = m.advance(
        Outcome(GATING, ok=False, fingerprint=fp, payload={"cards": [EXAMPLE]})
    )
    assert (m.state, d1.action, d1.escalate) == (FIXING, DISPATCH_MISSION, False)
    assert d1.escalate_level == 1
    for expected_level in (2, 3, 4, 5):
        m.advance(Outcome(FIXING, ok=True))  # fix ended → re-gate
        d = m.advance(Outcome(GATING, ok=False, fingerprint=fp))
        assert d.action == DISPATCH_MISSION, (
            f"round {expected_level}: a repeating failure must keep working "
            "while budget remains"
        )
        assert d.escalate and d.escalate_level == expected_level
    assert m.state == FIXING and not m.terminal
print("repeating failure escalates, never terminates: OK")

# ── a repeating STALL does end it ───────────────────────────────────────────
# A run that ends without producing a verdict is not an attempt at anything.
# Live: chili3d, 2026-08-05 — 37 redispatches in ~4 minutes.
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_stall=3, total_missions=12))
    m.advance(Outcome(SPECIFYING, ok=True))
    m.advance(Outcome(BUILDING, ok=True))
    for _ in range(2):
        d = m.advance(Outcome(m.state, ok=False, fingerprint="surrender", stall=True))
        assert d.action == DISPATCH_MISSION
    d = m.advance(Outcome(m.state, ok=False, fingerprint="surrender", stall=True))
    assert (m.state, d.action) == (STUCK, ANNOUNCE_STUCK)
    assert "without completing" in d.reason
    report = m.stuck_report()
    assert "could not be completed" in report and "Missions attempted" in report
print("repeating stall caps out: OK")

# ── the attempt ledger: rounds and ruled-out survive into the next brief ────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_stall=3, total_missions=12))
    m.advance(Outcome(SPECIFYING, ok=True))
    m.advance(Outcome(BUILDING, ok=True))
    m.advance(
        Outcome(
            GATING,
            ok=False,
            fingerprint="f1",
            payload={"cards": [{"key": "a", "sig": "/api/x|status403"}]},
        )
    )
    m.advance(Outcome(FIXING, ok=True))
    m.advance(
        Outcome(
            GATING,
            ok=False,
            fingerprint="f2",
            payload={"cards": [{"key": "a", "sig": "/api/x|status400"}]},
        )
    )
    rounds = m.rounds()
    assert [r["n"] for r in rounds] == [1, 2]
    assert rounds[-1]["cards"][0]["sig"].endswith("status400")

    assert m.record_ruled_out(["not the grant - dry run returns 200"]) == 1
    assert m.record_ruled_out(["NOT THE GRANT - dry run returns 200"]) == 0  # deduped
    assert m.ruled_out()[0]["what"].startswith("not the grant")
    assert "not the grant" in m.stuck_report()

    m2 = fresh_machine(Path(td))  # survives a restart, like everything else
    assert len(m2.rounds()) == 2 and len(m2.ruled_out()) == 1
print("attempt ledger: rounds + ruled-out persist: OK")

# ── the agent raises its hand: BLOCKED is terminal and carries a question ───
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_stall=3, total_missions=12))
    m.advance(Outcome(SPECIFYING, ok=True))
    d = m.advance(
        Outcome(
            BUILDING,
            ok=False,
            payload={"blocked": True, "question": "Which calendar do bookings use?"},
        )
    )
    assert (m.state, d.action) == (BLOCKED, ANNOUNCE_BLOCKED)
    assert m.terminal and not m.needs_redispatch(), (
        "a blocked build waits for the user; it must not redispatch itself"
    )
    report = m.blocked_report(d.reason)
    assert "Which calendar do bookings use?" in report
    assert "could not be completed" not in report, (
        "a question is not a failure report"
    )
    m.reopen(BUILDING)  # the user answers → work resumes
    assert m.state == BUILDING and not m.terminal
print("blocked: honest terminal with a question: OK")

# ── total mission budget ────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    m = fresh_machine(Path(td), caps=Caps(per_stall=99, total_missions=2))
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
    m = fresh_machine(Path(td), caps=Caps(per_stall=3, total_missions=2))
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
