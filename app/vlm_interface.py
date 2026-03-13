# -*- coding: utf-8 -*-
"""
VLM interface for CraftBot.

Re-exports VLMInterface from agent_core with CraftBot-specific hooks
for state access (using STATE singleton) and usage reporting.
"""

from typing import Optional

from agent_core.core.impl.vlm import VLMInterface as _VLMInterface
from agent_core.core.hooks.types import UsageEventData
from app.state.agent_state import STATE


def _get_token_count() -> int:
    """Get token count from CraftBot's global STATE."""
    return STATE.get_agent_property("token_count", 0)


def _set_token_count(count: int) -> None:
    """Set token count in CraftBot's global STATE."""
    STATE.set_agent_property("token_count", count)


async def _report_usage(event: UsageEventData) -> None:
    """Report usage to local storage via UsageReporter."""
    from app.usage import get_usage_reporter
    await get_usage_reporter().report(event)


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
        temperature: float = 0.5,
        deferred: bool = False,
    ) -> None:
        super().__init__(
            provider=provider,
            model=model,
            temperature=temperature,
            deferred=deferred,
            get_token_count=_get_token_count,
            set_token_count=_set_token_count,
            report_usage=_report_usage,  # Report usage to local SQLite storage
        )
