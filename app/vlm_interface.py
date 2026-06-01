# -*- coding: utf-8 -*-
"""
VLM interface for CraftBot.

Re-exports VLMInterface from agent_core with CraftBot-specific hooks
for state access (using STATE singleton) and usage reporting.

Hosted-version addition: managed-Bedrock quota guard. Symmetric with
app/llm/interface.py — when the dashboard has set a quota lock, the Bedrock
vision path short-circuits with a ManagedQuotaExceededError instead of
calling AWS. VLM doesn't use the LLMErrorInfo classifier (the upstream VLM
interface just re-raises), so we raise an exception; the calling code's
error handling surfaces the message. By the time a VLM-only path actually
hits this guard, the LLM path will usually have already surfaced the QUOTA
chat bubble (LLM is the user-facing surface), so the user has context.
"""

from typing import Any, Dict, Optional

from agent_core.core.impl.vlm import VLMInterface as _VLMInterface
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

    Symmetric with LLMInterface._report_usage — VLM calls are billed too, so
    they need to land in the same dashboard UsageRecord rows. See
    app/network_interface/outbound.py for the fire-and-forget semantics.
    """
    from app.usage import get_usage_reporter
    from app.network_interface import report_usage_to_dashboard

    await get_usage_reporter().report(event)
    await report_usage_to_dashboard(event)


class VLMInterface(_VLMInterface):
    """VLMInterface configured for CraftBot's STATE singleton.

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
        temperature: float = 0.5,
        deferred: bool = False,
    ) -> None:
        super().__init__(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
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
        """Override: attribute to active task synchronously, then defer to base.
        See LLMInterface._report_usage_async for the race-condition rationale.
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

    def _bedrock_describe_bytes(
        self,
        image_bytes,
        system_prompt: Optional[str],
        user_prompt: Optional[str],
    ) -> Dict[str, Any]:
        """Managed-Bedrock vision quota guard.

        Mirrors LLMInterface._generate_bedrock: if the cached dashboard lock
        state says the user is over their monthly budget, refuse locally with
        a ManagedQuotaExceededError. The upstream VLM interface re-raises any
        exception from this method, so the error propagates to the caller.

        The check is a pure local-memory read (no I/O) — keeps the VLM hot
        path unaffected when the user is NOT locked.
        """
        from app.network_interface import (
            is_quota_locked,
            get_quota_reset,
            ManagedQuotaExceededError,
        )

        if is_quota_locked():
            raise ManagedQuotaExceededError(reset_at=get_quota_reset())

        return super()._bedrock_describe_bytes(image_bytes, system_prompt, user_prompt)
