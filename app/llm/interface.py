# -*- coding: utf-8 -*-
"""
LLM interface for CraftBot.

Re-exports LLMInterface from agent_core with CraftBot-specific hooks
for state access (using STATE singleton) and usage reporting.
"""

from typing import Optional

from agent_core.core.impl.llm import LLMInterface as _LLMInterface
from agent_core.core.hooks.types import UsageEventData, LLMCallRecord
from app.state.agent_state import get_session_props


def _get_token_count() -> int:
    """Get token count from the active task's StateSession (per-task counter)."""
    return get_session_props().get_property("token_count", 0)


def _set_token_count(count: int) -> None:
    """Set token count on the active task's StateSession (per-task counter)."""
    get_session_props().set_property("token_count", count)


async def _report_usage(event: UsageEventData) -> None:
    """Report usage to local storage via UsageReporter."""
    from app.usage import get_usage_reporter

    await get_usage_reporter().report(event)


def _record_llm_call(record: LLMCallRecord) -> None:
    """Persist a full LLM call (prompt + response + identity + latency) to the
    local llm_calls store — the capture substrate for the prompt profiler and
    eval-case harvesting (docs/design/prompt-optimization.md).

    Runs synchronously in the LLM worker thread; the base wraps the call in
    try/except so a storage hiccup never breaks an LLM call.
    """
    from app.usage import get_llm_call_storage, LLMCallRow

    get_llm_call_storage().insert(
        LLMCallRow(
            provider=record.provider,
            model=record.model,
            system_prompt=record.system_prompt,
            user_prompt=record.user_prompt,
            response=record.response,
            status=record.status,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            cached_tokens=record.cached_tokens,
            cache_creation_tokens=record.cache_creation_tokens,
            latency_ms=record.latency_ms,
            prompt_name=record.prompt_name,
            prompt_version=record.prompt_version,
            call_type=record.call_type,
            task_id=record.task_id,
            session_id=record.session_id,
            metadata=record.metadata,
        )
    )


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
            record_llm_call=_record_llm_call,  # Full-call capture for profiler/eval
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
        """Override: attribute to the active session SYNCHRONOUSLY at the call
        site, then defer to the base for the async storage report.

        The base implementation schedules the report hook as an asyncio task,
        which means by the time the hook runs, STATE.current_session may have
        already been swapped to a different session (or cleared) by a
        subsequent trigger. Doing attribution synchronously here guarantees
        the counters land on the session that actually made the LLM call.
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
