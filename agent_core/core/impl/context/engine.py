# -*- coding: utf-8 -*-
"""
Shared ContextEngine for agent_core.

This module provides the ContextEngine class that builds structured prompts
for LLM calls. It handles system prompts, user prompts, and dynamic context
like event streams, task state, and memory.

Hooks allow runtime-specific behavior for conversation context:
- get_conversation_history_hook: For chat history (WCA only)
- get_chat_target_info_hook: For chat targets (WCA only)
- get_user_info_hook: For current user info (WCA only)
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

from tzlocal import get_localzone

from agent_core.core.prompts import (
    AGENT_ROLE_PROMPT,
    AGENT_INFO_PROMPT,
    ENVIRONMENTAL_CONTEXT_PROMPT,
    AGENT_FILE_SYSTEM_CONTEXT_PROMPT,
    POLICY_PROMPT,
    USER_PROFILE_PROMPT,
)
from agent_core.core.state import get_state, get_session_or_none
from agent_core.core.task import Task


# Import memory mode check (deferred to avoid circular imports)
def _is_memory_enabled() -> bool:
    """Check if memory mode is enabled. Returns True if unknown."""
    try:
        from app.ui_layer.settings.memory_settings import is_memory_enabled
        return is_memory_enabled()
    except ImportError:
        return True  # Default to enabled if settings module not available

# Set up logger - use shared agent_core logger for consistency
from agent_core.utils.logger import logger


class ContextEngine:
    """Build structured prompts for the LLM from runtime state.

    The engine centralizes all context-building logic so callers can request a
    ready-to-send pair of system and user messages without worrying about where
    the information originates (conversation history, event stream, etc.).

    KV Caching Strategy:
    - System prompt: STATIC only (agent_info, policy, role_info, environment basics)
    - User prompt: Static template first, then dynamic content, then output format

    Args:
        state_manager: The StateManager instance for accessing event streams.
        agent_identity: Default identity/persona string for system prompt.
        get_conversation_history_hook: Optional hook for WCA conversation history.
        get_chat_target_info_hook: Optional hook for WCA chat target info.
        get_user_info_hook: Optional hook for WCA current user info.
    """

    def __init__(
        self,
        state_manager,
        agent_identity: str = "General AI Assistant",
        *,
        get_conversation_history_hook: Optional[Callable[[], str]] = None,
        get_chat_target_info_hook: Optional[Callable[[], str]] = None,
        get_user_info_hook: Optional[Callable[[], str]] = None,
    ):
        self.agent_identity = agent_identity
        self.system_messages = []
        self.user_messages = []
        self._role_info_func = None
        self.state_manager = state_manager
        self._memory_manager = None

        # Message source context for external platform messages
        self._current_message_context: Optional[Dict[str, Any]] = None

        # Hooks for WCA-specific context (default to empty string)
        self._get_conversation_history = get_conversation_history_hook or (lambda: "")
        self._get_chat_target_info = get_chat_target_info_hook or (lambda: "")
        self._get_user_info = get_user_info_hook or (lambda: "")

    def set_memory_manager(self, memory_manager) -> None:
        """Set the memory manager for context retrieval."""
        self._memory_manager = memory_manager

    # ─────────────── MESSAGE SOURCE CONTEXT ───────────────

    def set_message_context(self, context: Optional[Dict[str, Any]]) -> None:
        """Set the current message source context for external platform messages.

        Args:
            context: Dict containing message metadata:
                - platform: Source platform (telegram, whatsapp, discord, slack, tui, cli)
                - contact_id: Contact/sender ID
                - contact_name: Human-readable contact name
                - channel_id: Channel/group ID (if applicable)
                - channel_name: Channel/group name (if applicable)
                - is_self_message: True if user messaged themselves
                - integration_type: Full integration type (telegram_bot, whatsapp_web, etc.)
        """
        self._current_message_context = context

    def clear_message_context(self) -> None:
        """Clear the current message context after processing."""
        self._current_message_context = None

    def get_message_source_block(self) -> str:
        """Get formatted message source context for inclusion in prompts.

        Returns:
            Formatted XML block with message source info, or empty string if no context.
        """
        if not self._current_message_context:
            return ""

        platform = self._current_message_context.get("platform", "tui")
        integration_type = self._current_message_context.get("integration_type", "")
        contact_name = self._current_message_context.get("contact_name", "")
        contact_id = self._current_message_context.get("contact_id", "")
        channel_name = self._current_message_context.get("channel_name", "")
        channel_id = self._current_message_context.get("channel_id", "")
        is_self_message = self._current_message_context.get("is_self_message", True)

        lines = [
            "<message_source>",
            f"Platform: {platform}",
        ]

        if integration_type:
            lines.append(f"Integration Type: {integration_type}")

        if is_self_message:
            lines.append("Message Type: Self-message (user talking to agent directly)")
        else:
            lines.append("Message Type: Third-party message (someone else sent this)")
            if contact_name:
                lines.append(f"Sender: {contact_name}")
            if contact_id:
                lines.append(f"Sender ID: {contact_id}")

        if channel_name:
            lines.append(f"Channel: {channel_name}")
        elif channel_id:
            lines.append(f"Channel ID: {channel_id}")

        lines.append("</message_source>")
        return "\n".join(lines)

    # ─────────────── SYSTEM MESSAGE COMPONENTS (STATIC ONLY) ───────────────

    def create_system_agent_info(self) -> str:
        """Create a system message block describing the agent's operational info."""
        return AGENT_INFO_PROMPT

    def set_role_info_hook(self, hook_fn):
        """Inject a role-specific system prompt generator."""
        self._role_info_func = hook_fn

    def create_system_role_info(self) -> str:
        """Call the injected role-specific prompt function."""
        if self._role_info_func:
            role = self._role_info_func()
            try:
                from app.onboarding import onboarding_manager
                agent_name = onboarding_manager.state.agent_name or "Agent"
            except ImportError:
                agent_name = "Agent"
            return AGENT_ROLE_PROMPT.format(agent_name=agent_name, role=role)
        return ""

    def create_system_policy(self) -> str:
        """Create a system message block with constraints."""
        return POLICY_PROMPT

    def create_system_environmental_context(self) -> str:
        """Create a system message block with environmental context."""
        import platform
        try:
            from app.config import AGENT_WORKSPACE_ROOT
        except ImportError:
            AGENT_WORKSPACE_ROOT = "."

        local_timezone = get_localzone()
        return ENVIRONMENTAL_CONTEXT_PROMPT.format(
            user_location=local_timezone,
            working_directory=AGENT_WORKSPACE_ROOT,
            operating_system=platform.system(),
            os_version=platform.release(),
            os_platform=platform.platform(),
            vm_operating_system="Linux",
            vm_os_version="6.12.13",
            vm_os_platform="Linux a5e39e32118c 6.12.13 #1 SMP Thu Mar 13 11:34:50 UTC 2025 x86_64 x86_64 x86_64 GNU/Linux",
            vm_resolution="1064 x 1064"
        )

    def create_system_file_system_context(self) -> str:
        """Create a system message block with agent file system context."""
        try:
            from app.config import AGENT_FILE_SYSTEM_PATH
        except ImportError:
            AGENT_FILE_SYSTEM_PATH = "."
        return AGENT_FILE_SYSTEM_CONTEXT_PROMPT.format(
            agent_file_system_path=AGENT_FILE_SYSTEM_PATH,
        )

    def create_system_user_profile(self) -> str:
        """Create a system message block with user profile from USER.md."""
        try:
            from app.config import AGENT_FILE_SYSTEM_PATH
            user_md_path = AGENT_FILE_SYSTEM_PATH / "USER.md"

            if user_md_path.exists():
                content = user_md_path.read_text(encoding="utf-8").strip()
                if content:
                    return USER_PROFILE_PROMPT.format(user_profile_content=content)
        except Exception as e:
            logger.warning(f"[CONTEXT] Failed to read USER.md: {e}")

        return ""

    def create_system_base_instruction(self) -> str:
        """Create a system message of instruction."""
        return "Please assist the user using the context given in the conversation or event stream."

    # ─────────────── USER PROMPT DYNAMIC COMPONENTS ───────────────

    def get_event_stream(self, session_id: Optional[str] = None) -> str:
        """Get the event stream content for inclusion in user prompts.

        Args:
            session_id: Optional session ID for session-specific state lookup.
                        If provided, reads DIRECTLY from EventStreamManager's task-specific stream.
                        This is CRITICAL for concurrent task execution - reading from
                        StateSession.event_stream would return a stale snapshot, not live events.

        Returns:
            Formatted string containing:
            1. Conversation history (recent user/agent messages from before this task)
            2. Current task's event stream (real-time events for this task)
        """
        sections = []

        # Get conversation history (recent messages from BEFORE this task)
        # This provides context without injecting into the actual event stream
        conversation_history = self._format_conversation_history()
        if conversation_history:
            sections.append(conversation_history)

        # Get current task's event stream
        event_stream = None

        # CRITICAL: Read directly from EventStreamManager's task-specific stream
        # Do NOT use StateSession.event_stream - that's just a snapshot taken at session start
        if session_id:
            try:
                event_stream_manager = self.state_manager.event_stream_manager
                if event_stream_manager:
                    stream = event_stream_manager.get_stream_by_id(session_id)
                    if stream:
                        event_stream = stream.to_prompt_snapshot(include_summary=True)
            except Exception:
                pass

        # Fall back to global state only if no session_id or stream not found
        if not event_stream:
            event_stream = get_state().event_stream

        if event_stream:
            sections.append(
                "<event_stream>\n"
                "Use the event stream to understand the current situation and past agent actions:\n"
                f"{event_stream}\n"
                "</event_stream>"
            )
        else:
            sections.append("<event_stream>\n(no events yet)\n</event_stream>")

        return "\n\n".join(sections)

    def _format_conversation_history(self, limit: int = 20) -> str:
        """Format recent conversation messages for inclusion in prompts.

        This retrieves messages from EventStreamManager's conversation history
        (stored separately from event streams) and formats them as a preamble.
        These are messages from BEFORE the current task was created.

        Args:
            limit: Maximum number of messages to include. Defaults to 20.

        Returns:
            Formatted conversation history section, or empty string if no history.
        """
        try:
            event_stream_manager = self.state_manager.event_stream_manager
            if not event_stream_manager:
                return ""

            recent_messages = event_stream_manager.get_recent_conversation_messages(limit)
            if not recent_messages:
                return ""

            lines = [
                "<conversation_history>",
                "Recent conversation context (messages from before this task):",
                "",
            ]

            for event in recent_messages:
                # Format: [kind]: message
                # kind already includes platform info (e.g., "user message from platform: Telegram")
                lines.append(f"[{event.kind}]: {event.message}")

            lines.append("")
            lines.append("Note: This is historical context. The current task's events are in <event_stream> below.")
            lines.append("</conversation_history>")

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"[CONTEXT] Failed to format conversation history: {e}")
            return ""

    def get_event_stream_delta(self, call_type: str, session_id: Optional[str] = None) -> tuple[str, bool]:
        """Get only new events since the last session sync.

        Args:
            call_type: Type of LLM call for delta tracking.
            session_id: Optional session ID for session-specific stream lookup.
                        CRITICAL for concurrent task execution - without this,
                        events from other tasks may leak into this task's context.
        """
        try:
            from app.event_stream import EventStreamManager
            event_stream_manager = self.state_manager.event_stream_manager

            # Use session-specific stream if session_id provided
            if session_id:
                stream = event_stream_manager.get_stream_by_id(session_id)
            else:
                stream = event_stream_manager.get_stream()

            if not stream:
                return "", False

            delta_str, has_delta = stream.get_delta_events(call_type)
            return (delta_str, True) if has_delta else ("", False)
        except Exception:
            return "", False

    def mark_event_stream_synced(self, call_type: str, session_id: Optional[str] = None) -> None:
        """Mark that the event stream has been synced to a session cache.

        Args:
            call_type: Type of LLM call for sync tracking.
            session_id: Optional session ID for session-specific stream lookup.
                        CRITICAL for concurrent task execution.
        """
        try:
            from app.event_stream import EventStreamManager
            event_stream_manager = self.state_manager.event_stream_manager

            # Use session-specific stream if session_id provided
            if session_id:
                stream = event_stream_manager.get_stream_by_id(session_id)
            else:
                stream = event_stream_manager.get_stream()

            if stream:
                stream.mark_session_synced(call_type)
        except Exception:
            pass

    def reset_event_stream_sync(self, call_type: str, session_id: Optional[str] = None) -> None:
        """Reset the session sync point for the event stream.

        Args:
            call_type: Type of LLM call for sync tracking.
            session_id: Optional session ID for session-specific stream lookup.
                        CRITICAL for concurrent task execution.
        """
        try:
            from app.event_stream import EventStreamManager
            event_stream_manager = self.state_manager.event_stream_manager

            # Use session-specific stream if session_id provided
            if session_id:
                stream = event_stream_manager.get_stream_by_id(session_id)
            else:
                stream = event_stream_manager.get_stream()

            if stream:
                stream.reset_session_sync(call_type)
        except Exception:
            pass

    def get_task_state(self, session_id: Optional[str] = None) -> str:
        """Get the current task state for inclusion in user prompts.

        Args:
            session_id: Optional session ID for session-specific state lookup.
                        If provided, uses session-specific task.
                        Falls back to global state if session not found.
        """
        # Try session-specific state first
        session = get_session_or_none(session_id)
        if session and session.current_task:
            current_task = session.current_task
        else:
            # CRITICAL: Log warning when falling back to global state
            if session_id:
                logger.warning(f"[CONTEXT_ENGINE] get_task_state: Session not found for session_id={session_id!r}, "
                             f"falling back to global STATE. This may cause context leakage!")
            current_task = get_state().current_task

        if current_task:
            is_simple = getattr(current_task, "mode", "complex") == "simple"

            if is_simple:
                return (
                    "<current_task>\n"
                    f"Task: {current_task.name} [SIMPLE MODE]\n"
                    f"Instruction: {current_task.instruction}\n"
                    "Mode: Simple task - execute directly, no todos required\n"
                    "</current_task>"
                )

            lines = [
                "<current_task>",
                f"Task: {current_task.name}",
                f"Instruction: {current_task.instruction}",
                "Mode: Complex task - use todos in event stream to track progress",
            ]

            skill_instructions = self.get_skill_instructions(session_id=session_id)
            if skill_instructions:
                lines.append("")
                lines.append(skill_instructions)

            lines.append("</current_task>")
            return "\n".join(lines)
        return "<current_task>\n(no active task)\n</current_task>"

    def get_skill_instructions(self, session_id: Optional[str] = None) -> str:
        """Get instructions from skills selected for the current task.

        Args:
            session_id: Optional session ID for session-specific state lookup.
        """
        # Try session-specific state first
        session = get_session_or_none(session_id)
        if session and session.current_task:
            current_task = session.current_task
        else:
            # CRITICAL: Log warning when falling back to global state
            if session_id:
                logger.warning(f"[CONTEXT_ENGINE] get_skill_instructions: Session not found for session_id={session_id!r}, "
                             f"falling back to global STATE. This may cause context leakage!")
            current_task = get_state().current_task

        if not current_task:
            return ""

        selected_skills = getattr(current_task, "selected_skills", [])
        if not selected_skills:
            return ""

        try:
            from app.skill import skill_manager
            instructions = skill_manager.get_skill_instructions(selected_skills)

            if not instructions:
                return ""

            return (
                "<active_skills>\n"
                "Follow these skill instructions for this task:\n\n"
                f"{instructions}\n"
                "</active_skills>"
            )
        except ImportError:
            return ""
        except Exception as e:
            logger.warning(f"[SKILLS] Failed to get skill instructions: {e}")
            return ""

    def get_agent_state(self, session_id: Optional[str] = None) -> str:
        """Get the current agent state for inclusion in user prompts.

        Args:
            session_id: Optional session ID for session-specific state lookup.
        """
        # Try session-specific state first
        session = get_session_or_none(session_id)
        if session:
            agent_properties = session.get_agent_properties()
            gui_mode_status = "GUI mode" if session.gui_mode else "CLI mode"
        else:
            # CRITICAL: Log warning when falling back to global state
            if session_id:
                logger.warning(f"[CONTEXT_ENGINE] get_agent_state: Session not found for session_id={session_id!r}, "
                             f"falling back to global STATE. This may cause context leakage!")
            agent_properties = get_state().get_agent_properties()
            gui_mode_status = "GUI mode" if get_state().gui_mode else "CLI mode"

        if agent_properties:
            return (
                "<agent_state>\n"
                f"- Active Task ID: {agent_properties.get('current_task_id')}\n"
                f"- Current Mode: {gui_mode_status}\n"
                "</agent_state>"
            )
        return f"<agent_state>\n- Current Mode: {gui_mode_status}\n</agent_state>"

    def get_conversation_history(self) -> str:
        """Get conversation history for user prompts (WCA-specific via hook)."""
        return self._get_conversation_history()

    def get_chat_target_info(self) -> str:
        """Get chat target info for user prompts (WCA-specific via hook)."""
        return self._get_chat_target_info()

    def get_user_info(self) -> str:
        """Get current user info for user prompts (WCA-specific via hook)."""
        return self._get_user_info()

    def get_memory_context(
        self, query: Optional[str] = None, top_k: int = 5, session_id: Optional[str] = None
    ) -> str:
        """Get relevant memories for inclusion in prompts.

        Args:
            query: Optional query string for memory retrieval. If not provided,
                   uses current task instruction.
            top_k: Number of top memories to retrieve.
            session_id: Optional session ID for session-specific state lookup.
        """
        if not self._memory_manager:
            return ""

        # Check if memory is enabled in settings
        if not _is_memory_enabled():
            return ""

        if not query:
            # Try session-specific state first
            session = get_session_or_none(session_id)
            if session and session.current_task:
                current_task = session.current_task
            else:
                current_task = get_state().current_task

            if current_task:
                query = current_task.instruction
            else:
                return ""

        try:
            pointers = self._memory_manager.retrieve(query, top_k=top_k, min_relevance=0.3)

            if not pointers:
                return ""

            lines = ["<relevant_memories>"]
            lines.append("Historical context from previous interactions (verify against current event stream):")
            lines.append("")

            for ptr in pointers:
                lines.append(
                    f"- [{ptr.file_path}] {ptr.section_path}: {ptr.summary} "
                    f"(relevance: {ptr.relevance_score:.2f})"
                )

            lines.append("")
            lines.append("Note: Memories may be outdated. Trust current event stream over memories if they conflict.")
            lines.append("Use memory_search action to retrieve full content if needed.")
            lines.append("</relevant_memories>")

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"[MEMORY] Failed to retrieve memory context: {e}")
            return ""

    # ──────────────────────── USER MESSAGE COMPONENTS ────────────────────────

    def create_user_query(self, query) -> str:
        """The direct user request or question."""
        return f"User Query: {query}"

    def create_user_expected_output(self, expected_format) -> str:
        """The final structure or format expected from the LLM response."""
        if not expected_format:
            return "No specific format requested."
        return f"Expected Output Format:\n{expected_format}"

    # ──────────────────────── MAKE PROMPT ────────────────────────

    def make_prompt(
        self,
        query=None,
        expected_format=None,
        system_flags=None,
        user_flags=None,
    ):
        """Assemble system and user messages for the LLM."""
        system_default_flags = {
            "role_info": True,
            "agent_info": True,
            "user_profile": True,
            "policy": False,
            "environment": True,
            "file_system": True,
            "base_instruction": True,
        }
        user_default_flags = {
            "query": True,
            "expected_output": False,
        }

        system_flags = {**system_default_flags, **(system_flags or {})}
        user_flags = {**user_default_flags, **(user_flags or {})}

        system_sections = [
            ("agent_info", self.create_system_agent_info),
            ("user_profile", self.create_system_user_profile),
            ("policy", self.create_system_policy),
            ("role_info", self.create_system_role_info),
            ("environment", self.create_system_environmental_context),
            ("file_system", self.create_system_file_system_context),
            ("base_instruction", self.create_system_base_instruction),
        ]

        system_content_list = []
        for key, section_fn in system_sections:
            if system_flags.get(key):
                section_content = section_fn()
                if section_content:
                    system_content_list.append(section_content)

        system_message_content = "\n".join(system_content_list).strip()

        user_sections = [
            ("query", lambda: self.create_user_query(query)),
            ("expected_output", lambda: self.create_user_expected_output(expected_format)),
        ]

        user_content_list = []
        for key, section_fn in user_sections:
            if user_flags.get(key):
                section_content = section_fn()
                if section_content:
                    user_content_list.append(section_content)

        user_message_content = "\n\n".join(user_content_list).strip()

        return system_message_content, user_message_content
