# -*- coding: utf-8 -*-
"""
Protocol definition for TaskManager.

This module defines the TaskManagerProtocol that specifies the
interface for task lifecycle management.
"""

from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core import Task


class TaskManagerProtocol(Protocol):
    """
    Protocol for task lifecycle management.

    This defines the minimal interface that a task manager must provide
    for creating, updating, and completing tasks.
    """

    @property
    def active(self) -> Optional["Task"]:
        """Current session's task."""
        ...

    def create_task(
        self,
        task_name: str,
        task_instruction: str,
        mode: str = "complex",
        action_sets: Optional[List[str]] = None,
        selected_skills: Optional[List[str]] = None,
    ) -> str:
        """
        Create a new task.

        Args:
            task_name: Human-readable identifier.
            task_instruction: Description of the work.
            mode: "simple" or "complex".
            action_sets: List of action set names to enable.
            selected_skills: List of skill names.

        Returns:
            The unique task identifier.
        """
        ...

    def update_todos(self, todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Update todo list for active task.

        Args:
            todos: List of todo item dicts.

        Returns:
            Updated todo list.
        """
        ...

    def get_todos(self) -> List[Dict[str, Any]]:
        """
        Get current todos.

        Returns:
            List of todo item dicts.
        """
        ...

    async def mark_task_completed(
        self,
        message: Optional[str] = None,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
    ) -> bool:
        """
        Mark task completed.

        Args:
            message: Optional completion message.
            summary: Optional summary.
            errors: Optional list of errors.

        Returns:
            True if successful.
        """
        ...

    async def mark_task_error(
        self,
        message: Optional[str] = None,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
    ) -> bool:
        """
        Mark task as failed.

        Args:
            message: Optional error message.
            summary: Optional summary.
            errors: Optional list of errors.

        Returns:
            True if successful.
        """
        ...

    def get_task_by_id(self, task_id: str) -> Optional["Task"]:
        """
        Look up task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            The Task, or None if not found.
        """
        ...

    def reset(self) -> None:
        """Clear all task state."""
        ...
