# -*- coding: utf-8 -*-
"""The deterministic workflow — one engine, domains as subclasses.

A :class:`Workflow` drives a task deterministically through the
one loop every "produce something and prove it works" domain shares:

    wait for the user → answer the user → bootstrap → WORK round (spawn the
    domain's worker agent) → independent CHECK (spawn the domain's checker
    agent) → budget-gated last-resort ask → present → end

Control flow lives in CODE; the LLM lives inside the steps (the worker agent
runs its own full agentic loop, and the model writes every user-facing
message through bounded "llm" steps). Handing these loop decisions to the
model is the historical failure mode this class exists to prevent: models
self-certify unfinished work, skip verification, and end tasks early.

A domain is ONE subclass (runtime shape: task → its program, resolved by the
task's ``workflow_id`` through the workflow registry — tasks persist across
restarts, so they carry a name, never a live object):

    class HotelBookingWorkflow(Workflow):
        name = "hotel_booking"
        system_prompt = "..."          # task surface (prompt dressing)
        worker_agent = "booking_agent" # engine surface (the loop)
        checker_agent = "confirmation_checker"

        def resolve_subject(self, task): ...
        def state_dir(self, subject): ...
        def is_bootstrapped(self, ctx): ...
        def work_query(self, ctx): ...
        def check_query(self, ctx): ...

    register_workflow(HotelBookingWorkflow())

The engine is roughly a third of a real domain. A new domain also needs:
its worker/checker subagents (``app/workflows/<domain>/subagents/``), tasks
created with its ``workflow_id``, an OUTCOME TAP — something that calls
:meth:`record_work_outcome` / :meth:`record_check_outcome` when work
finishes (Living UI uses its launch pipeline result and the spawn tap in
construction_events) — and a subject whose directory can hold the durable
:class:`WorkState`.

Checker contract: the checker agent's result must end with
``VERDICT: PASS | FAIL | BLOCKED``. FAIL means it OBSERVED the work product
misbehaving (its report becomes the next round's work order); BLOCKED means
it could not exercise the work product at all (retried up to
``check_attempt_budget``, then the worker is told to verify by its own
means). A domain with ``checker_agent = None`` treats staged work as
verified — allowed, but self-certification is exactly the failure mode the
checker exists to stop.

Everything here is fail-open: a step failure must never break a turn (the
loop falls back to the LLM), a recording failure must never break a run.
Module-level imports are stdlib + loguru only, so test suites can import
this layer without the full app stack.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

# A stage returns this to end the chain WITHOUT a step — the LLM decides
# the turn (used while the domain's subject is not bootstrapped yet).
LLM_TURN = object()


# ═════════════════════════════ durable state ═════════════════════════════════


@dataclass
class WorkState:
    """Durable per-subject state — the single source of truth the step
    program reads and the recording hooks write. Field semantics:

    - ``staged``: the work product was produced and is ready to check
      (for Living UI: built + launched);
    - ``verified``: the independent check passed → done;
    - ``check_failures``: defects the checker OBSERVED → next round's work
      order;
    - ``check_attempts``: consecutive checks that produced no verdict;
    - ``user_leads``: user replies kept as debugging leads, never commands.

    Subclass to change the on-disk location (``STATE_REL``) or to load
    files written under older field names (``LEGACY_KEYS``: old → new).
    """

    rounds: int = 0
    awaiting_user_decision: bool = False
    staged: bool = False
    verified: bool = False
    check_failures: List[str] = field(default_factory=list)
    check_attempts: int = 0
    last_result: Optional[Dict[str, Any]] = None
    user_leads: List[str] = field(default_factory=list)
    notify_step_issued: bool = False
    presentation_asked: bool = False
    # LLM infrastructure down (provider outage/credits): the loop WAITS
    # instead of spending rounds on sub-agents that die instantly. Set by
    # recorders seeing INFRA_LLM_MARKER; cleared by any successful outcome
    # or a user message (which also acts as the retry signal).
    infra_blocked: bool = False
    # Features verified PASS by checks WITHIN the current check phase —
    # the next check attempt covers only the remainder (big work can need
    # several capped checks). Invalidated by any new work outcome: a pass
    # against old code proves nothing about new code.
    checked_ok: List[str] = field(default_factory=list)
    # TARGETED UPDATE phase (adopted with a change request): work and check
    # scope to the CHANGE — proportionality for small fixes. The domain
    # decides how conservative to be (e.g. escalate to a full check when
    # touched_areas go beyond the frontend). Cleared when verified.
    update_scope: bool = False
    # Areas the work round actually touched (fed by the domain's write
    # tap; e.g. "frontend", "backend", "config") — the escalation signal.
    touched_areas: List[str] = field(default_factory=list)
    # Requests from previous phases that were never verified-done (leads
    # cleared by an adoption before a PASS). Never executed automatically —
    # the presentation step OFFERS them back to the user ("want me to
    # continue with X?"), who decides.
    backlog: List[str] = field(default_factory=list)
    # A failure happened since the engine last ran (set via fail_cycle by
    # the outcome recorders). The ENGINE settles it into at most ONE
    # counted round per turn — a boolean, so N same-cycle failures (e.g.
    # the worker's own mid-work restarts/probes) can never inflate the
    # round budget. See Workflow._settle_pending_round.
    pending_round: bool = False

    STATE_REL: ClassVar[Path] = Path("logs") / "work_state.json"
    LEGACY_KEYS: ClassVar[Dict[str, str]] = {}

    @property
    def phase(self) -> str:
        """Derived phase label — one word of legibility over the boolean
        pile (used by the journal and logs; behavior is still driven by
        the individual fields). Precedence mirrors the stage chain."""
        if self.verified:
            return "done"
        if self.infra_blocked:
            return "paused_infra"
        if self.awaiting_user_decision:
            return "gated"
        if self.staged:
            return "checking"
        return "working"

    # ── persistence ─────────────────────────────────────────────────────────
    @classmethod
    def load(cls, state_dir: Path) -> "WorkState":
        try:
            raw = json.loads(
                (Path(state_dir) / cls.STATE_REL).read_text(encoding="utf-8")
            )
            if isinstance(raw, dict):
                for old, new in cls.LEGACY_KEYS.items():
                    if old in raw and new not in raw:
                        raw[new] = raw.pop(old)
                known = set(cls.__dataclass_fields__)
                return cls(**{k: v for k, v in raw.items() if k in known})
        except Exception:
            pass
        return cls()

    def save(self, state_dir: Path) -> None:
        """Atomic write; never raises."""
        try:
            path = Path(state_dir) / self.STATE_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as e:
            logger.debug(f"[STEPS] state save skipped: {e}")

    # ── shared transitions ──────────────────────────────────────────────────
    def count_round(self, round_budget: int) -> None:
        """One work round spent; at the budget, the program must ask the user."""
        self.rounds += 1
        if self.rounds >= round_budget:
            self.awaiting_user_decision = True

    def fail_cycle(self) -> None:
        """A work/check failure happened this cycle. Recorders NEVER count
        rounds directly — outcomes can arrive from ANY launch_and_verify
        caller, including the worker restarting/probing its own
        in-progress work (session 20260717111534: two mid-work `livingui
        restart` calls + the staged validate burned 3 "rounds" inside ONE
        turn, spending the 8-round budget in ~3 real rounds). They set
        this flag; the ENGINE settles it into at most one round per turn
        (Workflow._settle_pending_round)."""
        self.pending_round = True

    def exhaust_checks(self, why: str) -> None:
        """The checker could not verify the work within its retry budget:
        hand the work back to the worker with a verify-it-yourself work
        order. One transition for both writers (verdict recorder + step
        guard) so the message and the mutation can never drift apart."""
        self.staged = False
        self.check_attempts = 0
        self.check_failures = [
            f"The automated check could not verify this ({why}). "
            "Verify it yourself — by any means that works — and confirm "
            "EVERY requirement is actually met, fixing anything that isn't."
        ]
        self.fail_cycle()


# ═════════════════════════════ per-turn context ══════════════════════════════


def journal(state_dir: Path, event: str, **fields: Any) -> None:
    """One structured line per loop event — the subject's run journal.

    Appends JSON lines to ``<state_dir>/logs/workflow_journal.jsonl`` so a
    run can be diagnosed with one ``jq``/grep instead of log archaeology:
    phase transitions, verdict kinds, rounds, budget/infra events. Written
    by the recorders (the single writers of state). Fail-open."""
    try:
        path = Path(state_dir) / "logs" / "workflow_journal.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": round(time.time(), 3), "event": event, **fields})
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


@dataclass(frozen=True)
class CheckReport:
    """A checker's result, PARSED once and classified — separated from the
    state transitions so the parsing rules are pure and testable.

    kind:
    - ``infra``      the checker never ran (LLM infrastructure death)
    - ``pass``       every feature in scope verified
    - ``defects``    observed misbehavior (``defects`` may be empty →
                     the transition applies the generic work order)
    - ``incomplete`` defect-free but coverage ran out (NOT REACHED)
    - ``blocked``    BLOCKED / no verdict / checker crashed
    """

    kind: str
    passed_features: List[str] = ()
    defects: List[str] = ()


def parse_check_report(result_text: str) -> CheckReport:
    """Classify a checker's raw result. Pure — no state, no I/O."""
    text = result_text or ""

    from app.agentic.engine import INFRA_LLM_MARKER

    if INFRA_LLM_MARKER in text:
        return CheckReport(kind="infra")

    m = re.search(r"VERDICT:\s*(PASS|FAIL|BLOCKED)", text, re.IGNORECASE)
    verdict = m.group(1).upper() if m else None

    # A FAIL whose body describes a blockage is a blockage wearing a FAIL
    # costume — the worker must never be dispatched to "fix" defects
    # nobody observed.
    if verdict == "FAIL" and _reads_as_blocked(text):
        verdict = "BLOCKED"

    if verdict == "PASS":
        return CheckReport(kind="pass")

    if verdict == "FAIL":
        # Parse per-feature lines from the FEATURES section ONLY — the
        # output contract puts declarations there and explanations under
        # FAILURES / BLOCKED BY. Prose must NEVER become a work order:
        # "- Overall Verdict: FAIL because not all features could be
        # reached" matches any line-level FAIL pattern (': FAIL'), and
        # dispatched a worker to 'fix' a sentence (session 20260717074437).
        # No section headers → the whole text is the feature list.
        feature_section = re.split(
            r"^\s*(?:FAILURES|BLOCKED BY)\b",
            text,
            maxsplit=1,
            flags=re.MULTILINE | re.IGNORECASE,
        )[0]
        passed = [
            f.strip()
            for f in re.findall(
                r"^-\s+(.{1,120}?)\s*(?:—|–|:|-)\s*PASS\b",
                feature_section,
                re.MULTILINE,
            )
            if f.strip()
        ]
        defects = [
            d.strip()
            for d in re.findall(
                r"^-\s+(?!.*\bNOT REACHED\b).*(?:—|–|:|-)\s*FAIL\b.*$",
                feature_section,
                re.MULTILINE,
            )
        ]
        if not defects and re.search(
            r"NOT REACHED", feature_section, re.IGNORECASE
        ):
            return CheckReport(kind="incomplete", passed_features=passed)
        return CheckReport(kind="defects", passed_features=passed, defects=defects)

    return CheckReport(kind="blocked")


@dataclass
class StepContext:
    """Everything one turn's stages need, resolved once. ``subject`` is the
    thing the domain works on (a Living UI project, a research topic, a
    booking record)."""

    subject: Any
    task: Any
    state: WorkState
    state_dir: Path
    user_message: Optional[str]


# ═════════════════════════════ the engine ════════════════════════════════════

# A checker FAIL whose body describes never having reached the work product
# is a blockage wearing a FAIL costume — routed to the retry path so the
# worker is never dispatched to "fix" defects nobody observed.
# ONLY phrases that name the CHECKER'S OWN TOOLING. Generic connectivity
# phrases ("connection refused", "net::err", "could not connect") are
# deliberately absent: they also appear in real app defects (the app's
# frontend failing to reach its own backend), and matching them flipped
# genuine, fixable FAILs into BLOCKED — discarding the observed defects.
_BLOCKED_MARKERS = (
    "mcp server connection lost",
    "browser mcp",
    "browser is unavailable",
    "browser tool",
    "no features could be tested",
    "could not launch a browser",
)


def _reads_as_blocked(result_text: str) -> bool:
    body = (result_text or "").lower()
    return any(marker in body for marker in _BLOCKED_MARKERS)


class Workflow:
    """The deterministic workflow: ``Task → workflow → actions``.

    One self-contained base. Subclasses set the task surface (``name``,
    ``system_prompt``, optionally ``select_action_prompt``), the engine
    attributes below, and the domain hooks. Every stage and every
    prompt/query builder is an overridable method. Instances are registry
    singletons — keep them stateless; per-subject state lives on disk via
    ``state_class``.
    """

    # ── task surface (read by the core each turn) ───────────────────────────
    name: str = ""  # matches Task.workflow_id; required, unique
    description: str = ""
    system_prompt: str = ""  # REPLACES the general system prompt verbatim
    select_action_prompt: Optional[str] = None  # per-turn protocol override
    include_skills: bool = False
    inject_essentials: bool = False
    inject_memory: bool = False

    def task_state(self, task: Any) -> str:
        """Optional per-turn computed context block. Base: none."""
        return ""

    # ── engine attributes (the OOP "config") ────────────────────────────────
    worker_agent: str = ""  # spawned each work round
    checker_agent: Optional[str] = None  # independent verifier; None = no gate
    stage_action: Optional[str] = None  # platform action run WITH the worker
    notify_action: Optional[str] = None  # "present it" action, if any
    round_budget: int = 8
    check_attempt_budget: int = 3
    state_class = WorkState
    work_label: str = "Working on it (round {round} of {budget})."
    check_label: str = "Verifying the result (round {round})."

    STAGES = (
        "stage_wait_for_user",
        "stage_answer_user",
        "stage_infra_blocked",
        "stage_bootstrap",
        "stage_budget_gate",
        "stage_work_round",
        "stage_check",
        "stage_finish",
    )

    _TALK_RULES = (
        "Write it in your own words, warm and honest. NEVER mention internal "
        "machinery (budgets, rounds, subagents, pipelines, step programs)."
    )

    # ── domain hooks (must override) ─────────────────────────────────────────
    def resolve_subject(self, task: Any) -> Optional[Any]:
        """The domain subject this task works on; None = LLM decides the
        turn (nothing to drive yet)."""
        return None

    def state_dir(self, subject: Any) -> Path:
        """Directory that holds this subject's durable WorkState."""
        raise NotImplementedError

    def is_bootstrapped(self, ctx: StepContext) -> bool:
        """False while the subject still needs its initial LLM-driven setup
        (the program's one delegated build duty)."""
        raise NotImplementedError

    def work_query(self, ctx: StepContext) -> str:
        """The worker agent's brief for this round. Include
        ``ctx.state.check_failures`` — a checker's FAIL report is the
        round's work order."""
        raise NotImplementedError

    def check_query(self, ctx: StepContext) -> str:
        """The checker agent's brief (must demand the VERDICT contract)."""
        raise NotImplementedError

    # ── the chain ────────────────────────────────────────────────────────────
    def step(self, task: Any, turn_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The per-turn entry the task loop calls: resolve the subject,
        run the program.
        Fail-open: any problem = None = the LLM decides the turn."""
        try:
            subject = self.resolve_subject(task)
            if subject is None:
                return None
            step = self.compute(subject, task, turn_context)
            if step is not None:
                self._log_step(task, step)
            return step
        except Exception as e:
            logger.warning(f"[STEPS:{self.name}] fell back to LLM: {e}")
            return None

    def compute(
        self, subject: Any, task: Any, turn_context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """This turn's step (app/agentic/steps contract); None = LLM decides.
        Runs the stages in ``STAGES`` order — first step dict wins, ``None``
        = not my turn, ``LLM_TURN`` = stop and let the LLM decide."""
        state_dir = Path(self.state_dir(subject))
        ctx = StepContext(
            subject=subject,
            task=task,
            state=self.state_class.load(state_dir),
            state_dir=state_dir,
            user_message=(turn_context or {}).get("user_message"),
        )
        self._settle_pending_round(ctx)
        self.on_turn(ctx)
        for name in self.STAGES:
            step = getattr(self, name)(ctx)
            if step is LLM_TURN:
                return None
            if step is not None:
                return step
        return {"kind": "wait", "label": "Working."}

    def _settle_pending_round(self, ctx: StepContext) -> None:
        """Rounds are counted HERE, by the engine — never by the outcome
        recorders. Recorders only raise the ``pending_round`` flag
        (fail_cycle), because outcomes arrive from any launch_and_verify
        caller, including the worker probing its own in-progress work; the
        boolean collapses all of one cycle's failures into at most ONE
        round, settled when the engine next takes a turn.

        - Cycle ended not-staged and not-verified → one round counted
          (arming the budget gate at the budget, before this turn's stages
          run — so the gate still intercepts the over-budget work round).
        - A later success staged or verified the work → the failures were
          transient probes inside a converged cycle: no round.
        - Infra pause → defer settling; an outage burns zero budget."""
        state = ctx.state
        if not state.pending_round or state.infra_blocked:
            return
        state.pending_round = False
        if not state.staged and not state.verified:
            state.count_round(self.round_budget)
            journal(
                ctx.state_dir,
                "round_counted",
                rounds=state.rounds,
                phase=state.phase,
            )
        state.save(ctx.state_dir)

    def on_turn(self, ctx: StepContext) -> None:
        """Per-turn side effects before the chain (e.g. todo sync). Base: none."""

    # ── stages (override points) ─────────────────────────────────────────────
    def stage_wait_for_user(self, ctx: StepContext) -> Optional[Dict[str, Any]]:
        """Parked at an ask and this turn brings no reply → stay parked."""
        if getattr(ctx.task, "waiting_for_user_reply", False) and not ctx.user_message:
            return {"kind": "wait", "label": "Waiting for the user's decision."}
        return None

    def stage_answer_user(self, ctx: StepContext) -> Optional[Dict[str, Any]]:
        """A user message is answered BETWEEN work steps, always."""
        if not ctx.user_message:
            return None
        return {
            "kind": "llm",
            "purpose": "answer_user",
            "prompt": self.answer_user_prompt(ctx, str(ctx.user_message)),
            "allowed_actions": ["send_message"],
        }

    def stage_infra_blocked(self, ctx: StepContext) -> Optional[Dict[str, Any]]:
        """LLM infrastructure down → WAIT instead of spending the budget on
        sub-agents that die instantly (the 2026-07-16 credit outage burned
        8 rounds in 4 seconds). The wait step parks the task; a user
        message clears the flag (record_user_lead) and acts as the retry
        signal, as does any successful outcome after the provider's
        breaker lets a probe call through."""
        if not ctx.state.infra_blocked:
            return None
        return {
            "kind": "wait",
            "label": (
                "Paused: the AI provider is unavailable (outage or exhausted "
                "credits). The build resumes automatically on your next "
                "message once the provider is back."
            ),
        }

    def stage_bootstrap(self, ctx: StepContext):
        """Not bootstrapped yet → the LLM performs the initial setup (its one
        delegated build duty); code drives every turn after that."""
        if not self.is_bootstrapped(ctx):
            return LLM_TURN
        return None

    def stage_budget_gate(self, ctx: StepContext) -> Optional[Dict[str, Any]]:
        """The genuine last resort: the work burned its full round budget."""
        if ctx.state.verified or not ctx.state.awaiting_user_decision:
            return None
        return {
            "kind": "llm",
            "purpose": "budget_gate_ask",
            "prompt": self.budget_gate_prompt(ctx),
            "allowed_actions": ["send_message"],
        }

    def stage_work_round(self, ctx: StepContext) -> Optional[Dict[str, Any]]:
        """Not staged → the worker agent produces/fixes the work product.
        Check failures from the previous round ride along in the query as
        the round's work order."""
        if ctx.state.verified or ctx.state.staged:
            return None
        return self._work_round(
            ctx,
            self.work_label.format(round=self._round(ctx), budget=self.round_budget),
        )

    def stage_check(self, ctx: StepContext) -> Optional[Dict[str, Any]]:
        """Staged → the INDEPENDENT checker verifies the work actually meets
        the requirements. "The worker says it's done" is never done.

        Guarded by check_attempts: record_check_outcome bounds the retries,
        but if its verdicts were ever dropped (a dead outcome tap) this
        stops the checker from re-spawning forever regardless. Domains with
        no checker treat staged work as verified (self-certified)."""
        if ctx.state.verified or not ctx.state.staged:
            return None
        if self.checker_agent is None:
            ctx.state.verified = True
            self.on_verified(ctx.state_dir)
            ctx.state.save(ctx.state_dir)
            return self.stage_finish(ctx)
        if ctx.state.check_attempts >= self.check_attempt_budget:
            ctx.state.exhaust_checks("the automated check could not run")
            ctx.state.save(ctx.state_dir)
            logger.warning(
                f"[STEPS:{self.name}] check gave no verdict "
                f"{self.check_attempt_budget}× — handing back to the worker "
                f"to verify itself: {ctx.state_dir}"
            )
            return self._work_round(
                ctx, f"Re-checking the result (round {self._round(ctx)})."
            )
        return {
            "kind": "actions",
            "label": self.check_label.format(round=self._round(ctx)),
            "actions": [
                {
                    "action_name": "spawn_subagent",
                    "parameters": {
                        "agent_type": self.checker_agent,
                        "query": self.check_query(ctx),
                        **self.spawn_context(ctx),
                    },
                }
            ],
        }

    def stage_finish(self, ctx: StepContext) -> Optional[Dict[str, Any]]:
        """Verified → notify, present, end — one step per turn, each guarded
        by durable state so an interrupted run resumes cleanly."""
        if not ctx.state.verified:
            return None
        if self.notify_action and not ctx.state.notify_step_issued:
            ctx.state.notify_step_issued = True
            ctx.state.save(ctx.state_dir)
            return {
                "kind": "actions",
                "label": "Presenting the finished result.",
                "actions": [
                    {
                        "action_name": self.notify_action,
                        "parameters": self.notify_params(ctx),
                    }
                ],
            }
        if not ctx.state.presentation_asked:
            ctx.state.presentation_asked = True
            ctx.state.save(ctx.state_dir)
            return {
                "kind": "llm",
                "purpose": "presentation",
                "prompt": self.presentation_prompt(ctx),
                "allowed_actions": ["send_message", "task_end"],
            }
        # The model presented but didn't end (or the turn died) — code ends.
        return self.end_step(ctx)

    # ── shared step builders ─────────────────────────────────────────────────
    @staticmethod
    def _round(ctx: StepContext) -> int:
        return ctx.state.rounds + 1

    def spawn_context(self, ctx: StepContext) -> Dict[str, Any]:
        """Extra STRUCTURED parameters for every worker/checker spawn, so
        outcome taps can route results without parsing free text.

        Base: the GENERIC routing keys consumed by
        :mod:`app.workflows.outcome_tap` — a domain that keeps them gets
        work/check outcomes recorded automatically when its sub-agents end.
        A domain with its OWN tap (Living UI's construction_events)
        overrides this WITHOUT calling super(), which opts it out of the
        generic tap."""
        return {
            "workflow_name": self.name,
            "workflow_state_dir": str(ctx.state_dir),
        }

    def _work_round(self, ctx: StepContext, label: str) -> Dict[str, Any]:
        """The one work-round shape: spawn the worker (+ the optional
        platform stage action that builds/deploys/validates the product)."""
        actions = [
            {
                "action_name": "spawn_subagent",
                "parameters": {
                    "agent_type": self.worker_agent,
                    "query": self.work_query(ctx),
                    **self.spawn_context(ctx),
                },
            }
        ]
        if self.stage_action:
            actions.append(
                {
                    "action_name": self.stage_action,
                    "parameters": self.stage_action_params(ctx),
                }
            )
        return {"kind": "actions", "label": label, "actions": actions}

    def stage_action_params(self, ctx: StepContext) -> Dict[str, Any]:
        """Parameters for ``stage_action``. Base: none."""
        return {}

    def notify_params(self, ctx: StepContext) -> Dict[str, Any]:
        """Parameters for ``notify_action``. Base: none."""
        return {}

    def describe_subject(self, ctx: StepContext) -> str:
        """Short human phrase for prompts (e.g. 'their app (Kanban)')."""
        return "their request"

    def end_step(self, ctx: StepContext) -> Dict[str, Any]:
        return {
            "kind": "end",
            "status": "complete",
            "label": "Work complete.",
            "reason": "The work was completed and passed verification.",
            "summary": f"Completed and verified: {self.describe_subject(ctx)}.",
        }

    def on_verified(self, state_dir: Path) -> None:
        """Domain side effect when verification passes. Base: none."""

    # ── talk-duty prompts (the ONLY LLM consultations in the loop) ───────────
    def answer_user_prompt(self, ctx: StepContext, user_message: str) -> str:
        progress = (
            "the work is done and verified"
            if ctx.state.verified
            else "the work is still in progress"
        )
        return (
            f'The user just said: "{user_message}"\n'
            f"You are working on {self.describe_subject(ctx)}; {progress}.\n"
            "Reply with ONE send_message: answer them briefly (1-3 sentences) "
            "and let them know the work continues. Do NOT start any of the "
            f"work yourself — the platform runs it. {self._TALK_RULES}"
        )

    def budget_gate_prompt(self, ctx: StepContext) -> str:
        """GENUINE LAST RESORT — only after a full honest budget of rounds.
        NOT a permission checkpoint and NOT a menu: an honest, SUBSTANTIVE
        report from someone still on the problem, asking for any info that
        could unblock it."""
        last = ctx.state.last_result or {}
        error_lines = [
            str(e).strip() for e in (last.get("errors") or []) if str(e).strip()
        ][:4]
        lines = [
            f"You have worked on {self.describe_subject(ctx)} through "
            f"{self.round_budget} full rounds and it still does not pass. This "
            "is a genuine last resort: report honestly, do NOT ask permission "
            "to continue, do NOT offer a menu of choices.",
        ]
        if error_lines:
            lines.append("The exact problem(s) that persist:")
            lines.extend(f"  - {t[:300]}" for t in error_lines)
        tried = self.budget_gate_tried_block(ctx)
        if tried:
            lines.append(
                "Approaches you ALREADY tried and that failed (do not "
                f"re-suggest these to the user):\n{tried}"
            )
        lines.append(
            "Send ONE send_message with wait_for_user_reply=true: say plainly "
            "what still fails and what you already ruled out, and ask whether "
            "they have any information that could help pin it down — make "
            "clear you will keep going with whatever they can tell you. Then "
            f"WAIT for their reply. {self._TALK_RULES}"
        )
        return "\n".join(lines)

    def budget_gate_tried_block(self, ctx: StepContext) -> str:
        """Domain-supplied 'already tried' evidence for the budget gate
        (e.g. a fix-ledger excerpt). Base: none."""
        return ""

    def presentation_prompt(self, ctx: StepContext) -> str:
        return (
            f"The work on {self.describe_subject(ctx)} is done and verified. "
            "In ONE decision: send_message the user a short, warm presentation "
            "of the result (2-4 sentences), AND call "
            'task_end(status="complete", reason, summary) in the same actions '
            f"list. {self._TALK_RULES}"
        )

    # ── recorders (the outcome side of the loop) ─────────────────────────────
    # Called by the domain's outcome tap, not by the stages.
    def record_work_outcome(self, state_dir: Path, result: Dict[str, Any]) -> None:
        """Record one work/stage result. success = the product is STAGED
        (ready to check) — NOT yet done; the checker decides done. A failure
        is one round; at the budget the program asks the user."""
        try:
            state = self.state_class.load(state_dir)
            step = str(result.get("step", ""))
            # New work happened → coverage from earlier checks is void (a
            # pass against old code proves nothing about new code).
            state.checked_ok = []
            if result.get("status") == "success":
                state.staged = True
                state.infra_blocked = False  # real outcome = provider alive
                state.last_result = {"step": "success", "at": time.time()}
                state.save(state_dir)
                journal(
                    state_dir,
                    "work_outcome",
                    ok=True,
                    rounds=state.rounds,
                    phase=state.phase,
                )
                return
            state.staged = False
            state.last_result = {
                "step": step,
                "at": time.time(),
                "errors": [str(e)[:500] for e in (result.get("errors") or [])[:12]],
            }
            state.fail_cycle()
            journal(
                state_dir,
                "work_outcome",
                ok=False,
                step=step,
                rounds=state.rounds,
                phase=state.phase,
            )
            self.on_work_failed(state_dir, step)
            state.save(state_dir)
        except Exception as e:
            logger.debug(f"[STEPS:{self.name}] record_work skipped: {e}")

    def on_work_failed(self, state_dir: Path, step: str) -> None:
        """Domain side effect on a failed work round (e.g. fix-ledger
        backfill). Base: none."""

    def record_check_outcome(
        self, state_dir: Path, sub_status: str, result_text: str
    ) -> None:
        """Record the checker's verdict — the ONLY thing that can mark the
        work done (the worker's self-report is never trusted).

        - PASS    → verified.
        - FAIL    → the observed defects go back to a FRESH worker next round.
        - BLOCKED / no verdict / checker crashed → the check learned NOTHING:
          never verify, never fabricate defects. Retry to
          check_attempt_budget, then hand back to the worker to verify
          itself. A FAIL whose body describes a blockage is treated as
          BLOCKED.
        """
        try:
            state = self.state_class.load(state_dir)
            report = parse_check_report(result_text)

            # Harvest cumulative coverage for any FAIL-family report.
            for feat in report.passed_features:
                if feat not in state.checked_ok:
                    state.checked_ok.append(feat)
            state.checked_ok = state.checked_ok[-60:]

            transition = {
                "infra": self._check_infra,
                "pass": self._check_pass,
                "defects": self._check_defects,
                "incomplete": self._check_incomplete,
                "blocked": self._check_blocked,
            }[report.kind]
            transition(state, state_dir, report, sub_status)
            journal(
                state_dir,
                "check_outcome",
                kind=report.kind,
                defects=len(report.defects),
                covered=len(state.checked_ok),
                attempts=state.check_attempts,
                rounds=state.rounds,
                phase=state.phase,
            )
        except Exception as e:
            logger.debug(f"[STEPS:{self.name}] record_check skipped: {e}")

    # ── check transitions (one small method per CheckReport.kind) ───────────

    def _check_infra(self, state, state_dir: Path, report, sub_status: str) -> None:
        """The checker never ran (LLM infrastructure death): pause the loop
        without burning a check attempt."""
        state.infra_blocked = True
        state.save(state_dir)
        logger.warning(
            f"[STEPS:{self.name}] check died of LLM infrastructure "
            f"failure — pausing (no budget spent): {state_dir}"
        )

    def _check_pass(self, state, state_dir: Path, report, sub_status: str) -> None:
        """Verified. Served leads and phase scope are cleared — they must
        not haunt the next phase."""
        state.infra_blocked = False
        state.verified = True
        state.awaiting_user_decision = False
        state.check_failures = []
        state.check_attempts = 0
        state.checked_ok = []
        state.update_scope = False
        state.touched_areas = []
        state.user_leads = []
        self.on_verified(state_dir)
        state.save(state_dir)

    def _check_defects(self, state, state_dir: Path, report, sub_status: str) -> None:
        """Observed misbehavior → the defects are a FRESH worker's next
        work order; one round spent."""
        state.infra_blocked = False
        state.verified = False
        state.staged = False
        state.check_attempts = 0
        state.check_failures = [d[:300] for d in report.defects][:10] or [
            "The independent check found the work does not meet the "
            "requirements (see the check report)."
        ]
        state.fail_cycle()
        self.on_check_failed(state_dir)
        state.save(state_dir)

    def _check_incomplete(
        self, state, state_dir: Path, report, sub_status: str
    ) -> None:
        """Defect-free but coverage ran out (NOT REACHED): nothing is
        broken — continue the CHECK phase on the remaining scope. No work
        order, no round burned; bounded by check_attempt_budget."""
        state.infra_blocked = False
        state.verified = False
        state.check_attempts += 1
        logger.info(
            f"[STEPS:{self.name}] check coverage incomplete "
            f"({len(state.checked_ok)} verified so far) — continuing with "
            f"the remainder, attempt "
            f"{state.check_attempts}/{self.check_attempt_budget}"
        )
        if state.check_attempts >= self.check_attempt_budget:
            state.exhaust_checks(
                "coverage stayed incomplete across the check budget"
            )
        state.save(state_dir)

    def _check_blocked(self, state, state_dir: Path, report, sub_status: str) -> None:
        """BLOCKED / no verdict / checker crashed: the check learned
        NOTHING — never verify, never fabricate defects. Retry to the
        budget, then hand back to the worker to verify itself."""
        failed_sub = str(sub_status or "").lower() in ("failed", "error")
        state.infra_blocked = False
        state.verified = False
        state.check_attempts += 1
        logger.warning(
            f"[STEPS:{self.name}] check reached no verdict "
            f"(sub_status={sub_status!r}) — attempt "
            f"{state.check_attempts}/{self.check_attempt_budget}"
        )
        if state.check_attempts >= self.check_attempt_budget:
            why = (
                "the checker failed"
                if failed_sub
                else "it was blocked from reaching the result"
            )
            state.exhaust_checks(why)
        state.save(state_dir)

    def on_check_failed(self, state_dir: Path) -> None:
        """Domain side effect on an observed-defects check FAIL. Base: none."""

    def record_user_lead(self, state_dir: Path, message: str) -> None:
        """A user reply is EVIDENCE, not a command. Store it as a lead the
        next work round investigates (reproduce and verify — never trust
        blindly), and un-park a program stuck at the budget gate so it
        resumes WITH the lead."""
        try:
            text = (message or "").strip()
            state = self.state_class.load(state_dir)
            if text:
                state.user_leads = (state.user_leads + [text[:1000]])[-5:]
            if state.awaiting_user_decision:
                state.awaiting_user_decision = False
                state.rounds = 0
                state.pending_round = False
            # A user message is the retry signal after an LLM outage: clear
            # the pause and let the next turn attempt a work round (the
            # provider breaker's cooldown allows a probe call by then).
            state.infra_blocked = False
            state.save(state_dir)
            journal(state_dir, "user_lead", chars=len(text), phase=state.phase)
            logger.info(
                f"[STEPS:{self.name}] user lead recorded "
                f"({len(text)} chars): {state_dir}"
            )
        except Exception as e:
            logger.debug(f"[STEPS:{self.name}] lead record skipped: {e}")

    # ── plumbing ─────────────────────────────────────────────────────────────
    def _log_step(self, task: Any, step: Dict[str, Any]) -> None:
        """One build_step event per computed step (fail-open)."""
        try:
            from agent_core import get_event_stream_manager

            esm = get_event_stream_manager()
            if esm is None:
                return
            label = step.get("label") or step.get("purpose") or step.get("kind")
            esm.log(
                kind="build_step",
                message=f"[{step.get('kind')}] {label}",
                severity="DEBUG",
                task_id=getattr(task, "id", None),
            )
        except Exception:
            pass
