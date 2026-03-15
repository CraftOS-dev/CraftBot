"""Main Textual application for the TUI interface."""
from __future__ import annotations

import os
import time
from asyncio import QueueEmpty, create_task
from typing import TYPE_CHECKING

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import var
from textual.widgets import Input, Static, ListView, ListItem, Label, Button

from rich.text import Text

from app.models.model_registry import MODEL_REGISTRY
from app.models.types import InterfaceType

from app.tui.styles import TUI_CSS
from app.tui.settings import save_settings_to_json, get_api_key_env_name, get_api_key_for_provider
from app.tui.widgets import ConversationLog, PasteableInput, VMFootageWidget, TaskSelected
from app.tui.mcp_settings import (
    list_mcp_servers,
    remove_mcp_server,
    enable_mcp_server,
    disable_mcp_server,
    update_mcp_server_env,
    get_server_env_vars,
)
from app.tui.skill_settings import (
    list_skills,
    get_skill_info,
    enable_skill,
    disable_skill,
    toggle_skill,
    get_skill_raw_content,
    install_skill_from_path,
    install_skill_from_git,
)
from app.external_comms.integration_settings import (
    list_integrations,
    get_integration_info,
    get_integration_fields,
    get_integration_auth_type,
    connect_integration_token,
    connect_integration_oauth,
    connect_integration_interactive,
    disconnect_integration,
    INTEGRATION_REGISTRY,
)
from app.onboarding import onboarding_manager
from app.logger import logger

if TYPE_CHECKING:
    from typing import Union
    from app.tui.interface import TUIInterface
    from app.ui_layer.adapters.tui_adapter import TUIAdapter


class CraftApp(App):
    """Textual application rendering the Craft Agent TUI."""

    CSS = TUI_CSS

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    status_text = var("Status: Idle")
    show_menu = var(True)
    show_settings = var(False)
    gui_mode_active = var(False)

    _STATUS_PREFIX = " "
    _STATUS_GAP = 4
    _STATUS_INITIAL_PAUSE = 6

    # Icons for task/action status
    ICON_COMPLETED = "+"
    ICON_ERROR = "x"
    ICON_LOADING_FRAMES = ["●", "○"]  # Animated loading icons

    _MENU_ITEMS = [
        ("menu-start", "start"),
        ("menu-settings", "setting"),
        ("menu-exit", "exit"),
    ]

    @staticmethod
    def _sanitize_id(name: str) -> str:
        """Sanitize a name for use as a Textual widget ID.

        Textual widget IDs must contain only letters, numbers, underscores, or hyphens,
        and must not begin with a number.

        Args:
            name: The name to sanitize.

        Returns:
            A sanitized ID string.
        """
        import re
        # Replace spaces and invalid characters with hyphens
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', name)
        # Ensure it doesn't start with a number
        if sanitized and sanitized[0].isdigit():
            sanitized = '_' + sanitized
        # Remove consecutive hyphens
        sanitized = re.sub(r'-+', '-', sanitized)
        # Remove leading/trailing hyphens
        sanitized = sanitized.strip('-')
        return sanitized or 'unknown'

    _SETTINGS_PROVIDER_TEXTS = [
        "OpenAI",
        "Google Gemini",
        "BytePlus",
        "Anthropic",
        "Ollama (remote)",
    ]

    _SETTINGS_PROVIDER_VALUES = [
        "openai",
        "gemini",
        "byteplus",
        "anthropic",
        "remote",
    ]

    _SETTINGS_ACTION_TEXTS = [
        "save",
        "cancel",
    ]

    _PROVIDER_API_KEY_NAMES = {
        "openai": "OpenAI",
        "gemini": "Google Gemini",
        "byteplus": "BytePlus",
        "anthropic": "Anthropic",
        "remote": "Ollama (remote)",
    }

    def _get_api_key_label(self) -> str:
        """Get the label for the API key input based on current provider."""
        provider_name = self._PROVIDER_API_KEY_NAMES.get(self._provider, self._provider)
        return f"API Key for {provider_name}"

    def _get_model_for_provider(self, provider: str) -> str:
        """Get the LLM model name for a provider from the model registry."""
        if provider in MODEL_REGISTRY:
            return MODEL_REGISTRY[provider].get(InterfaceType.LLM, "Unknown")
        return "Unknown"

    def __init__(self, interface: "Union[TUIInterface, TUIAdapter]", provider: str, api_key: str) -> None:
        super().__init__()
        self._interface = interface
        self._status_message: str = "Idle"
        self._status_offset: int = 0
        self._status_pause: int = self._STATUS_INITIAL_PAUSE
        self._last_rendered_status: str = ""
        self._provider = provider
        self._api_key = api_key
        # Track saved API keys per provider (to know whether to reset on provider change)
        self._saved_api_keys: dict[str, str] = {provider: api_key} if api_key else {}
        # Track the provider selected in settings before saving
        self._settings_provider: str = provider
        # Flag to block provider change events during settings initialization
        self._settings_init_complete: bool = True

    def _is_api_key_configured(self) -> bool:
        """Check if an API key is configured for the current provider."""
        # Remote (Ollama) doesn't need API key
        if self._provider == "remote":
            return True

        # Check local setting first
        if self._api_key:
            return True

        # Check settings.json or environment variable
        if get_api_key_for_provider(self._provider):
            return True

        return False

    def _get_menu_hint(self) -> str:
        """Generate the menu hint text based on API key configuration status."""
        if self._is_api_key_configured():
            return "API key configured. Press Enter on 'start' to begin."
        else:
            return "No API key found. Please configure in Settings before starting."

    def compose(self) -> ComposeResult:  # pragma: no cover - declarative layout
        yield Container(
            Container(
                Static(self._header_text(), id="menu-header"),
                Vertical(
                    Static("CraftBot V1.2.0. Your Personal AI Assistant that works 24/7 in your machine.", id="provider-hint"),
                    Static(
                        self._get_menu_hint(),
                        id="menu-hint",
                    ),
                    id="menu-copy",
                ),
                ListView(
                    ListItem(Label("start", classes="menu-item"), id="menu-start"),
                    ListItem(Label("setting", classes="menu-item"), id="menu-settings"),
                    ListItem(Label("exit", classes="menu-item"), id="menu-exit"),
                    id="menu-options",
                ),
                id="menu-panel",
            ),
            id="menu-layer",
        )

        yield Container(
            Horizontal(
                Container(
                    ConversationLog(id="chat-log"),
                    id="chat-panel",
                ),
                Vertical(
                    Container(
                        VMFootageWidget(id="vm-footage"),
                        id="vm-footage-panel",
                        classes="-hidden",
                    ),
                    Container(
                        ConversationLog(id="action-log"),
                        id="action-panel",
                    ),
                    id="right-panel",
                ),
                id="top-region",
            ),
            Vertical(
                Static(
                    Text(self.status_text, no_wrap=True, overflow="crop"),
                    id="status-bar",
                ),
                PasteableInput(placeholder="Type a message and press Enter…", id="chat-input"),
                id="bottom-region",
            ),
            id="chat-layer",
        )

    # ────────────────────────────── menu helpers ─────────────────────────────

    def _header_text(self) -> Text:
        """Generate combined icon and logo as a single Text object for proper centering."""
        orange = "#ff4f18"
        white = "#ffffff"

        b = "█"  # block character
        s = " "  # space

        # Icon: 9 chars wide, 6 rows
        icon_w = 9
        icon_lines = [
            (s * 2 + b * 2 + s * 5, [(2, 4, orange)]),  # Antenna
            (s * 2 + b * 2 + s * 5, [(2, 4, orange)]),  # Antenna
            (b * icon_w, [(0, icon_w, white)]),  # Face top
            (b * icon_w, [(0, 3, white), (3, 5, orange), (5, 6, white), (6, 8, orange), (8, icon_w, white)]),  # Eyes
            (b * icon_w, [(0, 3, white), (3, 5, orange), (5, 6, white), (6, 8, orange), (8, icon_w, white)]),  # Eyes
            (b * icon_w, [(0, icon_w, white)]),  # Face bottom
        ]

        # Logo: 67 chars wide, 6 rows
        logo_lines = [
            " ██████╗██████╗  █████╗ ███████╗████████╗██████╗  ██████╗ ████████╗",
            "██╔════╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗╚══██╔══╝",
            "██║     ██████╔╝███████║█████╗     ██║   ██████╔╝██║   ██║   ██║   ",
            "██║     ██╔══██╗██╔══██║██╔══╝     ██║   ██╔══██╗██║   ██║   ██║   ",
            "╚██████╗██║  ██║██║  ██║██║        ██║   ██████╔╝╚██████╔╝   ██║   ",
            " ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝        ╚═╝   ╚═════╝  ╚═════╝    ╚═╝   ",
        ]

        # Combine icon and logo side by side with 3 space gap
        gap = "   "
        combined_lines = []
        craft_len = 41  # CRAFT portion length in logo

        for i in range(6):
            icon_str = icon_lines[i][0]
            logo_str = logo_lines[i]
            combined_lines.append(icon_str + gap + logo_str)

        full_text = "\n".join(combined_lines)
        text = Text(full_text, justify="center")

        # Apply styles
        offset = 0
        for i in range(6):
            icon_str, icon_spans = icon_lines[i]
            logo_str = logo_lines[i]
            line_len = len(icon_str) + len(gap) + len(logo_str)

            # Style icon parts
            for start, end, color in icon_spans:
                text.stylize(color, offset + start, offset + end)

            # Style logo parts (offset by icon width + gap)
            logo_offset = len(icon_str) + len(gap)
            text.stylize(white, offset + logo_offset, offset + logo_offset + craft_len)
            text.stylize(orange, offset + logo_offset + craft_len, offset + logo_offset + len(logo_str))

            offset += line_len + 1  # +1 for newline

        return text

    def _open_settings(self) -> None:
        if self.query("#settings-card"):
            return

        # Hide the main menu panel while settings are open
        self.show_settings = True

        # Block provider change events during initialization
        self._settings_init_complete = False

        # Reset settings provider tracking to current provider
        self._settings_provider = self._provider

        # Get model name for current provider
        model_name = self._get_model_for_provider(self._provider)

        # Build MCP server list items
        mcp_server_items = self._build_mcp_server_list_items()

        # Build Skills list items
        skill_items = self._build_skill_list_items()

        # Build Integrations list items
        integration_items = self._build_integration_list_items()

        # Build tab buttons
        tab_buttons = Horizontal(
            Button("Models", id="tab-btn-models", classes="settings-tab -active"),
            Button("MCP Servers", id="tab-btn-mcp", classes="settings-tab"),
            Button("Skills", id="tab-btn-skills", classes="settings-tab"),
            Button("Integrations", id="tab-btn-integrations", classes="settings-tab"),
            id="settings-tab-bar",
        )

        # Build Models section content
        models_section = Container(
            Static("LLM Provider"),
            ListView(
                ListItem(Label("OpenAI", classes="menu-item")),
                ListItem(Label("Google Gemini", classes="menu-item")),
                ListItem(Label("BytePlus", classes="menu-item")),
                ListItem(Label("Anthropic", classes="menu-item")),
                ListItem(Label("Ollama (remote)", classes="menu-item")),
                id="provider-options",
            ),
            Static(f"Model: {model_name}", id="model-display"),
            Static(self._get_api_key_label(), id="api-key-label"),
            PasteableInput(
                placeholder="Enter API key (Ctrl+V to paste)",
                password=False,
                id="api-key-input",
                value=self._api_key,
            ),
            id="section-models",
        )

        # Build MCP section content
        mcp_section = Container(
            Static("MCP Servers", id="mcp-servers-title"),
            VerticalScroll(
                *mcp_server_items,
                id="mcp-server-list",
            ),
            Static("Custom MCP Server", id="mcp-add-title"),
            Static("For custom servers, edit: app/config/mcp_config.json",
                   id="mcp-add-instruction", classes="settings-instruction"),
            Static("Or use: /mcp add <name> <json-config>", id="mcp-hint"),
            id="section-mcp",
            classes="-hidden",  # Hidden by default
        )

        # Build Skills section content
        skills_section = Container(
            Static("Discovered Skills", id="skills-title"),
            VerticalScroll(
                *skill_items,
                id="skills-list",
            ),
            Static("Install Skill", id="skill-install-title"),
            Static("Enter local path or Git URL (e.g., https://github.com/user/skill-repo)",
                   id="skill-install-instruction", classes="settings-instruction"),
            PasteableInput(
                placeholder="Path or Git URL",
                id="skill-install-input",
            ),
            Horizontal(
                Button("Install", id="skill-install-btn", classes="settings-add-btn"),
                id="skill-install-actions",
            ),
            Static("Use /skill command for more options", id="skills-hint"),
            id="section-skills",
            classes="-hidden",  # Hidden by default
        )

        # Build Integrations section content
        integrations_section = Container(
            Static("3rd Party Integrations", id="integrations-title"),
            VerticalScroll(
                *integration_items,
                id="integrations-list",
            ),
            Static("Connect to external services like Slack, Notion, Google, etc.", id="integrations-hint"),
            id="section-integrations",
            classes="-hidden",  # Hidden by default
        )

        settings = Container(
            Static("Settings", id="settings-title"),
            tab_buttons,
            models_section,
            mcp_section,
            skills_section,
            integrations_section,
            ListView(
                ListItem(Label("save", classes="menu-item"), id="settings-save"),
                ListItem(Label("cancel", classes="menu-item"), id="settings-cancel"),
                id="settings-actions-list",
            ),
            id="settings-card",
        )

        self.query_one("#menu-layer").mount(settings)
        self.call_after_refresh(self._init_settings_provider_selection)

    def _build_mcp_server_list_items(self) -> list:
        """Build list items for configured MCP servers."""
        # Get configured servers as a dict for quick lookup
        configured_servers = {s["name"]: s for s in list_mcp_servers()}
        items = []

        # Store mapping from sanitized ID to original server name for handlers
        self._mcp_id_to_name: dict[str, str] = {}

        # Show all configured servers
        for name, server in configured_servers.items():
            # Sanitize name for use in widget IDs
            safe_id = self._sanitize_id(name)
            # Store mapping for reverse lookup
            self._mcp_id_to_name[safe_id] = name

            status = "[+]" if server["enabled"] else "[ ]"
            # Truncate name if too long
            display_name = name[:18] + ".." if len(name) > 18 else name
            desc = server.get("description", "MCP server")
            desc = desc[:35] + "..." if len(desc) > 35 else desc

            env_vars = server.get("env", {})
            empty_vars = [k for k, v in env_vars.items() if not v]
            warning = " (!)" if empty_vars else ""

            row_widgets = [
                Static(f"{status} {display_name}{warning}", classes="mcp-server-name"),
                Static(desc, classes="mcp-server-desc"),
            ]

            if env_vars:
                row_widgets.append(Button("Configure", id=f"mcp-config-{safe_id}", classes="mcp-config-btn"))

            if server["enabled"]:
                row_widgets.append(Button("Disable", id=f"mcp-disable-{safe_id}", classes="mcp-toggle-btn -enabled"))
            else:
                row_widgets.append(Button("Enable", id=f"mcp-enable-{safe_id}", classes="mcp-toggle-btn -disabled"))

            items.append(Horizontal(*row_widgets, classes="mcp-server-row"))

        if not items:
            items.append(Static("No MCP servers available", classes="mcp-empty"))

        return items

    def _refresh_mcp_server_list(self) -> None:
        """Refresh the MCP server list in settings."""
        if not self.query("#mcp-server-list"):
            return

        server_list = self.query_one("#mcp-server-list", VerticalScroll)
        server_list.remove_children()

        items = self._build_mcp_server_list_items()
        for item in items:
            server_list.mount(item)

    def _build_skill_list_items(self) -> list:
        """Build list items for discovered skills."""
        skills = list_skills()
        items = []

        # Store mapping from sanitized ID to original skill name for handlers
        self._skill_id_to_name: dict[str, str] = {}

        if not skills:
            items.append(Static("No skills discovered", classes="skill-empty"))
        else:
            # Sort skills alphabetically by name
            for skill in sorted(skills, key=lambda s: s["name"].lower()):
                status = "[+]" if skill["enabled"] else "[ ]"
                name = skill["name"]
                # Sanitize name for use in widget IDs
                safe_id = self._sanitize_id(name)
                # Store mapping for reverse lookup
                self._skill_id_to_name[safe_id] = name
                # Truncate name if too long (max 18 chars to leave room for status)
                display_name = name[:18] + ".." if len(name) > 18 else name
                desc = skill["description"][:35] + "..." if len(skill["description"]) > 35 else skill["description"]

                # Build row with: status+name, description, [View], [Enable/Disable]
                row_widgets = [
                    Static(f"{status} {display_name}", classes="skill-name"),
                    Static(desc, classes="skill-desc"),
                    Button("View", id=f"skill-view-{safe_id}", classes="skill-view-btn"),
                ]

                # Add Enable/Disable toggle button
                if skill["enabled"]:
                    row_widgets.append(Button("Disable", id=f"skill-disable-{safe_id}", classes="skill-toggle-btn -enabled"))
                else:
                    row_widgets.append(Button("Enable", id=f"skill-enable-{safe_id}", classes="skill-toggle-btn -disabled"))

                items.append(Horizontal(*row_widgets, classes="skill-row"))

        return items

    def _refresh_skill_list(self) -> None:
        """Refresh the skill list in settings."""
        if not self.query("#skills-list"):
            return

        skill_list = self.query_one("#skills-list", VerticalScroll)
        skill_list.remove_children()

        items = self._build_skill_list_items()
        for item in items:
            skill_list.mount(item)

    def _handle_mcp_add_button(self) -> None:
        """Handle the MCP Add button press - no longer supported in TUI."""
        self.notify("Add MCP servers via mcp_config.json or the browser interface", severity="information", timeout=3)

    def _handle_skill_install_button(self) -> None:
        """Handle the Skill Install button press."""
        if not self.query("#skill-install-input"):
            return

        install_input = self.query_one("#skill-install-input", PasteableInput)
        source = install_input.value.strip()

        if not source:
            self.notify("Please enter a path or Git URL", severity="warning", timeout=2)
            return

        # Determine if URL or path
        if source.startswith(("http://", "https://", "git@", "github.com", "gitlab.com")):
            self.notify("Installing skill from Git...", severity="information", timeout=2)
            success, message = install_skill_from_git(source)
        else:
            success, message = install_skill_from_path(source)

        if success:
            install_input.value = ""
            self._refresh_skill_list()
            self.notify(message, severity="information", timeout=2)
        else:
            self.notify(message, severity="error", timeout=3)

    def _build_integration_list_items(self) -> list:
        """Build list items for integrations."""
        integrations = list_integrations()
        items = []

        # Store mapping from sanitized ID to original integration ID for handlers
        self._integ_id_to_name: dict[str, str] = {}

        if not integrations:
            items.append(Static("No integrations available", classes="integration-empty"))
        else:
            for integ in integrations:
                status = "[+]" if integ["connected"] else "[ ]"
                name = integ["name"]
                # Truncate name if too long
                display_name = name[:18] + ".." if len(name) > 18 else name
                integ_id = integ["id"]
                # Sanitize ID for use in widget IDs
                safe_id = self._sanitize_id(integ_id)
                # Store mapping for reverse lookup
                self._integ_id_to_name[safe_id] = integ_id

                # Truncate description if too long
                desc = integ["description"][:35] + "..." if len(integ["description"]) > 35 else integ["description"]

                if integ["connected"]:
                    # Show view and disconnect buttons for connected integrations
                    account_count = len(integ.get("accounts", []))
                    account_text = f"({account_count})" if account_count > 0 else ""

                    items.append(
                        Horizontal(
                            Static(f"{status} {display_name} {account_text}", classes="integration-name"),
                            Static(desc, classes="integration-desc"),
                            Button("View", id=f"integ-view-{safe_id}", classes="integration-view-btn"),
                            Button("x", id=f"integ-disconnect-{safe_id}", classes="integration-disconnect-btn"),
                            classes="integration-row",
                        )
                    )
                else:
                    # Show connect button for disconnected integrations
                    items.append(
                        Horizontal(
                            Static(f"{status} {display_name}", classes="integration-name"),
                            Static(desc, classes="integration-desc"),
                            Button("Connect", id=f"integ-connect-{safe_id}", classes="integration-connect-btn"),
                            classes="integration-row",
                        )
                    )

        return items

    def _refresh_integration_list(self) -> None:
        """Refresh the integration list in settings."""
        if not self.query("#integrations-list"):
            return

        integration_list = self.query_one("#integrations-list", VerticalScroll)
        integration_list.remove_children()

        items = self._build_integration_list_items()
        for item in items:
            integration_list.mount(item)

    def _close_settings(self) -> None:
        for card in self.query("#settings-card"):
            card.remove()

        self.show_settings = False

        # Update the menu hint to reflect current API key status
        self._update_menu_hint()

        # Return focus to the main menu list
        if self.show_menu and self.query("#menu-options"):
            menu = self.query_one("#menu-options", ListView)
            if menu.index is None:
                menu.index = 0
            menu.focus()
            self._refresh_menu_prefixes()

    def _update_menu_hint(self) -> None:
        """Update the menu hint text and styling based on API key status."""
        if not self.query("#menu-hint"):
            return

        hint = self.query_one("#menu-hint", Static)
        hint.update(self._get_menu_hint())

        # Update styling based on API key status
        is_configured = self._is_api_key_configured()
        hint.set_class(not is_configured, "-warning")
        hint.set_class(is_configured, "-ready")

    def _save_settings(self) -> None:
        api_key_input = self.query_one("#api-key-input", PasteableInput)

        provider_value = self._provider
        if self.query("#provider-options"):
            providers = self.query_one("#provider-options", ListView)
            idx = providers.index if providers.index is not None else 0
            if 0 <= idx < len(self._SETTINGS_PROVIDER_VALUES):
                provider_value = self._SETTINGS_PROVIDER_VALUES[idx]

        new_api_key = api_key_input.value

        # Check if API key is required for the selected provider
        api_key_required = provider_value not in ("remote",)  # Ollama doesn't need API key

        if api_key_required and not new_api_key:
            # Require API key input - don't fall back to env vars
            provider_name = self._PROVIDER_API_KEY_NAMES.get(provider_value, provider_value)
            self.notify(
                f"API key required for {provider_name}. Please enter an API key or press Cancel.",
                severity="error",
                timeout=4,
            )
            return

        self._provider = provider_value
        self._api_key = new_api_key

        # Save the API key for this provider (so it persists when switching providers)
        if self._api_key:
            self._saved_api_keys[self._provider] = self._api_key

        # Persist settings to settings.json (also syncs to os.environ)
        if self._api_key:
            save_settings_to_json(self._provider, self._api_key)
            self.notify("Settings saved!", severity="information", timeout=2)
        else:
            self.notify("Settings saved (using existing API key)", severity="information", timeout=2)

        self._close_settings()

    def _start_chat(self) -> None:
        # Check if API key is required and configured
        api_key_required = self._provider not in ("remote",)  # Ollama doesn't need API key

        if api_key_required:
            # Check local setting first, then settings.json/environment
            effective_api_key = self._api_key or get_api_key_for_provider(self._provider)

            if not effective_api_key:
                self.notify(
                    f"API key required! Please configure your {self._PROVIDER_API_KEY_NAMES.get(self._provider, self._provider)} API key in Settings.",
                    severity="error",
                    timeout=5,
                )
                return

        # Check if we need to reinitialize BEFORE updating the provider:
        # 1. LLM not initialized yet, OR
        # 2. Provider has changed from what's currently configured
        current_provider = self._interface._agent.llm.provider
        needs_reinit = (
            not self._interface._agent.is_llm_initialized or
            current_provider != self._provider
        )

        # Configure provider (updates environment variables)
        self._interface.configure_provider(self._provider, self._api_key)

        if needs_reinit:
            success = self._interface._agent.reinitialize_llm(self._provider)
            if not success:
                self.notify(
                    f"Failed to initialize LLM. Please check your API key in Settings.",
                    severity="error",
                    timeout=5,
                )
                return

        self._close_settings()
        self.show_menu = False
        self._interface.notify_provider(self._provider)

        # Note: Soft onboarding is triggered by the agent in run() before
        # the interface starts. See agent_base.py.

    async def _launch_hard_onboarding(self) -> None:
        """Launch the hard onboarding wizard screen."""
        from app.tui.onboarding.hard_onboarding import TUIHardOnboarding
        from app.tui.onboarding.widgets import OnboardingWizardScreen

        handler = TUIHardOnboarding(self)
        screen = OnboardingWizardScreen(handler)
        await self.push_screen(screen)

    # Note: Soft onboarding is triggered by the agent in run() before
    # the interface starts. Interfaces should not contain agent logic.

    async def on_mount(self) -> None:  # pragma: no cover - UI lifecycle
        self.query_one("#chat-panel").border_title = "Chat"
        self.query_one("#action-panel").border_title = "Action"
        self.query_one("#vm-footage-panel").border_title = "VM Footage"

        # Runtime safeguard: enforce wrapping on the logs even if CSS/props vary by version
        chat_log = self.query_one("#chat-log", ConversationLog)
        action_log = self.query_one("#action-log", ConversationLog)

        chat_log.styles.text_wrap = "wrap"
        action_log.styles.text_wrap = "wrap"
        chat_log.styles.text_overflow = "fold"
        action_log.styles.text_overflow = "fold"

        self.set_interval(0.1, self._flush_pending_updates)
        self.set_interval(0.2, self._tick_status_marquee)
        self.set_interval(0.5, self._tick_loading_animation)  # Loading icon animation
        self._sync_layers()

        # Initialize menu selection visuals and API key status
        if self.show_menu:
            menu = self.query_one("#menu-options", ListView)
            menu.index = 0
            menu.focus()
            self._refresh_menu_prefixes()
            self._update_menu_hint()

        # Check if hard onboarding is needed
        if onboarding_manager.needs_hard_onboarding:
            logger.info("[ONBOARDING] Hard onboarding needed, launching wizard")
            self.call_after_refresh(self._launch_hard_onboarding)

    def clear_logs(self) -> None:
        """Clear chat and action logs from the display."""

        chat_log = self.query_one("#chat-log", ConversationLog)
        action_log = self.query_one("#action-log", ConversationLog)
        chat_log.clear()
        action_log.clear()

    def watch_show_menu(self, show: bool) -> None:
        self._sync_layers()

    def watch_show_settings(self, show: bool) -> None:
        # Hide / show the main menu panel when settings are toggled
        if self.query("#menu-panel"):
            menu_panel = self.query_one("#menu-panel")
            menu_panel.set_class(show, "-hidden")

    def watch_gui_mode_active(self, active: bool) -> None:
        """Handle GUI mode layout changes."""
        self._toggle_vm_footage_panel(active)

    def _toggle_vm_footage_panel(self, show: bool) -> None:
        """Show/hide the VM footage panel based on GUI mode."""
        footage_panel = self.query("#vm-footage-panel")
        if footage_panel:
            footage_panel.first().set_class(not show, "-hidden")
            if show:
                footage_panel.first().border_title = "VM Footage"

    def _sync_layers(self) -> None:
        menu_layer = self.query_one("#menu-layer")
        chat_layer = self.query_one("#chat-layer")
        menu_layer.set_class(self.show_menu is False, "-hidden")
        chat_layer.set_class(self.show_menu is True, "-hidden")

        if not self.show_menu:
            chat_input = self.query_one("#chat-input", PasteableInput)
            chat_input.focus()
            return

        # If settings are open, focus provider list first
        if self.show_settings and self.query("#provider-options"):
            providers = self.query_one("#provider-options", ListView)
            if providers.index is None:
                providers.index = 0
            providers.focus()
            self._refresh_provider_prefixes()
            self._refresh_settings_actions_prefixes()
            return

        # Menu visible: focus the list and refresh prefixes
        if self.query("#menu-options"):
            menu = self.query_one("#menu-options", ListView)
            if menu.index is None:
                menu.index = 0
            menu.focus()
            self._refresh_menu_prefixes()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        event.input.value = ""
        await self._interface.submit_user_message(message)

    async def action_quit(self) -> None:  # pragma: no cover - user-triggered
        await self._interface.request_shutdown()
        await super().action_quit()

    def _flush_pending_updates(self) -> None:
        chat_log = self.query_one("#chat-log", ConversationLog)
        action_log = self.query_one("#action-log", ConversationLog)
        while True:
            try:
                label, message, style = self._interface.chat_updates.get_nowait()
            except QueueEmpty:
                break
            entry = self._interface.format_chat_entry(label, message, style)
            chat_log.append_renderable(entry)

        while True:
            try:
                action_update = self._interface.action_updates.get_nowait()
            except QueueEmpty:
                break

            if action_update.operation == "clear":
                action_log.clear()
            elif action_update.operation == "add":
                item = action_update.item
                if self._interface._selected_task_id:
                    # In detail view: refresh if action belongs to selected task
                    if item.item_type == "action" and item.task_id == self._interface._selected_task_id:
                        self._refresh_action_panel()
                else:
                    # In main view: only show tasks
                    if item.item_type == "task":
                        renderable = self._interface.format_action_item(item)
                        action_log.append_renderable(renderable, entry_key=item.id)
            elif action_update.operation == "update":
                item = action_update.item
                if item and item.id in self._interface._action_items:
                    if self._interface._selected_task_id:
                        # In detail view: refresh if action belongs to selected task
                        if item.task_id == self._interface._selected_task_id or item.id == self._interface._selected_task_id:
                            self._refresh_action_panel()
                    else:
                        # In main view: only update tasks
                        if item.item_type == "task":
                            renderable = self._interface.format_action_item(item)
                            action_log.update_renderable(item.id, renderable)

        while True:
            try:
                status = self._interface.status_updates.get_nowait()
            except QueueEmpty:
                break
            self._set_status(status)

        # Process footage updates
        while True:
            try:
                footage_update = self._interface.footage_updates.get_nowait()
            except QueueEmpty:
                break

            # Activate GUI mode if not already active
            if not self.gui_mode_active:
                self.gui_mode_active = True

            # Update footage widget
            footage_widget = self.query_one("#vm-footage", VMFootageWidget)
            footage_widget.update_footage(footage_update.image_bytes)

        # Check if GUI mode ended
        if self._interface.gui_mode_ended():
            self.gui_mode_active = False
            footage_widget = self.query_one("#vm-footage", VMFootageWidget)
            footage_widget.clear_footage()

    async def on_shutdown_request(self, event: events.ShutdownRequest) -> None:
        await self._interface.request_shutdown()

    def _set_status(self, status: str) -> None:
        self._status_message = status
        self._status_offset = 0
        self._status_pause = self._STATUS_INITIAL_PAUSE
        self._render_status()

    def _tick_status_marquee(self) -> None:
        status_bar = self.query_one("#status-bar", Static)
        width = status_bar.size.width or self.size.width or (
            len(self._STATUS_PREFIX) + len(self._status_message)
        )
        available = max(0, width - len(self._STATUS_PREFIX))

        if available <= 0 or len(self._status_message) <= available:
            self._status_offset = 0
            self._status_pause = self._STATUS_INITIAL_PAUSE
        else:
            if self._status_pause > 0:
                self._status_pause -= 1
            else:
                scroll_span = len(self._status_message) + self._STATUS_GAP
                self._status_offset = (self._status_offset + 1) % scroll_span
                if self._status_offset == 0:
                    self._status_pause = self._STATUS_INITIAL_PAUSE

        self._render_status()

    def _tick_loading_animation(self) -> None:
        """Update loading animation frame and refresh action panel."""
        self._interface._loading_frame_index = (self._interface._loading_frame_index + 1) % len(self.ICON_LOADING_FRAMES)

        # Re-render running items visible in current view
        action_log = self.query_one("#action-log", ConversationLog)

        if self._interface._selected_task_id:
            # In detail view: update running actions for selected task
            task_item = self._interface._action_items.get(self._interface._selected_task_id)
            if task_item and task_item.status == "running":
                # Refresh the whole panel to update the header
                self._refresh_action_panel()
            else:
                # Just update running actions
                actions = self._interface.get_actions_for_task(self._interface._selected_task_id)
                for action in actions:
                    if action.status == "running":
                        renderable = self._interface.format_action_item(action)
                        action_log.update_renderable(action.id, renderable)
        else:
            # In main view: update running tasks
            for task in self._interface.get_task_items():
                if task.status == "running":
                    renderable = self._interface.format_action_item(task)
                    action_log.update_renderable(task.id, renderable)

        # Update status bar if agent is working (to animate the loading icon)
        if self._interface._agent_state == "working":
            new_status = self._interface._generate_status_message()
            if new_status != self._status_message:
                self._status_message = new_status
                self._render_status()

    def _render_status(self) -> None:
        status_bar = self.query_one("#status-bar", Static)
        width = status_bar.size.width or self.size.width or (
            len(self._STATUS_PREFIX) + len(self._status_message)
        )
        available = max(0, width - len(self._STATUS_PREFIX))
        visible = self._visible_status_content(available)
        full_text = f"{self._STATUS_PREFIX}{visible}"

        if full_text == self._last_rendered_status:
            return

        self.status_text = full_text
        status_bar.update(Text(full_text, no_wrap=True, overflow="crop"))
        self._last_rendered_status = full_text

    def _visible_status_content(self, available: int) -> str:
        if available <= 0:
            return ""
        message = self._status_message
        if len(message) <= available:
            return message

        scroll_span = len(message) + self._STATUS_GAP
        start = self._status_offset % scroll_span
        extended = message + " " * self._STATUS_GAP

        segment_chars = []
        for idx in range(available):
            segment_chars.append(extended[(start + idx) % scroll_span])
        return "".join(segment_chars)

    # ────────────────────────────── prompt-style prefix helpers ─────────────────────────────

    def _refresh_menu_prefixes(self) -> None:
        if not self.query("#menu-options"):
            return

        menu = self.query_one("#menu-options", ListView)
        if menu.index is None:
            menu.index = 0

        for idx, (item_id, text) in enumerate(self._MENU_ITEMS):
            item = self.query_one(f"#{item_id}", ListItem)
            label = item.query_one(Label)
            prefix = "> " if idx == menu.index else "  "
            label.update(f"{prefix}{text}")

    def _refresh_provider_prefixes(self) -> None:
        if not self.query("#provider-options"):
            return

        providers = self.query_one("#provider-options", ListView)
        items = list(providers.children)
        if not items:
            return

        if providers.index is None:
            providers.index = 0
        providers.index = max(0, min(providers.index, len(items) - 1))

        for idx, item in enumerate(items):
            label = item.query_one(Label) if item.query(Label) else None
            if label is None:
                continue
            text = (
                self._SETTINGS_PROVIDER_TEXTS[idx]
                if idx < len(self._SETTINGS_PROVIDER_TEXTS)
                else "provider"
            )
            prefix = "> " if idx == providers.index else "  "
            label.update(f"{prefix}{text}")

    def _refresh_settings_actions_prefixes(self) -> None:
        if not self.query("#settings-actions-list"):
            return

        actions = self.query_one("#settings-actions-list", ListView)
        items = list(actions.children)
        if not items:
            return

        if actions.index is None:
            actions.index = 0
        actions.index = max(0, min(actions.index, len(items) - 1))

        for idx, item in enumerate(items):
            label = item.query_one(Label) if item.query(Label) else None
            if label is None:
                continue
            text = self._SETTINGS_ACTION_TEXTS[idx] if idx < len(self._SETTINGS_ACTION_TEXTS) else "action"
            prefix = "> " if idx == actions.index else "  "
            label.update(f"{prefix}{text}")

    def _init_settings_provider_selection(self) -> None:
        try:
            if not self.query("#provider-options"):
                return

            providers = self.query_one("#provider-options", ListView)
            items = list(providers.children)
            if not items:
                return

            initial_index = 0
            for i, value in enumerate(self._SETTINGS_PROVIDER_VALUES):
                if value == self._provider:
                    initial_index = i
                    break

            initial_index = min(initial_index, len(items) - 1)
            providers.index = initial_index

            # Initialize action list selection
            if self.query("#settings-actions-list"):
                actions = self.query_one("#settings-actions-list", ListView)
                if actions.index is None:
                    actions.index = 0

            # Apply prefixes after refresh
            self._refresh_provider_prefixes()
            self._refresh_settings_actions_prefixes()

            # Focus provider list by default
            providers.focus()
        finally:
            # Always enable provider change events after initialization
            self._settings_init_complete = True

    # ────────────────────────────── list events ─────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "menu-options":
            self._refresh_menu_prefixes()
        elif event.list_view.id == "provider-options":
            self._refresh_provider_prefixes()
            self._on_provider_selection_changed()
        elif event.list_view.id == "settings-actions-list":
            self._refresh_settings_actions_prefixes()

    def _on_provider_selection_changed(self) -> None:
        """Handle provider selection change in settings."""
        # Skip during initialization to prevent auto-highlight from changing state
        if not self._settings_init_complete:
            return

        if not self.query("#provider-options"):
            return

        providers = self.query_one("#provider-options", ListView)
        idx = providers.index if providers.index is not None else 0
        if idx >= len(self._SETTINGS_PROVIDER_VALUES):
            return

        new_provider = self._SETTINGS_PROVIDER_VALUES[idx]
        if new_provider == self._settings_provider:
            return

        # Provider changed
        self._settings_provider = new_provider

        # Update API key label
        if self.query("#api-key-label"):
            provider_name = self._PROVIDER_API_KEY_NAMES.get(new_provider, new_provider)
            self.query_one("#api-key-label", Static).update(f"API Key for {provider_name}")

        # Update model display
        if self.query("#model-display"):
            model_name = self._get_model_for_provider(new_provider)
            self.query_one("#model-display", Static).update(f"Model: {model_name}")

        # Reset API key input if there's no saved key for this provider
        if self.query("#api-key-input"):
            api_key_input = self.query_one("#api-key-input", PasteableInput)
            saved_key = self._saved_api_keys.get(new_provider, "")
            api_key_input.value = saved_key

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        list_id = event.list_view.id

        if list_id == "menu-options":
            item_id = event.item.id
            if item_id == "menu-start":
                self._start_chat()
            elif item_id == "menu-settings":
                self._open_settings()
            elif item_id == "menu-exit":
                self.exit()
            return

        if list_id == "settings-actions-list":
            # In settings, treat this list like buttons.
            # Index 0 = save, 1 = cancel
            actions = event.list_view
            idx = actions.index if actions.index is not None else 0
            if idx == 0:
                self._save_settings()
            else:
                self._close_settings()
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        button_id = event.button.id

        # Handle settings tab switching
        if button_id == "tab-btn-models":
            self._switch_settings_section("models")
            return
        elif button_id == "tab-btn-mcp":
            self._switch_settings_section("mcp")
            return
        elif button_id == "tab-btn-skills":
            self._switch_settings_section("skills")
            return
        elif button_id == "tab-btn-integrations":
            self._switch_settings_section("integrations")
            return

        # Handle MCP server remove buttons
        if button_id and button_id.startswith("mcp-remove-"):
            safe_id = button_id[11:]  # Remove "mcp-remove-" prefix
            server_name = getattr(self, '_mcp_id_to_name', {}).get(safe_id, safe_id)
            success, message = remove_mcp_server(server_name)
            if success:
                self.notify(message, severity="information", timeout=2)
                self._refresh_mcp_server_list()
            else:
                self.notify(message, severity="error", timeout=3)

        # Handle MCP server config buttons
        if button_id and button_id.startswith("mcp-config-"):
            safe_id = button_id[11:]  # Remove "mcp-config-" prefix
            server_name = getattr(self, '_mcp_id_to_name', {}).get(safe_id, safe_id)
            self._open_mcp_env_editor(server_name)

        # Handle MCP server enable buttons
        if button_id and button_id.startswith("mcp-enable-"):
            safe_id = button_id[11:]  # Remove "mcp-enable-" prefix
            server_name = getattr(self, '_mcp_id_to_name', {}).get(safe_id, safe_id)
            success, message = enable_mcp_server(server_name)
            if success:
                self.notify(message, severity="information", timeout=2)
                self._refresh_mcp_server_list()
            else:
                self.notify(message, severity="error", timeout=3)

        # Handle MCP server disable buttons
        if button_id and button_id.startswith("mcp-disable-"):
            safe_id = button_id[12:]  # Remove "mcp-disable-" prefix
            server_name = getattr(self, '_mcp_id_to_name', {}).get(safe_id, safe_id)
            success, message = disable_mcp_server(server_name)
            if success:
                self.notify(message, severity="information", timeout=2)
                self._refresh_mcp_server_list()
            else:
                self.notify(message, severity="error", timeout=3)

        # Handle MCP add button
        if button_id == "mcp-add-btn":
            self._handle_mcp_add_button()

        # Handle MCP env editor buttons
        if button_id == "mcp-env-save":
            self._save_mcp_env()
        elif button_id == "mcp-env-cancel":
            self._close_mcp_env_editor()

        # Handle Skill enable buttons
        if button_id and button_id.startswith("skill-enable-"):
            safe_id = button_id[13:]  # Remove "skill-enable-" prefix
            skill_name = getattr(self, '_skill_id_to_name', {}).get(safe_id, safe_id)
            success, message = enable_skill(skill_name)
            if success:
                self.notify(message, severity="information", timeout=2)
                self._refresh_skill_list()
            else:
                self.notify(message, severity="error", timeout=3)

        # Handle Skill disable buttons
        if button_id and button_id.startswith("skill-disable-"):
            safe_id = button_id[14:]  # Remove "skill-disable-" prefix
            skill_name = getattr(self, '_skill_id_to_name', {}).get(safe_id, safe_id)
            success, message = disable_skill(skill_name)
            if success:
                self.notify(message, severity="information", timeout=2)
                self._refresh_skill_list()
            else:
                self.notify(message, severity="error", timeout=3)

        # Handle Skill install button
        if button_id == "skill-install-btn":
            self._handle_skill_install_button()

        # Handle Skill view buttons
        if button_id and button_id.startswith("skill-view-"):
            safe_id = button_id[11:]  # Remove "skill-view-" prefix
            skill_name = getattr(self, '_skill_id_to_name', {}).get(safe_id, safe_id)
            self._open_skill_detail_viewer(skill_name)

        # Handle Skill detail buttons
        if button_id == "skill-detail-close":
            self._close_skill_detail_viewer()
        elif button_id == "skill-detail-copy":
            self._copy_skill_content()
        elif button_id == "skill-detail-status-btn":
            self._toggle_skill_from_detail_viewer()

        # Handle Integration connect buttons
        if button_id and button_id.startswith("integ-connect-"):
            safe_id = button_id[14:]  # Remove "integ-connect-" prefix
            integration_id = getattr(self, '_integ_id_to_name', {}).get(safe_id, safe_id)
            self._open_integration_connect_modal(integration_id)

        # Handle Integration view buttons
        if button_id and button_id.startswith("integ-view-"):
            safe_id = button_id[11:]  # Remove "integ-view-" prefix
            integration_id = getattr(self, '_integ_id_to_name', {}).get(safe_id, safe_id)
            self._open_integration_detail_viewer(integration_id)

        # Handle Integration disconnect buttons
        if button_id and button_id.startswith("integ-disconnect-"):
            safe_id = button_id[17:]  # Remove "integ-disconnect-" prefix
            integration_id = getattr(self, '_integ_id_to_name', {}).get(safe_id, safe_id)
            self._disconnect_integration(integration_id)

        # Handle Integration modal buttons
        if button_id == "integ-modal-save":
            self._save_integration_connect()
        elif button_id == "integ-modal-cancel":
            self._close_integration_connect_modal()
        elif button_id == "integ-modal-oauth":
            self._start_oauth_connect()
        elif button_id == "integ-modal-interactive-connect":
            self._start_interactive_connect()
        elif button_id == "oauth-waiting-cancel":
            self._cancel_oauth_connect()

        # Handle Integration detail viewer buttons
        if button_id == "integ-detail-close":
            self._close_integration_detail_viewer()
        elif button_id == "integ-detail-add":
            # Get the integration ID from the stored state
            if hasattr(self, "_integ_detail_current_id"):
                self._open_integration_connect_modal(self._integ_detail_current_id)
                self._close_integration_detail_viewer()

        # Handle per-account disconnect buttons in detail viewer
        if button_id and button_id.startswith("integ-account-disconnect-"):
            # Format: integ-account-disconnect-{safe_integ_id}-{safe_acc_id}
            safe_key = button_id[25:]  # Remove prefix
            # Look up the original IDs from the mapping
            original_ids = getattr(self, '_integ_account_id_to_name', {}).get(safe_key, safe_key)
            if "|" in original_ids:
                integration_id, account_id = original_ids.split("|", 1)
                self._disconnect_integration_account(integration_id, account_id)
            else:
                # Fallback to old split logic for compatibility
                parts = safe_key.split("-", 1)
                if len(parts) == 2:
                    integration_id, account_id = parts
                    self._disconnect_integration_account(integration_id, account_id)

    def _switch_settings_section(self, section: str) -> None:
        """Switch between Models, MCP, Skills, and Integrations sections in settings."""
        # Update button styles
        models_btn = self.query_one("#tab-btn-models", Button)
        mcp_btn = self.query_one("#tab-btn-mcp", Button)
        skills_btn = self.query_one("#tab-btn-skills", Button)
        integrations_btn = self.query_one("#tab-btn-integrations", Button)

        # Reset all buttons
        models_btn.remove_class("-active")
        mcp_btn.remove_class("-active")
        skills_btn.remove_class("-active")
        integrations_btn.remove_class("-active")

        # Activate the selected tab
        if section == "models":
            models_btn.add_class("-active")
        elif section == "mcp":
            mcp_btn.add_class("-active")
        elif section == "skills":
            skills_btn.add_class("-active")
        elif section == "integrations":
            integrations_btn.add_class("-active")

        # Show/hide sections
        models_section = self.query_one("#section-models", Container)
        mcp_section = self.query_one("#section-mcp", Container)
        skills_section = self.query_one("#section-skills", Container)
        integrations_section = self.query_one("#section-integrations", Container)

        # Hide all sections first
        models_section.add_class("-hidden")
        mcp_section.add_class("-hidden")
        skills_section.add_class("-hidden")
        integrations_section.add_class("-hidden")

        # Show the selected section
        if section == "models":
            models_section.remove_class("-hidden")
        elif section == "mcp":
            mcp_section.remove_class("-hidden")
        elif section == "skills":
            skills_section.remove_class("-hidden")
        elif section == "integrations":
            integrations_section.remove_class("-hidden")

    def _open_mcp_env_editor(self, server_name: str) -> None:
        """Open a modal to edit environment variables for an MCP server."""
        env_vars = get_server_env_vars(server_name)

        if not env_vars:
            self.notify(f"No environment variables for '{server_name}'", severity="information", timeout=2)
            return

        # Remove any existing env editor overlay
        for overlay in self.query("#mcp-env-overlay"):
            overlay.remove()

        # Build input fields for each env var
        env_inputs = []
        for key, value in env_vars.items():
            env_inputs.append(Static(key, classes="mcp-env-label"))
            env_inputs.append(
                PasteableInput(
                    placeholder=f"Enter {key}",
                    value=value,
                    password=False,
                    id=f"mcp-env-{key}",
                    classes="mcp-env-input",
                )
            )

        # Create an overlay container with the editor inside
        overlay = Container(
            Container(
                Static(f"Configure {server_name}", id="mcp-env-title"),
                Vertical(*env_inputs, id="mcp-env-fields"),
                Horizontal(
                    Button("Save", id="mcp-env-save", classes="mcp-env-btn"),
                    Button("Cancel", id="mcp-env-cancel", classes="mcp-env-btn"),
                    id="mcp-env-actions",
                ),
                id="mcp-env-editor",
            ),
            id="mcp-env-overlay",
        )

        # Store the server name for saving
        self._mcp_env_editing_server = server_name

        self.mount(overlay)

    def _save_mcp_env(self) -> None:
        """Save the edited environment variables."""
        if not hasattr(self, "_mcp_env_editing_server"):
            return

        server_name = self._mcp_env_editing_server
        env_vars = get_server_env_vars(server_name)

        for key in env_vars.keys():
            input_id = f"#mcp-env-{key}"
            if self.query(input_id):
                input_widget = self.query_one(input_id, PasteableInput)
                new_value = input_widget.value
                if new_value != env_vars[key]:
                    update_mcp_server_env(server_name, key, new_value)

        self.notify(f"Saved environment variables for '{server_name}'", severity="information", timeout=2)
        self._close_mcp_env_editor()
        self._refresh_mcp_server_list()

    def _close_mcp_env_editor(self) -> None:
        """Close the env editor modal."""
        for overlay in self.query("#mcp-env-overlay"):
            overlay.remove()
        if hasattr(self, "_mcp_env_editing_server"):
            del self._mcp_env_editing_server

    def _open_skill_detail_viewer(self, skill_name: str) -> None:
        """Open a modal to view skill details and full SKILL.md content."""
        skill_info = get_skill_info(skill_name)
        if not skill_info:
            self.notify(f"Skill '{skill_name}' not found", severity="error", timeout=2)
            return

        # Remove any existing skill detail overlay
        for overlay in self.query("#skill-detail-overlay"):
            overlay.remove()

        # Get the raw SKILL.md content
        raw_content = get_skill_raw_content(skill_name)
        if not raw_content:
            raw_content = skill_info.get("instructions", "No instructions available")

        # Store raw content for copy functionality and skill name for toggling
        self._skill_detail_raw_content = raw_content
        self._skill_detail_current_name = skill_name

        # Build status button with colored dot
        is_enabled = skill_info["enabled"]
        status_dot = "●"  # Unicode bullet
        status_text = f"{status_dot} Enabled" if is_enabled else f"{status_dot} Disabled"

        # Build action sets display
        action_sets = ", ".join(skill_info.get("action_sets", [])) or "None"
        action_sets_text = f"Action Sets: {action_sets}"

        # Create the overlay with title row layout
        overlay = Container(
            Container(
                # Header section (fixed)
                Container(
                    # Title row: skill name on left, status button on right
                    Horizontal(
                        Static(f"Skill: {skill_name}", id="skill-detail-title"),
                        Button(status_text, id="skill-detail-status-btn"),
                        id="skill-detail-title-row",
                    ),
                    Static(skill_info["description"], id="skill-detail-desc"),
                    Static(action_sets_text, id="skill-detail-action-sets"),
                    id="skill-detail-header",
                ),
                # Scrollable content
                VerticalScroll(
                    Static(raw_content),
                    id="skill-detail-content",
                ),
                # Action buttons (fixed at bottom)
                Horizontal(
                    Button("Copy", id="skill-detail-copy", classes="skill-detail-btn -copy"),
                    Button("Close", id="skill-detail-close", classes="skill-detail-btn"),
                    id="skill-detail-actions",
                ),
                id="skill-detail-viewer",
            ),
            id="skill-detail-overlay",
        )

        self.mount(overlay)

        # Apply inline color to status button (CSS classes don't reliably override Button defaults)
        if self.query("#skill-detail-status-btn"):
            status_btn = self.query_one("#skill-detail-status-btn", Button)
            status_btn.styles.color = "#00cc00" if is_enabled else "#ff4f18"

    def _close_skill_detail_viewer(self) -> None:
        """Close the skill detail viewer modal."""
        for overlay in self.query("#skill-detail-overlay"):
            overlay.remove()
        if hasattr(self, "_skill_detail_raw_content"):
            del self._skill_detail_raw_content
        if hasattr(self, "_skill_detail_current_name"):
            del self._skill_detail_current_name

    def _toggle_skill_from_detail_viewer(self) -> None:
        """Toggle the skill status from within the detail viewer."""
        if not hasattr(self, "_skill_detail_current_name"):
            return

        skill_name = self._skill_detail_current_name
        success, message = toggle_skill(skill_name)

        if success:
            self.notify(message, severity="information", timeout=2)
            # Refresh the skill list in settings
            self._refresh_skill_list()
            # Close then reopen to show updated status (avoid duplicate ID)
            for overlay in self.query("#skill-detail-overlay"):
                overlay.remove()
            # Use call_after_refresh to ensure DOM is updated before reopening
            self.call_after_refresh(lambda: self._open_skill_detail_viewer(skill_name))
        else:
            self.notify(message, severity="error", timeout=3)

    def _copy_skill_content(self) -> None:
        """Copy the skill SKILL.md content to clipboard."""
        if not hasattr(self, "_skill_detail_raw_content"):
            self.notify("No content to copy", severity="error", timeout=2)
            return

        try:
            import pyperclip
            pyperclip.copy(self._skill_detail_raw_content)
            self.notify("Copied to clipboard!", severity="information", timeout=2)
        except ImportError:
            # Fallback: try using the system clipboard via subprocess
            try:
                import subprocess
                import sys
                if sys.platform == "win32":
                    subprocess.run(["clip"], input=self._skill_detail_raw_content.encode("utf-8"), check=True)
                    self.notify("Copied to clipboard!", severity="information", timeout=2)
                elif sys.platform == "darwin":
                    subprocess.run(["pbcopy"], input=self._skill_detail_raw_content.encode("utf-8"), check=True)
                    self.notify("Copied to clipboard!", severity="information", timeout=2)
                else:
                    # Linux - try xclip or xsel
                    try:
                        subprocess.run(["xclip", "-selection", "clipboard"], input=self._skill_detail_raw_content.encode("utf-8"), check=True)
                        self.notify("Copied to clipboard!", severity="information", timeout=2)
                    except FileNotFoundError:
                        subprocess.run(["xsel", "--clipboard", "--input"], input=self._skill_detail_raw_content.encode("utf-8"), check=True)
                        self.notify("Copied to clipboard!", severity="information", timeout=2)
            except Exception as e:
                self.notify(f"Could not copy: {e}", severity="error", timeout=3)

    # =========================================================================
    # Task Detail View Methods (in-panel navigation, not overlay)
    # =========================================================================

    def on_task_selected(self, event: TaskSelected) -> None:
        """Handle task click from action panel."""
        # Check if this is the back button
        if event.task_id == "action-panel-back":
            self._show_task_list_view()
            return

        # Otherwise, show actions for this task
        self._show_task_actions_view(event.task_id)

    def _show_task_actions_view(self, task_id: str) -> None:
        """Switch action panel to show actions for a specific task."""
        task_item = self._interface._action_items.get(task_id)
        if not task_item or task_item.item_type != "task":
            return

        self._interface._selected_task_id = task_id
        self._refresh_action_panel()

    def _show_task_list_view(self) -> None:
        """Switch action panel back to show task list."""
        self._interface._selected_task_id = None
        self._refresh_action_panel()

    def _refresh_action_panel(self) -> None:
        """Refresh the action panel based on current view mode."""
        action_log = self.query_one("#action-log", ConversationLog)
        action_log.clear()

        if self._interface._selected_task_id:
            # Detail view: show back button + actions for selected task
            task_item = self._interface._action_items.get(self._interface._selected_task_id)
            if task_item:
                # Add back button as first entry
                back_text = Text("< Back to tasks", style="bold #ff4f18")
                action_log.append_renderable(back_text, entry_key="action-panel-back")

                # Add task name as header
                status_icon = self.ICON_COMPLETED if task_item.status == "completed" else (
                    self.ICON_ERROR if task_item.status == "error" else
                    self.ICON_LOADING_FRAMES[self._interface._loading_frame_index % len(self.ICON_LOADING_FRAMES)]
                )
                header_text = Text(f"[{status_icon}] {task_item.display_name}", style="bold #ffffff")
                action_log.append_renderable(header_text)

                # Add actions for this task
                actions = self._interface.get_actions_for_task(self._interface._selected_task_id)
                for action in sorted(actions, key=lambda a: a.created_at):
                    renderable = self._interface.format_action_item(action)
                    action_log.append_renderable(renderable, entry_key=action.id)

                if not actions:
                    empty_text = Text("  No actions recorded yet", style="italic #666666")
                    action_log.append_renderable(empty_text)
        else:
            # Main view: show only tasks
            for task in self._interface.get_task_items():
                renderable = self._interface.format_action_item(task)
                action_log.append_renderable(renderable, entry_key=task.id)

    def _refresh_task_detail_view(self) -> None:
        """Refresh the detail view with current actions."""
        if self._interface._selected_task_id:
            self._refresh_action_panel()

    # =========================================================================
    # Integration Settings Methods
    # =========================================================================

    def _open_integration_connect_modal(self, integration_id: str) -> None:
        """Open a modal to connect an integration."""
        info = get_integration_info(integration_id)
        if not info:
            self.notify(f"Integration '{integration_id}' not found", severity="error", timeout=2)
            return

        # Remove any existing modal
        for overlay in self.query("#integ-connect-overlay"):
            overlay.remove()

        # Store current integration ID for later
        self._integ_connect_current_id = integration_id

        auth_type = info["auth_type"]
        fields = info.get("fields", [])

        # Build modal content based on auth type
        if auth_type == "oauth":
            # OAuth-only: show browser button
            modal_content = Container(
                Static(f"Connect {info['name']}", id="integ-modal-title"),
                Static("This will open a browser window for authentication.", classes="integ-modal-desc"),
                Horizontal(
                    Button("Open Browser", id="integ-modal-oauth", classes="integ-modal-btn -primary"),
                    Button("Cancel", id="integ-modal-cancel", classes="integ-modal-btn"),
                    id="integ-modal-actions",
                ),
                id="integ-connect-modal",
            )
        elif auth_type == "interactive":
            # Interactive (like WhatsApp): show connect button that starts login flow
            modal_content = Container(
                Static(f"Connect {info['name']}", id="integ-modal-title"),
                Static("A browser window will open for you to scan the QR code.", classes="integ-modal-desc"),
                Horizontal(
                    Button("Connect", id="integ-modal-interactive-connect", classes="integ-modal-btn -primary"),
                    Button("Cancel", id="integ-modal-cancel", classes="integ-modal-btn"),
                    id="integ-modal-actions",
                ),
                id="integ-connect-modal",
            )
        elif auth_type == "both":
            # Has both OAuth (invite) and token entry
            is_bot_platform = integration_id in ("telegram", "discord")

            # Section 1: Invite/OAuth our shared bot (most common)
            invite_section = [
                Horizontal(
                    Button("Invite Bot" if is_bot_platform else "Use OAuth", id="integ-modal-oauth", classes="integ-modal-btn -primary"),
                    id="integ-modal-invite-actions",
                ),
            ]

            # Section 2: Manual bot token entry
            field_inputs = [
                Static("— or enter your own bot token —", classes="integ-modal-separator"),
            ]
            for field in fields:
                field_inputs.append(Static(field["label"], classes="integ-field-label"))
                field_inputs.append(
                    PasteableInput(
                        placeholder=field.get("placeholder", f"Enter {field['label']}"),
                        password=field.get("password", False),
                        id=f"integ-field-{field['key']}",
                        classes="integ-field-input",
                    )
                )
            field_inputs.append(
                Horizontal(
                    Button("Save", id="integ-modal-save", classes="integ-modal-btn -primary"),
                    id="integ-modal-save-actions",
                )
            )

            modal_content = Container(
                Static(f"Connect {info['name']}", id="integ-modal-title"),
                VerticalScroll(*invite_section, *field_inputs, id="integ-modal-fields"),
                Horizontal(
                    Button("Cancel", id="integ-modal-cancel", classes="integ-modal-btn"),
                    id="integ-modal-actions",
                ),
                id="integ-connect-modal",
            )
        elif auth_type == "token_with_interactive":
            # Has both token entry and interactive (QR) login
            # Section 1: Manual bot token entry
            field_inputs = []
            for field in fields:
                field_inputs.append(Static(field["label"], classes="integ-field-label"))
                field_inputs.append(
                    PasteableInput(
                        placeholder=field.get("placeholder", f"Enter {field['label']}"),
                        password=field.get("password", False),
                        id=f"integ-field-{field['key']}",
                        classes="integ-field-input",
                    )
                )
            field_inputs.append(
                Horizontal(
                    Button("Save", id="integ-modal-save", classes="integ-modal-btn -primary"),
                    id="integ-modal-save-actions",
                )
            )

            # Section 2: Interactive login (QR scan) for user account
            link_section = [
                Static("— or link your personal account —", classes="integ-modal-separator"),
                Horizontal(
                    Button("Link Account (QR)", id="integ-modal-interactive-connect", classes="integ-modal-btn -primary"),
                    id="integ-modal-link-actions",
                ),
            ]

            modal_content = Container(
                Static(f"Connect {info['name']}", id="integ-modal-title"),
                VerticalScroll(*field_inputs, *link_section, id="integ-modal-fields"),
                Horizontal(
                    Button("Cancel", id="integ-modal-cancel", classes="integ-modal-btn"),
                    id="integ-modal-actions",
                ),
                id="integ-connect-modal",
            )
        else:
            # Token-only: show input fields
            field_inputs = []
            for field in fields:
                field_inputs.append(Static(field["label"], classes="integ-field-label"))
                field_inputs.append(
                    PasteableInput(
                        placeholder=field.get("placeholder", f"Enter {field['label']}"),
                        password=field.get("password", False),
                        id=f"integ-field-{field['key']}",
                        classes="integ-field-input",
                    )
                )

            modal_content = Container(
                Static(f"Connect {info['name']}", id="integ-modal-title"),
                Vertical(*field_inputs, id="integ-modal-fields"),
                Horizontal(
                    Button("Save", id="integ-modal-save", classes="integ-modal-btn -primary"),
                    Button("Cancel", id="integ-modal-cancel", classes="integ-modal-btn"),
                    id="integ-modal-actions",
                ),
                id="integ-connect-modal",
            )

        overlay = Container(modal_content, id="integ-connect-overlay")
        self.mount(overlay)

    async def _save_integration_connect_async(self, integration_id: str, credentials: dict) -> None:
        """Async helper to save integration credentials."""
        try:
            success, message = await connect_integration_token(integration_id, credentials)
            if success:
                self.notify(message, severity="information", timeout=3)
                self._close_integration_connect_modal()
                self._refresh_integration_list()
            else:
                self.notify(message, severity="error", timeout=4)
        except Exception as e:
            self.notify(f"Connection failed: {e}", severity="error", timeout=4)

    def _save_integration_connect(self) -> None:
        """Save the credentials from the connect modal."""
        if not hasattr(self, "_integ_connect_current_id"):
            return

        integration_id = self._integ_connect_current_id
        fields = get_integration_fields(integration_id)

        # Collect field values
        credentials = {}
        for field in fields:
            input_id = f"#integ-field-{field['key']}"
            if self.query(input_id):
                input_widget = self.query_one(input_id, PasteableInput)
                credentials[field["key"]] = input_widget.value

        # Run the connection asynchronously
        create_task(self._save_integration_connect_async(integration_id, credentials))

    def _close_integration_connect_modal(self) -> None:
        """Close the integration connect modal."""
        for overlay in self.query("#integ-connect-overlay"):
            overlay.remove()
        if hasattr(self, "_integ_connect_current_id"):
            del self._integ_connect_current_id

    async def _start_oauth_connect_async(self, integration_id: str) -> None:
        """Async helper to start OAuth flow in a background thread."""
        import asyncio
        import concurrent.futures

        logger.info(f"[TUI] _start_oauth_connect_async: starting for {integration_id}")
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        try:
            success, message = await loop.run_in_executor(
                executor,
                self._run_oauth_sync,
                integration_id
            )
            logger.info(f"[TUI] OAuth connect result: success={success}, message={message[:100]}")

            if hasattr(self, "_oauth_cancelled") and self._oauth_cancelled:
                self._oauth_cancelled = False
                return

            if success:
                self.notify(message, severity="information", timeout=3)
                self._refresh_integration_list()
            else:
                self.notify(message, severity="error", timeout=6)
        except concurrent.futures.CancelledError:
            self.notify("OAuth cancelled", severity="information", timeout=2)
        except Exception as e:
            logger.error(f"[TUI] OAuth connect exception: {e}", exc_info=True)
            self.notify(f"OAuth failed: {e}", severity="error", timeout=6)
        finally:
            executor.shutdown(wait=False)
            self._close_oauth_waiting_modal()

    def _run_oauth_sync(self, integration_id: str):
        """Synchronous wrapper to run OAuth flow in a thread."""
        import asyncio

        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(connect_integration_oauth(integration_id))
        finally:
            loop.close()

    def _start_oauth_connect(self) -> None:
        """Start OAuth flow for the current integration."""
        if not hasattr(self, "_integ_connect_current_id"):
            logger.warning("[TUI] _start_oauth_connect: no _integ_connect_current_id")
            return

        integration_id = self._integ_connect_current_id
        logger.info(f"[TUI] Starting OAuth connect for {integration_id}")

        # Close the connect modal
        self._close_integration_connect_modal()

        # Show a waiting modal with cancel button
        self._show_oauth_waiting_modal(integration_id)

        # Run OAuth asynchronously in background thread
        self._oauth_cancelled = False
        create_task(self._start_oauth_connect_async(integration_id))

    def _start_interactive_connect(self) -> None:
        """Start interactive connection flow (e.g. WhatsApp QR code scan)."""
        if not hasattr(self, "_integ_connect_current_id"):
            logger.warning("[TUI] _start_interactive_connect: no _integ_connect_current_id")
            return

        integration_id = self._integ_connect_current_id
        logger.info(f"[TUI] Starting interactive connect for {integration_id}")

        # Close the connect modal
        self._close_integration_connect_modal()

        # Show a waiting modal with QR scan instructions
        self._show_interactive_waiting_modal(integration_id)

        # Run login asynchronously in background thread
        self._oauth_cancelled = False
        create_task(self._start_interactive_connect_async(integration_id))

    def _show_interactive_waiting_modal(self, integration_id: str) -> None:
        """Show a modal while interactive login is in progress."""
        # Remove any existing waiting modal
        for overlay in self.query("#oauth-waiting-overlay"):
            overlay.remove()

        info = get_integration_info(integration_id)
        name = info["name"] if info else integration_id

        modal = Container(
            Container(
                Static(f"Connecting to {name}...", id="oauth-waiting-title"),
                Static("Scan the QR code that opened (check browser or terminal).", classes="oauth-waiting-desc"),
                Static("This window will update automatically when done.", classes="oauth-waiting-hint"),
                Horizontal(
                    Button("Cancel", id="oauth-waiting-cancel", classes="oauth-waiting-btn"),
                    id="oauth-waiting-actions",
                ),
                id="oauth-waiting-modal",
            ),
            id="oauth-waiting-overlay",
        )
        self.mount(modal)

    async def _start_interactive_connect_async(self, integration_id: str) -> None:
        """Async helper to start interactive login in a background thread."""
        import asyncio
        import concurrent.futures

        logger.info(f"[TUI] _start_interactive_connect_async: starting for {integration_id}")
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        try:
            success, message = await loop.run_in_executor(
                executor,
                self._run_interactive_sync,
                integration_id
            )
            logger.info(f"[TUI] Interactive connect result: success={success}, message={message[:100]}")

            if hasattr(self, "_oauth_cancelled") and self._oauth_cancelled:
                self._oauth_cancelled = False
                return

            if success:
                self.notify(message, severity="information", timeout=3)
                self._refresh_integration_list()
            else:
                self.notify(message, severity="error", timeout=6)
        except concurrent.futures.CancelledError:
            self.notify("Connection cancelled", severity="information", timeout=2)
        except Exception as e:
            logger.error(f"[TUI] Interactive connect exception: {e}", exc_info=True)
            self.notify(f"Connection failed: {e}", severity="error", timeout=6)
        finally:
            executor.shutdown(wait=False)
            self._close_oauth_waiting_modal()

    def _run_interactive_sync(self, integration_id: str):
        """Synchronous wrapper to run interactive login in a thread."""
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(connect_integration_interactive(integration_id))
        finally:
            loop.close()

    def _show_oauth_waiting_modal(self, integration_id: str) -> None:
        """Show a modal while OAuth is in progress with cancel option."""
        # Remove any existing waiting modal
        for overlay in self.query("#oauth-waiting-overlay"):
            overlay.remove()

        info = get_integration_info(integration_id)
        name = info["name"] if info else integration_id

        modal = Container(
            Container(
                Static(f"Connecting to {name}...", id="oauth-waiting-title"),
                Static("Complete the authentication in your browser.", classes="oauth-waiting-desc"),
                Static("This window will update automatically when done.", classes="oauth-waiting-hint"),
                Horizontal(
                    Button("Cancel", id="oauth-waiting-cancel", classes="oauth-waiting-btn"),
                    id="oauth-waiting-actions",
                ),
                id="oauth-waiting-modal",
            ),
            id="oauth-waiting-overlay",
        )
        self.mount(modal)

    def _close_oauth_waiting_modal(self) -> None:
        """Close the OAuth waiting modal."""
        for overlay in self.query("#oauth-waiting-overlay"):
            overlay.remove()

    def _cancel_oauth_connect(self) -> None:
        """Cancel the ongoing OAuth flow."""
        self._oauth_cancelled = True
        self._close_oauth_waiting_modal()
        self.notify("OAuth cancelled", severity="information", timeout=2)

    async def _disconnect_integration_async(self, integration_id: str, account_id: str = None) -> None:
        """Async helper to disconnect an integration."""
        try:
            success, message = await disconnect_integration(integration_id, account_id)
            if success:
                self.notify(message, severity="information", timeout=2)
                self._refresh_integration_list()
                # Close and reopen detail viewer to update if viewing
                if account_id and hasattr(self, "_integ_detail_current_id"):
                    self._close_integration_detail_viewer()
                    self.call_after_refresh(lambda: self._open_integration_detail_viewer(integration_id))
            else:
                self.notify(message, severity="error", timeout=3)
        except Exception as e:
            self.notify(f"Disconnect failed: {e}", severity="error", timeout=3)

    def _disconnect_integration(self, integration_id: str) -> None:
        """Disconnect the first account from an integration."""
        create_task(self._disconnect_integration_async(integration_id))

    def _disconnect_integration_account(self, integration_id: str, account_id: str) -> None:
        """Disconnect a specific account from an integration."""
        create_task(self._disconnect_integration_async(integration_id, account_id))

    def _open_integration_detail_viewer(self, integration_id: str) -> None:
        """Open a modal to view integration details and connected accounts."""
        info = get_integration_info(integration_id)
        if not info:
            self.notify(f"Integration '{integration_id}' not found", severity="error", timeout=2)
            return

        # Remove any existing detail overlay
        for overlay in self.query("#integ-detail-overlay"):
            overlay.remove()

        # Store current integration ID
        self._integ_detail_current_id = integration_id

        accounts = info.get("accounts", [])

        # Store mapping from sanitized account ID to original account ID for handlers
        self._integ_account_id_to_name: dict[str, str] = {}

        # Build account list
        account_items = []
        if accounts:
            for account in accounts:
                display = account.get("display", "Unknown")
                acc_id = account.get("id", "")
                # Sanitize IDs for use in widget IDs
                safe_integ_id = self._sanitize_id(integration_id)
                safe_acc_id = self._sanitize_id(acc_id)
                # Store mapping for reverse lookup
                self._integ_account_id_to_name[f"{safe_integ_id}-{safe_acc_id}"] = f"{integration_id}|{acc_id}"
                account_items.append(
                    Horizontal(
                        Static(f"  {display}", classes="integ-account-info"),
                        Button("x", id=f"integ-account-disconnect-{safe_integ_id}-{safe_acc_id}", classes="integ-account-disconnect-btn"),
                        classes="integ-account-row",
                    )
                )
        else:
            account_items.append(Static("  No accounts connected", classes="integ-account-empty"))

        # Build the detail viewer
        overlay = Container(
            Container(
                Static(f"{info['name']} - Connected Accounts", id="integ-detail-title"),
                Static(info["description"], id="integ-detail-desc"),
                VerticalScroll(*account_items, id="integ-detail-accounts"),
                Horizontal(
                    Button("Reconnect", id="integ-detail-add", classes="integ-detail-btn"),
                    Button("Close", id="integ-detail-close", classes="integ-detail-btn"),
                    id="integ-detail-actions",
                ),
                id="integ-detail-viewer",
            ),
            id="integ-detail-overlay",
        )

        self.mount(overlay)

    def _close_integration_detail_viewer(self) -> None:
        """Close the integration detail viewer modal."""
        for overlay in self.query("#integ-detail-overlay"):
            overlay.remove()
        if hasattr(self, "_integ_detail_current_id"):
            del self._integ_detail_current_id
