# -*- coding: utf-8 -*-
"""
LLM interface for CraftBot.

Re-exports LLMInterface from agent_core with CraftBot-specific hooks
for state access (using STATE singleton) and usage reporting.
"""

from typing import Any, Dict, Optional

from agent_core.core.impl.llm import LLMInterface as _LLMInterface
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
        db_interface: Optional[Any] = None,
        temperature: float = 0.0,
        max_tokens: int = 8000,
        deferred: bool = False,
    ) -> None:
        # Create log_to_db hook if db_interface provided
        log_to_db = None
        if db_interface:
            def _log_to_db(
                system_prompt: Optional[str],
                user_prompt: str,
                output: str,
                status: str,
                token_count_input: int,
                token_count_output: int,
            ) -> None:
                input_data: Dict[str, Optional[str]] = {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                }
                config: Dict[str, Any] = {
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
                db_interface.log_prompt(
                    input_data=input_data,
                    output=output,
                    provider=self.provider,
                    model=self.model,
                    config=config,
                    status=status,
                    token_count_input=token_count_input,
                    token_count_output=token_count_output,
                )
            log_to_db = _log_to_db

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
            log_to_db=log_to_db,
        )

        # Store db_interface reference for compatibility
        self.db_interface = db_interface
