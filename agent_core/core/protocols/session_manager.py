# -*- coding: utf-8 -*-
"""
Protocol definition for SessionManager.

This module defines the SessionManagerProtocol that specifies the
interface for persistent session management.
"""

from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.core.session import Session


class SessionManagerProtocol(Protocol):
    """
    Protocol for persistent session management.

    This defines the minimal interface a session manager must provide for
    creating, looking up, and mutating sessions.
    """

    def get(self, session_id: Optional[str]) -> Optional["Session"]:
        """Look up a session by id."""
        ...

    def ensure_main(self) -> "Session":
        """Create the main session if it does not exist yet."""
        ...

    def create_session(
        self,
        session_type: str = "chat",
        title: str = "",
        session_id: Optional[str] = None,
        action_sets: Optional[List[str]] = None,
        selected_skills: Optional[List[str]] = None,
        agent_app_project_id: Optional[str] = None,
        gui_mode: bool = False,
    ) -> "Session":
        """Create a new persistent session."""
        ...

    def delete_session(self, session_id: str) -> bool:
        """Delete a session permanently."""
        ...

    def clear_session(self, session_id: str) -> bool:
        """Clear a session's conversation."""
        ...

    def update_todos(
        self, session_id: str, todos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Update the todo list for a session."""
        ...

    def get_todos(self, session_id: str) -> List[Dict[str, Any]]:
        """Get a session's current todos."""
        ...

    def add_action_sets(
        self, session_id: str, sets_to_add: List[str]
    ) -> Dict[str, Any]:
        """Add action sets to a session."""
        ...

    def remove_action_sets(
        self, session_id: str, sets_to_remove: List[str]
    ) -> Dict[str, Any]:
        """Remove action sets from a session."""
        ...
