# -*- coding: utf-8 -*-
"""
Shared SessionManager for agent_core.

Owns the registry of persistent sessions (main / chat / living_ui), their
loaded capabilities (action sets + skills), todos, run budgets, workspace
directories, and their LLM session caches. Runtime-specific behavior is
injected via hooks:

State hooks:
- get_agent_property / set_agent_property: session-scoped state access

Event stream hooks:
- on_stream_create: called when a session is created to set up its stream
- on_stream_remove: called when a session is deleted to tear its stream down

Persistence hooks:
- on_session_persist: called on every session state change
- on_session_delete: called when a session is deleted
"""

import re
import shutil
import uuid
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional

from agent_core.core.session import (
    Session,
    SessionType,
    TodoItem,
    MAIN_SESSION_ID,
)
from agent_core.core.state import StateSession
from agent_core.core.impl.llm import LLMCallType

from agent_core.utils.logger import logger


# =============================================================================
# Hook Type Definitions
# =============================================================================

GetAgentPropertyHook = Callable[[str, Any], Any]
SetAgentPropertyHook = Callable[[str, Any], None]

OnStreamCreateHook = Callable[[str, Path], None]  # (session_id, workspace_dir)
OnStreamRemoveHook = Callable[[str], None]  # (session_id)

OnSessionPersistHook = Callable[[Session], None]
OnSessionDeleteHook = Callable[[str], None]  # (session_id)


class SessionManager:
    """
    Registry and lifecycle owner for persistent agent sessions.

    Sessions are never "ended" by the agent — they exist until the user
    deletes them. There is no task lifecycle: a session's runs start when a
    trigger wakes it and stop when the agent finishes without enqueuing a
    continuation.
    """

    def __init__(
        self,
        event_stream_manager,
        llm_interface=None,
        context_engine=None,
        workspace_root: Optional[Path] = None,
        *,
        get_agent_property: Optional[GetAgentPropertyHook] = None,
        set_agent_property: Optional[SetAgentPropertyHook] = None,
        on_stream_create: Optional[OnStreamCreateHook] = None,
        on_stream_remove: Optional[OnStreamRemoveHook] = None,
        on_session_persist: Optional[OnSessionPersistHook] = None,
        on_session_delete: Optional[OnSessionDeleteHook] = None,
    ):
        self.event_stream_manager = event_stream_manager
        self.llm_interface = llm_interface
        self.context_engine = context_engine
        self.sessions: Dict[str, Session] = {}
        self.workspace_root = workspace_root or Path(".")

        self._get_agent_property = get_agent_property or (lambda name, default: default)
        self._set_agent_property = set_agent_property or (lambda name, value: None)

        self._on_stream_create = on_stream_create
        self._on_stream_remove = on_stream_remove
        self._on_session_persist = on_session_persist
        self._on_session_delete = on_session_delete

    # ─────────────────────── Lookup ──────────────────────────────────────────

    def get(self, session_id: Optional[str]) -> Optional[Session]:
        """Look up a session by its id."""
        if not session_id:
            return None
        return self.sessions.get(session_id)

    @property
    def main(self) -> Optional[Session]:
        """The permanent main session."""
        return self.sessions.get(MAIN_SESSION_ID)

    def list_sessions(self, include_archived: bool = False) -> List[Session]:
        """All sessions: main first, then living_ui, then chats newest-first."""
        sessions = [
            s
            for s in self.sessions.values()
            if include_archived or not s.archived
        ]

        type_rank = {SessionType.MAIN: 0, SessionType.LIVING_UI: 1, SessionType.CHAT: 2}

        # Newest-first within each type bucket (two-pass stable sort)
        sessions.sort(key=lambda s: s.last_active_at, reverse=True)
        sessions.sort(key=lambda s: type_rank.get(s.type, 3))
        return sessions

    # ─────────────────────── Creation ─────────────────────────────────────────

    def ensure_main(self) -> Session:
        """Create the main session if it does not exist yet."""
        existing = self.sessions.get(MAIN_SESSION_ID)
        if existing:
            return existing
        return self.create_session(
            session_type=SessionType.MAIN,
            title="Main",
            session_id=MAIN_SESSION_ID,
        )

    def create_session(
        self,
        session_type: str = SessionType.CHAT,
        title: str = "",
        session_id: Optional[str] = None,
        action_sets: Optional[List[str]] = None,
        selected_skills: Optional[List[str]] = None,
        living_ui_project_id: Optional[str] = None,
        gui_mode: bool = False,
    ) -> Session:
        """
        Create a new persistent session.

        Args:
            session_type: main | chat | living_ui.
            title: Sidebar title ("New chat" placeholder until auto-titled).
            session_id: Explicit id (main / living-ui); random hex otherwise.
            action_sets: Extra action sets to load on top of core.
            selected_skills: Skills to preload (slash-command entry, Living UI).
            living_ui_project_id: Backing project for living_ui sessions.
            gui_mode: Whether the session starts in GUI mode.

        Returns:
            The created Session.
        """
        if session_type not in SessionType.ALL:
            raise ValueError(f"Unknown session type: {session_type}")
        sid = session_id or uuid.uuid4().hex[:12]
        if sid in self.sessions:
            return self.sessions[sid]

        workspace_dir = self._prepare_workspace_dir(sid)

        from app.action.action_set import action_set_manager

        selected_sets = list(action_sets or [])
        visibility_mode = "GUI" if gui_mode else "CLI"
        compiled_actions = action_set_manager.compile_action_list(
            selected_sets, mode=visibility_mode
        )

        session = Session(
            id=sid,
            type=session_type,
            title=title or ("Main" if session_type == SessionType.MAIN else "New chat"),
            action_sets=selected_sets,
            compiled_actions=compiled_actions,
            selected_skills=list(selected_skills or []),
            workspace_dir=str(workspace_dir),
            living_ui_project_id=living_ui_project_id,
            gui_mode=gui_mode,
        )
        self.sessions[sid] = session

        # Per-session isolated state (counters, current todo, ...)
        StateSession.start(sid, current_session=session, gui_mode=gui_mode)

        # Set up the session's event stream via hook
        if self._on_stream_create:
            self._on_stream_create(sid, workspace_dir)

        self._persist(session)

        # Create LLM session caches so every session benefits from
        # incremental context deltas from its very first run.
        if self.llm_interface and self.context_engine:
            self._create_session_caches(sid)

        logger.debug(f"[SessionManager] Session {sid} ({session_type}) created")
        return session

    # ─────────────────────── Deletion / clearing ─────────────────────────────

    def delete_session(self, session_id: str) -> bool:
        """Delete a session permanently. The main session cannot be deleted."""
        session = self.sessions.get(session_id)
        if not session:
            return False
        if session.type == SessionType.MAIN:
            logger.warning("[SessionManager] Refusing to delete the main session")
            return False

        self.sessions.pop(session_id, None)
        StateSession.end(session_id)

        if self._on_stream_remove:
            self._on_stream_remove(session_id)

        if self._on_session_delete:
            try:
                self._on_session_delete(session_id)
            except Exception as e:
                logger.warning(
                    f"[SessionManager] Delete persistence failed for {session_id}: {e}"
                )

        # Drop the session's LLM caches
        if self.llm_interface:
            try:
                self.llm_interface.remove_session_caches(session_id)
            except Exception:
                pass

        if session.workspace_dir:
            shutil.rmtree(session.workspace_dir, ignore_errors=True)

        logger.info(f"[SessionManager] Session {session_id} deleted")
        return True

    def clear_session(self, session_id: str) -> bool:
        """Clear a session's conversation: event stream, todos, run counters.

        The session itself (title, loaded action sets/skills) is kept.
        """
        session = self.sessions.get(session_id)
        if not session:
            return False

        session.todos = []
        session.reset_run_counters()

        stream = self.event_stream_manager.get_stream_by_id(session_id)
        if stream is not None and hasattr(stream, "clear"):
            stream.clear()

        # Reset per-session LLM caches so the next call rebuilds from the
        # now-empty stream.
        if self.llm_interface and self.context_engine:
            try:
                self.llm_interface.remove_session_caches(session_id)
            except Exception:
                pass
            self._create_session_caches(session_id)

        self._persist(session)
        logger.info(f"[SessionManager] Session {session_id} cleared")
        return True

    def rename_session(self, session_id: str, title: str) -> bool:
        """Rename a session (sidebar title)."""
        session = self.sessions.get(session_id)
        if not session or not title.strip():
            return False
        session.title = title.strip()
        self._persist(session)
        return True

    # ─────────────────────── Restore ─────────────────────────────────────────

    def restore_session(self, session: Session) -> Session:
        """Register a session loaded from persistence at boot.

        Recompiles the action list (the installed action registry may have
        changed between runs) and re-registers per-session state, but does
        NOT touch the persisted event stream — the caller restores that.
        """
        from app.action.action_set import action_set_manager

        visibility_mode = "GUI" if session.gui_mode else "CLI"
        session.compiled_actions = action_set_manager.compile_action_list(
            session.action_sets, mode=visibility_mode
        )
        if not session.workspace_dir:
            session.workspace_dir = str(self._prepare_workspace_dir(session.id))
        else:
            Path(session.workspace_dir).mkdir(parents=True, exist_ok=True)

        self.sessions[session.id] = session
        StateSession.start(
            session.id, current_session=session, gui_mode=session.gui_mode
        )
        return session

    # ─────────────────────── Todo Management ─────────────────────────────────

    def update_todos(
        self, session_id: str, todos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Update the todo list for a session.

        Args:
            session_id: The session whose todos to update.
            todos: List of todo dictionaries with content, status, and
                   optional active_form.

        Returns:
            The updated todo list as dictionaries.
        """
        session = self.sessions.get(session_id)
        if not session:
            logger.warning(f"[SessionManager] No session {session_id} to update todos")
            return []

        # Strip status suffixes that LLMs sometimes append to content
        def _clean_content(s: str) -> str:
            return re.sub(
                r"\s*-\s*(completed|in_progress|in progress|pending|done)\s*$",
                "",
                s,
                flags=re.IGNORECASE,
            ).strip()

        existing_by_content: Dict[str, TodoItem] = {
            _clean_content(t.content): t for t in session.todos
        }

        new_todos: List[TodoItem] = []
        for t_dict in todos:
            raw_content = t_dict.get("content", "")
            content = _clean_content(raw_content)
            new_status = t_dict.get("status", "pending")

            existing = existing_by_content.get(content)
            if existing:
                existing.status = new_status
                existing.content = content
                existing.active_form = t_dict.get("active_form", existing.active_form)
                new_todos.append(existing)
            else:
                t_dict_clean = {**t_dict, "content": content}
                new_todos.append(TodoItem.from_dict(t_dict_clean))

        session.todos = new_todos
        self._persist(session)

        # Track the current in-progress todo's ID for parent_action_id
        in_progress_todo = next(
            (t for t in session.todos if t.status == "in_progress"),
            None,
        )
        state = StateSession.get_or_none(session_id)
        if state:
            state.set_agent_property(
                "current_todo_action_id",
                in_progress_todo.id if in_progress_todo else None,
            )

        logger.debug(
            f"[SessionManager] Updated {len(session.todos)} todos for {session_id}"
        )
        return [t.to_dict() for t in session.todos]

    def get_todos(self, session_id: str) -> List[Dict[str, Any]]:
        """Get a session's current todo list as dictionaries."""
        session = self.sessions.get(session_id)
        if not session:
            return []
        return [t.to_dict() for t in session.todos]

    # ─────────────────────── Capability Management ───────────────────────────

    def add_action_sets(
        self, session_id: str, sets_to_add: List[str]
    ) -> Dict[str, Any]:
        """Add action sets to a session and recompile its action list."""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "error": f"No session {session_id}"}

        from app.action.action_set import action_set_manager

        current_sets = set(session.action_sets)
        new_sets = set(sets_to_add) - current_sets
        session.action_sets = list(current_sets | new_sets)

        visibility_mode = "GUI" if session.gui_mode else "CLI"
        old_actions = set(session.compiled_actions)
        session.compiled_actions = action_set_manager.compile_action_list(
            session.action_sets, mode=visibility_mode
        )
        new_actions = set(session.compiled_actions) - old_actions

        self._persist(session)

        logger.debug(
            f"[SessionManager] Added action sets {sets_to_add} to {session_id}, "
            f"now {len(session.compiled_actions)} actions"
        )
        return {
            "success": True,
            "current_sets": session.action_sets,
            "added_actions": list(new_actions),
            "total_actions": len(session.compiled_actions),
        }

    def remove_action_sets(
        self, session_id: str, sets_to_remove: List[str]
    ) -> Dict[str, Any]:
        """Remove action sets from a session and recompile."""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "error": f"No session {session_id}"}

        from app.action.action_set import action_set_manager

        sets_to_remove_filtered = [s for s in sets_to_remove if s != "core"]
        current_sets = set(session.action_sets)
        session.action_sets = list(current_sets - set(sets_to_remove_filtered))

        visibility_mode = "GUI" if session.gui_mode else "CLI"
        old_actions = set(session.compiled_actions)
        session.compiled_actions = action_set_manager.compile_action_list(
            session.action_sets, mode=visibility_mode
        )
        removed_actions = old_actions - set(session.compiled_actions)

        self._persist(session)

        return {
            "success": True,
            "current_sets": session.action_sets,
            "removed_actions": list(removed_actions),
            "total_actions": len(session.compiled_actions),
        }

    def add_skill(self, session_id: str, skill_name: str) -> bool:
        """Load a skill into a session (additive)."""
        session = self.sessions.get(session_id)
        if not session:
            return False
        if skill_name not in session.selected_skills:
            session.selected_skills.append(skill_name)
            self._persist(session)
        return True

    def remove_skill(self, session_id: str, skill_name: str) -> bool:
        """Unload a skill from a session."""
        session = self.sessions.get(session_id)
        if not session:
            return False
        if skill_name in session.selected_skills:
            session.selected_skills.remove(skill_name)
            self._persist(session)
        return True

    def get_action_sets(self, session_id: str) -> List[str]:
        """Get a session's loaded action sets."""
        session = self.sessions.get(session_id)
        return session.action_sets.copy() if session else []

    def get_compiled_actions(self, session_id: str) -> List[str]:
        """Get a session's compiled action list."""
        session = self.sessions.get(session_id)
        return session.compiled_actions.copy() if session else []

    # ─────────────────────── Run bookkeeping ─────────────────────────────────

    def start_run(self, session_id: str) -> None:
        """Reset run budgets when a fresh run wakes the session."""
        session = self.sessions.get(session_id)
        if not session:
            return
        session.reset_run_counters()
        session.touch()
        state = StateSession.get_or_none(session_id)
        if state:
            state.set_agent_property("action_count", 0)
            state.set_agent_property("token_count", 0)
        self._persist(session)

    def touch_session(self, session_id: str) -> None:
        """Mark activity on a session and persist it."""
        session = self.sessions.get(session_id)
        if not session:
            return
        session.touch()
        self._persist(session)

    def persist(self, session_id: str) -> None:
        """Persist a session's current state."""
        session = self.sessions.get(session_id)
        if session:
            self._persist(session)

    # ─────────────────────── LLM session caches ──────────────────────────────

    def rebuild_session_caches(self, session_id: str) -> None:
        """Re-register LLM session caches (after provider switch)."""
        if not self.llm_interface or not self.context_engine:
            return
        if session_id not in self.sessions:
            return
        self._create_session_caches(session_id)

    def _create_session_caches(self, session_id: str) -> None:
        """Create LLM session caches for a session."""
        try:
            system_prompt, _ = self.context_engine.make_prompt(
                user_flags={"query": False, "expected_output": False},
                system_flags={},
            )
            for call_type in [
                LLMCallType.REASONING,
                LLMCallType.ACTION_SELECTION,
                LLMCallType.GUI_REASONING,
                LLMCallType.GUI_ACTION_SELECTION,
            ]:
                cache_id = self.llm_interface.create_session_cache(
                    session_id, call_type, system_prompt
                )
                if cache_id:
                    logger.debug(
                        f"[SessionManager] Created session cache {cache_id} "
                        f"for {session_id}:{call_type}"
                    )
        except Exception as e:
            logger.warning(
                f"[SessionManager] Failed to create session caches for "
                f"{session_id}: {e}"
            )

    # ─────────────────────── Internal Helpers ────────────────────────────────

    def _persist(self, session: Session) -> None:
        """Persist session state via hook."""
        if self._on_session_persist:
            try:
                self._on_session_persist(session)
            except Exception as e:
                logger.warning(
                    f"[SessionManager] Failed to persist session {session.id}: {e}"
                )

    def _prepare_workspace_dir(self, session_id: str) -> Path:
        """Create the persistent workspace directory for a session."""
        ws_root = self.workspace_root / "sessions"
        ws_root.mkdir(parents=True, exist_ok=True)
        session_dir = ws_root / self._sanitize_id(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    @staticmethod
    def _sanitize_id(s: str) -> str:
        """Sanitize a string for use as a directory name."""
        s = s.strip()
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
        s = re.sub(r"_+", "_", s)
        return s.strip("._-") or "session"
