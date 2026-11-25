"""The security gate every action passes through (ActionManager hook).

Decisions use what an action declares (its ``effects`` and
``result_source``), never its name or the text of its arguments:

- With Auto mode on (the default) the gate only records where results came
  from, so behaviour and speed are what they were before security levels.
- With Auto mode off, an action whose effects the policy lists, or any
  action with an effect once the run has read untrusted content, waits for
  the user's approval on a card in the CraftBot window or terminal.
- When nobody can answer (an unattended run, the owner writing from a chat
  app, no window open) the action is refused and the agent is told why, so
  it can tell the user.

An action that declares nothing is treated by what it is:

- an integration's action changes the outside service when its developer
  marked it irreversible or not parallelizable (the framework's marker for
  writes), and otherwise only reads from it;
- any other undeclared action is code the agent can run, so it counts as
  ``execute``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, FrozenSet, Optional

from agent_core.utils.logger import logger
from app.security import audit
from app.security.approvals import ApprovalBroker, Decision, broker as default_broker
from app.security.content import RunRegistry, runs as default_runs, wrap_untrusted
from app.triggers.sources import TriggerSource
from app.security.policy import (
    ContentSource,
    Effect,
    SecurityPolicy,
    get_policy,
)

_DENIAL_LIMIT = 3

# Inputs that hold the command an EXECUTE action runs.
COMMAND_KEYS = ("command",)

# Runs the scheduler starts (Hermes: cron runs get no scheduling tools).
SCHEDULED_SOURCES = frozenset(
    s.value
    for s in (
        TriggerSource.SCHEDULED,
        TriggerSource.SCHEDULED_ONCE,
        TriggerSource.SCHEDULED_IMMEDIATE,
        TriggerSource.CRON_JOB,
    )
)

# What a third party's run may still do when the owner allowed replies to
# that contact; the integration limits it to replying (telegram_feedback.py).
_AUTO_REPLY_EFFECTS = frozenset({Effect.SEND_EXTERNAL})


def command_of(input_data: Dict[str, Any]) -> Optional[str]:
    for key in COMMAND_KEYS:
        value = input_data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def grant_key(action: Any, input_data: Dict[str, Any]) -> str:
    """What "allow for this session" covers: the action, or for a command
    that exact command in that folder (OpenClaw's allow-always binding)."""
    command = command_of(input_data)
    if command is None:
        return action.name
    cwd = input_data.get("cwd") or input_data.get("working_directory") or ""
    digest = hashlib.sha256(json.dumps([command, str(cwd)]).encode("utf-8")).hexdigest()
    return f"{action.name}:{digest}"


def effects_of(action: Any) -> FrozenSet[Effect]:
    declared = getattr(action, "effects", None)
    if declared is not None:
        result = set()
        for value in declared:
            try:
                result.add(Effect(value))
            except ValueError:
                # An effect this version does not know is still an effect:
                # treat it as the most general one rather than as none.
                result.add(Effect.EXECUTE)
        return frozenset(result)
    if getattr(action, "integration", None):
        if getattr(action, "irreversible", False) or not getattr(
            action, "parallelizable", True
        ):
            return frozenset({Effect.SEND_EXTERNAL})
        return frozenset()
    if getattr(action, "irreversible", False):
        return frozenset({Effect.SEND_EXTERNAL})
    return frozenset({Effect.EXECUTE})


def result_source_of(action: Any) -> ContentSource:
    declared = getattr(action, "result_source", None)
    if declared:
        try:
            return ContentSource(declared)
        except ValueError:
            return ContentSource.NETWORK
    if getattr(action, "integration", None):
        return ContentSource.NETWORK
    return ContentSource.LOCAL


def _blocked(message: str, code: str) -> Dict[str, Any]:
    return {"status": "error", "error": message, "error_code": code}


class SecurityGate:
    def __init__(
        self,
        approvals: Optional[ApprovalBroker] = None,
        run_registry: Optional[RunRegistry] = None,
    ) -> None:
        self.approvals = approvals or default_broker
        self.runs = run_registry or default_runs

    # ── before an action ──

    async def review(
        self, action: Any, input_data: Dict[str, Any], *, session_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        policy = get_policy()
        if not policy.gate_needed:
            return None

        effects = effects_of(action)
        if not effects:
            return None
        run = self.runs.get(session_id)
        session = session_id or ""

        limited = self._run_limit(policy, run, effects)
        if limited:
            self._audit(policy, action, effects, "refused_run_limit", session)
            return _blocked(
                f"Not run: {action.display_name}. {limited} (Settings > "
                f"Security). If the user should know, tell them with send_message.",
                "run_limited",
            )

        command, risk = None, None
        if policy.check_commands and Effect.EXECUTE in effects:
            command = command_of(input_data)
            if command:
                from app.security.command_review import find_risk

                risk = find_risk(command, windows=os.name == "nt")

        if not policy.gate_active:
            if risk:
                return await self._review_by_model(policy, action, effects, input_data, command, risk, session)
            return None

        if risk:
            reason, detail = "risky_command", risk
        elif effects & policy.approval_effects:
            reason, detail = "high_risk", ""
        elif policy.ask_after_untrusted and run.tainted:
            reason, detail = "untrusted_content", run.taint_reason
        else:
            return None

        grant = grant_key(action, input_data)
        if self.approvals.is_granted(session, grant):
            self._audit(policy, action, effects, "allowed_by_session_grant", session)
            return None

        effect_names = sorted(e.value for e in effects)
        unavailable = self._why_unanswerable(run)
        if unavailable:
            self._audit(policy, action, effects, "refused_no_reviewer", session)
            return _blocked(
                f"Not run: {action.display_name} needs the user's approval "
                f"because Auto mode is off, but {unavailable}. Tell the user it "
                f"is waiting for them in the CraftBot window, or that they can "
                f"turn Auto mode back on in Settings > Security.",
                "approval_unavailable",
            )

        decision = await self.approvals.request(
            session_id=session,
            action_name=action.name,
            action_display_name=action.display_name,
            effects=effect_names,
            reason=reason,
            reason_detail=detail,
            inputs=input_data,
            timeout_s=policy.approval_timeout_s,
            grant_key=grant,
            command_keys=COMMAND_KEYS,
        )
        self._audit(policy, action, effects, f"user_{decision.value}", session)
        if decision.allowed:
            return None

        denials = self.approvals.consecutive_denials(session)
        if decision == Decision.TIMEOUT:
            message = (
                f"Not run: the user did not approve {action.display_name} in time."
            )
        else:
            message = f"Not run: the user denied {action.display_name}."
        if denials >= _DENIAL_LIMIT:
            message += (
                f" The user has refused {denials} actions in a row: stop and "
                f"ask them how they want to proceed instead of trying again."
            )
        else:
            message += " Do not retry it; ask the user if unsure."
        return _blocked(message, "approval_denied")

    @staticmethod
    def _run_limit(policy: SecurityPolicy, run, effects: FrozenSet[Effect]) -> str:
        """Why this run may not take an action with these effects, or ""."""
        if policy.limit_third_party_runs and run.third_party:
            allowed = _AUTO_REPLY_EFFECTS if run.auto_reply else frozenset()
            if effects - allowed:
                return (
                    "This run was started by a message from a third party, so "
                    "it may only read and notify the user"
                )
        if (
            policy.limit_scheduled_runs
            and run.source in SCHEDULED_SOURCES
            and Effect.CHANGE_AGENT in effects
        ):
            return "A scheduled task cannot change schedules or CraftBot's setup"
        return ""

    async def _review_by_model(
        self, policy, action, effects, input_data, command: str, risk: str, session: str
    ) -> Optional[Dict[str, Any]]:
        """Auto mode on: a reviewer model decides on a risky command
        (OpenClaw's exec auto reviewer, Hermes' smart approvals)."""
        from app.security.command_review import review_with_model

        verdict, why = await review_with_model(
            command, risk, cwd=input_data.get("cwd") or input_data.get("working_directory")
        )
        if verdict == "allow":
            self._audit(policy, action, effects, "allowed_by_reviewer", session)
            return None
        self._audit(policy, action, effects, "refused_by_reviewer", session)
        return _blocked(
            f"Not run: {risk}, and the command reviewer refused it ({why}). "
            f"Do not try another way; ask the user to run it themselves if it "
            f"is really needed.",
            "command_refused",
        )

    def _why_unanswerable(self, run) -> str:
        if not run.interactive:
            return "this run was started by a schedule, with nobody to approve it"
        if run.remote_platform:
            return (
                f"the user is writing from {run.remote_platform}, and approvals "
                f"can only be given in the CraftBot window or terminal"
            )
        if not self.approvals.ui_available():
            return "no CraftBot window or terminal is open to approve it"
        return ""

    # ── after an action ──

    def after(self, action: Any, rendered_output: str, *, session_id: Optional[str]) -> str:
        if result_source_of(action) != ContentSource.NETWORK:
            return rendered_output
        self.runs.mark_tainted(
            session_id, f"the result of {getattr(action, 'display_name', action.name)}"
        )
        return wrap_untrusted(rendered_output, action.name)

    # ── audit ──

    @staticmethod
    def _audit(
        policy: SecurityPolicy, action: Any, effects, outcome: str, session_id: str
    ) -> None:
        try:
            audit.record(
                "action_approval",
                outcome=outcome,
                action=action.name,
                effects=sorted(e.value for e in effects),
                session_id=session_id,
            )
        except Exception as exc:
            logger.warning(f"[SECURITY] Audit write failed: {exc}")


gate = SecurityGate()
