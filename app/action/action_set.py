# core/action/action_set.py
"""
Action Set Management Module

This module provides the ActionSetManager for compiling static action lists
from predefined action sets. This eliminates the need for RAG-based action
retrieval during task execution, improving performance and predictability.
"""

import platform as platform_lib
from typing import Any, Iterable, Iterator, List, Dict, Set, Optional, Tuple
import logging

logger = logging.getLogger("ActionSetManager")

# Descriptions of the action sets this application defines. Sets are
# discovered from the registry; an integration's sets are described by its
# provider and an MCP server's by its config (ActionSetManager.list_all_sets).
# A set described nowhere is described by the actions it holds, and
# tests/test_capability_catalog.py fails on any such set.
DEFAULT_SET_DESCRIPTIONS: Dict[str, str] = {
    "agent_app": (
        "Agent Apps: create (scaffold), import and convert apps, restart and "
        "verify them, call their HTTP API and read their usage, report build "
        "progress and findings, approve their triggers, browse and install "
        "from the marketplace"
    ),
    "content_creation": "Generate images and videos",
    "proactive": (
        "Recurring proactive tasks in PROACTIVE.md (add, read, update, remove) "
        "and scheduled tasks"
    ),
    "scheduler": (
        "Schedule one-time and recurring tasks (create, list, enable or "
        "disable, remove)"
    ),
    "core": "Essential actions always available (send_message, task management, set management)",
    "file_operations": "File and folder manipulation (read, write, search, edit)",
    "web_research": "Internet search and browsing (web search, fetch URLs)",
    "mini_browser": (
        "Mini Browser: a live Chromium with the user's saved logins and cookies; "
        "each agent drives its own tab while the user can watch and take control. "
        "USE it to operate websites: logging in, filling and submitting forms, "
        "searching inside a site, shopping/booking, JavaScript-heavy or "
        "login-walled pages, anything web_fetch could not read. NOT for plain "
        "lookups (web_search / web_fetch are faster)."
    ),
    "mcp_playwright-mcp": (
        "Headless, invisible Playwright browser over MCP (separate profile "
        "without the user's logins) for automated app verification such as "
        "walk_verify. To browse or act on websites for the user, use "
        "mini_browser instead."
    ),
    "document_processing": "PDF and document handling (read, create, convert)",
    "image": "Image viewing, analysis, and OCR (screenshots, photos, diagrams)",
    "video": "Video analysis and understanding — describe, summarise, or answer questions about video files (MP4, AVI, MOV)",
    "clipboard": "Clipboard read/write operations",
    "shell": "Command line and Python execution",
}

# Renamed sets: old name -> current name. Sessions and schedules persist set
# names, so an old name must keep compiling to the renamed set's actions.
SET_ALIASES: Dict[str, str] = {"web_agent": "mini_browser"}

# How many of its actions describe a set no declaration describes.
_LISTED_ACTIONS = 8


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
            # set name -> provider id, for the provider actions the
            # integration adapter generates (declare_integration_set).
            cls._instance._integration_sets = {}
        return cls._instance

    # ───────────────────────────── integrations ─────────────────────────────

    def declare_integration_set(self, set_name: str, provider_id: str) -> None:
        """Record that ``set_name`` holds actions of provider ``provider_id``
        (the integration adapter declares the sets of the actions it
        generates from a provider's operations)."""
        self._integration_sets[set_name] = provider_id

    @staticmethod
    def _registered() -> Iterator[Any]:
        """Each registered action's implementation for this platform."""
        from agent_core import registry_instance, PLATFORM_ALL

        current_platform = platform_lib.system().lower()
        for platform_impls in registry_instance._registry.values():
            impl = platform_impls.get(current_platform) or platform_impls.get(
                PLATFORM_ALL
            )
            if impl is not None:
                yield impl

    def integration_sets(self) -> Dict[str, List[str]]:
        """Every integration's action sets, keyed by integration.

        The key is a provider id for the actions the integration adapter
        generates (it declares their sets), or a bridged platform's directory
        (account_bridge.BRIDGED_ACTION_DIRS) for the hand-written actions
        that live under it. Sets are in registration order.
        """
        from app.data.action.integrations.account_bridge import (
            BRIDGED_ACTION_DIRS,
            integration_dir_of,
        )

        owners: Dict[str, str] = dict(self._integration_sets)
        for impl in self._registered():
            directory = integration_dir_of(impl.handler)
            if directory not in BRIDGED_ACTION_DIRS:
                continue
            for set_name in impl.metadata.action_sets or []:
                if set_name != "core":
                    owners.setdefault(set_name, directory)
        grouped: Dict[str, List[str]] = {}
        for set_name, integration in owners.items():
            grouped.setdefault(integration, []).append(set_name)
        return grouped

    @staticmethod
    def integration_providers(integration: str) -> Tuple[str, ...]:
        """The provider ids of an integration key (see integration_sets)."""
        from app.data.action.integrations.account_bridge import BRIDGED_ACTION_DIRS

        platform = BRIDGED_ACTION_DIRS.get(integration)
        return platform.providers if platform else (integration,)

    @classmethod
    def integration_description(cls, integration: str) -> Tuple[str, str]:
        """(name, what it does) of an integration, from its provider's
        metadata; a bridged platform with several providers is named by its
        label, and what it does lists each provider."""
        from app.data.action.integrations.account_bridge import BRIDGED_ACTION_DIRS
        from craftos_integrations.providers import get_provider

        providers = [
            p
            for p in map(get_provider, cls.integration_providers(integration))
            if p is not None
        ]
        platform = BRIDGED_ACTION_DIRS.get(integration)
        if len(providers) == 1:
            return providers[0].display_name, providers[0].description
        if providers:
            return platform.label, "; ".join(
                f"{p.display_name}: {p.description}" for p in providers
            )
        return (platform.label if platform else integration), ""

    @staticmethod
    def _mcp_set_descriptions() -> Dict[str, str]:
        """Each connected MCP server's action set, described by its config."""
        try:
            from app.mcp import mcp_client
        except Exception:
            return {}
        descriptions: Dict[str, str] = {}
        for name, server in mcp_client.servers.items():
            config = server.config
            descriptions[config.resolved_action_set_name] = (
                config.description or f"Tools of the '{name}' MCP server"
            )
        return descriptions

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
        # Always include core set; renamed sets resolve to their new name.
        required_sets: Set[str] = {SET_ALIASES.get(s, s) for s in selected_sets}
        required_sets.add("core")
        compiled = [meta.name for meta in self.actions_in_sets(required_sets, mode)]
        logger.debug(f"Compiled {len(compiled)} actions from sets: {required_sets}")
        return compiled

    def actions_in_sets(self, set_names: Iterable[str], mode: str = "CLI") -> list:
        """Metadata of every action in any of exactly these sets.

        Unlike compile_action_list, "core" is not added implicitly. Uses each
        action's implementation for the current platform and filters by
        visibility mode.

        Args:
            set_names: Action set names.
            mode: Visibility mode filter - "CLI", "GUI", or "ALL".

        Returns:
            List of ActionMetadata, in registry order.
        """
        from agent_core import registry_instance, PLATFORM_ALL

        required_sets = set(set_names)
        current_platform = platform_lib.system().lower()
        found = []
        for platform_impls in registry_instance._registry.values():
            impl = platform_impls.get(current_platform) or platform_impls.get(
                PLATFORM_ALL
            )
            if impl is None:
                continue
            metadata = impl.metadata
            # Actions that declare no set are never compiled into a list.
            action_sets = getattr(metadata, "action_sets", [])
            if not self._action_in_sets(action_sets, required_sets):
                continue
            if not self._is_visible_in_mode(metadata.mode, mode):
                continue
            found.append(metadata)
        return found

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
            Dictionary mapping set names to their descriptions: an
            application set's declared one (DEFAULT_SET_DESCRIPTIONS), an MCP
            server's config, an integration's provider metadata, or else the
            actions the set holds.
        """
        members: Dict[str, List[str]] = {}
        for impl in self._registered():
            for set_name in getattr(impl.metadata, "action_sets", []):
                members.setdefault(set_name, []).append(impl.metadata.name)

        mcp = self._mcp_set_descriptions()
        owner = {
            set_name: integration
            for integration, sets in self.integration_sets().items()
            for set_name in sets
        }
        integrations: Dict[str, Tuple[str, str]] = {}
        discovered_sets: Dict[str, str] = {}
        for set_name, actions in members.items():
            if set_name in DEFAULT_SET_DESCRIPTIONS:
                description = DEFAULT_SET_DESCRIPTIONS[set_name]
            elif set_name in mcp:
                description = mcp[set_name]
            elif set_name in owner:
                integration = owner[set_name]
                if integration not in integrations:
                    integrations[integration] = self.integration_description(
                        integration
                    )
                name, what = integrations[integration]
                description = f"{name}: {what}" if what else name
            else:
                shown = ", ".join(actions[:_LISTED_ACTIONS])
                more = len(actions) - _LISTED_ACTIONS
                description = f"Actions: {shown}" + (
                    f", and {more} more" if more > 0 else ""
                )
            discovered_sets[set_name] = description

        return discovered_sets

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
            Formatted string describing available action sets: one line per
            set, then one line per integration naming all of its sets
            (described once, by the integration's provider). Sorted, so the
            catalog (part of the cached system prompt) renders the same on
            every boot.
        """
        all_sets = self.list_all_sets()
        integrations = {
            integration: [s for s in sets if s in all_sets]
            for integration, sets in self.integration_sets().items()
        }
        owned = {s for sets in integrations.values() for s in sets}

        lines = []
        for set_name, description in sorted(all_sets.items()):
            if set_name in owned or (exclude_core and set_name == "core"):
                continue
            if set_name == "core":
                lines.append(f"- {set_name}: {description} (always included)")
            else:
                lines.append(f"- {set_name}: {description}")

        rows = []
        for integration, sets in integrations.items():
            if not sets:
                continue
            name, what = self.integration_description(integration)
            # The set named after the integration first: its high-value actions.
            ordered = sorted(sets, key=lambda s: (s != integration, s))
            label = f"{name} ({what})" if what else name
            rows.append((name.lower(), f"- {label}: {', '.join(ordered)}"))
        if rows:
            lines.append(
                "Integration action sets. Load the set named after an "
                "integration for its high-value actions; load a narrower set "
                "when the task needs a specific area:"
            )
            lines.extend(row for _, row in sorted(rows))
        return "\n".join(lines)


# Global singleton instance
action_set_manager = ActionSetManager()
