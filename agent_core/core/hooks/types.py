# -*- coding: utf-8 -*-
"""
Hook type definitions for agent-specific behavior.

This module defines type aliases for hooks that can be injected into
shared components to customize their behavior. Each hook is an optional
callback that components invoke at specific lifecycle points.

Hook Categories:
    - Task hooks: Task creation, completion, todo transitions
    - Action hooks: Action start, action end
    - Event hooks: Event logging, event filtering
    - Context hooks: Conversation history, user info
    - State hooks: Team info, conversation state

All hooks are optional - if not provided, the component operates in
local-only mode (suitable for CraftBot).
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core import Task, TodoItem, Action


# =============================================================================
# Task Hooks
# =============================================================================

OnTaskCreatedHook = Callable[["Task"], Awaitable[None]]
"""
Called when a new task is created.

Args:
    task: The newly created Task object.

Used by CraftBot to POST task to chatserver as a divisible action.
"""

OnTaskEndedHook = Callable[["Task", str, Optional[str]], Awaitable[None]]
"""
Called when a task ends (completed, error, or cancelled).

Args:
    task: The Task that ended.
    status: The final status ("completed", "error", "cancelled").
    summary: Optional summary message.

Used by CraftBot to PUT final task status to chatserver.
"""

OnTodoTransitionHook = Callable[["TodoItem", str, str], Awaitable[None]]
"""
Called when a todo item transitions between statuses.

Args:
    todo: The TodoItem that transitioned.
    old_status: Previous status ("pending", "in_progress", "completed").
    new_status: New status.

Used by CraftBot to POST/PUT todo transitions to chatserver.
"""


# =============================================================================
# Action Hooks
# =============================================================================

OnActionStartHook = Callable[[str, "Action", Optional[Dict[str, Any]]], Awaitable[None]]
"""
Called when an action starts executing.

Args:
    run_id: Unique identifier for this action execution.
    action: The Action being executed.
    inputs: Input data passed to the action.

Used by CraftBot to POST action start to chatserver.
"""

OnActionEndHook = Callable[[str, "Action", Optional[Dict[str, Any]], str], Awaitable[None]]
"""
Called when an action finishes executing.

Args:
    run_id: Unique identifier for this action execution.
    action: The Action that was executed.
    outputs: Output data from the action (may include errors).
    status: Final status ("success", "error").

Used by CraftBot to PUT action completion to chatserver.
"""


# =============================================================================
# Event Hooks
# =============================================================================

OnEventLoggedHook = Callable[[str, str, str], None]
"""
Called when an event is logged to the event stream.

Args:
    kind: Event type (e.g., "ACTION_START", "TASK_UPDATE").
    message: Event message content.
    severity: Severity level ("INFO", "WARNING", "ERROR").

Used for file-based logging in both runtimes.
"""

GetSkipEventTypesHook = Callable[[], Set[str]]
"""
Returns event types to skip in unprocessed event logging.

Returns:
    Set of event kind strings to skip.

Used to filter routine events during memory processing.
"""


# =============================================================================
# Context Hooks
# =============================================================================

GetConversationHistoryHook = Callable[[], Awaitable[str]]
"""
Returns formatted conversation history for prompt context.

Returns:
    Formatted string containing conversation history.

Used by CraftBot to include chat history in prompts.
CraftBot returns empty string.
"""

GetChatTargetInfoHook = Callable[[], Awaitable[str]]
"""
Returns information about the current chat target.

Returns:
    Formatted string with chat target details.

Used by CraftBot for multi-conversation context.
CraftBot returns empty string.
"""

GetUserInfoHook = Callable[[], Awaitable[str]]
"""
Returns user profile information for prompt context.

Returns:
    Formatted string with user profile.

Used by CraftBot to personalize responses.
CraftBot returns empty string.
"""


# =============================================================================
# State Hooks
# =============================================================================

GetTeamInfoHook = Callable[[], Awaitable[Optional[Dict[str, Any]]]]
"""
Fetches team information from backend.

Returns:
    Dict with team info, or None if not available.

Used by CraftBot to fetch team context.
CraftBot returns None.
"""

GetConversationStateHook = Callable[[str], Awaitable[Optional[Dict[str, Any]]]]
"""
Fetches conversation state from backend.

Args:
    conversation_id: The conversation to fetch state for.

Returns:
    Dict with conversation state, or None if not available.

Used by CraftBot to fetch conversation history.
CraftBot returns None.
"""

TransformMessageHook = Callable[[Dict[str, Any]], Dict[str, Any]]
"""
Transforms a message dict for display or storage.

Args:
    message: Raw message dict from backend.

Returns:
    Transformed message dict.

Used by CraftBot to format messages.
CraftBot returns message unchanged.
"""


# =============================================================================
# Token/State Hooks
# =============================================================================

GetTokenCountHook = Callable[[], int]
"""
Gets the current token count from state.

Returns:
    Current token count.

CraftBot uses STATE.get_agent_property("token_count", 0).
CraftBot uses StateSession.get_or_none().get_agent_property("token_count", 0).
"""

SetTokenCountHook = Callable[[int], None]
"""
Sets the token count in state.

Args:
    count: New token count value.

CraftBot uses STATE.set_agent_property("token_count", count).
CraftBot uses session.set_agent_property("token_count", count).
"""


# =============================================================================
# Usage Reporting Hooks (CraftBot only)
# =============================================================================

class UsageEventData:
    """Data class for usage event reporting."""

    def __init__(
        self,
        service_type: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ):
        self.service_type = service_type
        self.provider = provider
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cached_tokens = cached_tokens


ReportUsageHook = Callable[[UsageEventData], Awaitable[None]]
"""
Reports usage event for cost tracking.

Args:
    event: UsageEventData with token counts and provider info.

Used by CraftBot to report LLM/VLM usage to backend.
CraftBot does not use this hook (set to None).
"""


# =============================================================================
# Database Logging Hooks (LLM-specific)
# =============================================================================

LogToDbHook = Callable[
    [
        Optional[str],  # system_prompt
        str,            # user_prompt
        str,            # output
        str,            # status ("success" or "failed")
        int,            # token_count_input
        int,            # token_count_output
    ],
    None,
]
"""
Logs LLM prompt/response to database.

Args:
    system_prompt: The system prompt used (can be None).
    user_prompt: The user prompt sent.
    output: The response content or error message.
    status: "success" or "failed".
    token_count_input: Input tokens used.
    token_count_output: Output tokens generated.

Used by both CraftBot and CraftBot when db_interface is provided.
The runtime wrapper creates this hook from the db_interface.
"""
