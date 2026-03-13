# -*- coding: utf-8 -*-
"""
Hook definitions for agent-specific behavior.

This module provides hook type definitions that allow agent-specific
behavior to be injected into shared components. Hooks are optional
callbacks that components can call at specific points in their lifecycle.

CraftBot typically passes no hooks (local-only operation).
CraftBot passes hooks for chatserver integration.

Example:
    from agent_core.core.hooks import OnTaskCreatedHook

    async def my_task_created_hook(task: Task) -> None:
        # Post task to chatserver
        await network.post("/api/tasks", task.to_dict())

    task_manager = TaskManager(on_task_created=my_task_created_hook)
"""

from agent_core.core.hooks.types import (
    # Task hooks
    OnTaskCreatedHook,
    OnTaskEndedHook,
    OnTodoTransitionHook,
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
)

__all__ = [
    # Task hooks
    "OnTaskCreatedHook",
    "OnTaskEndedHook",
    "OnTodoTransitionHook",
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
]
