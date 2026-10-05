# core/action/action_set.py
"""
Action Set Management Module

This module provides the ActionSetManager for compiling static action lists
from predefined action sets. This eliminates the need for RAG-based action
retrieval during task execution, improving performance and predictability.
"""

import platform as platform_lib
from typing import List, Dict, Set, Optional
import logging

logger = logging.getLogger("ActionSetManager")

# Default descriptions for known action sets
# These provide fallback descriptions; actual sets are discovered dynamically from the registry
DEFAULT_SET_DESCRIPTIONS: Dict[str, str] = {
    "core": "Essential actions always available (send_message, task management, set management)",
    "file_operations": "File and folder manipulation (read, write, search, edit)",
    "web_research": "Internet search and browsing (web search, fetch URLs)",
    "document_processing": "PDF and document handling (read, create, convert)",
    "image": "Image viewing, analysis, and OCR (screenshots, photos, diagrams)",
    "video": "Video analysis and understanding — describe, summarise, or answer questions about video files (MP4, AVI, MOV)",
    "clipboard": "Clipboard read/write operations",
    "shell": "Command line and Python execution",
}


_MAX_NOUNS = 6


def _umbrella_of(set_name: str, all_sets: Dict[str, List[str]]) -> Optional[str]:
    """Longest other set name that prefixes this one (``supabase`` for
    ``supabase_storage``) — the integration's shortlist set."""
    best = None
    for other in all_sets:
        if other != set_name and set_name.startswith(other + "_"):
            if best is None or len(other) > len(best):
                best = other
    return best


def describe_set(
    set_name: str, actions: List[str], all_sets: Dict[str, List[str]]
) -> str:
    """Catalog line for a set with no hand-written description.

    The agent picks sets from this catalog, so the line must say what is
    inside. Integration sets are named by integration and noun
    (``supabase_storage``) and their actions by verb + integration + noun
    (``delete_supabase_bucket``); listing the nouns tells the agent where
    an action lives without spending tokens on every action name.
    """
    sub_sets = sorted(s for s in all_sets if s.startswith(set_name + "_"))
    if sub_sets:
        return (
            f"shortlist of the most-used {set_name} actions ({len(actions)}); "
            f"not everything — load {set_name}_* sets for the rest"
        )

    umbrella = _umbrella_of(set_name, all_sets)
    strip = set(umbrella.split("_")) if umbrella else set()
    shown_as: Dict[str, str] = {}  # singular key -> display form, in order
    for action in actions:
        tokens = [t for t in action.split("_") if t not in strip]
        noun = "_".join(tokens[1:]) if len(tokens) > 1 else action
        key = noun[:-2] if noun.endswith(("ches", "shes", "xes", "sses")) else noun.rstrip("s")
        if not key:
            continue
        # Keep first-seen order, but prefer the plural form for display.
        if key not in shown_as or (noun.endswith("s") and not shown_as[key].endswith("s")):
            shown_as[key] = noun
    nouns = list(shown_as.values())
    shown = ", ".join(nouns[:_MAX_NOUNS])
    more = ", …" if len(nouns) > _MAX_NOUNS else ""
    return f"{len(actions)} actions: {shown}{more}"


class ActionSetManager:
    """
    Singleton managing action set compilation from the ActionRegistry.

    Compiles static action lists based on selected action sets, eliminating
    the need for RAG-based action retrieval during task execution.
    """

    _instance: Optional["ActionSetManager"] = None

    def __new__(cls) -> "ActionSetManager":
        if cls._instance is None:
            cls._instance = super(ActionSetManager, cls).__new__(cls)
        return cls._instance

    def compile_action_list(
        self, selected_sets: List[str], mode: str = "CLI"
    ) -> List[str]:
        """
        Compile a list of action names from selected action sets.

        Args:
            selected_sets: List of action set names to include (e.g., ["file_operations", "web_research"])
            mode: Visibility mode filter - "CLI", "GUI", or "ALL"

        Returns:
            List of action names available for the task

        Notes:
            - The "core" set is always included automatically
            - Actions are filtered by their visibility mode
            - Actions can belong to multiple sets
        """
        from agent_core import registry_instance, PLATFORM_ALL

        # Always include core set
        required_sets: Set[str] = set(selected_sets) | {"core"}
        compiled: List[str] = []

        # Get current platform for implementation lookup
        current_platform = platform_lib.system().lower()

        for action_name, platform_impls in registry_instance._registry.items():
            # Get the best implementation for current platform
            impl = platform_impls.get(current_platform) or platform_impls.get(
                PLATFORM_ALL
            )

            if impl is None:
                continue

            metadata = impl.metadata

            # Check if action belongs to any of the required sets
            action_sets = getattr(metadata, "action_sets", [])
            if not action_sets:
                # Actions without action_sets are not included (backward compatibility)
                # They will be included via RAG fallback if needed
                continue

            if not self._action_in_sets(action_sets, required_sets):
                continue

            # Filter by visibility mode
            if not self._is_visible_in_mode(metadata.mode, mode):
                continue

            compiled.append(action_name)

        logger.debug(f"Compiled {len(compiled)} actions from sets: {required_sets}")
        return compiled

    def _action_in_sets(self, action_sets: List[str], required_sets: Set[str]) -> bool:
        """Check if an action belongs to any of the required sets."""
        return bool(set(action_sets) & required_sets)

    def _is_visible_in_mode(self, action_mode: str, current_mode: str) -> bool:
        """
        Check if an action is visible in the current mode.

        Args:
            action_mode: The action's mode setting ("CLI", "GUI", or "ALL")
            current_mode: The current execution mode ("CLI" or "GUI")

        Returns:
            True if the action should be visible in the current mode
        """
        if not action_mode or action_mode.upper() == "ALL":
            return True
        if current_mode.upper() == "GUI":
            return action_mode.upper() in ("GUI", "ALL")
        else:  # CLI mode
            return action_mode.upper() in ("CLI", "ALL")

    def list_all_sets(self) -> Dict[str, str]:
        """
        Dynamically discover ALL action sets from the registry.

        This method scans all registered actions to find unique set names,
        supporting custom action sets and MCP tools automatically.

        Returns:
            Dictionary mapping set names to their descriptions
        """
        from agent_core import registry_instance, PLATFORM_ALL

        current_platform = platform_lib.system().lower()
        members: Dict[str, List[str]] = {}

        # Scan all registered actions to find unique set names
        for action_name, platform_impls in registry_instance._registry.items():
            impl = platform_impls.get(current_platform) or platform_impls.get(
                PLATFORM_ALL
            )

            if impl is None:
                continue

            action_sets = getattr(impl.metadata, "action_sets", [])
            for set_name in action_sets:
                members.setdefault(set_name, []).append(action_name)

        return {
            set_name: DEFAULT_SET_DESCRIPTIONS.get(set_name)
            or describe_set(set_name, actions, members)
            for set_name, actions in members.items()
        }

    def get_set_description(self, set_name: str) -> Optional[str]:
        """
        Get the description for a specific action set.

        Args:
            set_name: Name of the action set

        Returns:
            Description string or None if set doesn't exist
        """
        # First check if set exists in registry
        all_sets = self.list_all_sets()
        return all_sets.get(set_name)

    def get_actions_in_set(self, set_name: str) -> List[str]:
        """
        Return all action names belonging to a specific set.

        Args:
            set_name: Name of the action set to query

        Returns:
            List of action names in the set
        """
        from agent_core import registry_instance, PLATFORM_ALL

        current_platform = platform_lib.system().lower()
        actions_in_set: List[str] = []

        for action_name, platform_impls in registry_instance._registry.items():
            impl = platform_impls.get(current_platform) or platform_impls.get(
                PLATFORM_ALL
            )

            if impl is None:
                continue

            action_sets = getattr(impl.metadata, "action_sets", [])
            if set_name in action_sets:
                actions_in_set.append(action_name)

        return actions_in_set

    def get_available_set_names(self) -> List[str]:
        """
        Return a list of all available action set names.

        Returns:
            List of set names (dynamically discovered from registry)
        """
        return list(self.list_all_sets().keys())

    def format_sets_for_prompt(self, exclude_core: bool = False) -> str:
        """
        Format action set information for inclusion in prompts.

        Args:
            exclude_core: If True, don't include core set (it's always auto-included)

        Returns:
            Formatted string describing available action sets
        """
        all_sets = self.list_all_sets()
        lines = []
        for set_name, description in all_sets.items():
            if exclude_core and set_name == "core":
                continue
            if set_name == "core":
                lines.append(f"- {set_name}: {description} (always included)")
            else:
                lines.append(f"- {set_name}: {description}")
        return "\n".join(lines)


# Global singleton instance
action_set_manager = ActionSetManager()
