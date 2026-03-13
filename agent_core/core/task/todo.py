# -*- coding: utf-8 -*-
"""
Todo item dataclass for simple task tracking.

This replaces the complex Step-based workflow with a straightforward
todo list mechanism similar to Claude Code's TodoWrite tool.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Literal

TodoStatus = Literal["pending", "in_progress", "completed"]


@dataclass
class TodoItem:
    """
    A simple todo item for tracking task progress.

    Attributes:
        content: What needs to be done (imperative form, e.g., "Run tests")
        status: Current state - pending, in_progress, or completed
        active_form: Present continuous form shown during execution
                     (e.g., "Running tests")
        id: Unique identifier used as action_id when reporting to chatserver.
    """
    content: str
    status: TodoStatus = "pending"
    active_form: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the todo item."""
        result = {
            "content": self.content,
            "status": self.status,
            "id": self.id,
        }
        if self.active_form:
            result["active_form"] = self.active_form
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TodoItem":
        """Create a TodoItem from a dictionary."""
        return cls(
            content=data.get("content", ""),
            status=data.get("status", "pending"),
            active_form=data.get("active_form"),
            id=data.get("id", str(uuid.uuid4())),
        )
