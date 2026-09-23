# -*- coding: utf-8 -*-
"""The Arc — the ONE mutable supervision record per project.

Everything the old 12-state Machine + transition graph stored is either
here, derived, or deleted. Design rules (the fragility the rewrite kills):

- ABSENCE IS EXPLICIT. ``arc: "none"`` is a stored value, never a default
  that impersonates "building". A marketplace app that never had a build
  arc reads as exactly that, and no run-end hook can mistake it for an
  unfinished build.
- INTENT IS RECORDED. A user stop writes ``paused``; nothing may infer
  "surrendered" from a phantom mission id. A paused arc never auto-resumes.
- TWO PHASES, because only two things are ever actually reported: the
  launch pipeline succeeded ("verifying" — waiting on the walker) and
  everything else ("working" — the agent has the ball). The old
  gate/launch/build/fix states were only ever synthesized, never reported.
- Terminal states are not states. "done" is the arc closing back to
  ``none``; "stuck"/"blocked" are the arc closing plus one announcement.

The division of authority is unchanged: this record owns CONTINUATION and
MEMORY (budget, attempt ledger); the agent owns STRATEGY; only the verifier
says whether the app works.

Pure stdlib, JSON-persisted, no host imports.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Arc kinds — recorded at OPEN time, which is what replaces the old
# "generations" archive (announce flavor, skill choice, resume verb all
# read this one enum).
ARC_NONE = "none"
ARC_BUILD = "build"
ARC_MODIFY = "modify"

# Phases within an open arc.
WORKING = "working"
VERIFYING = "verifying"

# Budget. A wallet, not a verdict: an engineer has a timebox too.
MISSIONS_CAP = 12
# Consecutive supervisor dispatches with no evidence of work between them
# (no verdict, no launch report, no finding). Working on a hard bug for
# five rounds is fine; five empty rounds is a loop (chili3d, 2026-08-05:
# 37 redispatches in ~4 minutes).
STALLS_CAP = 3
# Idle time before the supervisor may dispatch, by stall count. Replaces
# the run-end thrash guard and its timestamp archaeology.
BACKOFF_S = (20.0, 60.0, 180.0)


def backoff_for(stalls: int) -> float:
    return BACKOFF_S[min(max(stalls, 0), len(BACKOFF_S) - 1)]


@dataclass
class Decision:
    """What the host decided after an outcome report — returned to the
    actions layer so it can shape agent-facing text. next_state is one of
    "done" | "fixing" | "stuck" | "blocked" | "verifying"."""

    next_state: str
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


def _fresh() -> Dict[str, Any]:
    return {
        "arc": ARC_NONE,
        "phase": WORKING,
        "mission": None,
        "paused": None,
        "missions_spent": 0,
        "stalls": 0,
        "opened_at": 0.0,
        "last_activity_at": 0.0,
        "unparseable_retried": False,
        "rounds": [],
        "ruled_out": [],
        "disputed": [],
    }


class Arc:
    """<project>/.factory/arc.json, atomically written.

    A missing or unreadable file IS the none-arc — but every mutation
    persists explicitly, so an app that ever had work carries its record.
    """

    _MAX_ROUNDS = 20
    _MAX_NOTES = 20  # ruled_out / disputed each

    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._d: Dict[str, Any] = _fresh()
        try:
            if self._path.exists():
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("arc") in (
                    ARC_NONE,
                    ARC_BUILD,
                    ARC_MODIFY,
                ):
                    self._d.update(loaded)
        except Exception:
            pass  # unreadable file = none-arc; the next mutation rewrites it

    # ── persistence ────────────────────────────────────────────────────────
    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._d, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)

    # ── facts ──────────────────────────────────────────────────────────────
    @property
    def kind(self) -> str:
        return str(self._d["arc"])

    @property
    def is_open(self) -> bool:
        return self.kind != ARC_NONE

    @property
    def phase(self) -> str:
        return str(self._d["phase"])

    @property
    def paused(self) -> Optional[Dict[str, Any]]:
        p = self._d.get("paused")
        return dict(p) if isinstance(p, dict) else None

    @property
    def mission_id(self) -> Optional[str]:
        m = self._d.get("mission")
        return str(m["id"]) if isinstance(m, dict) and m.get("id") else None

    @property
    def missions_spent(self) -> int:
        return int(self._d.get("missions_spent") or 0)

    @property
    def stalls(self) -> int:
        return int(self._d.get("stalls") or 0)

    @property
    def last_activity_at(self) -> float:
        return float(self._d.get("last_activity_at") or 0.0)

    @property
    def unparseable_retried(self) -> bool:
        return bool(self._d.get("unparseable_retried"))

    def rounds(self) -> List[Dict[str, Any]]:
        return list(self._d.get("rounds") or [])

    def ruled_out(self) -> List[Dict[str, Any]]:
        return list(self._d.get("ruled_out") or [])

    def disputed(self) -> List[Dict[str, Any]]:
        return list(self._d.get("disputed") or [])

    # ── lifecycle ──────────────────────────────────────────────────────────
    def open(self, kind: str) -> None:
        """Open an arc, or re-enter the one already open.

        Re-entry (a fix mission's notify_ready re-runs open_dev; the user
        asks again for a change that is mid-flight) clears a pause — the
        request IS the resume — and touches activity. It never resets the
        budget or the ledger: same arc, same wallet.
        """
        if kind not in (ARC_BUILD, ARC_MODIFY):
            raise ValueError(f"open() takes build|modify, got {kind!r}")
        if self.is_open:
            self._d["paused"] = None
            self.touch(save=False)
            self.save()
            return
        self._d = _fresh()
        self._d["arc"] = kind
        self._d["opened_at"] = time.time()
        self.touch(save=False)
        self.save()

    def close(self) -> None:
        """The arc is over (delivered, stuck, or blocked — the announcement
        is the host's job). The ledger dies with the arc: it describes a
        program that no longer exists."""
        self._d = _fresh()
        self.save()

    def pause(self, by: str, question: str = "") -> None:
        if not self.is_open:
            return
        self._d["paused"] = {
            "by": by,  # "user" | "question"
            "question": question[:500],
            "at": time.time(),
        }
        self.save()

    def unpause(self) -> None:
        if self._d.get("paused") is not None:
            self._d["paused"] = None
            self.touch(save=False)
            self.save()

    def set_phase(self, phase: str) -> None:
        if not self.is_open:
            return
        self._d["phase"] = phase
        self.touch(save=False)
        self.save()

    def touch(self, save: bool = True) -> None:
        self._d["last_activity_at"] = time.time()
        if save:
            self.save()

    # ── budget ─────────────────────────────────────────────────────────────
    def mission_dispatched(self, mission_id: str) -> None:
        self._d["mission"] = {"id": mission_id, "dispatched_at": time.time()}
        self._d["missions_spent"] = self.missions_spent + 1
        self.touch(save=False)
        self.save()

    def bump_stall(self) -> int:
        self._d["stalls"] = self.stalls + 1
        self.save()
        return self.stalls

    def evidence_of_work(self) -> None:
        """A verdict, launch report, or finding arrived: whatever is running
        is not an empty loop. Resets the stall counter, touches activity."""
        self._d["stalls"] = 0
        self.touch(save=False)
        self.save()

    def budget_exhausted(self) -> bool:
        return self.missions_spent >= MISSIONS_CAP or self.stalls >= STALLS_CAP

    def set_unparseable_retried(self, value: bool) -> None:
        self._d["unparseable_retried"] = bool(value)
        self.save()

    # ── the attempt ledger (what the next mission gets to know) ────────────
    def record_round(
        self,
        fingerprint: str,
        cards: Optional[List[Dict[str, str]]] = None,
        features: Optional[List[str]] = None,
        stall: bool = False,
    ) -> None:
        rounds = self._d.setdefault("rounds", [])
        rounds.append(
            {
                "n": len(rounds) + 1,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "fingerprint": fingerprint,
                "stall": bool(stall),
                "cards": list(cards or []),
                # Feature NAMES the walk observed broken — the next verify's
                # must-include scope (replaces the last_defects sidecar key).
                "features": list(features or []),
            }
        )
        del rounds[: -self._MAX_ROUNDS]
        self._d["unparseable_retried"] = False
        self.evidence_of_work()

    def _record_notes(self, key: str, items: List[str], cap: int) -> int:
        ledger = self._d.setdefault(key, [])
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
                }
            )
            added += 1
        del ledger[:-cap]
        if added:
            self.evidence_of_work()
        return added

    def record_ruled_out(self, items: List[str]) -> int:
        """Causes an agent PROVED innocent. Every later round is a fresh run
        that remembers nothing — what is not written here is not known."""
        return self._record_notes("ruled_out", items, self._MAX_NOTES)

    def record_disputed(self, items: List[str]) -> int:
        """Verdicts a builder reproduced and found wrong. Travels forward to
        the next VERIFIER, which is the party that must reconsider."""
        return self._record_notes("disputed", items, self._MAX_NOTES)

    def last_defect_features(self) -> List[str]:
        """Feature names from the latest defect round ([] outside a fix arc)."""
        for entry in reversed(self.rounds()):
            if not entry.get("stall"):
                return [str(x) for x in (entry.get("features") or [])]
        return []

    # ── honest reports (machine-composed, no agent self-assessment) ───────
    def stuck_report(self) -> str:
        """Why work stopped, in the user's terms. No mission counts, no
        failure fingerprints, no internal history: the user does not care."""
        return (
            "I wasn't able to finish this one automatically. You can ask me "
            "to try again, or tell me a bit more about what you'd like."
        )

    def blocked_report(self, question: str) -> str:
        """The agent needs something only the user has. Not a failure: it
        ends in a question, and work resumes the moment it is answered."""
        return (
            "I need a decision from you before I can continue.\n\n"
            + (question.strip() or "(no question was given)")
        )
