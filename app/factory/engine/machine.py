# -*- coding: utf-8 -*-
"""The generic machine runtime (FACTORY-PLAN §3.3) — owns the ARC.

Domain-agnostic: states are strings supplied by a domain pack's transition
function. The engine owns what weak models empirically cannot (I1/I6):
persistence, budget, escalation, redispatch-on-surrender, and the ATTEMPT
LEDGER. It decides nothing domain-specific and talks to nothing external —
pure stdlib, JSON-persisted, so a host or a future TS port carries it whole.

The MODEL never decides "should I retry": outcomes come in, Decisions go out.

What the machine does NOT decide is whether the agent's approach is working.
It used to: three outcomes sharing a fingerprint ended the build. That is a
judgement, and the machine made it from a hash — so a loop clearing one gate
per round (create_gmail_draft ungranted → send_gmail ungranted → send_gmail
unconfirmed) was declared hopeless one gate from done, while the agent, told
only "this failure has repeated", had no way to see the pattern it was in.

The division now:
  - The machine owns CONTINUATION and MEMORY. Work continues while budget
    remains; every round is recorded and handed back to the next mission, so
    the agent can see what it already tried and what it ruled out.
  - The agent owns STRATEGY, and can end the arc honestly in one direction
    only — BLOCKED, meaning "I need a decision or a credential from the
    user", which carries a question. It still cannot end it by giving up:
    a run that stops mid-arc is redispatched (I6).
  - The budget (total_missions) is the one hard stop, and it is a wallet,
    not a verdict: an engineer has a timebox too.
One cap survives on the judgement side, and only because it needs no
judgement: repeated STALL — a run ending without completing the arc — is not
a strategy, it is an empty loop, and it once burned 37 redispatches in ~4
minutes (chili3d, 2026-08-05).
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
# BLOCKED is the agent's honest exit: it has a question only the user can
# answer (a decision, a credential, a capability that does not exist). It is
# terminal because grinding on is pointless, NOT because attempts ran out —
# the two read very differently to the user, and conflating them meant a
# blocked agent could only express itself by failing until the cap fired.
BLOCKED = "blocked"
TERMINAL = (DONE, STUCK, BLOCKED)

# Actions a Decision can carry — the full vocabulary the host executes.
DISPATCH_MISSION = "dispatch_mission"
ANNOUNCE_READY = "announce_ready"
ANNOUNCE_STUCK = "announce_stuck"
ANNOUNCE_BLOCKED = "announce_blocked"
NONE = "none"


@dataclass
class Outcome:
    """What just happened, reported by gate/verifier/mission — never by the
    model's self-assessment."""

    state: str  # state this outcome belongs to
    ok: bool
    fingerprint: Optional[str] = None  # stable failure identity (card fingerprint)
    # A stall is a run that ended without completing the arc — no verdict, no
    # work reported. Distinct from a failure: a failure is a result, a stall
    # is the absence of one, and only the second is capped.
    stall: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)  # cards, urls, reports


@dataclass
class Decision:
    next_state: str
    action: str = NONE
    escalate: bool = False  # same failure seen again → richer brief
    escalate_level: int = 0  # HOW many times: 1 = first sighting, 3+ = dig in
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Caps:
    # Repeated STALLS (empty rounds), not repeated failures. Working on the
    # same bug for five rounds is what fixing a hard bug looks like; ending
    # five runs without producing a verdict is a loop.
    per_stall: int = 3
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
            # The attempt ledger: one entry per failing round, and the list of
            # causes an agent has PROVED are not to blame. History records
            # what the machine did; these record what the work found, and they
            # are the only part of the state that goes back into a brief.
            "rounds": [],
            "ruled_out": [],
            # Verdicts a builder investigated and REJECTED on evidence. A
            # verifier can be wrong, and when it is, the builder is the only
            # party positioned to notice — it can reproduce the feature. Its
            # options used to be to edit working code, re-run and hope, or
            # end the run (which the machine reads as a stall). This is the
            # third move: say so, on the record, with what you observed.
            "disputed": [],
            "caps": {
                "per_stall": self._caps.per_stall,
                "total_missions": self._caps.total_missions,
            },
        }
        if self._store_path.exists():
            self._state.update(json.loads(self._store_path.read_text(encoding="utf-8")))
        # The record follows the constructor, not the file: caps are code, and
        # a machine loaded from a state file written before a cap was renamed
        # would otherwise keep publishing the retired name forever.
        self._state["caps"] = {
            "per_stall": self._caps.per_stall,
            "total_missions": self._caps.total_missions,
        }

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
                "rounds": list(self._state.get("rounds") or []),
                "ruled_out": list(self._state.get("ruled_out") or []),
                "disputed": list(self._state.get("disputed") or []),
            }
        )
        self._state["state"] = state
        self._state["mission_id"] = None
        self._state["total_missions"] = 0
        self._state["defect_fingerprints"] = {}
        self._state["history"] = []
        # The ledger is scoped to ONE arc. A modify starts against changed
        # code, so "ruled out during the build" is a claim about a program
        # that no longer exists — archived above, never carried forward.
        self._state["rounds"] = []
        self._state["ruled_out"] = []
        self._state["disputed"] = []
        self.save()

    # ── the arc ────────────────────────────────────────────────────────────
    def advance(self, outcome: Outcome) -> Decision:
        """Feed one outcome; get the machine's Decision, budget applied.

        Policy: a repeating failure ESCALATES (the brief gets the attempt
        ledger and a harder instruction) for as long as the budget lasts. It
        never ends the arc by itself — see the module docstring. Repeated
        STALLS do end it, and the total mission budget is absolute."""
        decision = self._transition(self.state, outcome)

        if not outcome.ok and outcome.fingerprint:
            counts = self._state["defect_fingerprints"]
            n = counts.get(outcome.fingerprint, 0) + 1
            counts[outcome.fingerprint] = n
            if decision.action == DISPATCH_MISSION:
                if outcome.stall and n >= self._caps.per_stall:
                    decision = Decision(
                        next_state=STUCK,
                        action=ANNOUNCE_STUCK,
                        reason=(
                            f"{n} runs ended without completing the arc; "
                            f"stall cap {self._caps.per_stall} reached"
                        ),
                        payload=decision.payload,
                    )
                else:
                    # Level, not a flag: round 2 means "your fix did not take",
                    # round 4 means "stop fixing and go find out why" — the
                    # brief needs to say different things.
                    decision.escalate_level = n
                    decision.escalate = n >= 2

        if not outcome.ok and outcome.fingerprint:
            self._record_round(outcome)

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

    # ── the attempt ledger (what the next mission gets to know) ────────────
    _MAX_ROUNDS = 20  # bounds the state file; the brief shows fewer still

    def _record_round(self, outcome: Outcome) -> None:
        rounds = self._state.setdefault("rounds", [])
        rounds.append(
            {
                "n": len(rounds) + 1,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "state": self.state,
                "fingerprint": outcome.fingerprint,
                "stall": bool(outcome.stall),
                # Opaque to the engine: whatever identities the host chose to
                # describe this round's failures with.
                "cards": list(outcome.payload.get("cards") or []),
            }
        )
        del rounds[: -self._MAX_ROUNDS]

    def rounds(self) -> List[Dict[str, Any]]:
        return list(self._state.get("rounds") or [])

    def ruled_out(self) -> List[Dict[str, Any]]:
        return list(self._state.get("ruled_out") or [])

    def disputed(self) -> List[Dict[str, Any]]:
        return list(self._state.get("disputed") or [])

    def record_disputed(self, items: List[str], mission: str = "") -> int:
        """Verdicts a builder reproduced and found to be wrong.

        Kept for the same reason as ruled_out — every later round is a fresh
        run that remembers nothing — but pointed the other way: ruled_out says
        "this cause is innocent", disputed says "this VERDICT is". It is also
        the only entry that travels forward to the VERIFIER, which is the
        party that has to reconsider (see build_verify_evidence).

        No cap on how often a verdict may be disputed: a dispute is a result,
        not a stall, so the ordinary round and repeat-failure budgets already
        apply. A builder that disputes the same feature round after round
        while it keeps failing escalates exactly like any other repeat.
        """
        ledger = self._state.setdefault("disputed", [])
        seen = {str(e.get("what", "")).strip().lower() for e in ledger}
        added = 0
        for raw in items or []:
            what = str(raw).strip()
            if not what or what.lower() in seen:
                continue
            seen.add(what.lower())
            ledger.append(
                {
                    "what": what[:600],
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "mission": mission,
                }
            )
            added += 1
        del ledger[:-20]
        if added:
            self.save()
        return added

    def record_ruled_out(self, items: List[str], mission: str = "") -> int:
        """Causes an agent PROVED innocent, kept for every later mission.

        This is the half of memory a bare attempt history misses: knowing what
        you tried does not stop you re-testing a theory you already killed,
        and across fresh missions with no shared context, agents did exactly
        that. Deduped on text, oldest dropped first, cheap to carry.
        """
        ledger = self._state.setdefault("ruled_out", [])
        seen = {str(e.get("what", "")).strip().lower() for e in ledger}
        added = 0
        for raw in items or []:
            what = str(raw).strip()
            if not what or what.lower() in seen:
                continue
            seen.add(what.lower())
            ledger.append(
                {
                    "what": what[:400],
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "mission": mission,
                }
            )
            added += 1
        del ledger[:-20]
        if added:
            self.save()
        return added

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
        """Why work stopped, in the user's terms. Ends on the budget, because
        that is what actually ran out — the machine no longer claims a defect
        was unfixable, only that it stopped paying to find out."""
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
        ruled = self.ruled_out()
        if ruled:
            lines.append("Ruled out along the way:")
            lines.extend(f"  - {e['what']}" for e in ruled[-5:])
        lines.append("The full attempt history is preserved for review.")
        return "\n".join(lines)

    def blocked_report(self, question: str) -> str:
        """The agent needs something only the user has. Not a failure report:
        it ends in a question, and the work is resumable the moment it is
        answered."""
        lines = ["The build needs a decision from you before it can continue."]
        ruled = self.ruled_out()
        if ruled:
            lines.append("Already established:")
            lines.extend(f"  - {e['what']}" for e in ruled[-5:])
        lines.append("")
        lines.append(question.strip() or "(no question was given)")
        return "\n".join(lines)
