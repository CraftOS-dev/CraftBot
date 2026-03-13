# -*- coding: utf-8 -*-
"""
State registry for unified state access.

This module provides the StateRegistry class and convenience functions that allow
shared code to access state without knowing whether it's running in CraftBot
(global STATE) or CraftBot (StateSession.get()).

Usage:
    # At application startup (once):

    # CraftBot:
    from agent_core.core.state import StateRegistry
    from app.state.agent_state import STATE
    StateRegistry.register(lambda: STATE)

    # CraftBot:
    from agent_core.core.state import StateRegistry
    from app.state.session import StateSession
    StateRegistry.register(lambda: StateSession.get())

    # In shared code:
    from agent_core.core.state import get_state

    def shared_function():
        state = get_state()
        task = state.current_task
        # ... use state
"""

from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.core.state.protocols import StateProvider
    from agent_core.core.state.session import StateSession


class StateRegistry:
    """
    Global registry that provides access to the current state provider.

    Each project (CraftBot, CraftBot) registers their state provider
    factory function at startup. Shared code then uses get_state() to access
    state without knowing the underlying implementation.

    This uses a factory function pattern rather than storing the state directly
    because:
    - CraftBot: STATE is a module-level singleton, factory returns it directly
    - CraftBot: StateSession.get() returns the current session instance,
      which may change between calls

    Thread Safety:
        The registry itself is not thread-safe for registration (register() should
        only be called once at startup). The factory function may return different
        instances per thread/session depending on the implementation.
    """

    _provider_factory: Optional[Callable[[], "StateProvider"]] = None

    @classmethod
    def register(cls, factory: Callable[[], "StateProvider"]) -> None:
        """
        Register a factory function that returns the current state provider.

        This should be called once at application startup, before any shared
        code attempts to access state.

        Args:
            factory: Callable that returns the current StateProvider instance.
                For CraftBot: lambda: STATE
                For CraftBot: lambda: StateSession.get()

        Example:
            # CraftBot startup
            from app.state.agent_state import STATE
            StateRegistry.register(lambda: STATE)

            # CraftBot startup
            from app.state.session import StateSession
            StateRegistry.register(lambda: StateSession.get())
        """
        cls._provider_factory = factory

    @classmethod
    def get_state(cls) -> "StateProvider":
        """
        Get the current state provider.

        This calls the registered factory function to get the current state
        provider instance.

        Returns:
            The current StateProvider instance.

        Raises:
            RuntimeError: If no provider has been registered via register().
        """
        if cls._provider_factory is None:
            raise RuntimeError(
                "StateRegistry not initialized. "
                "Call StateRegistry.register() with a factory function at application startup. "
                "Example: StateRegistry.register(lambda: STATE)"
            )
        return cls._provider_factory()

    @classmethod
    def get_state_or_none(cls) -> Optional["StateProvider"]:
        """
        Get the current state provider, or None if not available.

        Unlike get_state(), this will not raise an error if the registry
        is not initialized or if the factory function fails.

        Returns:
            The current StateProvider instance, or None if unavailable.
        """
        if cls._provider_factory is None:
            return None
        try:
            return cls._provider_factory()
        except Exception:
            return None

    @classmethod
    def is_registered(cls) -> bool:
        """
        Check if a state provider has been registered.

        Returns:
            True if a provider factory has been registered, False otherwise.
        """
        return cls._provider_factory is not None

    @classmethod
    def clear(cls) -> None:
        """
        Clear the registered provider factory.

        This is primarily useful for testing to reset state between tests.
        """
        cls._provider_factory = None


# Convenience functions for shared code
def get_state() -> "StateProvider":
    """
    Get the current state provider.

    This is the primary function shared code should use to access state.

    Returns:
        The current StateProvider instance.

    Raises:
        RuntimeError: If StateRegistry has not been initialized.

    Example:
        from agent_core.core.state import get_state

        def some_shared_function():
            state = get_state()
            if state.current_task:
                task_id = state.get_agent_property("current_task_id")
                # ... do something
    """
    return StateRegistry.get_state()


def get_state_or_none() -> Optional["StateProvider"]:
    """
    Get the current state provider, or None if not available.

    Use this when state access is optional or when you need to gracefully
    handle the case where state is not available.

    Returns:
        The current StateProvider instance, or None if unavailable.

    Example:
        from agent_core.core.state import get_state_or_none

        def optional_state_access():
            state = get_state_or_none()
            if state and state.current_task:
                # ... do something with state
            else:
                # ... handle no state case
    """
    return StateRegistry.get_state_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# Session-specific state access (for multi-task isolation)
# ─────────────────────────────────────────────────────────────────────────────

def get_session(session_id: str) -> "StateSession":
    """
    Get state for a specific session by ID.

    Use this when you need session-specific state in concurrent task execution.
    Each session has its own isolated state (event_stream, current_task, etc.).

    Args:
        session_id: The session identifier (typically task_id)

    Returns:
        The StateSession instance for this session

    Raises:
        RuntimeError: If session is not found

    Example:
        from agent_core.core.state import get_session

        def task_specific_function(session_id: str):
            session = get_session(session_id)
            event_stream = session.event_stream
            task = session.current_task
            # ... use session-specific state
    """
    from agent_core.core.state.session import StateSession
    return StateSession.get(session_id)


def get_session_or_none(session_id: Optional[str]) -> Optional["StateSession"]:
    """
    Get state for a specific session, or None if not found.

    Use this when session access is optional or when you need to gracefully
    handle the case where the session doesn't exist.

    Args:
        session_id: The session identifier (can be None)

    Returns:
        The StateSession instance, or None if not found or session_id is None

    Example:
        from agent_core.core.state import get_session_or_none

        def optional_session_access(session_id: Optional[str]):
            session = get_session_or_none(session_id)
            if session:
                # Use session-specific state
                event_stream = session.event_stream
            else:
                # Fall back to global state
                event_stream = get_state().event_stream
    """
    from agent_core.core.state.session import StateSession
    return StateSession.get_or_none(session_id)
