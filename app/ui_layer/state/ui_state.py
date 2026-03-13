"""Unified UI state definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class AgentStateType(Enum):
    """Agent state types."""

    IDLE = "idle"
    WORKING = "working"
    WAITING_FOR_USER = "waiting_for_user"
    TASK_COMPLETED = "task_completed"


@dataclass
class ActionItemState:
    """
    State for an action or task item in the action panel.

    Attributes:
        id: Unique identifier for this item
        display_name: Name to display in the UI
        item_type: Either "task" or "action"
        status: "running", "completed", or "error"
        task_id: Parent task ID (for actions under a task)
        created_at: Unix timestamp when created
    """

    id: str
    display_name: str
    item_type: str  # "task" or "action"
    status: str  # "running", "completed", "error"
    task_id: Optional[str] = None
    created_at: float = 0.0


@dataclass
class UIState:
    """
    Unified UI state shared across all interfaces.

    This is the single source of truth for UI state. All interfaces
    (CLI, TUI, Browser) read from this state and receive updates
    when it changes.

    Attributes:
        agent_state: Current agent state (idle, working, etc.)
        gui_mode: Whether GUI mode is active (screen automation)
        current_task_id: ID of the currently active task
        current_task_name: Display name of the current task
        action_items: All tasks and actions by ID
        action_order: Order in which to display action items
        selected_task_id: Task selected for detail view (TUI/Browser)
        show_menu: Whether to show the menu screen
        show_settings: Whether to show settings panel
        settings_tab: Current settings tab
        current_provider: Active LLM provider
        seen_event_keys: Keys of events already processed (for deduplication)
        status_message: Current status bar message
    """

    # Agent state
    agent_state: AgentStateType = AgentStateType.IDLE
    gui_mode: bool = False

    # Current task tracking
    current_task_id: Optional[str] = None
    current_task_name: Optional[str] = None

    # Action panel state
    action_items: Dict[str, ActionItemState] = field(default_factory=dict)
    action_order: List[str] = field(default_factory=list)
    selected_task_id: Optional[str] = None

    # Loading animation state
    loading_frame_index: int = 0

    # Navigation state
    show_menu: bool = True
    show_settings: bool = False
    settings_tab: str = "models"

    # Provider state
    current_provider: str = "openai"

    # Event deduplication
    seen_event_keys: Set[tuple] = field(default_factory=set)

    # Status message
    status_message: str = "Agent is idle"

    # Tracked sessions
    tracked_sessions: Set[str] = field(default_factory=set)

    def get_tasks(self) -> List[ActionItemState]:
        """Get all task items."""
        return [
            item
            for item_id in self.action_order
            if (item := self.action_items.get(item_id))
            and item.item_type == "task"
        ]

    def get_actions_for_task(self, task_id: str) -> List[ActionItemState]:
        """Get all actions under a specific task."""
        return [
            item
            for item_id in self.action_order
            if (item := self.action_items.get(item_id))
            and item.item_type == "action"
            and item.task_id == task_id
        ]

    def has_running_items(self) -> bool:
        """Check if there are any running tasks or actions."""
        return any(
            item.status == "running" for item in self.action_items.values()
        )
