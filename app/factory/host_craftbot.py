# -*- coding: utf-8 -*-
"""CraftBot host adapter for the Factory (FACTORY-PLAN §5 Phase 1).

HOST layer: may import app.* freely; nothing in engine/appfactory imports it.

Phase-1 scope (deliberate, per plan):
- The machine owns the VERIFY→FIX arc, redispatch-on-surrender, caps, and all
  user-facing ready/stuck status — the empirically failing parts.
- The tight gate-error loop inside one run (types → fix → relaunch) stays
  agent-owned for now: it is per-STEP work and measured competent. Phase 3
  moves it onto the ACI runner.
- Missions are fresh triggers into the project's session, _escalate_crash
  style (the proven prototype): concrete brief, ready-made calls, high
  priority. Stream reset is NOT attempted in Phase 1 (plan R3): a fresh
  concrete instruction alone was the "100% of observed cases" mechanism.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.factory.appfactory import (
    BUILDING,
    FIXING,
    GATING,
    LAUNCHING,
    MODIFYING,
    VERIFYING,
    transition,
)
from app.factory.engine import (
    ANNOUNCE_BLOCKED,
    ANNOUNCE_READY,
    ANNOUNCE_STUCK,
    DISPATCH_MISSION,
    DONE,
    STUCK,
    Caps,
    Decision,
    Machine,
    Outcome,
)

try:
    from app.logger import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

_REDISPATCH_MIN_INTERVAL_S = 20  # thrash guard on the run-end hook


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
    """One per process; machines are per-project, persisted in the project."""

    def __init__(self) -> None:
        self._machines: Dict[str, Machine] = {}

    # ── machine access ─────────────────────────────────────────────────────
    def _project(self, project_id: str):
        from app.agent_app import get_agent_app_manager

        mgr = get_agent_app_manager()
        return mgr.get_project(project_id) if mgr else None

    def machine_for(self, project_id: str) -> Optional[Machine]:
        if project_id in self._machines:
            return self._machines[project_id]
        project = self._project(project_id)
        if project is None:
            return None
        store = Path(project.path) / ".factory" / "state.json"
        machine = Machine(transition, store, initial_state=BUILDING, caps=Caps())
        self._machines[project_id] = machine
        return machine

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
    # announce wording) — never a control input. The retired "delivered"
    # flag used to pick the data-safety mode and went stale on real apps
    # (2026-08-19: a two-week-in-use CRM read as never-delivered and its
    # live DB was wiped by the first-delivery baseline restore). Every
    # lifecycle predicate is now structural: lifecycle.live_db_exists().
    def stamp_delivered(self, project_id: str) -> None:
        side = self._sidecar_read(project_id)
        if side.get("delivered_at"):
            return
        side["delivered_at"] = time.time()
        self._sidecar_write(project_id, side)
        logger.info(f"[FACTORY] {project_id} delivery stamped")

    # ── trigger-plane consent (spec TRIGGERS-PLAN) ─────────────────────────
    # An app that can fire the agent can drive a session holding the user's
    # integrations, so fires are gated on consent. First-party builds are
    # approved at creation (the user asked for the app and the agent authored
    # its triggers); marketplace/imported apps stay unapproved until the user
    # explicitly says yes. Fails closed: no flag → no fires reach the agent.
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
        times gets ONE prompt, not five (observed live 2026-08-06: three
        silent consent-blocks in as many minutes). READ-ONLY — call
        mark_consent_nudged only after the ask actually queued, or a failed
        ask suppresses every retry for an hour (also observed live: the
        13:52 ask died silently and the 14:17 block was then capped)."""
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
        times without the machine burning its unparseable retry on provider
        rate limits (observed live 2026-08-06: two walkers died on rate
        limits 4 seconds apart and a healthy modify went STUCK), while still
        escalating for real if the provider stays down."""
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
        answers later requests from stale state (observed live 2026-08-05)."""
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
            import asyncio

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

    def delivered_at(self, project_id: str) -> Optional[float]:
        """Epoch time of first delivery (comparable to st_mtime), or None.
        Backs the warn-only requirements-staleness belt — fail-open."""
        value = self._sidecar_read(project_id).get("delivered_at")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    # ── backup bookkeeping (sidecar-backed; spec agent-app-backups-plan) ───
    # last_at drives the scheduler's due check (absent -> due now, which is
    # also the catch-up-after-restart path); last_error is surfaced on the
    # settings card and cleared by the next success.
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

    def begin_modify(self, project_id: str) -> None:
        """A modify of an app with a live database is starting (called from
        open_dev success — deterministic, never agent-dependent):
        re-arm the machine into MODIFYING so the whole supervision apparatus
        (fix missions, caps, stuck reports, announcements) applies to the
        modify exactly as it did to the build (LIFECYCLE-PLAN Phase 2).

        Reopen when the machine is TERMINAL (a finished build/modify arc) or
        VIRGIN (no history — machine_for mints BUILDING for marketplace/
        imported apps that never had an arc). A non-terminal machine WITH
        history means a modify/fix arc is already in flight — a fix
        mission's notify_ready re-enters open_dev — so no-op.
        """
        machine = self.machine_for(project_id)
        if machine is None:
            return
        if not machine.terminal and machine.history():
            return
        machine.reopen(MODIFYING)
        # Build-era leftovers must not leak into the new arc: a stale
        # last_brief would make on_run_end resume a build-era fix mission
        # into this modify.
        side = self._sidecar_read(project_id)
        for key in ("last_brief", "verify_retried", "running_mission"):
            side.pop(key, None)
        self._sidecar_write(project_id, side)
        logger.info(
            f"[FACTORY] {project_id} reopened for modify "
            f"(generation {machine.generation})"
        )

    # The staging record is the single source of truth for "a dev environment
    # of this app exists": actions redirect to it, the reaper kills from it,
    # and clearing it is what ends dev mode. (Key name "staging" is
    # historical — kept so records from older versions stay readable.)
    def get_staging_record(self, project_id: str) -> Optional[Dict[str, Any]]:
        record = self._sidecar_read(project_id).get("staging")
        return record if isinstance(record, dict) else None

    def set_staging_record(self, project_id: str, record: Dict[str, Any]) -> None:
        side = self._sidecar_read(project_id)
        side["staging"] = record
        self._sidecar_write(project_id, side)

    def clear_staging_record(self, project_id: str) -> None:
        side = self._sidecar_read(project_id)
        if side.pop("staging", None) is not None:
            self._sidecar_write(project_id, side)

    # ── outcome reporting (called by the pipeline actions) ─────────────────
    def _normalize_to(self, machine: Machine, target: str) -> None:
        """Advance through implicit-ok states so outcomes land on the right
        state (a mission that reaches walk_verify implicitly passed its
        earlier states). Never dispatches: BUILD/FIX ok and GATE/LAUNCH ok
        transitions carry no mission action."""
        order = [BUILDING, MODIFYING, FIXING, GATING, LAUNCHING, VERIFYING]
        guard = 0
        while machine.state != target and machine.state in order and guard < 6:
            machine.advance(Outcome(machine.state, ok=True))
            guard += 1

    def report_launch_success(self, project_id: str) -> None:
        """notify_ready fully succeeded → the machine is now waiting on the
        independent verifier."""
        machine = self.machine_for(project_id)
        if machine is None or machine.terminal:
            return
        self._normalize_to(machine, VERIFYING)
        side = self._sidecar_read(project_id)
        side.pop("verify_retried", None)
        self._sidecar_write(project_id, side)

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
        """Feed the walk_verify verdict; act on the machine's Decision.
        Returns the Decision so the action can shape its agent-facing text.
        `scope_note` is the verifier's scope in one clause ('' = full walk)
        for the ready announcement."""
        # Fix-mission input for the NEXT verify: the features observed broken
        # (must-include), cleared on any clean verdict.
        try:
            side = self._sidecar_read(project_id)
            if kind == "defects":
                side["last_defects"] = self._defect_feature_names(defects or [])
                self._sidecar_write(project_id, side)
            elif (
                kind in ("pass", "incomplete", "blocked")
                and side.pop("last_defects", None) is not None
            ):
                self._sidecar_write(project_id, side)
        except Exception as e:
            logger.debug(f"[FACTORY] last_defects bookkeeping failed: {e}")
        machine = self.machine_for(project_id)
        if machine is None:
            return None
        if machine.terminal:
            if machine.state == STUCK:
                # A fresh verify verdict on a stuck arc means someone (the
                # user, via the agent) made a new fix attempt: re-arm with a
                # fresh mission budget so the factory loop resumes. Ignoring
                # the verdict here stranded the agent — no mission dispatched,
                # while the walk_verify action still promised one.
                machine.reopen(VERIFYING)
                # Stuck-era leftovers must not leak into the new arc (same
                # hygiene as begin_modify): a stale last_brief would make
                # on_run_end resume a dead mission into this arc.
                side = self._sidecar_read(project_id)
                for key in ("last_brief", "verify_retried", "running_mission"):
                    side.pop(key, None)
                self._sidecar_write(project_id, side)
                logger.info(
                    f"[FACTORY] {project_id} stuck arc re-armed by fresh "
                    f"verify (generation {machine.generation})"
                )
            else:
                # A re-verify after done (e.g. modify flows Phase 2+); ignore.
                return None
        self._normalize_to(machine, VERIFYING)

        if kind in ("pass", "incomplete", "blocked"):
            decision = machine.advance(
                Outcome(
                    VERIFYING, ok=True, payload={"url": url, "verified": verified or []}
                )
            )
            if decision.action == ANNOUNCE_READY:
                # "Your change is live" only when the PREVIOUS arc actually
                # delivered (final_state done) — a virgin re-arm (adapt
                # install, import verify) is still the app's first delivery.
                # The staging record is already cleared by the flip, so the
                # machine is the only witness either way.
                generations = machine.generations()
                self._announce_ready(
                    project_id,
                    url,
                    verified or [],
                    caveat,
                    modify=bool(generations)
                    and generations[-1].get("final_state") == DONE,
                    scope_note=scope_note,
                )
            return decision

        if kind == "unparseable":
            side = self._sidecar_read(project_id)
            already = bool(side.get("verify_retried"))
            side["verify_retried"] = True
            self._sidecar_write(project_id, side)
            decision = machine.advance(
                Outcome(
                    VERIFYING,
                    ok=False,
                    payload={"unknown_verdict": True, "already_retried": already},
                )
            )
            if decision.action == ANNOUNCE_STUCK:
                self._announce_stuck(project_id, machine)
            return decision

        # defects → DISTILL to cards (E3: cards are the fix-mission input)
        from app.factory.appfactory.distill import distill

        project = self._project(project_id)
        cards = distill(
            walk_report=walk_report or "\n".join(defects or []),
            server_log=server_log,
            console_lines=console_lines or [],
            project_path=str(project.path) if project else "<project>",
            cli=_cli(),
        )
        # Fingerprint = the identity of the whole outstanding defect SET, cause
        # included. cards[0].fingerprint() keyed on the first card's feature
        # NAME, so a loop that was clearing one gate per round looked identical
        # every round and hit the cap while still making progress.
        from app.factory.engine.cards import fingerprint_all

        fp = fingerprint_all(cards) or _fingerprint(
            details or "verification failed"
        )
        decision = machine.advance(
            Outcome(
                VERIFYING,
                ok=False,
                fingerprint=fp,
                # Key AND cause, because the next mission has to be told which
                # of the two moved: same key + new cause is progress, same key
                # + same cause is a fix that missed. A list of keys cannot
                # tell them apart.
                payload={
                    "cards": [
                        {"key": c.key, "sig": c.cause_signature()} for c in cards
                    ]
                },
            )
        )
        if decision.action == DISPATCH_MISSION:
            self._dispatch_fix_mission(project_id, machine, decision, cards)
        elif decision.action == ANNOUNCE_STUCK:
            self._announce_stuck(project_id, machine)
        return decision

    # ── missions ───────────────────────────────────────────────────────────
    @staticmethod
    def _select_cookbooks(text: str) -> List[str]:
        """Known-good snippets by evidence keywords (weak models copy-adapt
        far better than they synthesize — E6/I3)."""
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

    def _compose_fix_brief(
        self, project, machine: Machine, decision: Decision, cards: list
    ) -> str:
        n = len([h for h in machine.history() if h["action"] == DISPATCH_MISSION])
        # No "do something DIFFERENT" line any more. It was the machine
        # telling the agent how to work off a repeat count, which is the same
        # mistake the retry cap made — and unanswerable anyway to a mission
        # that could not see what the previous one did. The log below says
        # what happened; the approach is the agent's.
        log = _render_attempt_log(machine.rounds())
        log_text = f"\n{log}\n" if log else ""
        ruled = machine.ruled_out()
        ruled_text = (
            "\n=== RULED OUT BY EARLIER ROUNDS (their evidence, not mine) ===\n"
            + "\n".join(f"- {e['what']}" for e in ruled[-8:])
            + "\n"
            if ruled
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
        # The RUNNING instance is the dev environment when one is up —
        # repro commands and logs must target it, not the (possibly not even
        # running) live project dir.
        _dev_rec = self.get_staging_record(project.id)
        run_dir = (
            str(_dev_rec.get("dir"))
            if _dev_rec and _dev_rec.get("dir")
            else str(project.path)
        )
        return f"""FIX MISSION {n} for Agent App '{project.name}' ({project.id}).

The independent verifier drove the app in a real browser. Each DEFECT below
carries its evidence and a repro. Your ONLY goal: make these features work.

=== DEFECT CARDS ===
{cards_text}
{log_text}{ruled_text}{books_text}

=== HOW TO WORK (concrete) ===
1. Reproduce first: use the repro commands / exercise the failing op
   against the RUNNING dev instance:
   {cli} run {run_dir} <op-name>
2. Read the evidence before theorizing: {run_dir}/logs/pocketbase.log
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
   — agent_app_notify_ready syncs your edits into the dev instance.
5. Relaunch: agent_app_notify_ready(project_id="{project.id}")
6. Verify: agent_app_walk_verify(project_id="{project.id}")
Two things you can write into the record. Both optional; both are read by
every later round, and each round is a fresh run that remembers nothing of
this one, so what you do not write here is not known next time.

   agent_app_report_finding(project_id="{project.id}",
       ruled_out=["the grant is fine — dry-run of send_gmail returns 200"])
       Your notes: causes you eliminated, and what eliminated them.

   agent_app_report_finding(project_id="{project.id}",
       blocked_question="Which calendar should new bookings write to?")
       Ends the work and puts one question to the user. It is for something
       you cannot GET — a decision, an account, a credential — not something
       you have not yet solved. It is also the only way to stop that the
       system does not read as walking out of the room.

How you use the round is yours. The system tracks attempts and reports
status to the user — do NOT send status messages; when verification passes
the user is informed automatically."""

    def _dispatch_fix_mission(
        self, project_id: str, machine: Machine, decision: Decision, cards: list
    ) -> None:
        project = self._project(project_id)
        if project is None:
            return
        brief = self._compose_fix_brief(project, machine, decision, cards)
        side = self._sidecar_read(project_id)
        side["last_brief"] = brief
        self._sidecar_write(project_id, side)
        self._emit_mission(project, brief, mission_kind="fix", machine=machine)

    def _emit_mission(
        self, project, brief: str, mission_kind: str, machine: Machine
    ) -> None:
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

        # Modify-era missions (a reopened machine) get the modify skill —
        # dev-env semantics and the never-touch-pb_data rules live there;
        # build-era missions keep the full creator workflow. A machine
        # re-armed from a stuck BUILD (no live database yet — no user data
        # to protect) is still build-era despite generation > 0; a stuck
        # MODIFY of an app with live data keeps the modify skill.
        gens = machine.generations()
        try:
            from app.agent_app.lifecycle import has_live_env

            _has_live = has_live_env(project, self)
        except Exception:
            _has_live = False
        resumed_stuck_build = (
            bool(gens) and gens[-1].get("final_state") == STUCK and not _has_live
        )
        workflow_skill = (
            "agent-app-modify"
            if machine.generation > 0 and not resumed_stuck_build
            else "agent-app-creator"
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

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_emit())
        except RuntimeError:
            asyncio.run(_emit())
        machine.mission_started(mission_id)
        logger.info(f"[FACTORY] dispatched {mission_id} for {project.id}")

    def mission_run_started(self, project_id: str, mission_id: str) -> None:
        """The queued mission's run has actually begun. Lets a later run-end
        WITHOUT a mission id (run_continuation triggers carry none) still be
        attributed to the running mission."""
        side = self._sidecar_read(project_id)
        side["running_mission"] = mission_id
        self._sidecar_write(project_id, side)

    # ── run-end hook (closes I6) ───────────────────────────────────────────
    def on_run_end(self, project_id: str, trigger_payload: Dict[str, Any]) -> None:
        """Called by the host when ANY run in a project session ends. If the
        machine says work should be in flight but isn't, redispatch — the
        agent surrendering is no longer a terminal event."""
        try:
            machine = self.machine_for(project_id)
            if machine is None:
                return
            side = self._sidecar_read(project_id)
            mission_id = (trigger_payload or {}).get("factory_mission_id")
            if (
                not mission_id
                and machine.active_mission
                and (side.get("running_mission") == machine.active_mission)
            ):
                # This run belonged to the active mission (it started via the
                # mission trigger; the FINAL trigger of the run was a
                # continuation with no id).
                mission_id = machine.active_mission
            if mission_id:
                machine.mission_ended(str(mission_id))
                if side.get("running_mission") == str(mission_id):
                    side.pop("running_mission", None)
                    self._sidecar_write(project_id, side)
            if not machine.needs_redispatch():
                return
            # Thrash guard: history timestamps are UTC ("...Z"); parse them
            # as UTC (calendar.timegm) — time.mktime read them as LOCAL time,
            # skewing the guard by the UTC offset (never tripping in +offset
            # zones). A freshly reopened machine has an empty history — fall
            # back to the archived generation's closed_at so the first
            # modify run-end can't redispatch instantly either.
            import calendar as _calendar

            last = ""
            history = machine.history()
            if history:
                last = history[-1].get("at", "")
            else:
                generations = machine.generations()
                if generations:
                    last = generations[-1].get("closed_at", "")
            if last:
                try:
                    last_ts = _calendar.timegm(
                        time.strptime(last, "%Y-%m-%dT%H:%M:%SZ")
                    )
                    elapsed = time.time() - last_ts
                    if elapsed < _REDISPATCH_MIN_INTERVAL_S:
                        # NEVER drop the wakeup. This suppression used to be a
                        # bare return — and when the guard trips on the LAST
                        # run's end there is nothing left to re-fire it:
                        # observed live 2026-08-05 (Rock Bottom Outreach
                        # Automator), a 5s surrender was suppressed and the
                        # build sat stale at 'fixing' forever. Re-check after
                        # the guard interval instead; idempotent — if a
                        # mission became active meanwhile, needs_redispatch
                        # is False and the re-check no-ops.
                        delay = max(1.0, _REDISPATCH_MIN_INTERVAL_S - elapsed + 1.0)
                        try:
                            import asyncio as _asyncio

                            _asyncio.get_running_loop().call_later(
                                delay, self.on_run_end, project_id, {}
                            )
                            logger.info(
                                f"[FACTORY] redispatch deferred {delay:.0f}s "
                                f"(thrash guard) for {project_id}"
                            )
                        except RuntimeError:
                            logger.warning(
                                f"[FACTORY] thrash guard tripped with no event "
                                f"loop — {project_id} may need a manual nudge"
                            )
                        return
                except Exception:
                    pass
            project = self._project(project_id)
            if project is None:
                return

            # A redispatch is a MACHINE event, not a free retry: feed the
            # surrender through advance() so the budget applies and the
            # STALL cap can trip. Without this, resumes bypassed everything:
            # observed live (chili3d, 2026-08-05) a fix agent that correctly
            # judged a defect unfixable end_turned into a 37-cycle redispatch
            # loop, one LLM call every ~7s, until CraftBot was killed. This
            # is the one place stall=True is set, and the reason the stall
            # cap survived the removal of the per-failure one: a run that
            # produced no verdict is not an attempt at anything.
            decision = machine.advance(
                Outcome(
                    machine.state,
                    ok=False,
                    fingerprint="surrender-loop",
                    stall=True,
                    payload={"reason": "run ended without completing the arc"},
                )
            )
            if machine.terminal or decision.action == ANNOUNCE_STUCK:
                self._announce_stuck(project_id, machine)
                logger.warning(
                    f"[FACTORY] surrender loop capped — {project_id} is stuck "
                    f"(state {machine.state})"
                )
                return

            side = self._sidecar_read(project_id)
            _verb = "MODIFY of" if machine.generation > 0 else "BUILD for"
            brief = side.get("last_brief") or (
                f"CONTINUE {_verb} Agent App '{project.name}' ({project.id}).\n"
                f"The previous run ended before the change was verified. Continue from "
                f"the current state of {project.path}: finish the work, then\n"
                f'agent_app_notify_ready(project_id="{project.id}") and\n'
                f'agent_app_walk_verify(project_id="{project.id}").\n'
                f"The system reports status to the user automatically — do not send "
                f"status messages."
            )
            brief = (
                "PREVIOUS ATTEMPT ENDED WITHOUT COMPLETING.\n\n" + brief
                if side.get("last_brief")
                else brief
            )
            self._emit_mission(project, brief, mission_kind="resume", machine=machine)
            logger.warning(
                f"[FACTORY] run ended with machine at '{machine.state}' and no active "
                f"mission — redispatched (project={project_id})"
            )
        except Exception as e:
            logger.error(f"[FACTORY] on_run_end failed for {project_id}: {e}")

    # ── what the working agent may tell the machine ────────────────────────
    # Two reports, and neither is a self-assessment of the code (E2 still
    # holds: only the verifier says whether the app works). One is evidence
    # the agent gathered; the other is a question it cannot answer alone.
    def record_ruled_out(self, project_id: str, items: List[str]) -> int:
        """Causes proved innocent this round. Carried into every later brief."""
        machine = self.machine_for(project_id)
        if machine is None:
            return 0
        added = machine.record_ruled_out(items, mission=machine.active_mission or "")
        if added:
            logger.info(f"[FACTORY] {project_id} ruled out {added} cause(s)")
        return added

    def report_blocked(
        self, project_id: str, question: str, ruled_out: Optional[List[str]] = None
    ) -> Optional[Decision]:
        """The agent needs a decision only the user can make. Ends the arc in
        BLOCKED — a terminal that carries a question, so the user gets the
        question instead of a stuck report they have to decode. Reopening the
        machine (the answer arrives, the user asks for a change) resumes work
        normally."""
        machine = self.machine_for(project_id)
        if machine is None:
            return None
        if machine.terminal:
            # Nothing is in flight to block. A late call (the run kept going
            # after the build was announced) must not drag a delivered app
            # back into a waiting state.
            logger.info(
                f"[FACTORY] ignoring blocked report for {project_id}: "
                f"machine is already {machine.state}"
            )
            return None
        if ruled_out:
            machine.record_ruled_out(ruled_out, mission=machine.active_mission or "")
        question = (question or "").strip()
        decision = machine.advance(
            Outcome(
                machine.state,
                ok=False,
                payload={"blocked": True, "question": question},
            )
        )
        if decision.action == ANNOUNCE_BLOCKED:
            self._announce_blocked(project_id, machine, question)
        logger.warning(f"[FACTORY] {project_id} BLOCKED on a user decision")
        return decision

    # ── machine-composed status (§3.6: retire agent announcements) ─────────
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
                    event_type=EventType.AGENT_MESSAGE,
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

    def get_last_defects(self, project_id: str) -> List[str]:
        """Features the last walk observed broken (empty outside a fix arc)."""
        side = self._sidecar_read(project_id)
        val = side.get("last_defects")
        return [str(x) for x in val] if isinstance(val, list) else []

    def _announce_ready(
        self,
        project_id: str,
        url: str,
        verified: List[str],
        caveat: str,
        modify: bool = False,
        scope_note: str = "",
    ) -> None:
        n = len(verified)
        lead = (
            f"✅ Your change is live at {url}"
            if modify
            else f"✅ The app is ready at {url}"
        )
        scoped = f" ({scope_note})" if scope_note else ""
        text = lead + (
            f" — {n} feature(s) verified in a real browser{scoped}." if n else "."
        )
        if caveat:
            text += f"\n⚠️ {caveat}"
        self._emit_chat(project_id, text)
        self._notify_origin(
            project_id,
            f"FYI: the Agent App build for project {project_id} is COMPLETE. {text}",
        )

    def _announce_blocked(
        self, project_id: str, machine: Machine, question: str
    ) -> None:
        self._emit_chat(project_id, "🙋 " + machine.blocked_report(question))
        self._notify_origin(
            project_id,
            f"FYI: the Agent App build for project {project_id} is waiting on a "
            f"decision from the user: {question[:300]}",
        )
        try:
            import asyncio

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

    def _announce_stuck(self, project_id: str, machine: Machine) -> None:
        self._emit_chat(project_id, "❌ " + machine.stuck_report())
        self._notify_origin(
            project_id,
            f"FYI: the Agent App build for project {project_id} is STUCK "
            "(could not be completed automatically; the user has the full "
            "report in the project tab).",
        )
        try:
            import asyncio

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
