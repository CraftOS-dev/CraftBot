# -*- coding: utf-8 -*-
"""
Protocol definitions for state management.

This module defines the StateProvider protocol that abstracts the difference
between CraftBot's global STATE singleton and CraftBot's session-based
StateSession pattern.

Both implementations satisfy this protocol through structural typing (duck typing),
meaning they don't need to explicitly inherit from StateProvider - they just need
to implement the required methods and properties.
"""

from typing import Protocol, Optional, Any, Dict


class StateProvider(Protocol):
    """
    Protocol defining the common interface for state access.

    This protocol is satisfied by:
    - CraftBot's AgentState (accessed via global STATE)
    - CraftBot's StateSession (accessed via StateSession.get())

    Both implementations provide the same core functionality:
    - Session context (current_session)
    - Event stream tracking
    - GUI mode flag
    - Agent properties storage

    Example usage in shared code:
        from agent_core.core.state import get_state

        def some_shared_function():
            state = get_state()
            if state.current_session:
                # do something with the session
                pass
    """

    @property
    def current_session(self) -> Optional[Any]:
        """
        Get the current session being processed.

        Returns:
            The current Session object, or None if no session is active.
        """
        ...

    @property
    def event_stream(self) -> Optional[str]:
        """
        Get the current event stream content.

        Returns:
            String content of the event stream, or None if empty.
        """
        ...

    @property
    def gui_mode(self) -> bool:
        """
        Check if the agent is in GUI mode.

        Returns:
            True if GUI mode is active, False otherwise.
        """
        ...

    def get_agent_property(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a global agent property value.

        Args:
            key: The property key to retrieve.
            default: Default value if key doesn't exist.

        Returns:
            The property value, or default if not found.
        """
        ...

    def set_agent_property(self, key: str, value: Any) -> None:
        """
        Set a global agent property value.

        Args:
            key: The property key to set.
            value: The value to store.
        """
        ...

    def get_agent_properties(self) -> Dict[str, Any]:
        """
        Retrieve all global agent properties.

        Returns:
            Dictionary of all agent properties.
        """
        ...

    def update_current_session(self, session: Optional[Any]) -> None:
        """
        Update the current session.

        Args:
            session: The new Session object, or None to clear.
        """
        ...

    def update_event_stream(self, event_stream: Optional[str]) -> None:
        """
        Update the event stream content.

        Args:
            event_stream: New event stream content, or None to clear.
        """
        ...

    def update_gui_mode(self, gui_mode: bool) -> None:
        """
        Update the GUI mode flag.

        Args:
            gui_mode: True to enable GUI mode, False to disable.
        """
        ...
