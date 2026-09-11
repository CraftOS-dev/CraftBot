# -*- coding: utf-8 -*-
"""CraftBot host adapter for the Factory.

HOST layer: may import app.* freely; nothing in engine/appfactory imports it.

The supervision model (the 2026-09 rewrite — one record, one loop):

- Each project carries ONE mutable record, the Arc (engine/machine.py):
  ``none`` (stored explicitly) or an open build/modify with a phase, a
  pause, a budget, and the attempt ledger. Runtime app status is derived
  elsewhere and never consulted here.
- ONE supervisor loop replaces the run-end redispatch hook, its deferred
  wakeups, the thrash guard, and phantom-mission attribution. It ticks at
  boot, on every run-end, and periodically, and asks four questions per
  project: is an arc open, is it paused, is a run live in its session, and
  has it been idle past backoff. Dispatch and the stuck cap live here and
  nowhere else.
- Run-end and run-stop record FACTS (a question was asked; the user
  stopped the work); the loop draws the conclusions.

Missions are fresh triggers into the project's session: concrete brief,
ready-made calls, high priority. The machine owns continuation and memory;
the agent owns strategy; only the verifier says whether the app works.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.factory.engine import (
    ARC_MODIFY,
    MISSIONS_CAP,
    STALLS_CAP,
    VERIFYING,
    WORKING,
    Arc,
    Decision,
    backoff_for,
)

try:
    from app.logger import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

_TICK_S = 60.0  # supervisor heartbeat between kicks


def _cli() -> str:
    """The lui CLI invocation, absolute and quoted so a pasted repro runs from
    any cwd and survives a space in the path. Imported inside the call: this
    module is imported during app startup and app.config pulls settings."""
    from app.config import PROJECT_ROOT

    return f'node "{Path(PROJECT_ROOT).as_posix()}/agent-app/tools/src/cli.ts"'


def _fingerprint(text: str) -> str:
    """Stable identity of a failure from its first meaningful line."""
    first = next(
        (ln.strip() for ln in (text or "").splitlines() if ln.strip()), "unknown"
    )
    return hashlib.sha1(first[:200].encode("utf-8")).hexdigest()[:12]


# ── the attempt log, rendered for the next mission ─────────────────────────
# Missions are fresh triggers with no shared context: mission 4 knows nothing
# of missions 1-3. This is the log it would have kept if it had been there —
# rounds, causes, and what moved between them.
#
# It states facts and stops. An earlier version editorialised ("your last fix
# did not reach this failure", "stop fixing and diagnose") and that is the
# machine deciding strategy again, one layer up from the cap it replaced: an
# inference drawn from a hash, phrased as an order, by the party that cannot
# see the code. The agent reads the log and decides. What it may NOT do is
# work without it, which is why this is pushed rather than offered.


def _round_cards(entry: Dict[str, Any]) -> Dict[str, str]:
    """{feature key → cause signature} for one recorded round. Tolerates the
    older shape (a bare list of keys) so a mid-build upgrade reads its own
    state file instead of crashing on it."""
    out: Dict[str, str] = {}
    for card in entry.get("cards") or []:
        if isinstance(card, dict):
            out[str(card.get("key", ""))] = str(card.get("sig", ""))
        else:
            out[str(card)] = ""
    out.pop("", None)
    return out


def _delta(prev: Dict[str, str], cur: Dict[str, str]) -> Dict[str, List[str]]:
    """What moved between two rounds. `changed` — still failing, but on a
    different cause — is the distinction the old fingerprint could not draw
    and the one a reader most needs."""
    return {
        "gone": sorted(k for k in prev if k not in cur),
        "new": sorted(k for k in cur if k not in prev),
        "identical": sorted(k for k in cur if k in prev and cur[k] == prev[k]),
        "changed": sorted(k for k in cur if k in prev and cur[k] != prev[k]),
    }


def _routes(signature: str) -> set:
    return {t for t in (signature or "").split("|") if t.startswith("/")}


def _patterns(rounds: List[Dict[str, Any]]) -> List[str]:
    """Streaks a single round cannot show, stated as measurements.

    Both shapes below were live incidents, and both are invisible from inside
    one round: a defect whose cause never moves, and a defect whose cause
    moves every round on the same route (preconditions being cleared one at a
    time — grant, another grant, confirmation). What they IMPLY is the
    reader's call; the numbers are the machine's.
    """
    real = [_round_cards(r) for r in rounds if not r.get("stall")]
    if len(real) < 3:
        return []
    out = []
    for key in sorted(real[-1]):
        streak = [c[key] for c in real if key in c]
        if len(streak) < 3 or len(streak) != len(real):
            continue  # not present every round — no streak to report
        if len(set(streak)) == 1:
            out.append(f"{key}: {len(streak)} rounds, byte-identical cause each time")
        elif len(set(streak)) == len(streak):
            shared = set.intersection(*(_routes(s) for s in streak)) if streak else set()
            where = f" at {sorted(shared)[0]}" if shared else ""
            out.append(
                f"{key}: {len(streak)} rounds, a different cause each round{where}"
            )
    return out


def _render_attempt_log(rounds: List[Dict[str, Any]], show: int = 4) -> str:
    """Rounds so far, oldest of the window first. Empty until there IS a
    history — a first-round brief must not read as though it were a retry."""
    if len(rounds) < 2:
        return ""
    window = rounds[-show:]
    lines = [
        "=== ATTEMPT LOG (recorded by the system; read it as you would your "
        "own notes) ==="
    ]
    prev_cards: Optional[Dict[str, str]] = None
    prev_n = None
    for entry in window:
        n = entry.get("n")
        if entry.get("stall"):
            lines.append(f"Round {n}: run ended without producing a verdict")
            continue
        cards = _round_cards(entry)
        lines.append(f"Round {n}: {len(cards)} defect{'' if len(cards) == 1 else 's'}")
        for key, sig in sorted(cards.items()):
            lines.append(f"  {key}{('  ' + sig) if sig else ''}")
        if prev_cards is not None:
            d = _delta(prev_cards, cards)
            moved = []
            if d["gone"]:
                moved.append(f"gone: {', '.join(d['gone'])}")
            if d["changed"]:
                moved.append(f"cause changed: {', '.join(d['changed'])}")
            if d["identical"]:
                moved.append(f"cause identical: {', '.join(d['identical'])}")
            if d["new"]:
                moved.append(f"new: {', '.join(d['new'])}")
            if moved:
                lines.append(f"  vs round {prev_n} — " + "; ".join(moved))
        prev_cards, prev_n = cards, n
    for line in _patterns(rounds):
        lines.append(f"Across rounds — {line}")
    return "\n".join(lines)


class FactoryHost:
    """One per process; arcs are per-project, persisted in the project."""

    def __init__(self) -> None:
        self._arcs: Dict[str, Arc] = {}
        self._runtime: Any = None  # SessionRuntimeManager, bound at boot
        self._supervisor: Optional[asyncio.Task] = None
        self._kick_event: Optional[asyncio.Event] = None

    # ── arc access ─────────────────────────────────────────────────────────
    def _project(self, project_id: str):
        from app.agent_app import get_agent_app_manager

        mgr = get_agent_app_manager()
        return mgr.get_project(project_id) if mgr else None

    def arc_for(self, project_id: str) -> Optional[Arc]:
        if project_id in self._arcs:
            return self._arcs[project_id]
        project = self._project(project_id)
        if project is None or not getattr(project, "path", ""):
            return None
        arc = Arc(Path(project.path) / ".factory" / "arc.json")
        self._arcs[project_id] = arc
        return arc

    def _sidecar(self, project_id: str) -> Path:
        project = self._project(project_id)
        return Path(project.path) / ".factory" / "host.json"

    def _sidecar_read(self, project_id: str) -> Dict[str, Any]:
        try:
            return json.loads(self._sidecar(project_id).read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _sidecar_write(self, project_id: str, data: Dict[str, Any]) -> None:
        try:
            path = self._sidecar(project_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except Exception as e:
            logger.debug(f"[FACTORY] sidecar write failed: {e}")

    # ── delivery bookkeeping (sidecar-backed) ──────────────────────────────
    # delivered_at is a COSMETIC timestamp (requirements-staleness warning,
    # announce wording) — never a control input. Every lifecycle predicate
    # is structural: lifecycle.live_db_exists().
    def stamp_delivered(self, project_id: str) -> None:
        side = self._sidecar_read(project_id)
        if side.get("delivered_at"):
            return
        side["delivered_at"] = time.time()
        self._sidecar_write(project_id, side)
        logger.info(f"[FACTORY] {project_id} delivery stamped")

    def delivered_at(self, project_id: str) -> Optional[float]:
        """Epoch time of first delivery (comparable to st_mtime), or None.
        Backs the warn-only requirements-staleness belt — fail-open."""
        value = self._sidecar_read(project_id).get("delivered_at")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    # ── trigger-plane consent (spec TRIGGERS-PLAN) ─────────────────────────
    # An app that can fire the agent can drive a session holding the user's
    # integrations, so fires are gated on consent. First-party builds are
    # approved at creation; marketplace/imported apps stay unapproved until
    # the user explicitly says yes. Fails closed.
    def is_triggers_approved(self, project_id: str) -> bool:
        return bool(self._sidecar_read(project_id).get("triggers_approved"))

    def set_triggers_approved(self, project_id: str, approved: bool = True) -> None:
        side = self._sidecar_read(project_id)
        if bool(side.get("triggers_approved")) == bool(approved):
            return
        side["triggers_approved"] = bool(approved)
        self._sidecar_write(project_id, side)
        logger.info(f"[FACTORY] {project_id} trigger consent set to {bool(approved)}")

    def consent_nudge_due(self, project_id: str) -> bool:
        """True at most once per hour per project: gates the 'this app needs
        trigger approval' ask so a user clicking a refused ⚡ button five
        times gets ONE prompt, not five. READ-ONLY — call mark_consent_nudged
        only after the ask actually queued."""
        side = self._sidecar_read(project_id)
        try:
            last = float(side.get("consent_nudge_at") or 0)
        except (TypeError, ValueError):
            last = 0.0
        return time.time() - last >= 3600

    def mark_consent_nudged(self, project_id: str) -> None:
        side = self._sidecar_read(project_id)
        side["consent_nudge_at"] = time.time()
        self._sidecar_write(project_id, side)

    def bump_throttle_retry(self, project_id: str) -> int:
        """Count LLM-throttled verifier deaths within a rolling hour and
        return the new count. Lets walk_verify say 'wait and retry' a few
        times without burning the arc's unparseable retry on provider rate
        limits, while still escalating if the provider stays down."""
        now = time.time()
        side = self._sidecar_read(project_id)
        try:
            window_start = float(side.get("throttle_window_start") or 0)
        except (TypeError, ValueError):
            window_start = 0.0
        count = side.get("throttle_retries") or 0
        if now - window_start > 3600:
            window_start, count = now, 0
        count = int(count) + 1
        side["throttle_window_start"] = window_start
        side["throttle_retries"] = count
        self._sidecar_write(project_id, side)
        return count

    def set_origin_session(self, project_id: str, session_id: str) -> None:
        """Remember the chat session that requested this build (chat-path
        scaffold), so ready/stuck announcements can be mirrored there —
        without it that agent's last knowledge is 'build is running' and it
        answers later requests from stale state."""
        if not session_id:
            return
        side = self._sidecar_read(project_id)
        side["origin_session"] = session_id
        self._sidecar_write(project_id, side)

    def origin_session(self, project_id: str) -> Optional[str]:
        value = self._sidecar_read(project_id).get("origin_session")
        return str(value) if value else None

    def _notify_origin(self, project_id: str, text: str) -> None:
        """Trigger into the origin chat session (if any): the requesting
        conversation relays the outcome to the user in one sentence and the
        fact lands in that session's stream so later requests resolve against
        current state. Best-effort — never breaks an announce."""
        origin = self.origin_session(project_id)
        if not origin:
            return
        try:
            from app.agent_app import get_agent_app_manager
            from app.triggers import TriggerSource, TriggerSpec

            mgr = get_agent_app_manager()
            if mgr is None or not getattr(mgr, "_trigger_service", None):
                return

            async def _emit() -> None:
                await mgr._trigger_service.emit(
                    TriggerSpec(
                        source=TriggerSource.AGENT_APP_CREATED,
                        description=(
                            f"{text} Relay this to the user in ONE short "
                            "sentence (include the URL if one is present), "
                            "then end the run — no summaries, no next-step "
                            "suggestions. The user is in THIS chat and saw "
                            "no other notification."
                        ),
                        priority=10,
                        session_id=origin,
                        payload={"project_id": project_id},
                    )
                )

            try:
                asyncio.get_running_loop().create_task(_emit())
            except RuntimeError:
                asyncio.run(_emit())
        except Exception as e:
            logger.debug(f"[FACTORY] origin notify failed: {e}")

    # ── backup bookkeeping (sidecar-backed; spec agent-app-backups-plan) ───
    def record_backup_ok(self, project_id: str, ts: float) -> None:
        side = self._sidecar_read(project_id)
        side["backup"] = {"last_at": float(ts)}
        self._sidecar_write(project_id, side)

    def record_backup_error(self, project_id: str, message: str) -> None:
        side = self._sidecar_read(project_id)
        state = side.get("backup")
        state = dict(state) if isinstance(state, dict) else {}
        state["last_error"] = str(message)[:500]
        side["backup"] = state
        self._sidecar_write(project_id, side)

    def backup_state(self, project_id: str) -> Dict[str, Any]:
        """{"last_at": float|None, "last_error": str|None} — always both keys."""
        state = self._sidecar_read(project_id).get("backup")
        state = state if isinstance(state, dict) else {}
        try:
            last_at = (
                float(state["last_at"]) if state.get("last_at") is not None else None
            )
        except (TypeError, ValueError):
            last_at = None
        return {"last_at": last_at, "last_error": state.get("last_error") or None}

    # "A dev environment of this app exists" is now the shadow Instance in the
    # InstanceRegistry (app.agent_app.instances) — a running-process fact, not
    # a sidecar record that could outlive its process. The redirects, the era
    # gate, the log-dir picker and the reaper all resolve it from there.

    # ── arc lifecycle (opened at INTENT, never at first success) ───────────
    def open_arc(self, project_id: str, kind: str) -> None:
        """Open (or re-enter) the supervised arc. Re-entry clears a pause —
        the request IS the resume — and never resets the budget."""
        arc = self.arc_for(project_id)
        if arc is None:
            return
        was_open = arc.is_open
        arc.open(kind)
        if not was_open:
            logger.info(f"[FACTORY] {project_id} {kind} arc opened")
        self.kick()

    def begin_modify(self, project_id: str) -> None:
        """A modify is starting (called from the modify entry points,
        deterministic, never agent-dependent): the whole supervision
        apparatus — fix missions, caps, stuck reports, announcements —
        applies to the modify exactly as to a build."""
        self.open_arc(project_id, ARC_MODIFY)

    def pause_by_user(self, project_id: str) -> None:
        """The user stopped the run. Recorded as INTENT: a paused arc never
        auto-resumes; asking for the work again is the resume."""
        arc = self.arc_for(project_id)
        if arc is None or not arc.is_open or arc.paused:
            return
        arc.pause("user")
        self._emit_chat(
            project_id,
            "⏸ Work on this app is paused because you stopped the run. "
            "Ask for the change again when you want it to continue.",
        )
        logger.info(f"[FACTORY] {project_id} arc paused by user stop")

    # ── outcome reporting (called by the pipeline actions) ─────────────────
    def report_launch_success(self, project_id: str) -> None:
        """notify_ready fully succeeded → the arc now waits on the
        independent verifier."""
        arc = self.arc_for(project_id)
        if arc is None or not arc.is_open:
            return
        arc.set_phase(VERIFYING)
        arc.evidence_of_work()

    def report_verify(
        self,
        project_id: str,
        kind: str,  # pass | defects | incomplete | blocked | unparseable
        defects: Optional[List[str]] = None,
        details: str = "",
        walk_report: str = "",
        server_log: str = "",
        console_lines: Optional[List[str]] = None,
        url: str = "",
        verified: Optional[List[str]] = None,
        caveat: str = "",
        scope_note: str = "",
    ) -> Optional[Decision]:
        """Feed the walk_verify verdict; act on it. Returns the Decision so
        the action can shape its agent-facing text, or None when no arc is
        open (a re-verify after delivery, an app that arrived finished) —
        the action then owns the announcement itself."""
        arc = self.arc_for(project_id)
        if arc is None or not arc.is_open:
            return None
        arc.unpause()  # a verdict arriving IS the work moving

        if kind in ("pass", "incomplete", "blocked"):
            self._announce_ready(
                project_id,
                url,
                verified or [],
                caveat,
                modify=arc.kind == ARC_MODIFY,
                scope_note=scope_note,
            )
            arc.close()
            return Decision("done", payload={"url": url})

        if kind == "unparseable":
            # Fail closed: NEVER announce on an unparseable verdict.
            if arc.unparseable_retried:
                self._announce_stuck(project_id, arc)
                arc.close()
                return Decision("stuck", reason="verifier verdict unparseable twice")
            arc.set_unparseable_retried(True)
            arc.touch()
            return Decision(
                "verifying", reason="re-verify once", payload={"redo": "verify"}
            )

        # defects → DISTILL to cards (cards are the fix-mission input)
        from app.factory.appfactory import distill
        from app.factory.engine.cards import fingerprint_all

        project = self._project(project_id)
        cards = distill(
            walk_report=walk_report or "\n".join(defects or []),
            server_log=server_log,
            console_lines=console_lines or [],
            project_path=str(project.path) if project else "<project>",
            cli=_cli(),
        )
        fp = fingerprint_all(cards) or _fingerprint(details or "verification failed")
        arc.record_round(
            fingerprint=fp,
            # Key AND cause, because the next mission has to be told which
            # of the two moved: same key + new cause is progress, same key
            # + same cause is a fix that missed.
            cards=[{"key": c.key, "sig": c.cause_signature()} for c in cards],
            features=self._defect_feature_names(defects or []),
        )
        arc.set_phase(WORKING)

        if arc.missions_spent >= MISSIONS_CAP:
            self._announce_stuck(project_id, arc)
            arc.close()
            return Decision(
                "stuck", reason=f"mission budget exhausted ({MISSIONS_CAP})"
            )
        if project is None:
            return Decision("stuck", reason="project vanished mid-arc")
        brief = self._compose_fix_brief(project, arc, cards)
        self._emit_mission(project, brief, mission_kind="fix", arc=arc)
        return Decision("fixing")

    def report_blocked(
        self, project_id: str, question: str, ruled_out: Optional[List[str]] = None
    ) -> Optional[Decision]:
        """The agent needs a decision only the user can make. Closes the arc
        with the question — the user gets the question, not a stuck report
        they have to decode. Asking for the change again resumes work."""
        arc = self.arc_for(project_id)
        if arc is None:
            return None
        if not arc.is_open:
            # Nothing is in flight to block. A late call (the run kept going
            # after the build was announced) must not invent a waiting state.
            logger.info(
                f"[FACTORY] ignoring blocked report for {project_id}: no open arc"
            )
            return None
        if ruled_out:
            arc.record_ruled_out(ruled_out)
        question = (question or "").strip()
        self._announce_blocked(project_id, arc, question)
        arc.close()
        logger.warning(f"[FACTORY] {project_id} BLOCKED on a user decision")
        return Decision("blocked", reason=question)

    # ── what the working agent may tell the record ─────────────────────────
    def record_ruled_out(self, project_id: str, items: List[str]) -> int:
        """Causes proved innocent this round. Carried into every later brief."""
        arc = self.arc_for(project_id)
        if arc is None or not arc.is_open:
            return 0
        added = arc.record_ruled_out(items)
        if added:
            logger.info(f"[FACTORY] {project_id} ruled out {added} cause(s)")
        return added

    def record_disputed(self, project_id: str, items: List[str]) -> int:
        """Verdicts the builder reproduced and rejected. Carried into every
        later brief AND into the next verifier's evidence."""
        arc = self.arc_for(project_id)
        if arc is None or not arc.is_open:
            return 0
        added = arc.record_disputed(items)
        if added:
            logger.info(f"[FACTORY] {project_id} disputed {added} verdict(s)")
        return added

    def disputed(self, project_id: str) -> List[Dict[str, Any]]:
        arc = self.arc_for(project_id)
        return arc.disputed() if arc else []

    def get_last_defects(self, project_id: str) -> List[str]:
        """Features the last walk observed broken (empty outside a fix arc)."""
        arc = self.arc_for(project_id)
        return arc.last_defect_features() if arc else []

    # ── run-end / run-start facts ──────────────────────────────────────────
    def on_run_end(
        self,
        project_id: str,
        trigger_payload: Dict[str, Any],
        awaiting_answer: bool = False,
    ) -> None:
        """Called when ANY run in a project session ends. Records the fact
        and kicks the supervisor — no dispatch decision is made here.

        ``awaiting_answer`` marks a run that parked on a question the user
        can answer: that is a pause, not a surrender, and the user's reply
        is the wakeup (a deadline here would just be the system deciding how
        long the agent may wait)."""
        try:
            arc = self.arc_for(project_id)
            if arc is None or not arc.is_open:
                return
            if awaiting_answer:
                arc.pause("question")
                logger.info(
                    f"[FACTORY] {project_id} parked on a question to the user"
                )
                return
            paused = arc.paused
            if paused and paused.get("by") == "question":
                # A run just finished AFTER the question park: the answer
                # arrived and was processed. Whatever remains is supervisable.
                arc.unpause()
            self.kick()
        except Exception as e:
            logger.error(f"[FACTORY] on_run_end failed for {project_id}: {e}")

    def mission_run_started(self, project_id: str, mission_id: str) -> None:
        """The queued mission's run has actually begun — activity, so the
        supervisor's idle clock restarts."""
        arc = self.arc_for(project_id)
        if arc is not None and arc.is_open:
            arc.touch()

    # ── the supervisor (the ONE dispatch decision point) ───────────────────
    def bind_runtime(self, runtime: Any) -> None:
        """Attach the SessionRuntimeManager so ticks can ask 'is a run live
        in this project's session' structurally."""
        self._runtime = runtime

    def start_supervisor(self, runtime: Any = None) -> None:
        """Idempotent; call once the event loop is up (boot). Also runs an
        immediate first tick so arcs frozen by a restart are found now, not
        at the next accidental run-end."""
        if runtime is not None:
            self._runtime = runtime
        if self._supervisor is not None and not self._supervisor.done():
            return
        self._kick_event = asyncio.Event()
        self._kick_event.set()  # first tick immediately
        self._supervisor = asyncio.get_running_loop().create_task(
            self._supervisor_loop(), name="factory-supervisor"
        )
        logger.info("[FACTORY] supervisor started")

    def kick(self, _project_id: str = "") -> None:
        """Wake the supervisor now (run-end, arc open). Safe from any thread
        state — a missed kick only costs one heartbeat."""
        if self._kick_event is not None:
            try:
                self._kick_event.set()
            except Exception:
                pass

    async def _supervisor_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._kick_event.wait(), timeout=_TICK_S)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                return
            self._kick_event.clear()
            try:
                self.supervise_once()
            except Exception as e:
                logger.error(f"[FACTORY] supervisor tick failed: {e}")

    def supervise_once(self) -> List[str]:
        """One pass over every project. Returns the ids acted on (dispatched
        or closed as stuck) — the loop calls this; tests call it directly."""
        from app.agent_app import get_agent_app_manager

        mgr = get_agent_app_manager()
        if mgr is None:
            return []
        acted: List[str] = []
        for project_id, project in list(getattr(mgr, "projects", {}).items()):
            try:
                if self._tick_project(project_id, project):
                    acted.append(project_id)
            except Exception as e:
                logger.error(f"[FACTORY] tick failed for {project_id}: {e}")
        return acted

    def _session_active(self, project) -> bool:
        if self._runtime is None:
            return False  # no runtime bound — backoff alone paces dispatch
        session_id = getattr(project, "session_id", None) or f"lui_{project.id}"
        try:
            return bool(self._runtime.is_session_active(session_id))
        except Exception:
            return False

    def _tick_project(self, project_id: str, project) -> bool:
        arc = self.arc_for(project_id)
        if arc is None or not arc.is_open:
            return False
        if arc.paused:
            return False  # user stop or open question — their move, not ours
        if self._session_active(project):
            return False  # work IS in flight; nothing to conclude
        idle = time.time() - arc.last_activity_at
        if idle < backoff_for(arc.stalls):
            return False
        stalls = arc.bump_stall()
        if stalls >= STALLS_CAP or arc.missions_spent >= MISSIONS_CAP:
            reason = (
                f"{stalls} runs ended without completing the arc"
                if stalls >= STALLS_CAP
                else f"mission budget exhausted ({MISSIONS_CAP})"
            )
            logger.warning(f"[FACTORY] {project_id} stuck: {reason}")
            self._announce_stuck(project_id, arc)
            arc.close()
            return True
        self._dispatch_resume(project_id, project, arc)
        return True

    def _dispatch_resume(self, project_id: str, project, arc: Arc) -> None:
        verb = "MODIFY of" if arc.kind == ARC_MODIFY else "BUILD for"
        log = _render_attempt_log(arc.rounds())
        log_text = f"\n{log}\n" if log else ""
        ruled = arc.ruled_out()
        ruled_text = (
            "\n=== RULED OUT BY EARLIER ROUNDS ===\n"
            + "\n".join(f"- {e['what']}" for e in ruled[-8:])
            + "\n"
            if ruled
            else ""
        )
        brief = (
            f"CONTINUE {verb} Agent App '{project.name}' ({project.id}).\n"
            f"The previous run ended before the change was verified. Continue "
            f"from the current state of {project.path}: finish the work, then\n"
            f'agent_app_notify_ready(project_id="{project.id}") and\n'
            f'agent_app_walk_verify(project_id="{project.id}").\n'
            f"{log_text}{ruled_text}"
            f"The system reports status to the user automatically — do not "
            f"send status messages."
        )
        self._emit_mission(project, brief, mission_kind="resume", arc=arc)
        logger.warning(
            f"[FACTORY] idle open arc — resume dispatched (project={project_id})"
        )

    # ── missions ───────────────────────────────────────────────────────────
    @staticmethod
    def _select_cookbooks(text: str) -> List[str]:
        """Known-good snippets by evidence keywords (weak models copy-adapt
        far better than they synthesize)."""
        from pathlib import Path as _P

        books_dir = _P(__file__).parent / "appfactory" / "cookbooks"
        lowered = text.lower()
        picks = []
        rules = [
            (
                "integration_actions.md",
                (
                    "gmail",
                    "email",
                    "smtp",
                    "mailer",
                    "send_",
                    "callaction",
                    "slack",
                    "notion",
                    "discord",
                    "not granted",
                    "irreversible",
                    "bridge",
                ),
            ),
            (
                "pocketbase_traps.md",
                (
                    "cannot be blank",
                    "not defined",
                    "dao",
                    "404",
                    "migration",
                    "no rows",
                    "panic",
                    "invalid sort",
                    "record(",
                ),
            ),
            (
                "third_party_fetch.md",
                ("http.send", "502", "fetch failed", "statuscode", "api."),
            ),
            (
                "frontend_rules.md",
                (
                    "err_connection",
                    "request failed",
                    "console error",
                    "first paint",
                    "mount",
                ),
            ),
        ]
        for name, keys in rules:
            if any(k in lowered for k in keys):
                path = books_dir / name
                if path.exists():
                    picks.append(path.read_text(encoding="utf-8")[:2200])
        return picks[:2]

    def _compose_fix_brief(self, project, arc: Arc, cards: list) -> str:
        n = arc.missions_spent + 1  # the mission this brief dispatches
        log = _render_attempt_log(arc.rounds())
        log_text = f"\n{log}\n" if log else ""
        ruled = arc.ruled_out()
        ruled_text = (
            "\n=== RULED OUT BY EARLIER ROUNDS (their evidence, not mine) ===\n"
            + "\n".join(f"- {e['what']}" for e in ruled[-8:])
            + "\n"
            if ruled
            else ""
        )
        disputed = arc.disputed()
        disputed_text = (
            "\n=== VERDICTS EARLIER ROUNDS DISPUTED (and why) ===\n"
            + "\n".join(f"- {e['what']}" for e in disputed[-8:])
            + "\nIf one of your cards repeats a disputed verdict, read that "
            "reasoning before you touch code.\n"
            if disputed
            else ""
        )
        cli = _cli()
        cards_text = "\n\n".join(c.render() for c in cards)[:6000]
        books = self._select_cookbooks(cards_text)
        books_text = (
            (
                "\n\n=== PROVEN PATTERNS (copy-adapt; do not invent) ===\n"
                + "\n---\n".join(books)
            )
            if books
            else ""
        )
        # Logs live with the RUNNING instance: the shadow's per-boot state
        # dir when one is up, the project's own logs otherwise. CLI commands
        # always take the PROJECT path — while a shadow exists they route to
        # it automatically (.lui/shadow.json).
        from app.agent_app.instances import get_instance_registry

        _registry = get_instance_registry()
        _dev = _registry.shadow(project.id) if _registry is not None else None
        log_dir = str(_dev.dir) if (_dev is not None and _dev.dir) else str(project.path)
        return f"""FIX MISSION {n} for Agent App '{project.name}' ({project.id}).

The independent verifier drove the app in a real browser. Each DEFECT below
carries its evidence and a repro. Your ONLY goal: make these features work.

=== DEFECT CARDS ===
{cards_text}
{log_text}{ruled_text}{disputed_text}{books_text}

=== HOW TO WORK (concrete) ===
1. Reproduce first: use the repro commands / exercise the failing op
   against the RUNNING shadow instance (CLI calls on the project path are
   routed to it automatically while it is up):
   {cli} run {project.path} <op-name>
2. Read the evidence before theorizing: {log_dir}/logs/pocketbase.log
   (every causal claim must quote a log line; if you can't quote it, gather
   more evidence — "unknown, investigating" is valid, a guess is not).
3. If the error text you are quoting was written by YOUR OWN code, it is not
   evidence of a cause — a catch-all reports one message for every possible
   failure. Before fixing, make it tell the truth:
       catch (err) {{ return e.json(400, {{ error: 'Invalid payload' }}) }}   // says nothing
       catch (err) {{ return e.json(400, {{ error: String(err) }}) }}         // says everything
   Relaunch, reproduce, read the REAL exception, then fix that. Spending one
   round to learn the cause beats two rounds guessing at it — a fix aimed at
   a message your own handler invented will not work.
4. Fix in {project.path} (hooks/migrations/frontend per the ownership rules)
   — agent_app_notify_ready boots a fresh shadow running your edits.
5. Relaunch: agent_app_notify_ready(project_id="{project.id}")
6. Verify: agent_app_walk_verify(project_id="{project.id}")
Three things you can write into the record. All optional; all are read by
every later round, and each round is a fresh run that remembers nothing of
this one, so what you do not write here is not known next time.

   agent_app_report_finding(project_id="{project.id}",
       ruled_out=["the grant is fine — dry-run of send_gmail returns 200"])
       Your notes: causes you eliminated, and what eliminated them.

   agent_app_report_finding(project_id="{project.id}",
       disputed=["AI Explore — I ran it against the dev instance, the graph
       went 1 -> 5 nodes with AI-written ideas, and the hook evidence above
       confirms callLLM at ops.pb.js:32. The verdict is wrong; nothing here
       is broken."])
       The verifier can be wrong, and you are the only one who can find out
       — you can reproduce the feature; it only watched it once. If you did
       reproduce it and it works, say so HERE rather than editing code that
       is not broken. Your reasoning goes to the next verifier, which must
       re-judge that feature knowing what you observed. Use it on evidence
       you gathered, never to skip a defect you have not reproduced.

   agent_app_report_finding(project_id="{project.id}",
       blocked_question="Which calendar should new bookings write to?")
       Ends the work and puts one question to the user. It is for something
       you cannot GET — a decision, an account, a credential — not something
       you have not yet solved. It is also the only way to stop that the
       system does not read as walking out of the room.

How you use the round is yours. The system tracks attempts and reports
status to the user — do NOT send status messages; when verification passes
the user is informed automatically."""

    def _emit_mission(self, project, brief: str, mission_kind: str, arc: Arc) -> None:
        from app.agent_app import get_agent_app_manager

        mgr = get_agent_app_manager()
        if mgr is None or not getattr(mgr, "_trigger_service", None):
            logger.error("[FACTORY] cannot dispatch mission — trigger service unbound")
            return
        session = mgr.ensure_project_session(project)
        if not session:
            logger.error("[FACTORY] cannot dispatch mission — no project session")
            return
        mission_id = f"{mission_kind}-{int(time.time())}"

        # Modify arcs get the modify skill — dev-env semantics and the
        # never-touch-pb_data rules live there; build arcs keep the full
        # creator workflow. The arc KIND was recorded at open time, so this
        # is one enum read, not an archaeology of archived generations.
        workflow_skill = (
            "agent-app-modify" if arc.kind == ARC_MODIFY else "agent-app-creator"
        )

        async def _emit() -> None:
            from app.triggers import TriggerSource, TriggerSpec

            await mgr._trigger_service.emit(
                TriggerSpec(
                    source=TriggerSource.AGENT_APP_CRASH_FIX,  # existing fix-run source
                    description=brief,
                    priority=30,
                    session_id=session.id,
                    payload={
                        "project_id": project.id,
                        "factory_mission_id": mission_id,
                        "workflow_skills": [workflow_skill],
                    },
                )
            )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_emit())
        except RuntimeError:
            asyncio.run(_emit())
        arc.mission_dispatched(mission_id)
        logger.info(f"[FACTORY] dispatched {mission_id} for {project.id}")

    # ── machine-composed status (no agent announcements) ───────────────────
    def _emit_chat(self, project_id: str, text: str) -> None:
        try:
            from app.internal_action_interface import InternalActionInterface as I
            from app.agent_app import get_agent_app_manager
            from agent_core.core.event_stream.event import EventType

            mgr = get_agent_app_manager()
            project = mgr.get_project(project_id) if mgr else None
            session = mgr.ensure_project_session(project) if (mgr and project) else None
            if I.event_stream_manager and session:
                I.event_stream_manager.log(
                    kind="factory_status",
                    message=text,
                    # A SYSTEM note, not the agent speaking: the agent is free
                    # to add its own sentence, or not. Nothing forces it to.
                    event_type=EventType.SYSTEM,
                    display_message=text,
                    task_id=session.id,
                )
        except Exception as e:
            logger.debug(f"[FACTORY] chat emit failed: {e}")

    @staticmethod
    def _defect_feature_names(defects: List[str]) -> List[str]:
        """'- <feature> — FAIL — …' lines → feature names (fix-mission scope)."""
        import re as _re

        names: List[str] = []
        for line in defects:
            m = _re.match(
                r"^-?\s*(.{1,160}?)\s*(?:—|–|:|-)\s*FAIL\b", str(line).strip()
            )
            name = (m.group(1) if m else str(line)).strip(" -")
            if name and name not in names:
                names.append(name[:160])
        return names[:20]

    def _announce_ready(
        self,
        project_id: str,
        url: str,
        verified: List[str],
        caveat: str,
        modify: bool = False,
        scope_note: str = "",
    ) -> None:
        # Plain, user-facing outcome only. No URL (the user is already in the
        # CraftBot interface), no feature counts, no scope/verifier internals.
        # Name the app so the message reads about THEIR app, not a generic one.
        project = self._project(project_id)
        name = (getattr(project, "name", "") or "").strip()
        if modify:
            text = (
                f'✅ Your change to "{name}" is live.'
                if name
                else "✅ Your change is live."
            )
        else:
            text = (
                f'✅ Your app "{name}" is ready.' if name else "✅ Your app is ready."
            )
        if caveat:
            text += f"\n⚠️ {caveat}"
        self._emit_chat(project_id, text)
        self._notify_origin(
            project_id,
            f"FYI: the Agent App build for project {project_id} is COMPLETE. {text}",
        )

    def announce_undeployed(self, project_id: str, name: str) -> None:
        """This project holds code the running app has not been given.

        Said by the SYSTEM because the agent's own account cannot be trusted
        here (2026-09-02, brainstorm_graph f1eb1c85: three "Done —" claims
        while the running app never changed). Phrased as a STATE, not an act:
        the trigger is a tree that differs from the last promote, which can
        be true on a run that edited nothing."""
        self._emit_chat(
            project_id,
            f"⚠️ {name} has code changes that were never deployed — your live "
            "app is still running the previous version. Tell me to deploy it "
            "and I'll relaunch and verify.",
        )

    def _announce_blocked(self, project_id: str, arc: Arc, question: str) -> None:
        self._emit_chat(project_id, "🙋 " + arc.blocked_report(question))
        self._notify_origin(
            project_id,
            f"FYI: the Agent App build for project {project_id} is waiting on a "
            f"decision from the user: {question[:300]}",
        )
        try:
            from app.agent_app.broadcast import broadcast_agent_app_progress

            coroutine = broadcast_agent_app_progress(
                project_id, "error", 100, "Waiting on your answer — see chat"
            )
            try:
                asyncio.get_running_loop().create_task(coroutine)
            except RuntimeError:
                asyncio.run(coroutine)
        except Exception as e:
            logger.debug(f"[FACTORY] blocked broadcast failed: {e}")

    def _announce_stuck(self, project_id: str, arc: Arc) -> None:
        self._emit_chat(project_id, "❌ " + arc.stuck_report())
        self._notify_origin(
            project_id,
            f"FYI: the Agent App build for project {project_id} is STUCK "
            "(could not be completed automatically; the user has the full "
            "report in the project tab).",
        )
        try:
            from app.agent_app.broadcast import broadcast_agent_app_progress

            coroutine = broadcast_agent_app_progress(
                project_id, "error", 100, "Build stuck — see the report in chat"
            )
            try:
                asyncio.get_running_loop().create_task(coroutine)
            except RuntimeError:
                asyncio.run(coroutine)
        except Exception as e:
            logger.debug(f"[FACTORY] stuck broadcast failed: {e}")


_HOST: Optional[FactoryHost] = None


def get_factory_host() -> FactoryHost:
    global _HOST
    if _HOST is None:
        _HOST = FactoryHost()
    return _HOST
