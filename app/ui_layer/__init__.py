"""
CraftBot UI Layer.

Centralized UI abstraction layer that provides common functionality for
all interface implementations (CLI, TUI, Browser).

Core Components:
- controller: Central UIController that coordinates all UI operations
- events: Pub/sub event system for UI updates
- state: Unified state management with reactive updates
- commands: Command registration and execution
- themes: Abstract styling that adapters implement
- components: Protocol definitions for UI components
- adapters: Interface-specific implementations
- onboarding: Shared onboarding flow logic
- settings: MCP and skill settings management
"""

from app.ui_layer.controller.ui_controller import UIController
from app.ui_layer.events.event_types import UIEvent, UIEventType
from app.ui_layer.events.event_bus import EventBus
from app.ui_layer.state.ui_state import UIState, AgentStateType
from app.ui_layer.state.store import UIStateStore
from app.ui_layer.commands.registry import CommandRegistry
from app.ui_layer.commands.base import Command, CommandResult
from app.ui_layer.adapters.base import InterfaceAdapter

__all__ = [
    "UIController",
    "UIEvent",
    "UIEventType",
    "EventBus",
    "UIState",
    "AgentStateType",
    "UIStateStore",
    "CommandRegistry",
    "Command",
    "CommandResult",
    "InterfaceAdapter",
]
