# -*- coding: utf-8 -*-
"""
Image generation interface for CraftBot.

Re-exports ImageGenInterface from agent_core with CraftBot-specific hooks
for state access (using STATE singleton) and usage reporting.
"""

from typing import Optional

from agent_core.core.impl.image_gen import ImageGenInterface as _ImageGenInterface
from agent_core.core.hooks.types import UsageEventData
from app.state.agent_state import get_session_props


def _get_token_count() -> int:
    return get_session_props().get_property("token_count", 0)


def _set_token_count(count: int) -> None:
    get_session_props().set_property("token_count", count)


async def _report_usage(event: UsageEventData) -> None:
    from app.usage import get_usage_reporter

    await get_usage_reporter().report(event)


class ImageGenInterface(_ImageGenInterface):
    """ImageGenInterface configured for CraftBot's STATE singleton.

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
        deferred: bool = False,
    ) -> None:
        super().__init__(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            deferred=deferred,
            get_token_count=_get_token_count,
            set_token_count=_set_token_count,
            report_usage=_report_usage,
        )
