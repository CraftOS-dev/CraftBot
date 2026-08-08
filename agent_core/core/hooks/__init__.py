# -*- coding: utf-8 -*-
"""
Hook definitions for agent-specific behavior.

This module provides hook type definitions that allow agent-specific
behavior to be injected into shared components. Hooks are optional
callbacks that components can call at specific points in their lifecycle.

CraftBot typically passes no hooks (local-only operation).
CraftBot passes hooks for chatserver integration.

Example:
    from agent_core.core.hooks import OnActionStartHook

    async def my_action_start_hook(run_id, action, inputs) -> None:
        # Post action start to chatserver
        await network.post("/api/actions", {"run_id": run_id})

    action_manager = ActionManager(..., on_action_start=my_action_start_hook)
"""

from agent_core.core.hooks.types import (
    # Action hooks
    OnActionStartHook,
    OnActionEndHook,
    # Event hooks
    OnEventLoggedHook,
    GetSkipEventTypesHook,
    # Context hooks
    GetConversationHistoryHook,
    GetChatTargetInfoHook,
    GetUserInfoHook,
    # State hooks
    GetTeamInfoHook,
    GetConversationStateHook,
    TransformMessageHook,
    # Token/State hooks
    GetTokenCountHook,
    SetTokenCountHook,
    # Usage reporting hooks
    UsageEventData,
    ReportUsageHook,
    # Database logging hooks
    LogToDbHook,
    # LLM call capture hooks (prompt profiler / eval)
    LLMCallRecord,
    RecordLLMCallHook,
)

__all__ = [
    # Action hooks
    "OnActionStartHook",
    "OnActionEndHook",
    # Event hooks
    "OnEventLoggedHook",
    "GetSkipEventTypesHook",
    # Context hooks
    "GetConversationHistoryHook",
    "GetChatTargetInfoHook",
    "GetUserInfoHook",
    # State hooks
    "GetTeamInfoHook",
    "GetConversationStateHook",
    "TransformMessageHook",
    # Token/State hooks
    "GetTokenCountHook",
    "SetTokenCountHook",
    # Usage reporting hooks
    "UsageEventData",
    "ReportUsageHook",
    # Database logging hooks
    "LogToDbHook",
    # LLM call capture hooks (prompt profiler / eval)
    "LLMCallRecord",
    "RecordLLMCallHook",
]
