# -*- coding: utf-8 -*-
"""
Task dataclass for simple task management.

This simplified version removes the complex Step-based workflow
and uses a simple todo list mechanism instead.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

from agent_core.core.task.todo import TodoItem


@dataclass
class Task:
    """
    A task representing work to be done by the agent.

    Attributes:
        id: Unique identifier for the task
        name: Human-readable name for the task
        instruction: The original user instruction/request
        mode: Task execution mode - "simple" for quick tasks, "complex" for multi-step work
        todos: List of todo items for tracking progress (not used in simple mode)
        temp_dir: Temporary workspace directory for the task
        created_at: ISO timestamp when the task was created
        status: Current state - running, completed, error, paused, or cancelled
        action_sets: Selected action set names for this task (e.g., ["file_operations", "web_research"])
        compiled_actions: Cached list of action names compiled from action_sets
        selected_skills: Skills selected for this task (instructions injected into context)
        conversation_id: Conversation that spawned this task (CraftBot)
        action_count: Per-task action counter
        token_count: Per-task token counter
        chatserver_action_id: UUID for the task-level action on chatserver (CraftBot)
    """
    id: str
    name: str
    instruction: str
    # Allowed: simple | complex
    mode: str = "complex"
    todos: List[TodoItem] = field(default_factory=list)
    temp_dir: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    # Allowed: running | completed | error | paused | cancelled
    status: str = "running"
    # Action sets selected for this task - determines available actions
    action_sets: List[str] = field(default_factory=list)
    # Compiled action names from action_sets - cached for performance
    compiled_actions: List[str] = field(default_factory=list)
    # Backup of CLI actions when in GUI mode (internal use only, CraftBot)
    _saved_cli_actions: List[str] = field(default_factory=list)
    # Skills selected for this task - instructions injected into context
    selected_skills: List[str] = field(default_factory=list)
    # ISO timestamp when the task ended (None if still running)
    ended_at: Optional[str] = None
    # Errors encountered during task execution (if any)
    errors: List[str] = field(default_factory=list)
    # Final summary of the task (populated on task_end)
    final_summary: Optional[str] = None
    # Conversation that spawned this task (persisted across triggers, CraftBot)
    conversation_id: Optional[str] = None
    # Per-task counters (persisted across trigger cycles, CraftBot)
    action_count: int = 0
    token_count: int = 0
    # UUID for the task-level "divisible" action on the chatserver (CraftBot)
    chatserver_action_id: Optional[str] = None

    def get_current_todo(self) -> Optional[TodoItem]:
        """
        Return the todo item that should be worked on next.

        First looks for any todo marked as in_progress, then falls back
        to the first pending todo. Returns None if all todos are completed.
        """
        # Prefer explicitly marked in_progress
        for todo in self.todos:
            if todo.status == "in_progress":
                return todo
        # Fallback to first pending
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
        """Return a dictionary representation of the task."""
        return {
            "id": self.id,
            "name": self.name,
            "instruction": self.instruction,
            "mode": self.mode,
            "status": self.status,
            "todos": [todo.to_dict() for todo in self.todos],
            "action_sets": self.action_sets,
            "compiled_actions": self.compiled_actions,
            "selected_skills": self.selected_skills,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
            "errors": self.errors,
            "final_summary": self.final_summary,
            "conversation_id": self.conversation_id,
            "action_count": self.action_count,
            "token_count": self.token_count,
            "chatserver_action_id": self.chatserver_action_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create a Task from a dictionary."""
        todos = [TodoItem.from_dict(t) for t in data.get("todos", [])]
        return cls(
            id=data["id"],
            name=data["name"],
            instruction=data["instruction"],
            mode=data.get("mode", "complex"),
            todos=todos,
            temp_dir=data.get("temp_dir"),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
            status=data.get("status", "running"),
            action_sets=data.get("action_sets", []),
            compiled_actions=data.get("compiled_actions", []),
            selected_skills=data.get("selected_skills", []),
            ended_at=data.get("ended_at"),
            errors=data.get("errors", []),
            final_summary=data.get("final_summary"),
            conversation_id=data.get("conversation_id"),
            action_count=data.get("action_count", 0),
            token_count=data.get("token_count", 0),
            chatserver_action_id=data.get("chatserver_action_id"),
        )
