# -*- coding: utf-8 -*-
"""
LLM interface for CraftBot.

Re-exports LLMInterface from agent_core with CraftBot-specific hooks
for state access (using STATE singleton) and usage reporting.

Hosted-version addition: a managed-Bedrock quota guard. When the dashboard
has set a usage lock (signalled back to the agent in the response body of
the most recent /heartbeat or /usage callback), Bedrock calls short-circuit
locally with a QUOTA-category error that prompts the user to switch to BYOK.
The check itself is a pure local-memory read — no I/O on the LLM hot path.
"""

from typing import Any, Dict, Optional

from agent_core.core.impl.llm import LLMInterface as _LLMInterface
from agent_core.core.impl.llm.errors import (
    ErrorAction,
    ErrorCategory,
    LLMErrorInfo,
)
from agent_core.core.hooks.types import UsageEventData
from app.state.agent_state import get_session_props


def _get_token_count() -> int:
    """Get token count from the active task's StateSession (per-task counter)."""
    return get_session_props().get_property("token_count", 0)


def _set_token_count(count: int) -> None:
    """Set token count on the active task's StateSession (per-task counter)."""
    get_session_props().set_property("token_count", count)


async def _report_usage(event: UsageEventData) -> None:
    """Report usage to local SQLite AND forward to the craftbot.live dashboard.

    Local storage stays the source of truth for in-container analytics and
    works offline. The dashboard mirror is fire-and-forget — if the dashboard
    is unreachable, the network_interface drops/retries on its own and the
    local copy is unaffected. See app/network_interface/outbound.py.
    """
    from app.usage import get_usage_reporter
    from app.network_interface import report_usage_to_dashboard

    await get_usage_reporter().report(event)
    # Fire-and-forget: returns immediately, actual HTTP happens in a background
    # task with bounded retry. Disabled (no-op) when CONTAINER_AUTH_TOKEN /
    # CONTAINER_INSTANCE_ID / CONTAINER_DASHBOARD_URL are unset.
    await report_usage_to_dashboard(event)


class LLMInterface(_LLMInterface):
    """LLMInterface configured for CraftBot's STATE singleton.

    Automatically injects the get_token_count and set_token_count hooks
    that use CraftBot's global STATE object.
    """

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 8000,
        deferred: bool = False,
    ) -> None:
        super().__init__(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            deferred=deferred,
            get_token_count=_get_token_count,
            set_token_count=_set_token_count,
            report_usage=_report_usage,  # Report usage to local SQLite storage
        )

    def _report_usage_async(
        self,
        service_type: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        """Override: attribute to the active task SYNCHRONOUSLY at the call
        site, then defer to the base for the async storage report.

        The base implementation schedules the report hook as an asyncio task,
        which means by the time the hook runs, STATE.current_task may have
        already been swapped to a different task (or cleared) by a subsequent
        trigger. Doing attribution synchronously here guarantees the counters
        land on the task that actually made the LLM call.
        """
        from app.usage.task_attribution import attribute_usage_to_current_task

        attribute_usage_to_current_task(
            UsageEventData(
                service_type=service_type,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
            )
        )
        super()._report_usage_async(
            service_type,
            provider,
            model,
            input_tokens,
            output_tokens,
            cached_tokens,
        )

    def _generate_bedrock(
        self,
        system_prompt: Optional[str],
        user_prompt: Optional[str],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Managed-provider quota guard.

        Only fires when the active provider is `craftbot` (the managed default
        that bills back to craftbot.live). BYOK `bedrock` uses the user's own
        AWS account, so quota lock is not applicable and the call falls
        through to the base interface unmodified.

        For `craftbot`: if the cached dashboard lock state says the user is
        over their monthly budget, refuse the call locally with a structured
        error in the same shape the base interface expects from a failed
        provider call. The chat surface picks up `error_info_obj` and renders
        the QUOTA bubble with the "Open settings" action so the user can
        switch to BYOK.

        The check is `is_quota_locked()`, a pure local-memory read: no HTTP,
        no DB, no lock contention with the dashboard.
        """
        if self.provider == "craftbot":
            from app.network_interface import is_quota_locked, get_quota_reset

            if is_quota_locked():
                reset_at = get_quota_reset()
                reset_str = (
                    reset_at.strftime("%B %d, %Y")
                    if reset_at
                    else "the next billing period"
                )
                message = (
                    f"Your CraftBot managed quota has been used up for this "
                    f"month (resets {reset_str}). To keep using LLM features, "
                    f"switch to a BYOK provider under Settings > Models, or "
                    f"wait for the monthly reset."
                )
                info = LLMErrorInfo(
                    category=ErrorCategory.QUOTA,
                    title="CraftBot managed quota exhausted",
                    message=message,
                    provider="craftbot",
                    model=self.model,
                    actions=[
                        ErrorAction(
                            label="Open settings",
                            action="open_settings_model",
                        ),
                    ],
                )
                return {
                    "content": "",
                    "error": info.message,
                    "error_info_obj": info,
                    "tokens_used": 0,
                }

        return super()._generate_bedrock(system_prompt, user_prompt, **kwargs)
