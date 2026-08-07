# -*- coding: utf-8 -*-
"""
Shared type definitions for state management.

This module contains types that are used by both CraftBot and CraftBot
state implementations.
"""

from dataclasses import dataclass
from typing import Any, Dict, NamedTuple, Optional
import logging

# Default configuration values - can be overridden at runtime
DEFAULT_MAX_ACTIONS_PER_TASK = 150
DEFAULT_MAX_TOKEN_PER_TASK = 6_000_000

# Use standard logging since loguru may not be available during import
_logger = logging.getLogger(__name__)


class AgentProperties:
    """
    Container for global agent properties that persist across a task lifecycle.

    This class provides a flexible key-value store for agent properties
    with some predefined fields for common use cases like action counting
    and token tracking.

    Attributes:
        current_task_id: ID of the currently active task
        action_count: Number of actions executed in current task
        max_actions_per_task: Maximum allowed actions per task
        token_count: Number of tokens used in current task
        max_tokens_per_task: Maximum allowed tokens per task
    """

    def __init__(
        self,
        current_task_id: str = "",
        action_count: int = 0,
        max_actions_per_task: Optional[int] = None,
        max_tokens_per_task: Optional[int] = None,
    ):
        """
        Initialize AgentProperties.

        Args:
            current_task_id: ID of the current task (default: empty string)
            action_count: Initial action count (default: 0)
            max_actions_per_task: Maximum actions allowed per task.
                If None, uses DEFAULT_MAX_ACTIONS_PER_TASK.
            max_tokens_per_task: Maximum tokens allowed per task.
                If None, uses DEFAULT_MAX_TOKEN_PER_TASK.
        """
        self.current_task_id = current_task_id
        self.action_count: int = action_count
        self.max_actions_per_task: int = (
            max_actions_per_task
            if max_actions_per_task is not None
            else DEFAULT_MAX_ACTIONS_PER_TASK
        )
        self.token_count: int = 0
        self.max_tokens_per_task: int = (
            max_tokens_per_task
            if max_tokens_per_task is not None
            else DEFAULT_MAX_TOKEN_PER_TASK
        )

        # Validate config values
        if self.max_actions_per_task < 5:
            _logger.warning(
                f"[MAX ACTIONS] The maximum actions per task is set to "
                f"{self.max_actions_per_task}, which is lesser than the minimum. "
                "Resetting maximum actions per task to 5"
            )
            self.max_actions_per_task = 5

        if self.max_tokens_per_task < 100000:
            _logger.warning(
                f"[MAX TOKENS] The maximum tokens per task is set to "
                f"{self.max_tokens_per_task}, which is lesser than the minimum. "
                "Resetting maximum tokens per task to 100,000"
            )
            self.max_tokens_per_task = 100000

    # ───────────────
    # Public API
    # ───────────────

    def set_property(self, key: str, value: Any) -> None:
        """
        Set or override an agent property.

        Args:
            key: Property name
            value: Property value
        """
        setattr(self, key, value)

    def get_property(self, key: str, default: Any = None) -> Any:
        """
        Safely read a property value.

        Args:
            key: Property name
            default: Default value if property doesn't exist

        Returns:
            Property value or default
        """
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        """
        Get external-safe snapshot of agent state.

        Returns:
            Dictionary containing all standard properties
        """
        return self._to_dict()

    # ───────────────
    # Internal helpers
    # ───────────────

    def _to_dict(self) -> Dict[str, Any]:
        """
        Internal: canonical source of agent state.

        Returns:
            Dictionary with core property values
        """
        return {
            "current_task_id": self.current_task_id,
            "action_count": self.action_count,
            "max_actions_per_task": self.max_actions_per_task,
            "token_count": self.token_count,
            "max_tokens_per_task": self.max_tokens_per_task,
        }


class ReasoningResult(NamedTuple):
    """
    Result of an agent reasoning step.

    Attributes:
        reasoning: The reasoning/thought process explanation
        action_query: The query/instruction for action selection
    """

    reasoning: str
    action_query: str


# ─────────────────────────────────────────────────────────────────────────────
# Two-Tier State Types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MainState:
    """Cross-session runtime state.

    Holds process-wide context that is not owned by any single session,
    such as the main event stream snapshot and the GUI flag.

    Attributes:
        main_event_stream: Snapshot of main event stream for context
        gui_mode: Whether running in GUI mode
    """

    main_event_stream: str = ""
    gui_mode: bool = False
