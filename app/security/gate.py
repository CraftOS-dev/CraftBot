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

from typing import Any, Dict, FrozenSet, Optional

from agent_core.utils.logger import logger
from app.security import audit
from app.security.approvals import ApprovalBroker, Decision, broker as default_broker
from app.security.content import RunRegistry, runs as default_runs, wrap_untrusted
from app.security.policy import (
    ContentSource,
    Effect,
    SecurityPolicy,
    get_policy,
)

_DENIAL_LIMIT = 3


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
        if not policy.gate_active:
            return None

        effects = effects_of(action)
        if not effects:
            return None
        run = self.runs.get(session_id)
        if effects & policy.approval_effects:
            reason, detail = "high_risk", ""
        elif policy.ask_after_untrusted and run.tainted:
            reason, detail = "untrusted_content", run.taint_reason
        else:
            return None

        session = session_id or ""
        if self.approvals.is_granted(session, action.name):
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
