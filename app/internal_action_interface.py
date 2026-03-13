"""
app.internal_action_interface

This interface contains all the agent actions calling to the agent
framework internal functions.
"""

from typing import Dict, Any, Optional, List, TYPE_CHECKING
from app.llm import LLMInterface, LLMCallType
from app.vlm_interface import VLMInterface
from app.task.task_manager import TaskManager
from app.task import Task
from app.state.state_manager import StateManager
from app.state.agent_state import STATE
from datetime import datetime
from app.logger import logger
from pathlib import Path
from app.config import AGENT_WORKSPACE_ROOT
from app.gui.gui_module import GUI_MODE_ACTIONS
from app.memory import MemoryManager
import mss, mss.tools, os

if TYPE_CHECKING:
    from app.context_engine import ContextEngine
    from app.gui.gui_module import GUIModule
    from app.scheduler import SchedulerManager
    from app.proactive import ProactiveManager


class InternalActionInterface:
    """
    Provides static/class methods so it can be used without instantiation.
    Allow agent to access internal functions of the CraftBot framework
    via actions.
    """

    # Class-level references
    llm_interface: Optional[LLMInterface] = None
    task_manager: Optional[TaskManager] = None
    state_manager: Optional[StateManager] = None
    vlm_interface: Optional[VLMInterface] = None
    context_engine: Optional["ContextEngine"] = None
    gui_module: Optional["GUIModule"] = None
    memory_manager: Optional[MemoryManager] = None
    scheduler: Optional["SchedulerManager"] = None
    proactive_manager: Optional["ProactiveManager"] = None
    ui_adapter: Optional[Any] = None  # Reference to UI adapter (browser, TUI, etc.)

    @classmethod
    def initialize(
        cls,
        llm_interface: LLMInterface,
        task_manager: TaskManager,
        state_manager: StateManager,
        vlm_interface: Optional[VLMInterface] = None,
        context_engine: Optional["ContextEngine"] = None,
        gui_module: Optional["GUIModule"] = None,
        memory_manager: MemoryManager | None = None,
        scheduler: Optional["SchedulerManager"] = None,
        ui_adapter: Optional[Any] = None
    ):
        """
        Register the shared interfaces that actions depend on.

        This must be called once at application startup so later static calls can
        access the language model, task manager, state manager, and optional
        vision model without creating new instances.
        """
        cls.llm_interface = llm_interface
        cls.task_manager = task_manager
        cls.state_manager = state_manager
        cls.vlm_interface = vlm_interface
        cls.context_engine = context_engine
        cls.gui_module = gui_module
        cls.memory_manager = memory_manager
        cls.scheduler = scheduler
        cls.ui_adapter = ui_adapter

    @classmethod
    def set_ui_adapter(cls, ui_adapter: Any) -> None:
        """Set the UI adapter reference (can be called after initialization)."""
        cls.ui_adapter = ui_adapter 

    # ─────────────────────── LLM Access for Actions ───────────────────────

    @classmethod
    async def use_llm(cls, prompt: str, system_message: Optional[str] = None) -> Dict[str, Any]:
        """Generate a response from the configured LLM (async to avoid blocking TUI)."""
        if cls.llm_interface is None:
            raise RuntimeError("InternalActionInterface not initialized with LLMInterface.")
        response = await cls.llm_interface.generate_response_async(prompt, system_message)
        return {"llm_response": response}

    @classmethod
    def describe_image(cls, image_path: str, prompt: Optional[str] = None) -> str:
        """Produce a textual description for an image using the VLM."""
        if cls.vlm_interface is None:
            raise RuntimeError("InternalActionInterface not initialized with VLMInterface.")
        return cls.vlm_interface.describe_image(image_path, user_prompt=prompt)

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
            raise RuntimeError("InternalActionInterface not initialized with MemoryManager.")

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
        if cls.vlm_interface is None:
            raise RuntimeError("InternalActionInterface not initialised with VLMInterface.")

        temp_dir = Path(AGENT_WORKSPACE_ROOT)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        img_path = os.path.join(temp_dir, f"viewscreen_{ts}.png")

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            mss.tools.to_png(shot.rgb, shot.size, output=img_path)

        description = cls.describe_image(img_path)
        return {"description": description, "file_path": img_path}

    @staticmethod
    async def do_chat(message: str, platform: str = "CraftBot TUI") -> None:
        """Record an agent-authored chat message to the event stream.

        Args:
            message: The message content to record.
            platform: The platform the message is sent to (default: "CraftBot TUI").
        """
        if InternalActionInterface.state_manager is None:
            raise RuntimeError("InternalActionInterface not initialized with StateManager.")
        InternalActionInterface.state_manager.record_agent_message(message, platform=platform)

    @staticmethod
    async def do_chat_with_attachment(message: str, file_path: str) -> Dict[str, Any]:
        """
        Send a chat message with a single attachment to the user.

        Deprecated: Use do_chat_with_attachments for new code.

        Args:
            message: The message content
            file_path: Path to the file (absolute or relative to workspace)

        Returns:
            Dict with 'success', 'files_sent', and optionally 'errors'
        """
        return await InternalActionInterface.do_chat_with_attachments(message, [file_path])

    @staticmethod
    async def do_chat_with_attachments(message: str, file_paths: List[str]) -> Dict[str, Any]:
        """
        Send a chat message with one or more attachments to the user.

        Args:
            message: The message content
            file_paths: List of paths to the files (absolute or relative to workspace)

        Returns:
            Dict with 'success' (bool), 'files_sent' (int), and optionally 'errors' (list of str)
        """
        from app.onboarding import onboarding_manager

        ui_adapter = InternalActionInterface.ui_adapter

        # Get the actual agent name from onboarding state
        agent_name = onboarding_manager.state.agent_name or "Agent"

        # Check if UI adapter supports attachments (browser adapter)
        if ui_adapter and hasattr(ui_adapter, 'send_message_with_attachments'):
            return await ui_adapter.send_message_with_attachments(message, file_paths, sender=agent_name)
        else:
            # Fallback: send message with attachment notes for non-browser adapters
            if InternalActionInterface.state_manager is None:
                raise RuntimeError("InternalActionInterface not initialized with StateManager.")

            attachment_notes = "\n".join([f"[Attachment: {fp}]" for fp in file_paths])
            InternalActionInterface.state_manager.record_agent_message(
                f"{message}\n\n{attachment_notes}"
            )
            # For non-browser adapters, we can't verify files exist, so assume success
            return {"success": True, "files_sent": len(file_paths), "errors": None}

    @staticmethod
    def do_ignore():
        """Note that the agent chose to ignore the latest user input."""
        logger.debug("[Agent Action] Ignoring user message.")

    # ───────────────── CLI and GUI mode ─────────────────

    @classmethod
    def switch_to_CLI_mode(cls):
        """Switch to CLI mode and restore saved CLI actions."""
        STATE.update_gui_mode(False)

        # Restore saved CLI actions if available
        if cls.task_manager and cls.task_manager.active:
            task = cls.task_manager.active

            if task._saved_cli_actions:
                task.compiled_actions = task._saved_cli_actions.copy()
                task._saved_cli_actions = []  # Clear backup after restoration
                logger.info(f"[CLI MODE] Restored {len(task.compiled_actions)} CLI actions")
            else:
                logger.debug("[CLI MODE] No saved CLI actions to restore")

    @classmethod
    def switch_to_GUI_mode(cls):
        """Switch to GUI mode with hardcoded action list."""
        # Check if GUI mode is globally enabled
        gui_globally_enabled = os.getenv("GUI_MODE_ENABLED", "True") == "True"
        if not gui_globally_enabled:
            logger.warning("[GUI MODE] Cannot switch - GUI mode is globally disabled")
            raise RuntimeError("GUI mode is disabled. Restart with --enable-gui to enable.")

        STATE.update_gui_mode(True)

        # Replace compiled_actions with hardcoded GUI mode actions
        if cls.task_manager and cls.task_manager.active:
            task = cls.task_manager.active

            # Save current CLI actions before switching (only if not already saved)
            if not task._saved_cli_actions:
                task._saved_cli_actions = task.compiled_actions.copy()
                logger.info(f"[GUI MODE] Saved {len(task._saved_cli_actions)} CLI actions for restoration")

            task.compiled_actions = GUI_MODE_ACTIONS.copy()
            logger.info(f"[GUI MODE] Set compiled_actions to {len(GUI_MODE_ACTIONS)} hardcoded GUI actions")

    # ───────────────── Task Management ─────────────────

    @classmethod
    async def do_create_task(
        cls,
        task_name: str,
        task_description: str,
        task_mode: str = "complex",
        session_id: Optional[str] = None,
        original_query: Optional[str] = None,
        original_platform: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new task with automatic skill and action set selection.

        Skills are selected first, then action sets. The action sets from
        selected skills are merged with LLM-selected action sets.

        Args:
            task_name: Short name for the task.
            task_description: Detailed description of the work to perform.
            task_mode: Task execution mode - "simple" for quick tasks, "complex" for multi-step work.
            session_id: Optional session ID to use as task_id. If provided,
                       ensures session_id == task_id for event stream isolation.
            original_query: Optional original user message to log to the task's
                           event stream before the task_start event.
            original_platform: Optional platform where the original message came from
                              (e.g., "CraftBot TUI", "Telegram", "Whatsapp").

        Returns:
            Dictionary with task_id, action_sets, action_count, and selected_skills.
        """
        if cls.task_manager is None or cls.state_manager is None:
            raise RuntimeError("InternalActionInterface not initialized with Task/State managers.")

        # NOTE: Do NOT call clear_all() here - it destroys event streams from concurrent tasks.
        # Each task's stream is created when the task starts and cleaned up when the task ends.
        # Stream lifecycle is managed by TaskManager via on_stream_create/on_stream_remove hooks.

        # Select skills and action sets in a single LLM call (optimized)
        # Skills are selected first, then action sets with knowledge of skill recommendations
        selected_skills, all_action_sets = await cls._select_skills_and_action_sets_via_llm(
            task_name, task_description, source_platform=original_platform
        )
        logger.info(f"[TASK] Auto-selected skills for '{task_name}': {selected_skills}")
        logger.info(f"[TASK] Final action sets: {all_action_sets}")

        # Create task with selected skills and action sets
        # Note: Session caches are now created automatically by TaskManager.create_task()
        # for complex tasks, so we don't need to create them here
        # Pass session_id so task_id == session_id for event stream isolation
        # Pass original_query to log user message to the task's event stream
        task_id = cls.task_manager.create_task(
            task_name, task_description,
            mode=task_mode,
            action_sets=all_action_sets,
            selected_skills=selected_skills,
            session_id=session_id,
            original_query=original_query,
            original_platform=original_platform,
        )
        # Use get_task_by_id instead of get_task() to handle parallel task creation
        # get_task() returns the global active task which can be overwritten by concurrent tasks
        task: Optional[Task] = cls.task_manager.get_task_by_id(task_id)
        if task:
            cls.state_manager.add_to_active_task(task)

        return {
            "task_id": task_id,
            "action_sets": task.action_sets if task else [],
            "action_count": len(task.compiled_actions) if task else 0,
            "selected_skills": task.selected_skills if task else [],
        }

    @classmethod
    async def _select_action_sets_via_llm(cls, task_name: str, task_description: str) -> List[str]:
        """
        Make LLM call to automatically select action sets based on task description.

        This dynamically discovers available action sets from the registry,
        supporting custom actions and MCP tools.

        Args:
            task_name: Short name for the task.
            task_description: Detailed description of the task.

        Returns:
            List of action set names selected by the LLM.
        """
        import json
        from app.action.action_set import action_set_manager
        from app.prompt import ACTION_SET_SELECTION_PROMPT

        # If no LLM interface, fall back to empty list (core-only)
        if cls.llm_interface is None:
            logger.warning("[TASK] No LLM interface available, using core-only action sets")
            return []

        try:
            # Step 1: Get available action sets dynamically from registry
            available_sets = action_set_manager.list_all_sets()

            # DEBUG: Log all discovered action sets and their actions
            logger.info("[ACTION_SETS] ========== Available Action Sets ==========")
            for set_name, set_desc in available_sets.items():
                actions_in_set = action_set_manager.get_actions_in_set(set_name)
                logger.info(f"[ACTION_SETS] {set_name}: {set_desc}")
                logger.info(f"[ACTION_SETS]   Actions ({len(actions_in_set)}): {actions_in_set}")
            logger.info("[ACTION_SETS] ============================================")

            # Format sets for prompt (exclude 'core' since it's always included)
            sets_text = "\n".join(
                f"- {name}: {desc}"
                for name, desc in available_sets.items()
                if name != "core"
            )

            if not sets_text:
                # No additional sets available beyond core
                return []

            # Step 2: Build the prompt
            prompt = ACTION_SET_SELECTION_PROMPT.format(
                task_name=task_name,
                task_description=task_description,
                available_sets=sets_text
            )

            # Step 3: Call LLM asynchronously to avoid blocking TUI
            response = await cls.llm_interface.generate_response_async(
                user_prompt=prompt,
                system_prompt="You are a helpful assistant that selects action sets for tasks. Return only valid JSON.",
            )

            # Step 4: Parse the JSON response
            # Clean up the response (remove markdown code blocks if present)
            response = response.strip()
            if response.startswith("```"):
                # Remove markdown code block markers
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            selected_sets = json.loads(response)

            # Validate that it's a list of strings
            if not isinstance(selected_sets, list):
                logger.warning(f"[TASK] LLM returned non-list for action sets: {selected_sets}")
                return []

            # Filter to only valid set names
            valid_set_names = set(available_sets.keys())
            valid_selected = [s for s in selected_sets if isinstance(s, str) and s in valid_set_names and s != "core"]

            # DEBUG: Log selection result
            logger.info(f"[ACTION_SETS] LLM raw response: {selected_sets}")
            logger.info(f"[ACTION_SETS] Valid selected sets: {valid_selected}")

            # Log what actions will be available
            total_actions = []
            for set_name in ["core"] + valid_selected:
                actions_in_set = action_set_manager.get_actions_in_set(set_name)
                total_actions.extend(actions_in_set)
            logger.info(f"[ACTION_SETS] Total actions for task: {len(set(total_actions))} from sets: {['core'] + valid_selected}")

            return valid_selected

        except json.JSONDecodeError as e:
            logger.warning(f"[TASK] Failed to parse LLM response for action sets: {e}")
            return []
        except Exception as e:
            logger.warning(f"[TASK] Failed to select action sets via LLM: {e}")
            return []

    @classmethod
    async def _select_skills_via_llm(cls, task_name: str, task_description: str) -> List[str]:
        """
        Make LLM call to select relevant skills based on task description.

        Args:
            task_name: Short name for the task.
            task_description: Detailed description of the task.

        Returns:
            List of skill names, or empty list if no skills match.
        """
        import json

        # If no LLM interface, return empty list
        if cls.llm_interface is None:
            logger.warning("[SKILLS] No LLM interface available, skipping skill selection")
            return []

        try:
            from app.skill import skill_manager
            from app.prompt import SKILL_SELECTION_PROMPT

            # Get available skills
            available_skills = skill_manager.list_skills_for_selection()

            if not available_skills:
                logger.debug("[SKILLS] No skills available for selection")
                return []

            # Format skills for prompt
            skills_text = "\n".join(
                f"- {name}: {desc}"
                for name, desc in available_skills.items()
            )

            # Build prompt
            prompt = SKILL_SELECTION_PROMPT.format(
                task_name=task_name,
                task_description=task_description,
                available_skills=skills_text
            )

            # Call LLM asynchronously to avoid blocking TUI
            response = await cls.llm_interface.generate_response_async(
                user_prompt=prompt,
                system_prompt="You are a helpful assistant that selects skills for tasks. Return only valid JSON.",
            )

            # Parse response (clean up markdown if present)
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            selected_skills = json.loads(response)

            # Validate
            if not isinstance(selected_skills, list):
                logger.warning(f"[SKILLS] LLM returned non-list for skills: {selected_skills}")
                return []

            # Filter to only valid skill names
            valid_skill_names = set(available_skills.keys())
            valid_selected = [s for s in selected_skills if isinstance(s, str) and s in valid_skill_names]

            logger.info(f"[SKILLS] LLM raw response: {selected_skills}")
            logger.info(f"[SKILLS] Valid selected skills: {valid_selected}")

            return valid_selected

        except ImportError as e:
            logger.debug(f"[SKILLS] Skill module not available: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"[SKILLS] Failed to parse LLM response for skills: {e}")
            return []
        except Exception as e:
            logger.warning(f"[SKILLS] Failed to select skills via LLM: {e}")
            return []

    @classmethod
    def _get_skill_action_sets(cls, skill_names: List[str]) -> List[str]:
        """
        Get action sets required by selected skills.

        Args:
            skill_names: List of skill names.

        Returns:
            List of action set names from selected skills.
        """
        if not skill_names:
            return []

        try:
            from app.skill import skill_manager
            return skill_manager.get_skill_action_sets(skill_names)
        except ImportError:
            return []
        except Exception as e:
            logger.warning(f"[SKILLS] Failed to get skill action sets: {e}")
            return []

    @classmethod
    async def _select_skills_and_action_sets_via_llm(
        cls, task_name: str, task_description: str, source_platform: Optional[str] = None
    ) -> tuple[List[str], List[str]]:
        """
        Select skills and action sets in a single LLM call.

        This combines skill and action set selection into one call for efficiency.
        Skills are selected first, then action sets are selected with knowledge
        of which skills were chosen and their recommended action sets.

        Args:
            task_name: Short name for the task.
            task_description: Detailed description of the task.
            source_platform: Platform where the message originated (e.g., "Telegram", "Whatsapp").
                            Used to guide action set selection for reply capability.

        Returns:
            Tuple of (selected_skills, selected_action_sets).
        """
        import json
        from app.action.action_set import action_set_manager
        from app.prompt import SKILLS_AND_ACTION_SETS_SELECTION_PROMPT

        # If no LLM interface, return empty lists
        if cls.llm_interface is None:
            logger.warning("[TASK] No LLM interface available, using defaults")
            return [], []

        try:
            # Get available skills
            available_skills = {}
            skill_action_sets_map = {}
            try:
                from app.skill import skill_manager
                for skill in skill_manager.get_enabled_skills():
                    # Include action set recommendations in skill description
                    desc = skill.description
                    if skill.metadata.action_sets:
                        desc += f" (recommends: {skill.metadata.action_sets})"
                        skill_action_sets_map[skill.name] = skill.metadata.action_sets
                    available_skills[skill.name] = desc
            except ImportError:
                logger.debug("[TASK] Skill module not available")

            # Get available action sets
            available_sets = action_set_manager.list_all_sets()

            # Format skills for prompt (or indicate none available)
            if available_skills:
                skills_text = "\n".join(
                    f"- {name}: {desc}"
                    for name, desc in available_skills.items()
                )
            else:
                skills_text = "(no skills available)"

            # Format action sets for prompt (exclude 'core')
            sets_text = "\n".join(
                f"- {name}: {desc}"
                for name, desc in available_sets.items()
                if name != "core"
            )
            if not sets_text:
                sets_text = "(no additional action sets available)"

            # Build the combined prompt
            prompt = SKILLS_AND_ACTION_SETS_SELECTION_PROMPT.format(
                task_name=task_name,
                task_description=task_description,
                source_platform=source_platform or "CraftBot TUI",
                available_skills=skills_text,
                available_sets=sets_text
            )

            # Call LLM asynchronously to avoid blocking TUI
            response = await cls.llm_interface.generate_response_async(
                user_prompt=prompt,
                system_prompt="You are a helpful assistant that selects skills and action sets for tasks. Return only valid JSON.",
            )

            # Parse response (clean up markdown if present)
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            result = json.loads(response)

            # Extract and validate skills (LIMIT TO 1 SKILL)
            selected_skills = result.get("skills", [])
            if not isinstance(selected_skills, list):
                selected_skills = []
            valid_skill_names = set(available_skills.keys())
            valid_skills = [s for s in selected_skills if isinstance(s, str) and s in valid_skill_names]

            # Enforce limit: only keep the first skill to prevent context overload
            if len(valid_skills) > 1:
                logger.info(f"[TASK] Multiple skills selected, limiting to first one: {valid_skills[0]}")
                valid_skills = valid_skills[:1]

            # Extract and validate action sets
            selected_sets = result.get("action_sets", [])
            if not isinstance(selected_sets, list):
                selected_sets = []
            valid_set_names = set(available_sets.keys())
            valid_sets = [s for s in selected_sets if isinstance(s, str) and s in valid_set_names and s != "core"]

            # Add action sets recommended by selected skills (ensure they're included)
            for skill_name in valid_skills:
                if skill_name in skill_action_sets_map:
                    for rec_set in skill_action_sets_map[skill_name]:
                        if rec_set in valid_set_names and rec_set not in valid_sets:
                            valid_sets.append(rec_set)

            logger.info(f"[TASK] LLM response: skills={selected_skills}, action_sets={selected_sets}")
            logger.info(f"[TASK] Valid selection: skills={valid_skills}, action_sets={valid_sets}")

            return valid_skills, valid_sets

        except json.JSONDecodeError as e:
            logger.warning(f"[TASK] Failed to parse LLM response: {e}")
            return [], []
        except Exception as e:
            logger.warning(f"[TASK] Failed to select skills/action sets via LLM: {e}")
            return [], []

    @classmethod
    def update_todos(cls, todos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Update the todo list for the current task.

        Args:
            todos: List of todo dictionaries with content, status, and
                   optional active_form.

        Returns:
            Status and the updated todo list.
        """
        if cls.task_manager is None:
            raise RuntimeError("InternalActionInterface not initialized with TaskManager.")

        updated_todos = cls.task_manager.update_todos(todos)

        # Emit [todos] event to unified event stream for session caching optimization
        # Format: [ ] Pending | [>] In Progress | [x] Completed
        # Note: CLI and GUI modes now share the same event stream
        cls._emit_todos_event(updated_todos)

        return {"status": "ok", "todos": updated_todos}

    @classmethod
    def _emit_todos_event(cls, todos: List[Dict[str, Any]]) -> None:
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

        # Get current task_id for proper event stream isolation in multi-task scenarios
        task_id = cls._get_current_task_id()

        # Log to event stream with kind="todos"
        cls.state_manager.event_stream_manager.log(
            kind="todos",
            message=todos_str,
            severity="INFO",
            task_id=task_id,
        )
        cls.state_manager.bump_event_stream()

    @classmethod
    async def mark_task_completed(
        cls,
        message: Optional[str] = None,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mark a specific task as completed.

        Args:
            message: Completion message/reason.
            summary: Summary of what was accomplished.
            errors: List of errors encountered.
            task_id: Specific task ID to complete. If None, uses current task (legacy behavior).
        """
        try:
            # Use provided task_id or fall back to current task (legacy behavior)
            effective_task_id = task_id or cls._get_current_task_id()
            ok = await cls.task_manager.mark_task_completed(
                message=message,
                summary=summary,
                errors=errors or [],
                task_id=effective_task_id,
            )
            # End session cache if task was successfully completed
            if ok and effective_task_id:
                cls._end_task_session_cache(effective_task_id)
            return {"status": "ok" if ok else "error"}
        except Exception as e:
            logger.error(f"[InternalActions] mark_task_completed failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    @classmethod
    async def mark_task_cancel(
        cls,
        reason: Optional[str] = None,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cancel a specific task.

        Args:
            reason: Reason for cancellation.
            summary: Summary of what was done before cancellation.
            errors: List of errors encountered.
            task_id: Specific task ID to cancel. If None, uses current task (legacy behavior).
        """
        try:
            # Use provided task_id or fall back to current task (legacy behavior)
            effective_task_id = task_id or cls._get_current_task_id()
            ok = await cls.task_manager.mark_task_cancel(
                reason=reason,
                summary=summary,
                errors=errors or [],
                task_id=effective_task_id,
            )
            # End session cache if task was successfully cancelled
            if ok and effective_task_id:
                cls._end_task_session_cache(effective_task_id)
            return {"status": "ok" if ok else "error"}
        except Exception as e:
            logger.error(f"[InternalActions] mark_task_cancel failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    @classmethod
    async def mark_task_error(cls, message: Optional[str] = None) -> Dict[str, Any]:
        """Mark the current session task as failed."""
        try:
            # Get task_id before marking as error (task will be cleared)
            task_id = cls._get_current_task_id()
            ok = await cls.task_manager.mark_task_error(message=message)
            # End session cache if task was successfully marked as error
            if ok and task_id:
                cls._end_task_session_cache(task_id)
            return {"status": "ok" if ok else "error"}
        except Exception as e:
            logger.error(f"[InternalActions] mark_task_error failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    @classmethod
    def _get_current_task_id(cls) -> Optional[str]:
        """Get the current task ID from the task manager."""
        if cls.task_manager:
            task = cls.task_manager.get_task()
            if task:
                return task.id
        return None

    @classmethod
    def _end_task_session_cache(cls, task_id: str) -> None:
        """End ALL session caches for a task (all call types)."""
        if cls.llm_interface:
            try:
                cls.llm_interface.end_all_session_caches(task_id)
                logger.debug(f"[TASK] Ended all session caches for task {task_id}")
            except Exception as e:
                logger.warning(f"[TASK] Failed to end session caches for task {task_id}: {e}")

    # ───────────────── Action Set Management ─────────────────

    @classmethod
    def add_action_sets(cls, sets_to_add: List[str]) -> Dict[str, Any]:
        """
        Add action sets to the current task.

        Args:
            sets_to_add: List of action set names to add.

        Returns:
            Dictionary with success status and updated set information.
        """
        if cls.task_manager is None:
            raise RuntimeError("InternalActionInterface not initialized with TaskManager.")

        result = cls.task_manager.add_action_sets(sets_to_add)

        # Invalidate session cache - action list has changed
        cls._invalidate_action_selection_caches()

        return result

    @classmethod
    def remove_action_sets(cls, sets_to_remove: List[str]) -> Dict[str, Any]:
        """
        Remove action sets from the current task.

        Args:
            sets_to_remove: List of action set names to remove.

        Returns:
            Dictionary with success status and updated set information.
        """
        if cls.task_manager is None:
            raise RuntimeError("InternalActionInterface not initialized with TaskManager.")

        result = cls.task_manager.remove_action_sets(sets_to_remove)

        # Invalidate session cache - action list has changed
        cls._invalidate_action_selection_caches()

        return result

    @classmethod
    def _invalidate_action_selection_caches(cls) -> None:
        """
        Invalidate action selection session caches when action sets change.

        When action sets are added or removed, the cached prompt becomes stale
        because the <actions> section has changed. This method clears the
        session caches for both CLI and GUI action selection.
        """
        task_id = cls._get_current_task_id()
        if not task_id or not cls.llm_interface:
            return

        try:
            # End action selection caches (both CLI and GUI)
            cls.llm_interface.end_session_cache(task_id, LLMCallType.ACTION_SELECTION)
            cls.llm_interface.end_session_cache(task_id, LLMCallType.GUI_ACTION_SELECTION)

            # Also reset event stream sync points
            if cls.context_engine:
                cls.context_engine.reset_event_stream_sync(LLMCallType.ACTION_SELECTION)
                cls.context_engine.reset_event_stream_sync(LLMCallType.GUI_ACTION_SELECTION)

            logger.info(f"[CACHE] Invalidated action selection caches for task {task_id} due to action set change")
        except Exception as e:
            logger.warning(f"[CACHE] Failed to invalidate caches for task {task_id}: {e}")

    @classmethod
    def list_action_sets(cls) -> Dict[str, Any]:
        """
        List all available action sets and their descriptions.

        Returns:
            Dictionary with available sets and current task's active sets.
        """
        from app.action.action_set import action_set_manager

        available_sets = action_set_manager.list_all_sets()
        current_sets = []
        if cls.task_manager:
            current_sets = cls.task_manager.get_action_sets()

        return {
            "available_sets": available_sets,
            "current_sets": current_sets,
        }
