from typing import Optional, TYPE_CHECKING

from agent_core.core.state.types import MainState
from agent_core.core.state.session import StateSession
from agent_core.core.event_stream.event import EventType
from agent_core.core.session import MAIN_SESSION_ID
from app.state.types import AgentProperties
from app.state.agent_state import STATE
from app.event_stream import EventStreamManager
from app.logger import logger

if TYPE_CHECKING:
    from app.session.session_manager import SessionManager


class StateManager:
    """Manages per-session runtime state.

    Every persistent session (main / chat / living_ui) owns a StateSession
    bag with its run counters and pointers; this manager refreshes those
    bags per turn and offers session-scoped message recording.
    """

    def __init__(
        self,
        event_stream_manager: EventStreamManager,
    ):
        self._main_state: MainState = MainState()
        self.event_stream_manager = event_stream_manager
        self._session_manager: Optional["SessionManager"] = None

    def bind_session_manager(self, session_manager: "SessionManager") -> None:
        """Bind the session manager for session lookups."""
        self._session_manager = session_manager

    # ─────────────────────────────────────────────────────────────────────────
    # Main State
    # ─────────────────────────────────────────────────────────────────────────

    def get_main_state(self) -> MainState:
        """Get main state (cross-session runtime context)."""
        return self._main_state

    def log_to_main_stream(self, kind: str, message: str, **kwargs) -> None:
        """Log event to the main session's stream."""
        self.event_stream_manager.log(
            kind, message, task_id=MAIN_SESSION_ID, **kwargs
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Turn lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def start_turn(self, session_id: str) -> None:
        """Refresh per-session state at the start of a turn.

        Updates the session's StateSession bag (stream snapshot, gui flag)
        and points the process-global STATE at this turn's context. Code on
        the turn's critical path should prefer session-scoped lookups; the
        global STATE mirrors the most recent turn for legacy readers.
        """
        session = (
            self._session_manager.get(session_id) if self._session_manager else None
        )
        gui_mode = bool(session.gui_mode) if session else False
        event_stream = self.event_stream_manager.snapshot_by_id(session_id)

        StateSession.start(
            session_id=session_id,
            current_session=session,
            event_stream=event_stream,
            gui_mode=gui_mode,
        )

        STATE.refresh(
            current_session=session, event_stream=event_stream, gui_mode=gui_mode
        )
        STATE.set_agent_property("current_task_id", session_id)

    def clean_state(self):
        """
        End the turn, clearing the global mirror so the next turn starts fresh.
        """
        STATE.refresh()

    def reset(self) -> None:
        """Fully reset runtime state."""
        STATE.agent_properties: AgentProperties = AgentProperties(
            current_task_id="", action_count=0
        )
        self._main_state = MainState()
        self.clean_state()

    # ─────────────────────────────────────────────────────────────────────────
    # Message recording
    # ─────────────────────────────────────────────────────────────────────────

    def record_user_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        """Record a user message to a session's event stream.

        Args:
            content: The message content.
            session_id: The session the message belongs to (main if omitted).
            platform: Optional platform identifier (e.g., "Telegram").
        """
        target = session_id or MAIN_SESSION_ID

        if platform:
            event_label = f"user message from platform: {platform}"
        else:
            event_label = "user message"

        self.event_stream_manager.log(
            event_label,
            content,
            event_type=EventType.USER_MESSAGE,
            display_message=content,
            platform=platform,
            task_id=target,
        )

        # Inject relevant memories into the same event stream right after the
        # user message. The agent sees them as part of the chronological flow.
        from agent_core.core.impl.memory.injector import inject_memory_event

        inject_memory_event(query=content, session_id=target)

        self.bump_event_stream()

    def record_agent_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        platform: Optional[str] = None,
        continue_work: bool = False,
    ) -> None:
        """Record an agent message to a session's event stream.

        Args:
            content: The message content.
            session_id: The session the message belongs to (main if omitted).
            platform: Optional platform identifier (e.g., "Telegram").
            continue_work: True when this is a mid-run progress update and
                the agent keeps working after sending it (send_message's
                continue_work=true). Carried on the event so the UI keeps
                its "Working…" indicator up across the bubble.
        """
        target = session_id or MAIN_SESSION_ID

        if platform:
            event_label = f"agent message to platform: {platform}"
        else:
            event_label = "agent message"

        self.event_stream_manager.log(
            event_label,
            content,
            event_type=EventType.AGENT_MESSAGE,
            display_message=content,
            platform=platform,
            continue_work=continue_work,
            task_id=target,
        )

        self.bump_event_stream()

    # ─────────────────────────────────────────────────────────────────────────
    # Snapshots
    # ─────────────────────────────────────────────────────────────────────────

    def get_event_stream_snapshot(self, session_id: Optional[str] = None) -> str:
        if session_id:
            return self.event_stream_manager.snapshot_by_id(session_id)
        return self.event_stream_manager.snapshot_by_id(MAIN_SESSION_ID)

    def bump_event_stream(self) -> None:
        current = STATE.get_agent_property("current_task_id", "") or MAIN_SESSION_ID
        try:
            STATE.update_event_stream(
                self.event_stream_manager.snapshot_by_id(current)
            )
        except Exception as e:
            logger.debug(f"[STATE] bump_event_stream failed for {current}: {e}")
