# -*- coding: utf-8 -*-
"""
Session dataclass — the single work primitive of the agent.

A Session is a persistent, standalone agent lane. Every session has its own
event stream, its own durable trigger queue, its own serial agent loop, and
its own loaded capabilities (action sets + skills), todos and run budgets.

Sessions never "end": a run (wake → work → final message) simply stops
enqueuing continuation triggers, and the session waits for its next input.
Sessions exist until the user deletes them (main is permanent).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

from agent_core.core.session.todo import TodoItem


class SessionType:
    """Allowed session types (plain constants — stored as strings)."""

    MAIN = "main"
    CHAT = "chat"
    LIVING_UI = "living_ui"

    ALL = (MAIN, CHAT, LIVING_UI)


# The singleton main session id. All ambient input (integrations, scheduler,
# special workflows, restart notices, dead letters) lands here.
MAIN_SESSION_ID = "main"


@dataclass
class Session:
    """
    A persistent agent session.

    Attributes:
        id: Unique identifier (``main`` for the main session).
        type: One of SessionType.ALL — main | chat | living_ui.
        title: Human-readable title shown in the sidebar (auto-generated
            for chat sessions after the first exchange, renamable).
        created_at: ISO timestamp when the session was created.
        last_active_at: ISO timestamp of the last run activity.
        archived: Soft-hide flag (session kept, hidden from the sidebar).
        action_sets: Loaded action set names (always includes ``core``).
        compiled_actions: Cached action names compiled from action_sets.
        selected_skills: Skills currently loaded into this session.
        todos: Current todo list for the active run.
        workspace_dir: Persistent scratch directory for this session.
        living_ui_project_id: Backing project id for living_ui sessions.
        gui_mode: Whether this session drives the GUI action space.
        action_count/token_count: Budget counters for the current run
            (reset when a new run starts).
        input_tokens/output_tokens/cache_tokens: LLM usage breakdown for
            the current run.
    """

    id: str
    type: str = SessionType.CHAT
    title: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_active_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    archived: bool = False
    # Capabilities
    action_sets: List[str] = field(default_factory=list)
    compiled_actions: List[str] = field(default_factory=list)
    selected_skills: List[str] = field(default_factory=list)
    # Backup of CLI actions when in GUI mode (internal use only)
    _saved_cli_actions: List[str] = field(default_factory=list)
    # Run state
    todos: List[TodoItem] = field(default_factory=list)
    workspace_dir: Optional[str] = None
    living_ui_project_id: Optional[str] = None
    gui_mode: bool = False
    # Per-run budget counters
    action_count: int = 0
    token_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0

    def touch(self) -> None:
        """Update last_active_at to now."""
        self.last_active_at = datetime.utcnow().isoformat()

    def reset_run_counters(self) -> None:
        """Reset per-run budget counters (called when a new run starts)."""
        self.action_count = 0
        self.token_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_tokens = 0

    def get_current_todo(self) -> Optional[TodoItem]:
        """
        Return the todo item that should be worked on next.

        First looks for any todo marked as in_progress, then falls back
        to the first pending todo. Returns None if all todos are completed.
        """
        for todo in self.todos:
            if todo.status == "in_progress":
                return todo
        for todo in self.todos:
            if todo.status == "pending":
                return todo
        return None

    def all_todos_completed(self) -> bool:
        """Check if all todos are completed."""
        if not self.todos:
            return True
        return all(t.status == "completed" for t in self.todos)

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the session."""
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "archived": self.archived,
            "action_sets": self.action_sets,
            "compiled_actions": self.compiled_actions,
            "selected_skills": self.selected_skills,
            "todos": [todo.to_dict() for todo in self.todos],
            "workspace_dir": self.workspace_dir,
            "living_ui_project_id": self.living_ui_project_id,
            "gui_mode": self.gui_mode,
            "action_count": self.action_count,
            "token_count": self.token_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_tokens": self.cache_tokens,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create a Session from a dictionary."""
        todos = [TodoItem.from_dict(t) for t in data.get("todos", [])]
        return cls(
            id=data["id"],
            type=data.get("type", SessionType.CHAT),
            title=data.get("title", ""),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            last_active_at=data.get(
                "last_active_at", datetime.utcnow().isoformat()
            ),
            archived=data.get("archived", False),
            action_sets=data.get("action_sets", []),
            compiled_actions=data.get("compiled_actions", []),
            selected_skills=data.get("selected_skills", []),
            todos=todos,
            workspace_dir=data.get("workspace_dir"),
            living_ui_project_id=data.get("living_ui_project_id"),
            gui_mode=data.get("gui_mode", False),
            action_count=data.get("action_count", 0),
            token_count=data.get("token_count", 0),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_tokens=data.get("cache_tokens", 0),
        )
