"""Unified UI state definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set


class AgentStateType(Enum):
    """Agent state types."""

    IDLE = "idle"
    WORKING = "working"


@dataclass
class ActionItemState:
    """
    State for an activity item (action/reasoning) tracked by the UI.

    Attributes:
        id: Unique identifier for this item
        display_name: Name to display in the UI
        item_type: Either "action" or "reasoning"
        status: "running", "completed", or "error"
        created_at: Unix timestamp when created
    """

    id: str
    display_name: str
    item_type: str  # "action" or "reasoning"
    status: str  # "running", "completed", "error"
    created_at: float = 0.0


@dataclass
class UIState:
    """
    Unified UI state shared across all interfaces.

    This is the single source of truth for UI state. All interfaces
    (CLI, Browser) read from this state and receive updates
    when it changes.

    Attributes:
        agent_state: Current agent state (idle, working)
        gui_mode: Whether GUI mode is active (screen automation)
        action_items: All activity items by ID
        action_order: Order in which to display activity items
        show_menu: Whether to show the menu screen
        show_settings: Whether to show settings panel
        settings_tab: Current settings tab
        current_provider: Active LLM provider
        seen_event_keys: Keys of events already processed (for deduplication)
        status_message: Current status bar message
        tracked_sessions: Session IDs the UI is aware of
    """

    # Agent state
    agent_state: AgentStateType = AgentStateType.IDLE
    gui_mode: bool = False

    # Activity feed state
    action_items: Dict[str, ActionItemState] = field(default_factory=dict)
    action_order: List[str] = field(default_factory=list)

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

    def has_running_items(self) -> bool:
        """Check if there are any running activity items."""
        return any(item.status == "running" for item in self.action_items.values())
