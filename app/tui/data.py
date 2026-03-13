"""Data classes and types for the TUI interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


TimelineEntry = Tuple[str, str, str]


@dataclass
class ActionItem:
    """Single action or task entry for display in the action panel.

    This is a simplified structure that tracks both tasks and actions
    in a flat list, using unique IDs for reliable matching.
    """
    id: str                          # Unique ID (task_id for tasks, generated for actions)
    display_name: str                # What to show in UI
    item_type: str                   # "task" or "action"
    status: str                      # "running", "completed", "error"
    task_id: Optional[str] = None    # Parent task ID (for actions only)
    created_at: float = 0.0          # Timestamp for ordering


@dataclass
class ActionPanelUpdate:
    """Update message for action panel."""
    operation: str                   # "add", "update", "clear"
    item: Optional[ActionItem] = None


@dataclass
class FootageUpdate:
    """Container for VM footage updates."""
    image_bytes: bytes
    timestamp: float
    container_id: str = ""
