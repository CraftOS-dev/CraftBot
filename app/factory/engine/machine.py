# -*- coding: utf-8 -*-
"""The generic machine runtime (FACTORY-PLAN §3.3) — owns the ARC.

Domain-agnostic: states are strings supplied by a domain pack's transition
function. The engine owns what weak models empirically cannot (I1/I6):
persistence, retry caps, fingerprint escalation, redispatch-on-surrender,
history. It decides nothing domain-specific and talks to nothing external —
pure stdlib, JSON-persisted, so a host or a future TS port carries it whole.

The MODEL never decides "should I retry": outcomes come in, Decisions go out.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Terminal states are engine-level concepts; domain graphs must use them.
DONE = "done"
STUCK = "stuck"
TERMINAL = (DONE, STUCK)

# Actions a Decision can carry — the full vocabulary the host executes.
DISPATCH_MISSION = "dispatch_mission"
ANNOUNCE_READY = "announce_ready"
ANNOUNCE_STUCK = "announce_stuck"
NONE = "none"


@dataclass
class Outcome:
    """What just happened, reported by gate/verifier/mission — never by the
    model's self-assessment."""

    state: str  # state this outcome belongs to
    ok: bool
    fingerprint: Optional[str] = None  # stable failure identity (card fingerprint)
    payload: Dict[str, Any] = field(default_factory=dict)  # cards, urls, reports


@dataclass
class Decision:
    next_state: str
    action: str = NONE
    escalate: bool = False  # same fingerprint seen again → richer brief
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Caps:
    per_fingerprint: int = 3
    total_missions: int = 12


# A domain pack supplies: (current_state, outcome) -> Decision (pre-caps).
TransitionFn = Callable[[str, Outcome], Decision]


class Machine:
    def __init__(
        self,
        transition: TransitionFn,
        store_path: Path,
        initial_state: str,
        caps: Optional[Caps] = None,
    ) -> None:
        self._transition = transition
        self._store_path = Path(store_path)
        self._caps = caps or Caps()
        self._state: Dict[str, Any] = {
            "state": initial_state,
            "mission_id": None,
            "total_missions": 0,
            "defect_fingerprints": {},
            "history": [],
            "caps": {
                "per_fingerprint": self._caps.per_fingerprint,
                "total_missions": self._caps.total_missions,
            },
        }
        if self._store_path.exists():
            self._state.update(json.loads(self._store_path.read_text(encoding="utf-8")))

    # ── persistence ────────────────────────────────────────────────────────
    def save(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(
            json.dumps(self._state, indent=2) + "\n", encoding="utf-8"
        )

    # ── introspection ──────────────────────────────────────────────────────
    @property
    def state(self) -> str:
        return str(self._state["state"])

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    @property
    def active_mission(self) -> Optional[str]:
        return self._state.get("mission_id")

    @property
    def generation(self) -> int:
        """How many completed arcs precede the current one (0 = first build).
        Hosts use this to flavor announcements (build ready vs change
        deployed) — the staging record is gone by announce time."""
        return len(self._state.get("generations") or [])

    def history(self) -> List[Dict[str, Any]]:
        return list(self._state["history"])

    def generations(self) -> List[Dict[str, Any]]:
        return list(self._state.get("generations") or [])

    # ── lifecycle (LIFECYCLE-PLAN Phase 2 — engine amendment) ──────────────
    def reopen(self, state: str) -> None:
        """Re-arm a TERMINAL machine for a new arc (a modify of a delivered
        app), archiving the finished arc as a generation and resetting the
        caps counters — each modify gets a fresh budget.

        Deliberately NOT a graph transition: reopening is a host-level
        lifecycle event (nothing "happens" to cause it inside the arc), so
        no DONE→MODIFYING edge exists. The terminal guard lives here, with
        the state: callers that want to re-arm an in-flight machine are
        holding it wrong. Virgin machines (no history — e.g. minted for a
        marketplace-installed app that never had a build arc) may also
        reopen: there is no arc to protect.
        """
        if not self.terminal and self._state["history"]:
            raise ValueError(
                f"refusing to reopen a machine mid-arc (state={self.state!r})"
            )
        # ALWAYS archive — even a virgin arc (empty history). generation > 0
        # is the durable "this arc is a reopened one" signal hosts key
        # announce flavor and mission skills on; an empty archived record is
        # harmless, a missed one mislabels every modify of an app whose
        # machine never ran a build arc (marketplace/imported installs).
        self._state.setdefault("generations", []).append(
            {
                "closed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "final_state": self.state,
                "total_missions": self._state["total_missions"],
                "defect_fingerprints": dict(self._state["defect_fingerprints"]),
                "history": list(self._state["history"]),
            }
        )
        self._state["state"] = state
        self._state["mission_id"] = None
        self._state["total_missions"] = 0
        self._state["defect_fingerprints"] = {}
        self._state["history"] = []
        self.save()

    # ── the arc ────────────────────────────────────────────────────────────
    def advance(self, outcome: Outcome) -> Decision:
        """Feed one outcome; get the machine's Decision, caps applied.

        Cap policy (§3.3): a repeating fingerprint first ESCALATES the brief
        (more evidence, wider excerpts) and only then goes stuck; total
        mission budget is absolute."""
        decision = self._transition(self.state, outcome)

        if not outcome.ok and outcome.fingerprint:
            counts = self._state["defect_fingerprints"]
            n = counts.get(outcome.fingerprint, 0) + 1
            counts[outcome.fingerprint] = n
            if decision.action == DISPATCH_MISSION:
                if n >= self._caps.per_fingerprint:
                    decision = Decision(
                        next_state=STUCK,
                        action=ANNOUNCE_STUCK,
                        reason=(
                            f"same failure {n}× (fingerprint {outcome.fingerprint}); "
                            f"cap {self._caps.per_fingerprint} reached"
                        ),
                        payload=decision.payload,
                    )
                elif n >= 2:
                    decision.escalate = True

        if decision.action == DISPATCH_MISSION:
            total = self._state["total_missions"] + 1
            if total > self._caps.total_missions:
                decision = Decision(
                    next_state=STUCK,
                    action=ANNOUNCE_STUCK,
                    reason=f"mission budget exhausted ({self._caps.total_missions})",
                    payload=decision.payload,
                )
            else:
                self._state["total_missions"] = total

        self._state["history"].append(
            {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "state": self.state,
                "ok": outcome.ok,
                "fingerprint": outcome.fingerprint,
                "next": decision.next_state,
                "action": decision.action,
            }
        )
        self._state["state"] = decision.next_state
        self.save()
        return decision

    # ── redispatch-on-surrender (closes I6) ────────────────────────────────
    def mission_started(self, mission_id: str) -> None:
        self._state["mission_id"] = mission_id
        self.save()

    def mission_ended(self, mission_id: str) -> None:
        if self._state.get("mission_id") == mission_id:
            self._state["mission_id"] = None
            self.save()

    def needs_redispatch(self) -> bool:
        """True when work should be in flight but is not: non-terminal state
        and no active mission. The host's run-end hook polls this — the
        mechanism that makes surrender structurally impossible."""
        return not self.terminal and self.active_mission is None

    # ── honest stuck report (machine-composed, §3.6) ───────────────────────
    def stuck_report(self) -> str:
        tried = [h for h in self._state["history"] if h["action"] == DISPATCH_MISSION]
        lines = [
            "The build could not be completed automatically.",
            f"State reached: {self.state}. Missions attempted: "
            f"{self._state['total_missions']}/{self._caps.total_missions}.",
        ]
        fps = self._state["defect_fingerprints"]
        if fps:
            worst = max(fps.items(), key=lambda kv: kv[1])
            lines.append(f"Most persistent failure: {worst[0]} ({worst[1]}×).")
        if tried:
            lines.append(f"Last attempt: {tried[-1]['state']} → {tried[-1]['next']}.")
        lines.append("The full attempt history is preserved for review.")
        return "\n".join(lines)
