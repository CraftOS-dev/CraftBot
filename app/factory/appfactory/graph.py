# -*- coding: utf-8 -*-
"""The app-factory state graph (FACTORY-PLAN §3.3) — the domain pack's ONLY
knowledge the engine consumes: (state, outcome) → Decision.

Pure function, no I/O, no host imports. Phase 1 wires real gate/verify
outcomes into it; Phase 0 pins the shape with tests so the wiring cannot
drift from the plan.
"""

from __future__ import annotations

from app.factory.engine.machine import (
    ANNOUNCE_READY,
    ANNOUNCE_STUCK,
    DISPATCH_MISSION,
    DONE,
    NONE,
    STUCK,
    Decision,
    Outcome,
)

# States (plan §3.3). Terminal names come from the engine.
INTERVIEWING = "interviewing"
SPECIFYING = "specifying"
BUILDING = "building"
RESEARCHING = "researching"
GATING = "gating"
LAUNCHING = "launching"
VERIFYING = "verifying"
FIXING = "fixing"
MODIFYING = "modifying"

MISSION_STATES = (BUILDING, RESEARCHING, FIXING, MODIFYING)


def transition(state: str, outcome: Outcome) -> Decision:  # noqa: C901
    """Pre-caps Decision for every (state, outcome) pair the plan defines.
    The engine applies caps/escalation on top; the model decides nothing."""

    # ── happy path ─────────────────────────────────────────────────────────
    if state == INTERVIEWING and outcome.ok:
        return Decision(SPECIFYING)
    if state == SPECIFYING and outcome.ok:
        return Decision(BUILDING, DISPATCH_MISSION, payload={"mission": "build"})
    if state == BUILDING and outcome.ok:
        # The spec may demand external data with no covering action → research
        # is a STATE the machine enters, not a step the agent remembers.
        if outcome.payload.get("needs_research"):
            return Decision(
                RESEARCHING,
                DISPATCH_MISSION,
                payload={
                    "mission": "research",
                    "topics": outcome.payload.get("topics", []),
                },
            )
        return Decision(GATING)
    if state == RESEARCHING and outcome.ok:
        return Decision(BUILDING, DISPATCH_MISSION, payload={"mission": "build"})
    if state == GATING and outcome.ok:
        return Decision(LAUNCHING)
    if state == LAUNCHING and outcome.ok:
        return Decision(VERIFYING)
    if state == VERIFYING and outcome.ok:
        return Decision(DONE, ANNOUNCE_READY, payload=outcome.payload)
    if state == MODIFYING and outcome.ok:
        return Decision(GATING)
    if state == FIXING and outcome.ok:
        # A fix mission ended; truth comes from re-running the pipeline,
        # never from the mission's self-assessment (E2).
        return Decision(GATING)

    # ── failures ───────────────────────────────────────────────────────────
    if state == VERIFYING and outcome.payload.get("unknown_verdict"):
        # Fail closed: NEVER announce on an unparseable verdict (§3.3).
        if outcome.payload.get("already_retried"):
            return Decision(
                STUCK, ANNOUNCE_STUCK, reason="verifier verdict unparseable twice"
            )
        return Decision(
            VERIFYING, NONE, reason="re-verify once", payload={"redo": "verify"}
        )

    if (
        state in (GATING, LAUNCHING, VERIFYING, BUILDING, MODIFYING, FIXING)
        and not outcome.ok
    ):
        return Decision(
            FIXING,
            DISPATCH_MISSION,
            payload={"mission": "fix", "cards": outcome.payload.get("cards", [])},
        )
    if state in (INTERVIEWING, SPECIFYING, RESEARCHING) and not outcome.ok:
        # Pre-code states failing is a host/wizard problem, not a fix mission.
        return Decision(
            STUCK, ANNOUNCE_STUCK, reason=f"{state} failed: {outcome.payload}"
        )

    return Decision(
        STUCK, ANNOUNCE_STUCK, reason=f"undefined transition: {state}/{outcome.ok}"
    )
