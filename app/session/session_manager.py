# -*- coding: utf-8 -*-
"""
SessionManager for CraftBot.

Thin wrapper around the shared agent_core SessionManager. CraftBot uses the
per-session state registry and per-session event streams, and persists
sessions to SessionStorage on every state change.
"""

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from pathlib import Path

from agent_core.core.impl.session import SessionManager as _SessionManager
from agent_core.core.session import Session
from agent_core.core.state.session import StateSession
from app.event_stream import EventStreamManager
from app.config import AGENT_WORKSPACE_ROOT
from app.logger import logger

if TYPE_CHECKING:
    from app.llm import LLMInterface
    from app.context_engine import ContextEngine


# Hook signature: (session, updated_todos_as_dicts) -> None.
# Fires after every update_todos call, regardless of transitions, so
# subscribers see the initial all-pending plan as well as later updates.
PostUpdateTodosHook = Callable[[Session, List[Dict[str, Any]]], None]


def _get_agent_property(session_id: str):
    def getter(name: str, default):
        state = StateSession.get_or_none(session_id)
        return state.get_agent_property(name, default) if state else default

    return getter


def _make_on_stream_create(event_stream_manager: EventStreamManager):
    """Create hook for per-session event stream creation."""

    def on_stream_create(session_id: str, workspace_dir: Path) -> None:
        event_stream_manager.create_stream(session_id, workspace_dir)

    return on_stream_create


def _make_on_stream_remove(event_stream_manager: EventStreamManager):
    """Create hook for event stream removal on session deletion."""

    def on_stream_remove(session_id: str) -> None:
        event_stream_manager.remove_stream(session_id)

    return on_stream_remove


def _on_session_persist(session: Session) -> None:
    """Persist session state to SessionStorage."""
    try:
        from app.usage.session_storage import get_session_storage

        get_session_storage().persist_session(session)
    except Exception as e:
        logger.warning(f"[SessionManager] Failed to persist session {session.id}: {e}")


def _on_session_delete(session_id: str) -> None:
    """Remove a deleted session's persisted rows (session + event stream)."""
    try:
        from app.usage.session_storage import get_session_storage

        get_session_storage().remove_session(session_id)
    except Exception as e:
        logger.warning(
            f"[SessionManager] Failed to remove persisted session {session_id}: {e}"
        )


class SessionManager(_SessionManager):
    """SessionManager configured for CraftBot.

    Per-session event streams, SessionStorage persistence, and todo-update
    hooks for UI observers (Living UI creation progress, browser todos).
    """

    def __init__(
        self,
        event_stream_manager: EventStreamManager,
        llm_interface: Optional["LLMInterface"] = None,
        context_engine: Optional["ContextEngine"] = None,
    ):
        self._post_update_todos_hooks: List[PostUpdateTodosHook] = []

        super().__init__(
            event_stream_manager=event_stream_manager,
            llm_interface=llm_interface,
            context_engine=context_engine,
            workspace_root=Path(AGENT_WORKSPACE_ROOT),
            on_stream_create=_make_on_stream_create(event_stream_manager),
            on_stream_remove=_make_on_stream_remove(event_stream_manager),
            on_session_persist=_on_session_persist,
            on_session_delete=_on_session_delete,
        )

    def add_post_update_todos_hook(self, hook: PostUpdateTodosHook) -> None:
        """Register a hook that fires after every update_todos call.

        Use this to observe todo changes without coupling domain-specific
        logic into SessionManager. Each hook receives the Session and the
        updated todo list (as dicts).
        """
        self._post_update_todos_hooks.append(hook)

    def update_todos(
        self, session_id: str, todos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Update todos, then notify registered post-update hooks."""
        result = super().update_todos(session_id, todos)
        session = self.get(session_id)
        if session and self._post_update_todos_hooks:
            for hook in self._post_update_todos_hooks:
                try:
                    hook(session, result)
                except Exception as e:
                    logger.warning(
                        f"[SessionManager] post_update_todos hook failed: {e}"
                    )
        return result


__all__ = ["SessionManager", "PostUpdateTodosHook"]
