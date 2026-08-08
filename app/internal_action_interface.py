"""
app.internal_action_interface

This interface contains all the agent actions calling to the agent
framework internal functions.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List, TYPE_CHECKING
from app.llm import LLMInterface, LLMCallType
from app.vlm_interface import VLMInterface
from app.image_gen_interface import ImageGenInterface
from app.video_gen_interface import VideoGenInterface
from app.session.session_manager import SessionManager
from app.state.state_manager import StateManager
from app.state.agent_state import STATE
from datetime import datetime
from app.logger import logger
from pathlib import Path
from app.config import AGENT_WORKSPACE_ROOT
from agent_core.core.event_stream.event import EventType
from app.memory import MemoryManager
import mss
import mss.tools
import os

if TYPE_CHECKING:
    from app.context_engine import ContextEngine
    from app.scheduler import SchedulerManager
    from app.proactive import ProactiveManager
    from app.subagent.manager import SubAgentManager
    from app.event_stream import EventStreamManager
    from agent_core.core.impl.action.manager import ActionManager
    from agent_core.core.impl.action.library import ActionLibrary


class InternalActionInterface:
    """
    Provides static/class methods so it can be used without instantiation.
    Allow agent to access internal functions of the CraftBot framework
    via actions.
    """

    # Class-level references
    llm_interface: Optional[LLMInterface] = None
    session_manager: Optional[SessionManager] = None
    state_manager: Optional[StateManager] = None
    vlm_interface: Optional[VLMInterface] = None
    image_gen_interface: Optional[ImageGenInterface] = None
    video_gen_interface: Optional[VideoGenInterface] = None
    context_engine: Optional["ContextEngine"] = None
    memory_manager: Optional[MemoryManager] = None
    scheduler: Optional["SchedulerManager"] = None
    proactive_manager: Optional["ProactiveManager"] = None
    ui_adapter: Optional[Any] = None  # Reference to UI adapter (browser, CLI, etc.)
    # Sub-agent runtime — set during AgentBase.__init__. Used by
    # spawn_subagent / sub_task_end actions.
    subagent_manager: Optional["SubAgentManager"] = None
    action_manager: Optional["ActionManager"] = None
    action_library: Optional["ActionLibrary"] = None
    event_stream_manager: Optional["EventStreamManager"] = None

    @classmethod
    def initialize(
        cls,
        llm_interface: LLMInterface,
        session_manager: SessionManager,
        state_manager: StateManager,
        vlm_interface: Optional[VLMInterface] = None,
        image_gen_interface: Optional[ImageGenInterface] = None,
        video_gen_interface: Optional[VideoGenInterface] = None,
        context_engine: Optional["ContextEngine"] = None,
        memory_manager: MemoryManager | None = None,
        scheduler: Optional["SchedulerManager"] = None,
        ui_adapter: Optional[Any] = None,
        subagent_manager: Optional["SubAgentManager"] = None,
        action_manager: Optional["ActionManager"] = None,
        action_library: Optional["ActionLibrary"] = None,
        event_stream_manager: Optional["EventStreamManager"] = None,
    ):
        """
        Register the shared interfaces that actions depend on.

        This must be called once at application startup so later static calls can
        access the language model, session manager, state manager, and optional
        vision model without creating new instances.
        """
        cls.llm_interface = llm_interface
        cls.session_manager = session_manager
        cls.state_manager = state_manager
        cls.vlm_interface = vlm_interface
        cls.image_gen_interface = image_gen_interface
        cls.video_gen_interface = video_gen_interface
        cls.context_engine = context_engine
        cls.memory_manager = memory_manager
        cls.scheduler = scheduler
        cls.ui_adapter = ui_adapter
        cls.subagent_manager = subagent_manager
        cls.action_manager = action_manager
        cls.action_library = action_library
        cls.event_stream_manager = event_stream_manager

    @classmethod
    def set_ui_adapter(cls, ui_adapter: Any) -> None:
        """Set the UI adapter reference (can be called after initialization)."""
        cls.ui_adapter = ui_adapter

    # ─────────────────────── LLM Access for Actions ───────────────────────

    @classmethod
    async def use_llm(
        cls, prompt: str, system_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a response from the configured LLM (async to avoid blocking UI)."""
        if cls.llm_interface is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with LLMInterface."
            )
        response = await cls.llm_interface.generate_response_async(
            system_message, prompt, prompt_name="USE_LLM"
        )
        return {"llm_response": response}

    @classmethod
    def _ensure_vlm_available(cls) -> None:
        """Raise a clear error if the configured provider has no VLM model.

        The agent's main LLM provider (e.g. deepseek) may not support vision.
        Without this guard, calls fall through to VLMInterface methods that
        either crash or return provider-specific gibberish. Raising here lets
        the action wrappers catch it and inject the error into the event stream.
        """
        if cls.vlm_interface is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with VLMInterface."
            )
        if not cls.vlm_interface.is_initialized:
            from agent_core.core.models.model_registry import MODEL_REGISTRY
            from agent_core.core.models.types import InterfaceType
            from app.errors import CatalogError, make_error

            provider = cls.vlm_interface.provider or "unknown"
            if MODEL_REGISTRY.get(provider, {}).get(InterfaceType.VLM) is None:
                raise CatalogError(
                    make_error("VLM_PROVIDER_UNAVAILABLE", provider=provider)
                )
            raise CatalogError(
                make_error("VLM_PROVIDER_NOT_INITIALIZED", provider=provider)
            )

    @classmethod
    def describe_image(cls, image_path: str, prompt: Optional[str] = None) -> str:
        """Produce a textual description for an image using the VLM."""
        cls._ensure_vlm_available()
        return cls.vlm_interface.describe_image(image_path, user_prompt=prompt)

    @classmethod
    def generate_image(cls, **kwargs) -> List[str]:
        """Generate image(s) from a prompt using the image generation interface.

        Delegates all arguments to ImageGenInterface.generate_image().

        Returns:
            List of absolute file paths to the generated images.

        Raises:
            RuntimeError: If image_gen_interface is not initialized or generation fails.
        """
        if cls.image_gen_interface is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with ImageGenInterface."
            )
        return cls.image_gen_interface.generate_image(**kwargs)

    @classmethod
    def generate_video(cls, **kwargs) -> List[str]:
        """Generate video(s) from a prompt using the video generation interface.

        Delegates all arguments to VideoGenInterface.generate_video(). Blocks
        until the long-running generation completes (or the executor's action
        timeout kills it).

        Returns:
            List of absolute file paths to the generated MP4 files.

        Raises:
            RuntimeError: If video_gen_interface is not initialized or generation fails.
        """
        if cls.video_gen_interface is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with VideoGenInterface."
            )
        return cls.video_gen_interface.generate_video(**kwargs)

    @classmethod
    def perform_ocr(cls, image_path: str, user_prompt: Optional[str] = None) -> dict:
        """
        Run OCR on an image and persist the extracted text to workspace.
        Returns a concise status dict + saved file path to avoid UI flooding.
        """
        cls._ensure_vlm_available()

        import os
        from datetime import datetime

        raw_text = cls.vlm_interface.describe_image_ocr(
            image_path, user_prompt=user_prompt
        )

        # Persist to workspace to prevent token ballooning in the agent context
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(AGENT_WORKSPACE_ROOT, f"ocr_result_{ts}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(raw_text)

        line_count = raw_text.count("\n") + 1
        char_count = len(raw_text)
        return {
            "status": "success",
            "summary": f"OCR complete: {line_count} lines, {char_count} characters extracted.",
            "text": raw_text,
            "file_path": out_path,
            "file_saved": True,
        }

    @classmethod
    def understand_video(
        cls,
        video_path: str,
        query: Optional[str] = None,
        max_frames: int = 8,
    ) -> dict:
        """
        Analyse a video by extracting keyframes and querying the VLM.
        Persists the summary to workspace to avoid UI/context flooding.
        """
        cls._ensure_vlm_available()

        import os
        from datetime import datetime

        summary = cls.vlm_interface.describe_video_frames(
            video_path, query=query, max_frames=max_frames
        )

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(AGENT_WORKSPACE_ROOT, f"video_summary_{ts}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(summary)

        return {
            "status": "success",
            "summary": summary[:500] + ("..." if len(summary) > 500 else ""),
            "file_path": out_path,
            "file_saved": True,
        }

    # ───────────────── Memory Search ─────────────────

    @classmethod
    def memory_search(cls, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search the agent's memory for relevant information.

        Args:
            query: The search query string
            top_k: Maximum number of results to return (default: 5)

        Returns:
            List of memory pointers with file_path, section_path, title, summary, and relevance_score
        """
        if cls.memory_manager is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with MemoryManager."
            )

        pointers = cls.memory_manager.retrieve(query=query, top_k=top_k)

        # Convert MemoryPointer objects to dictionaries for JSON serialization
        return [
            {
                "chunk_id": ptr.chunk_id,
                "file_path": ptr.file_path,
                "section_path": ptr.section_path,
                "title": ptr.title,
                "summary": ptr.summary,
                "relevance_score": ptr.relevance_score,
            }
            for ptr in pointers
        ]

    # ─────────────────────── GUI Actions ───────────────────────

    @classmethod
    def describe_screen(cls) -> Dict[str, str]:
        """Capture the current virtual desktop and describe it with the VLM."""
        cls._ensure_vlm_available()

        temp_dir = Path(AGENT_WORKSPACE_ROOT)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        img_path = os.path.join(temp_dir, f"viewscreen_{ts}.png")

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            mss.tools.to_png(shot.rgb, shot.size, output=img_path)

        description = cls.describe_image(img_path)
        return {"description": description, "file_path": img_path}

    @staticmethod
    def _resolve_outbound_platform(
        platform: Optional[str],
        session_id: Optional[str],
    ) -> str:
        """Decide which platform an outbound message should be routed to.

        Resolution order:
            1. Explicit `platform` argument if provided.
            2. The session's last inbound platform (recorded per session when
               a message arrives).
            3. User's Preferred Messaging Platform from USER.md (which itself
               falls back to "CraftBot Interface" when unset).
        """
        if platform:
            return platform
        if session_id:
            from agent_core.core.state.session import StateSession

            state = StateSession.get_or_none(session_id)
            if state:
                last = state.get_agent_property("source_platform", None)
                if last:
                    return last
        from app.onboarding.profile_writer import read_preferred_messaging_platform

        return read_preferred_messaging_platform()

    @staticmethod
    async def do_chat(
        message: str,
        platform: Optional[str] = None,
        session_id: Optional[str] = None,
        continue_work: bool = False,
    ) -> None:
        """Record an agent-authored chat message to the event stream.

        Args:
            message: The message content to record.
            platform: Optional platform override. If omitted, the task's
                source_platform (looked up via session_id) is used, falling
                back to "CraftBot Interface".
            session_id: Optional task/session ID for multi-task isolation.
            continue_work: True when this is a mid-run progress update and
                the agent keeps working after sending it.
        """
        if InternalActionInterface.state_manager is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with StateManager."
            )
        resolved_platform = InternalActionInterface._resolve_outbound_platform(
            platform, session_id
        )
        InternalActionInterface.state_manager.record_agent_message(
            message,
            session_id=session_id,
            platform=resolved_platform,
            continue_work=continue_work,
        )

    @staticmethod
    async def do_chat_with_attachment(
        message: str,
        file_path: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a chat message with a single attachment to the user.

        Deprecated: Use do_chat_with_attachments for new code.

        Args:
            message: The message content
            file_path: Path to the file (absolute or relative to workspace)
            session_id: Optional task/session ID for multi-task isolation.

        Returns:
            Dict with 'success', 'files_sent', and optionally 'errors'
        """
        return await InternalActionInterface.do_chat_with_attachments(
            message, [file_path], session_id=session_id
        )

    @staticmethod
    async def do_chat_with_attachments(
        message: str,
        file_paths: List[str],
        session_id: Optional[str] = None,
        continue_work: bool = False,
    ) -> Dict[str, Any]:
        """
        Send a chat message with one or more attachments to the user.

        Args:
            message: The message content
            file_paths: List of paths to the files (absolute or relative to workspace)
            session_id: Optional task/session ID for multi-task isolation.
            continue_work: True when this is a mid-run progress update and
                the agent keeps working after sending it.

        Returns:
            Dict with 'success' (bool), 'files_sent' (int), and optionally 'errors' (list of str)
        """
        import os
        from app.onboarding import onboarding_manager

        # Validate file paths before passing to UI adapter
        errors = []
        for fp in file_paths:
            if not os.path.exists(fp):
                errors.append(f"File not found: {fp}")
            elif os.path.isdir(fp):
                errors.append(f"Cannot attach directory: {fp}")

        if errors:
            return {"success": False, "files_sent": 0, "errors": errors}

        ui_adapter = InternalActionInterface.ui_adapter

        # Get the actual agent name from onboarding state
        agent_name = onboarding_manager.state.agent_name or "Agent"

        # Check if UI adapter supports attachments (browser adapter)
        if ui_adapter and hasattr(ui_adapter, "send_message_with_attachments"):
            return await ui_adapter.send_message_with_attachments(
                message,
                file_paths,
                sender=agent_name,
                session_id=session_id,
                continue_work=continue_work,
            )
        else:
            # Fallback: send message with attachment notes for non-browser adapters
            if InternalActionInterface.state_manager is None:
                raise RuntimeError(
                    "InternalActionInterface not initialized with StateManager."
                )

            attachment_notes = "\n".join([f"[Attachment: {fp}]" for fp in file_paths])
            resolved_platform = InternalActionInterface._resolve_outbound_platform(
                None, session_id
            )
            InternalActionInterface.state_manager.record_agent_message(
                f"{message}\n\n{attachment_notes}",
                session_id=session_id,
                platform=resolved_platform,
                continue_work=continue_work,
            )
            # For non-browser adapters, we can't verify files exist, so assume success
            return {"success": True, "files_sent": len(file_paths), "errors": None}

    @staticmethod
    def do_end_turn():
        """Note that the agent chose to end the run without responding."""
        logger.debug("[Agent Action] Ending turn without a response.")

    @classmethod
    def _get_session(cls, session_id: Optional[str] = None):
        """Resolve a Session: explicit id, else the current turn's session."""
        if cls.session_manager is None:
            return None
        sid = session_id or cls._get_current_session_id()
        return cls.session_manager.get(sid)

    @classmethod
    def update_todos(
        cls, todos: List[Dict[str, Any]], session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update the todo list for a session.

        Args:
            todos: List of todo dictionaries with content, status, and
                   optional active_form.
            session_id: The session whose todos to update.

        Returns:
            Status and the updated todo list.
        """
        if cls.session_manager is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with SessionManager."
            )

        sid = session_id or cls._get_current_session_id()
        updated_todos = cls.session_manager.update_todos(sid, todos)

        # Emit [todos] event to unified event stream for session caching optimization
        # Format: [ ] Pending | [>] In Progress | [x] Completed
        cls._emit_todos_event(updated_todos, session_id=sid)

        return {"status": "ok", "todos": updated_todos}

    @classmethod
    def _emit_todos_event(
        cls, todos: List[Dict[str, Any]], session_id: Optional[str] = None
    ) -> None:
        """
        Emit a [todos] event to the event stream showing current todo status.

        Format:
        HH:MM:SS [todos]:
          [ ] Item1
          [>] Item2
          [x] Item3

        This enables session caching by keeping todos in the dynamic event stream
        rather than as a separate prompt component.
        """
        if cls.state_manager is None:
            return

        todo_lines = []
        for todo in todos:
            status = todo.get("status", "pending")
            content = todo.get("content", "")

            # Determine checkbox based on status
            if status == "completed":
                checkbox = "[x]"
            elif status == "in_progress":
                checkbox = "[>]"
            else:
                checkbox = "[ ]"

            todo_lines.append(f"  {checkbox} {content}")

        if todo_lines:
            todos_str = "\n" + "\n".join(todo_lines)
        else:
            todos_str = "(no todos)"

        # Session id for proper event stream isolation across sessions
        sid = session_id or cls._get_current_session_id()

        # Log to event stream with kind="todos"
        cls.state_manager.event_stream_manager.log(
            kind="todos",
            message=todos_str,
            severity="INFO",
            event_type=EventType.TODOS,
            task_id=sid,
        )
        cls.state_manager.bump_event_stream()

    @classmethod
    def update_requirements(
        cls,
        requirements: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record the deliverable requirement list by emitting a [requirements]
        event into the event stream.

        Requirements are NOT persisted on the Session — the action is
        standalone. The agent re-issues the full list on every update; the
        event stream is the source of truth that the LLM reads back.

        Args:
            requirements: List of requirement dictionaries with keys
                          dimension, requirement, done_when, and optional status.
            session_id: The session whose stream receives the event.

        Returns:
            Status and the requirement list as passed in.
        """
        cls._emit_requirements_event(requirements, session_id=session_id)
        return {"status": "ok", "requirements": requirements}

    @classmethod
    def _emit_requirements_event(
        cls,
        requirements: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> None:
        """
        Emit a [requirements] event to the event stream.

        Each requirement is rendered on three lines so the model can read
        the dimension, the spec, and the check independently:
            [SAT]/[VIO]/[ ] <dimension>: <requirement>
                   done_when: <done_when>
        """
        if cls.state_manager is None:
            return

        lines = []
        for r in requirements:
            status = r.get("status", "pending")
            dimension = r.get("dimension", "")
            requirement = r.get("requirement", "")
            done_when = r.get("done_when", "")

            if status == "satisfied":
                marker = "[SAT]"
            elif status == "violated":
                marker = "[VIO]"
            else:
                marker = "[ ]"

            lines.append(f"  {marker} {dimension}: {requirement}")
            if done_when:
                lines.append(f"         done_when: {done_when}")

        if lines:
            req_str = "\n" + "\n".join(lines)
        else:
            req_str = "(no requirements set)"

        sid = session_id or cls._get_current_session_id()

        cls.state_manager.event_stream_manager.log(
            kind="requirements",
            message=req_str,
            severity="INFO",
            task_id=sid,
        )
        cls.state_manager.bump_event_stream()

    @classmethod
    def _get_current_session_id(cls):
        """Get the current turn's session id from the global state mirror."""
        return STATE.get_agent_property("current_task_id", "") or None

    @classmethod
    def _invalidate_action_selection_caches(
        cls, session_id: Optional[str] = None
    ) -> None:
        """
        Invalidate and re-create action selection session caches when the
        session's capabilities change.

        When action sets or skills change, the cached prompt becomes stale.
        This method clears the old session caches, resets event stream sync
        points, and re-creates fresh session caches so the next action
        selection call sees the updated capabilities.
        """
        sid = session_id or cls._get_current_session_id()
        if not sid or not cls.llm_interface:
            return

        try:
            # End old action selection caches (both CLI and GUI)
            cls.llm_interface.end_session_cache(sid, LLMCallType.ACTION_SELECTION)
            cls.llm_interface.end_session_cache(sid, LLMCallType.GUI_ACTION_SELECTION)

            # Reset event stream sync points
            if cls.context_engine:
                cls.context_engine.reset_event_stream_sync(
                    LLMCallType.ACTION_SELECTION, session_id=sid
                )
                cls.context_engine.reset_event_stream_sync(
                    LLMCallType.GUI_ACTION_SELECTION, session_id=sid
                )

            # Re-create session caches with fresh system prompt so the next
            # action selection call establishes a new session with updated actions
            if cls.context_engine:
                system_prompt, _ = cls.context_engine.make_prompt(
                    user_flags={"query": False, "expected_output": False},
                    system_flags={},
                )
                for call_type in [
                    LLMCallType.ACTION_SELECTION,
                    LLMCallType.GUI_ACTION_SELECTION,
                ]:
                    cache_id = cls.llm_interface.create_session_cache(
                        sid, call_type, system_prompt
                    )
                    if cache_id:
                        logger.debug(
                            f"[CACHE] Re-created session cache {cache_id} for {sid}:{call_type}"
                        )

            logger.info(
                f"[CACHE] Invalidated and re-created action selection caches "
                f"for session {sid} due to capability change"
            )
        except Exception as e:
            logger.warning(
                f"[CACHE] Failed to invalidate/re-create caches for {sid}: {e}"
            )

    # ───────────────── Action Set Management ─────────────────

    @classmethod
    def add_action_sets(
        cls, sets_to_add: List[str], session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load action sets into a session.

        Args:
            sets_to_add: List of action set names to add.
            session_id: The session to load into.

        Returns:
            Dictionary with success status and updated set information.
        """
        if cls.session_manager is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with SessionManager."
            )

        sid = session_id or cls._get_current_session_id()
        result = cls.session_manager.add_action_sets(sid, sets_to_add)

        # Invalidate session cache - action list has changed
        cls._invalidate_action_selection_caches(sid)

        return result

    @classmethod
    def remove_action_sets(
        cls, sets_to_remove: List[str], session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Unload action sets from a session.

        Args:
            sets_to_remove: List of action set names to remove.
            session_id: The session to unload from.

        Returns:
            Dictionary with success status and updated set information.
        """
        if cls.session_manager is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with SessionManager."
            )

        sid = session_id or cls._get_current_session_id()
        result = cls.session_manager.remove_action_sets(sid, sets_to_remove)

        # Invalidate session cache - action list has changed
        cls._invalidate_action_selection_caches(sid)

        return result

    @classmethod
    def list_action_sets(cls, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        List all available action sets and their descriptions.

        Returns:
            Dictionary with available sets and this session's loaded sets.
        """
        from app.action.action_set import action_set_manager

        available_sets = action_set_manager.list_all_sets()
        current_sets = []
        if cls.session_manager:
            sid = session_id or cls._get_current_session_id()
            current_sets = cls.session_manager.get_action_sets(sid)

        return {
            "available_sets": available_sets,
            "current_sets": current_sets,
        }

    # ───────────────── Skill Management ─────────────────

    @classmethod
    def list_skills(cls) -> Dict[str, Any]:
        """
        List all enabled skills with their names and descriptions.

        Returns:
            Dictionary with skill names mapped to descriptions.
        """
        from agent_core.core.impl.skill.manager import skill_manager

        skills = skill_manager.list_skills_for_selection()
        return {"skills": skills}

    @classmethod
    def use_skill(
        cls, skill_name: str, session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load a skill into a session (additive). Its instructions are injected
        into the session's context and its recommended action sets are loaded.
        Invalidates and re-creates LLM session caches so the updated prompt
        takes effect.

        Args:
            skill_name: Name of the skill to load.
            session_id: The session to load into.

        Returns:
            Dictionary with success status and skill details.
        """
        if cls.session_manager is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with SessionManager."
            )

        from agent_core.core.impl.skill.manager import skill_manager

        # Validate skill exists and is enabled
        skill = skill_manager.get_skill(skill_name)
        if not skill:
            return {"success": False, "error": f"Skill '{skill_name}' not found."}
        if not skill.enabled:
            return {"success": False, "error": f"Skill '{skill_name}' is not enabled."}

        sid = session_id or cls._get_current_session_id()
        session = cls.session_manager.get(sid)
        if not session:
            return {"success": False, "error": f"No session {sid}."}

        cls.session_manager.add_skill(sid, skill_name)

        # Record the skill invocation for metrics
        try:
            from app.ui_layer.metrics.collector import MetricsCollector

            collector = MetricsCollector.get_instance()
            if collector:
                collector.record_skill_invocation(skill_name)
        except Exception:
            pass

        # Add skill-recommended action sets (if any new ones)
        added_action_sets = []
        recommended_sets = skill_manager.get_skill_action_sets([skill_name])
        if recommended_sets:
            current_sets = set(session.action_sets)
            new_sets = [s for s in recommended_sets if s not in current_sets]
            if new_sets:
                cls.add_action_sets(new_sets, session_id=sid)  # invalidates caches
                added_action_sets = new_sets
            else:
                cls._invalidate_action_selection_caches(sid)
        else:
            cls._invalidate_action_selection_caches(sid)

        logger.info(f"[SKILL] Loaded skill '{skill_name}' into session {sid}")

        return {
            "success": True,
            "active_skills": list(session.selected_skills),
            "skill_description": skill.description,
            "added_action_sets": added_action_sets,
        }

    @classmethod
    def unload_skill(
        cls, skill_name: str, session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Unload a previously loaded skill from a session.

        Args:
            skill_name: Name of the skill to unload.
            session_id: The session to unload from.

        Returns:
            Dictionary with success status and remaining loaded skills.
        """
        if cls.session_manager is None:
            raise RuntimeError(
                "InternalActionInterface not initialized with SessionManager."
            )

        sid = session_id or cls._get_current_session_id()
        session = cls.session_manager.get(sid)
        if not session:
            return {"success": False, "error": f"No session {sid}."}

        if skill_name not in session.selected_skills:
            return {
                "success": False,
                "error": f"Skill '{skill_name}' is not loaded in this session.",
                "active_skills": list(session.selected_skills),
            }

        cls.session_manager.remove_skill(sid, skill_name)
        cls._invalidate_action_selection_caches(sid)

        logger.info(f"[SKILL] Unloaded skill '{skill_name}' from session {sid}")

        return {
            "success": True,
            "active_skills": list(session.selected_skills),
        }
