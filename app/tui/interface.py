"""Main TUI interface class for agent interaction."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from asyncio import Queue
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from app.logger import logger


def suppress_console_logging() -> None:
    """
    Suppress all console (stdout/stderr) logging handlers.

    This MUST be called before the TUI starts to prevent log messages
    from corrupting the Textual display. Any logging.basicConfig() calls
    in imported modules add StreamHandlers that output to stderr by default,
    which interferes with Textual's terminal rendering.
    """
    # Get the root logger
    root_logger = logging.getLogger()

    # Remove all StreamHandlers (console handlers) from root logger
    handlers_to_remove = []
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            # Check if it's outputting to stdout or stderr
            if handler.stream in (sys.stdout, sys.stderr):
                handlers_to_remove.append(handler)

    for handler in handlers_to_remove:
        root_logger.removeHandler(handler)

    # Also suppress any handlers on named loggers that might have been configured
    # by logging.basicConfig() or getLogger() calls in various modules
    for name in list(logging.Logger.manager.loggerDict.keys()):
        named_logger = logging.getLogger(name)
        handlers_to_remove = []
        for handler in named_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                if handler.stream in (sys.stdout, sys.stderr):
                    handlers_to_remove.append(handler)
        for handler in handlers_to_remove:
            named_logger.removeHandler(handler)

    # Set a NullHandler on root to prevent "No handler found" warnings
    # and prevent basicConfig from being called again
    if not root_logger.handlers:
        root_logger.addHandler(logging.NullHandler())


# Call suppression immediately on module import to catch early handlers
# This handles modules that call logging.basicConfig() at import time
suppress_console_logging()
from app.state.agent_state import STATE
from app.gui.handler import GUIHandler
from app.tui.app import CraftApp
from app.tui.data import TimelineEntry, ActionItem, ActionPanelUpdate, FootageUpdate
from app.tui.mcp_settings import (
    list_mcp_servers,
    add_mcp_server,
    add_mcp_server_from_json,
    add_mcp_server_from_template,
    remove_mcp_server,
    enable_mcp_server,
    disable_mcp_server,
    get_available_templates,
    get_template_env_vars,
    update_mcp_server_env,
)
from app.tui.skill_settings import (
    list_skills,
    get_skill_info,
    enable_skill,
    disable_skill,
    reload_skills,
    get_skill_search_directories,
    install_skill_from_path,
    install_skill_from_git,
    create_skill_scaffold,
    remove_skill,
)
from app.credentials.handlers import INTEGRATION_HANDLERS

if TYPE_CHECKING:
    from app.agent_base import AgentBase


class TUIInterface:
    """Asynchronous Textual TUI driver that feeds user prompts to the agent."""

    _STYLE_COLORS = {
        "user": "bold #ffffff",
        "agent": "bold #ff4f18",
        "action": "bold #a0a0a0",
        "task": "bold #ff4f18",
        "error": "bold #ff4f18",
        "info": "bold #666666",
        "system": "bold #a0a0a0",
    }

    _CHAT_LABEL_WIDTH = 7
    _ACTION_LABEL_WIDTH = 5  # Adjusted for icon format [+] or [●]/[○]

    # Internal actions that should not be displayed in the action panel
    # Note: task_end is NOT hidden - it shows as "Task completed" action in detail view
    HIDDEN_ACTIONS = {"task_start", "task_update_todos"}

    def __init__(
        self, agent: "AgentBase", *, default_provider: str, default_api_key: str
    ) -> None:
        self._agent = agent
        self._running: bool = False
        self._tracked_sessions: set[str] = set()
        self._seen_events: set[Tuple[str, str, str]] = set()
        self._status_message: str = "Agent is idle"
        self._app: CraftApp | None = None
        self._event_task: asyncio.Task[None] | None = None

        self._command_handlers: dict[str, Callable[[], Awaitable[None]]] = {}

        self.chat_updates: Queue[TimelineEntry] = Queue()
        self.action_updates: Queue[ActionPanelUpdate] = Queue()
        self.status_updates: Queue[str] = Queue()
        self.footage_updates: Queue[FootageUpdate] = Queue()
        self._gui_mode_ended_flag: bool = False
        self._last_gui_mode: bool = False

        # ─────────────────────────────────────────────────────────────────────
        # Action Panel State (Simplified Flat Structure)
        # ─────────────────────────────────────────────────────────────────────
        # Flat storage of all action items (tasks and actions)
        self._action_items: Dict[str, ActionItem] = {}  # id -> ActionItem
        self._action_order: List[str] = []              # Display order by id
        self._cached_streams: Dict[str, any] = {}       # Cache stream references to handle race condition
        self._loading_frame_index: int = 0              # Current frame of loading animation

        # Agent state tracking
        self._agent_state: str = "idle"  # idle, working, waiting_for_user, task_completed

        # Selected task for detail view (None = main view, task_id = detail view)
        self._selected_task_id: Optional[str] = None

        self._default_provider = default_provider
        self._default_api_key = default_api_key

        self._register_commands()

    def _register_commands(self) -> None:
        self._command_handlers = {
            "/exit": self._handle_exit_command,
            "/clear": self._handle_clear_command,
            "/reset": self._handle_reset_command,
            "/menu": self._handle_menu_command,
            "/help": self._handle_help_command,
        }

    # =====================================
    # Footage Methods
    # =====================================

    async def push_footage(self, image_bytes: bytes, container_id: str = "") -> None:
        """Push a new screenshot to the footage display."""
        update = FootageUpdate(
            image_bytes=image_bytes,
            timestamp=time.time(),
            container_id=container_id,
        )
        await self.footage_updates.put(update)

    def signal_gui_mode_end(self) -> None:
        """Signal that GUI mode has ended."""
        self._gui_mode_ended_flag = True

    def gui_mode_ended(self) -> bool:
        """Check if GUI mode has ended since last check."""
        if self._gui_mode_ended_flag:
            self._gui_mode_ended_flag = False
            return True
        return False

    async def _maybe_handle_command(self, message: str) -> bool:
        parts = message.split()
        command = parts[0].lower()

        # Handle /mcp command with subcommands
        if command == "/mcp":
            await self._handle_mcp_command(parts[1:])
            return True

        # Handle /skill command with subcommands
        if command == "/skill":
            await self._handle_skill_command(parts[1:])
            return True

        # Handle /cred command
        if command == "/cred":
            await self._handle_cred_command(parts[1:])
            return True

        # Handle per-integration commands (/google, /slack, /telegram, etc.)
        # Only check for integration commands if the input starts with "/"
        if command.startswith("/"):
            integration_name = command.lstrip("/")
            if integration_name in INTEGRATION_HANDLERS:
                await self._handle_integration_command(integration_name, parts[1:])
                return True

        handler = self._command_handlers.get(command)
        if handler:
            await handler()
            return True

        agent_command = self._agent.get_commands().get(command)
        if agent_command:
            result = await agent_command.handler()
            await self.chat_updates.put(
                (
                    "System",
                    result or f"Command '{command}' executed.",
                    "system",
                )
            )
            return True

        return False

    async def start(self) -> None:
        """Start the Textual TUI session and background consumers."""
        if self._running:
            return

        # CRITICAL: Suppress console logging BEFORE starting the TUI
        # This prevents log messages from corrupting the Textual display
        suppress_console_logging()

        self._running = True
        logger.debug("Starting Textual TUI interface. Press Ctrl+C to exit.")

        # Set footage callback on agent for GUI mode screen display
        self._agent._tui_footage_callback = self.push_footage
        # Also set on existing GUIModule if already created
        if GUIHandler.gui_module:
            GUIHandler.gui_module.set_tui_footage_callback(self.push_footage)

        await self.chat_updates.put(
            (
                "System",
                "CraftBot TUI ready. Type /help for more info and /exit to quit.",
                "system",
            )
        )
        await self.status_updates.put(self._status_message)

        trigger_consumer = asyncio.create_task(self._consume_triggers())
        self._event_task = asyncio.create_task(self._watch_events())

        self._app = CraftApp(self, self._default_provider, self._default_api_key)

        try:
            await self._app.run_async()
        finally:
            self._running = False
            self._agent.is_running = False

            trigger_consumer.cancel()
            try:
                await trigger_consumer
            except asyncio.CancelledError:  # pragma: no cover - event loop teardown
                pass

            if self._event_task:
                self._event_task.cancel()
                try:
                    await self._event_task
                except asyncio.CancelledError:  # pragma: no cover - event loop teardown
                    pass

    async def submit_user_message(self, message: str) -> None:
        """Handle chat input captured by the Textual app."""
        if not message:
            return

        if await self._maybe_handle_command(message):
            return

        # Display user message IMMEDIATELY - don't wait for event stream
        # This provides instant visual feedback while routing happens in background
        user_label = "You"  # Match _label_for_style() for "user" style
        await self.chat_updates.put((user_label, message, "user"))

        # Set state to working when user submits a message
        self._agent_state = "working"
        status = self._generate_status_message()
        self._status_message = status
        await self.status_updates.put(status)

        payload = {
            "text": message,
            "sender": {"id": "cli_user", "type": "user"},
            "gui_mode": False,
        }
        await self._agent._handle_chat_message(payload)

    def configure_provider(self, provider: str, api_key: str) -> None:
        """Configure environment variables for the selected provider.

        Note: This only sets environment variables. To actually switch providers,
        call agent.reinitialize_llm() after this.
        """
        key_lookup = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "byteplus": "BYTEPLUS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        key_name = key_lookup.get(provider)
        if key_name and api_key:
            os.environ[key_name] = api_key
        os.environ["LLM_PROVIDER"] = provider
        # Note: Don't set self._agent.llm.provider here as it creates inconsistent state.
        # The provider will be properly set when reinitialize_llm() is called.

    def notify_provider(self, provider: str) -> None:
        self.chat_updates.put_nowait(
            (
                "System",
                f"Launching agent with provider: {provider}",
                "system",
            )
        )

    async def request_shutdown(self) -> None:
        """Stop the interface and close the Textual application."""
        if not self._running:
            return

        self._running = False
        self._agent.is_running = False

        if self._app and self._app.is_running:
            self._app.exit()

    async def _handle_exit_command(self) -> None:
        await self.chat_updates.put(("System", "Session terminated by user.", "system"))
        self._agent_state = "idle"
        await self.status_updates.put("Agent is idle")
        await self.request_shutdown()

    async def _handle_menu_command(self) -> None:
        # Switch UI back to menu layer if the app is running
        if self._app:
            self._app.show_settings = False
            self._app.show_menu = True

        await self.chat_updates.put(("System", "Returned to menu.", "system"))
        self._agent_state = "idle"
        await self.status_updates.put("Agent is idle")

    async def _handle_help_command(self) -> None:
        help_text = self._build_help_text()
        await self.chat_updates.put(("System", help_text, "system"))

    async def _handle_mcp_command(self, args: list[str]) -> None:
        """Handle /mcp command with subcommands."""
        if not args:
            # Show help for /mcp command
            help_text = self._build_mcp_help_text()
            await self.chat_updates.put(("System", help_text, "system"))
            return

        subcommand = args[0].lower()

        if subcommand == "list":
            await self._mcp_list()
        elif subcommand == "add":
            if len(args) < 2:
                templates = get_available_templates()
                template_names = ", ".join(t["name"] for t in templates)
                await self.chat_updates.put(
                    ("System", f"Usage: /mcp add <template> or /mcp add <name> --transport <type> ...\nAvailable templates: {template_names}", "system")
                )
            elif "--transport" in args:
                # Custom server: /mcp add <name> --transport <type> ...
                await self._mcp_add_custom(args[1:])
            else:
                await self._mcp_add(args[1])
        elif subcommand == "add-json":
            if len(args) < 3:
                await self.chat_updates.put(("System", "Usage: /mcp add-json <name> '<json>'", "system"))
            else:
                name = args[1]
                json_str = " ".join(args[2:])
                await self._mcp_add_json(name, json_str)
        elif subcommand == "remove":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /mcp remove <server_name>", "system"))
            else:
                await self._mcp_remove(args[1])
        elif subcommand == "enable":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /mcp enable <server_name>", "system"))
            else:
                await self._mcp_enable(args[1])
        elif subcommand == "disable":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /mcp disable <server_name>", "system"))
            else:
                await self._mcp_disable(args[1])
        elif subcommand == "templates":
            await self._mcp_templates()
        elif subcommand == "env":
            if len(args) < 4:
                await self.chat_updates.put(
                    ("System", "Usage: /mcp env <server_name> <env_key> <value>", "system")
                )
            else:
                # Join remaining args to allow values with spaces
                await self._mcp_set_env(args[1], args[2], " ".join(args[3:]))
        else:
            await self.chat_updates.put(
                ("System", f"Unknown /mcp subcommand: {subcommand}. Type /mcp for help.", "system")
            )

    async def _mcp_list(self) -> None:
        """List configured MCP servers."""
        servers = list_mcp_servers()
        if not servers:
            await self.chat_updates.put(("System", "No MCP servers configured.", "system"))
            return

        lines = ["Configured MCP Servers:", ""]
        for server in servers:
            status = "[+]" if server["enabled"] else "[-]"
            lines.append(f"  {status} {server['name']}: {server['description']}")
            lines.append(f"      Action set: {server['action_set']}")
        await self.chat_updates.put(("System", "\n".join(lines), "system"))

    async def _mcp_add(self, template_name: str) -> None:
        """Add an MCP server from a template."""
        success, message = add_mcp_server_from_template(template_name)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

        if success:
            # Check for required env vars and show hint
            env_vars = get_template_env_vars(template_name)
            empty_vars = [k for k, v in env_vars.items() if not v]
            if empty_vars:
                hint = "\nTo configure environment variables, use:"
                for var in empty_vars:
                    hint += f"\n  /mcp env {template_name} {var} <value>"
                await self.chat_updates.put(("System", hint, "system"))

    async def _mcp_remove(self, server_name: str) -> None:
        """Remove an MCP server."""
        success, message = remove_mcp_server(server_name)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _mcp_enable(self, server_name: str) -> None:
        """Enable an MCP server."""
        success, message = enable_mcp_server(server_name)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _mcp_disable(self, server_name: str) -> None:
        """Disable an MCP server."""
        success, message = disable_mcp_server(server_name)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _mcp_templates(self) -> None:
        """Show available MCP server templates."""
        templates = get_available_templates()
        lines = ["Available MCP Server Templates:", ""]
        for template in templates:
            lines.append(f"  {template['name']}: {template['description']}")
        lines.append("")
        lines.append("Use '/mcp add <template>' to add a server.")
        await self.chat_updates.put(("System", "\n".join(lines), "system"))

    async def _mcp_set_env(self, server_name: str, env_key: str, env_value: str) -> None:
        """Set an environment variable for an MCP server."""
        success, message = update_mcp_server_env(server_name, env_key, env_value)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _mcp_add_custom(self, args: list[str]) -> None:
        """Add a custom MCP server.

        Parse: <name> --transport <type> [--env KEY=VAL]... [-- <command> [args]] or [<url>]
        """
        if not args:
            await self.chat_updates.put(
                ("System", "Usage: /mcp add <name> --transport <type> [--env KEY=VAL] [-- <command> [args]]", "system")
            )
            return

        name = args[0]
        transport = "stdio"
        env: dict[str, str] = {}
        command = None
        cmd_args: list[str] = []
        url = None
        description = ""

        i = 1
        while i < len(args):
            if args[i] == "--transport" and i + 1 < len(args):
                transport = args[i + 1]
                i += 2
            elif args[i] == "--env" and i + 1 < len(args):
                key, _, val = args[i + 1].partition("=")
                env[key] = val
                i += 2
            elif args[i] == "--description" and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            elif args[i] == "--":
                # Everything after -- is the command
                if i + 1 < len(args):
                    command = args[i + 1]
                    cmd_args = args[i + 2:]
                break
            elif transport in ("http", "sse", "websocket") and not url:
                url = args[i]
                i += 1
            else:
                i += 1

        # Validate required fields
        if transport == "stdio" and not command:
            await self.chat_updates.put(
                ("System", "stdio transport requires a command. Use: /mcp add <name> --transport stdio -- <command> [args]", "system")
            )
            return
        if transport in ("http", "sse", "websocket") and not url:
            await self.chat_updates.put(("System", f"{transport} transport requires a URL.", "system"))
            return

        success, message = add_mcp_server(
            name=name,
            description=description or f"Custom {transport} MCP server",
            transport=transport,
            command=command,
            args=cmd_args,
            url=url,
            env=env,
        )
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _mcp_add_json(self, name: str, json_str: str) -> None:
        """Add an MCP server from JSON configuration."""
        success, message = add_mcp_server_from_json(name, json_str)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    def _build_mcp_help_text(self) -> str:
        """Build help text for /mcp command."""
        return """MCP Server Management Commands:

  /mcp list                                    - List configured servers
  /mcp add <template>                          - Add from predefined template
  /mcp add <name> --transport stdio -- <cmd>   - Add custom stdio server
  /mcp add <name> --transport http <url>       - Add custom HTTP server
  /mcp add-json <name> '<json>'                - Add from JSON configuration
  /mcp remove <name>                           - Remove a server
  /mcp enable <name>                           - Enable a server
  /mcp disable <name>                          - Disable a server
  /mcp templates                               - List available templates
  /mcp env <name> <key> <value>                - Set environment variable

Examples:
  /mcp add filesystem
  /mcp add my-server --transport stdio -- python -m my_mcp_server
  /mcp add api --transport http https://api.example.com/mcp

Note: Changes require restart to take effect."""

    # =====================================
    # Skill Commands
    # =====================================

    async def _handle_skill_command(self, args: list[str]) -> None:
        """Handle /skill command with subcommands."""
        if not args:
            # Show help for /skill command
            help_text = self._build_skill_help_text()
            await self.chat_updates.put(("System", help_text, "system"))
            return

        subcommand = args[0].lower()

        if subcommand == "list":
            await self._skill_list()
        elif subcommand == "info":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /skill info <name>", "system"))
            else:
                await self._skill_info(args[1])
        elif subcommand == "install":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /skill install <path-or-url>", "system"))
            else:
                await self._skill_install(args[1])
        elif subcommand == "create":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /skill create <name> [description]", "system"))
            else:
                name = args[1]
                description = " ".join(args[2:]) if len(args) > 2 else ""
                await self._skill_create(name, description)
        elif subcommand == "remove":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /skill remove <name>", "system"))
            else:
                await self._skill_remove(args[1])
        elif subcommand == "enable":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /skill enable <name>", "system"))
            else:
                await self._skill_enable(args[1])
        elif subcommand == "disable":
            if len(args) < 2:
                await self.chat_updates.put(("System", "Usage: /skill disable <name>", "system"))
            else:
                await self._skill_disable(args[1])
        elif subcommand == "reload":
            await self._skill_reload()
        elif subcommand == "dirs":
            await self._skill_dirs()
        else:
            await self.chat_updates.put(
                ("System", f"Unknown /skill subcommand: {subcommand}. Type /skill for help.", "system")
            )

    async def _skill_list(self) -> None:
        """List all discovered skills."""
        skills = list_skills()
        if not skills:
            dirs = get_skill_search_directories()
            dirs_text = ", ".join(dirs) if dirs else "none configured"
            await self.chat_updates.put(
                ("System", f"No skills discovered.\nSearch directories: {dirs_text}", "system")
            )
            return

        lines = ["Discovered Skills:", ""]
        for skill in skills:
            status = "[+]" if skill["enabled"] else "[-]"
            lines.append(f"  {status} {skill['name']}: {skill['description']}")
            if skill["action_sets"]:
                lines.append(f"      Action sets: {', '.join(skill['action_sets'])}")
        await self.chat_updates.put(("System", "\n".join(lines), "system"))

    async def _skill_info(self, name: str) -> None:
        """Show detailed information about a skill."""
        info = get_skill_info(name)
        if not info:
            await self.chat_updates.put(("System", f"Skill '{name}' not found.", "system"))
            return

        lines = [
            f"Skill: {info['name']}",
            f"Description: {info['description']}",
            f"Enabled: {'Yes' if info['enabled'] else 'No'}",
            f"User Invocable: {'Yes' if info['user_invocable'] else 'No'}",
        ]
        if info.get("argument_hint"):
            lines.append(f"Argument Hint: {info['argument_hint']}")
        if info.get("action_sets"):
            lines.append(f"Action Sets: {', '.join(info['action_sets'])}")
        if info.get("allowed_tools"):
            lines.append(f"Allowed Tools: {', '.join(info['allowed_tools'])}")
        lines.append(f"Source: {info['source']}")
        lines.append("")
        lines.append("Instructions Preview:")
        # Show first 500 chars of instructions
        instructions = info.get("instructions", "")
        if len(instructions) > 500:
            lines.append(f"  {instructions[:500]}...")
        else:
            lines.append(f"  {instructions}")

        await self.chat_updates.put(("System", "\n".join(lines), "system"))

    async def _skill_enable(self, name: str) -> None:
        """Enable a skill."""
        success, message = enable_skill(name)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _skill_disable(self, name: str) -> None:
        """Disable a skill."""
        success, message = disable_skill(name)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _skill_reload(self) -> None:
        """Reload skills from disk."""
        success, message = reload_skills()
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _skill_dirs(self) -> None:
        """Show skill search directories."""
        dirs = get_skill_search_directories()
        if not dirs:
            await self.chat_updates.put(("System", "No skill directories configured.", "system"))
            return

        lines = ["Skill Search Directories:", ""]
        for d in dirs:
            lines.append(f"  {d}")
        await self.chat_updates.put(("System", "\n".join(lines), "system"))

    async def _skill_install(self, source: str) -> None:
        """Install a skill from local path or Git URL."""
        # Determine if it's a URL or local path
        if source.startswith(("http://", "https://", "git@", "github.com", "gitlab.com")):
            await self.chat_updates.put(("System", f"Cloning skill from {source}...", "system"))
            success, message = install_skill_from_git(source)
        else:
            success, message = install_skill_from_path(source)

        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _skill_create(self, name: str, description: str = "") -> None:
        """Create a new skill with template."""
        success, message = create_skill_scaffold(name, description)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    async def _skill_remove(self, name: str) -> None:
        """Remove an installed skill."""
        success, message = remove_skill(name)
        severity = "system" if success else "error"
        await self.chat_updates.put(("System", message, severity))

    def _build_skill_help_text(self) -> str:
        """Build help text for /skill command."""
        return """Skill Management Commands:

  /skill list                   - List all discovered skills
  /skill info <name>            - Show skill details and instructions
  /skill install <path>         - Install skill from local folder
  /skill install <git-url>      - Install skill from GitHub/GitLab
  /skill create <name> [desc]   - Create new skill in skills/ folder
  /skill remove <name>          - Remove an installed skill
  /skill enable <name>          - Enable a skill
  /skill disable <name>         - Disable a skill
  /skill reload                 - Reload skills from disk
  /skill dirs                   - Show skill search directories

Examples:
  /skill install /path/to/my-skill
  /skill install https://github.com/user/my-skill
  /skill create my-skill "My custom skill"

Invoking Skills:
  Skills can be invoked directly using /<skill-name> in the chat.
  For example: /research-weather or /web-search

Skills are also automatically selected during task creation based on the task description."""

    # ── Credential / Integration Commands ──

    async def _handle_cred_command(self, args: list[str]) -> None:
        if not args:
            await self.chat_updates.put(("System", "Usage: /cred <list|status|integrations>", "system"))
            return
        sub = args[0].lower()
        if sub == "list":
            from app.tui.credential_commands import list_all_credentials
            _, msg = list_all_credentials()
            await self.chat_updates.put(("System", msg, "system"))
        elif sub == "status":
            lines = ["Integration Status:", ""]
            for name, handler in INTEGRATION_HANDLERS.items():
                try:
                    _, s = await handler.status()
                    lines.append(f"  {s.split(chr(10))[0]}")
                except Exception as e:
                    lines.append(f"  {name}: Error ({e})")
            await self.chat_updates.put(("System", "\n".join(lines), "system"))
        elif sub == "integrations":
            from app.tui.credential_commands import list_integrations
            _, msg = list_integrations()
            await self.chat_updates.put(("System", msg, "system"))
        else:
            await self.chat_updates.put(("System", f"Unknown /cred subcommand: {sub}", "error"))

    async def _handle_integration_command(self, name: str, args: list[str]) -> None:
        handler = INTEGRATION_HANDLERS[name]
        if not args:
            subs = handler.subcommands
            await self.chat_updates.put(("System", f"Usage: /{name} <{'|'.join(subs)}>", "system"))
            return
        sub = args[0].lower()
        ok, msg = await handler.handle(sub, args[1:])
        await self.chat_updates.put(("System", msg, "system" if ok else "error"))

    def _build_help_text(self) -> str:
        intro = (
            "I am a computer-use AI agent., I can perform computer-based task autonomously "
            "for you with simple instruction."
        )

        builtin = {
            "/help": "Show this help message.",
            "/menu": "Return to the main menu.",
            "/clear": "Clear chat and action timelines from the display.",
            "/reset": "Reset the agent and clear interface state.",
            "/exit": "Exit the session.",
            "/mcp": "Manage MCP servers (list, add, remove, enable, disable).",
            "/skill": "Manage skills (list, info, enable, disable, reload).",
            "/cred": "Manage credentials (list, status, integrations).",
        }

        lines: list[str] = [intro, "", "Available commands:"]

        # Built-in commands first
        for cmd in sorted(builtin.keys()):
            lines.append(f"  {cmd}  - {builtin[cmd]}")

        # Agent-provided commands (if any)
        agent_cmds = self._agent.get_commands() if self._agent else {}
        extra = [c for c in agent_cmds.keys() if c not in builtin]

        if extra:
            lines.append("")
            lines.append("Agent commands:")
            for cmd in sorted(extra):
                obj = agent_cmds[cmd]
                desc = (
                    getattr(obj, "description", None)
                    or getattr(obj, "help", None)
                    or getattr(obj, "doc", None)
                )
                if not desc and getattr(obj, "handler", None):
                    desc = getattr(obj.handler, "__doc__", None)

                desc = (desc or "Agent command.").strip()
                lines.append(f"  {cmd}  - {desc}")

        return "\n".join(lines)

    def _clear_display_logs(self) -> None:
        if self._app:
            self._app.clear_logs()

    async def _handle_clear_command(self) -> None:
        self._clear_display_logs()
        self.chat_updates = Queue()
        self.action_updates = Queue()
        await self.chat_updates.put(("System", "Cleared chat and action timelines.", "system"))

    async def _handle_reset_command(self) -> None:
        # Show message before reset starts
        await self.chat_updates.put(("System", "Resetting agent... please wait.", "system"))
        await self.status_updates.put("Resetting agent...")
        # Force app refresh to display message immediately
        if self._app:
            self._app.refresh()
        # Yield control to allow UI to render
        await asyncio.sleep(0.05)

        response: str | None = None
        reset_command = self._agent.get_commands().get("/reset")
        if reset_command:
            response = await reset_command.handler()

        await self._reset_interface_state()
        await self.chat_updates.put(("System", response or "Agent reset. Starting fresh.", "system"))

    async def _reset_interface_state(self) -> None:
        self._tracked_sessions.clear()
        self._seen_events.clear()
        self.chat_updates = Queue()
        self.action_updates = Queue()
        self.status_updates = Queue()
        self._agent_state = "idle"
        self._status_message = "Agent is idle"
        # Clear action panel state
        self._action_items.clear()
        self._action_order.clear()
        self._cached_streams.clear()
        self._selected_task_id = None
        self._clear_display_logs()
        await self.status_updates.put(self._status_message)

    async def _consume_triggers(self) -> None:
        """Continuously consume triggers and hand them to the agent.

        The agent.react() call is run in a dedicated thread with its own event loop
        to completely isolate the agent's processing from the TUI event loop.
        This ensures animations and user input remain responsive during agent processing.
        """
        try:
            while self._agent.is_running:
                trigger = await self._agent.triggers.get()
                if trigger.session_id:
                    self._tracked_sessions.add(trigger.session_id)
                # Run react() in a separate thread with its own event loop
                # This completely decouples agent processing from the TUI
                await asyncio.get_event_loop().run_in_executor(
                    None,  # Use default executor (ThreadPoolExecutor)
                    self._run_react_in_thread,
                    trigger,
                )
        except asyncio.CancelledError:  # pragma: no cover
            raise

    def _run_react_in_thread(self, trigger) -> None:
        """Run agent.react() in a dedicated thread with its own event loop.

        This method is called from run_in_executor and creates a fresh event loop
        in the worker thread. This ensures that all async operations within react()
        (including asyncio.to_thread() calls for LLM) are completely isolated from
        the main TUI event loop.
        """
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._agent.react(trigger))
        finally:
            loop.close()

    async def _watch_events(self) -> None:
        """Refresh the conversation timeline with agent actions.

        Watches all event streams (main + all task streams) to support concurrent tasks.
        Each stream is associated with a task_id so events can be correctly grouped.

        Uses cached stream references to handle race condition where stream is removed
        from manager before TUI processes task_end event.
        """
        try:
            while self._running and self._agent.is_running:
                # Get current streams and ADD new ones to cache (don't replace)
                # This handles the race condition where stream is removed before we process task_end
                current_streams = self._agent.event_stream_manager.get_all_streams_with_ids()
                for stream_task_id, stream in current_streams:
                    if stream_task_id not in self._cached_streams:
                        self._cached_streams[stream_task_id] = stream

                if not self._cached_streams:
                    await asyncio.sleep(0.05)
                    continue

                # Track streams to remove after processing task_end
                streams_to_remove: set = set()

                # Process events from ALL cached streams
                for stream_task_id, stream in list(self._cached_streams.items()):
                    for event in stream.as_list():
                        key = (event.iso_ts, event.kind, event.message)
                        if key in self._seen_events:
                            continue
                        self._seen_events.add(key)

                        if event.kind == "screen":
                            continue

                        # Skip user messages - they're displayed immediately in submit_user_message()
                        # to provide instant visual feedback while routing happens in background
                        # Use "in" to catch:
                        # - "user message" and "user message from platform: X" (current messages)
                        # - "[older message] user message from platform: X" (historical context)
                        if "user message" in event.kind:
                            continue

                        style = self._style_for_event(event.kind, event.severity)
                        label = self._label_for_style(style, event.kind)
                        display_text = event.display_text()

                        if style in {"action", "task"}:
                            await self._handle_action_event(
                                event.kind,
                                display_text,
                                style=style,
                                stream_task_id=stream_task_id,
                            )
                            # Track task_end events for cache cleanup
                            if event.kind in {"task_end", "task_ended"} and stream_task_id:
                                streams_to_remove.add(stream_task_id)
                            continue

                        if style not in {"agent", "system", "user", "error", "info"}:
                            continue

                        if display_text is not None:
                            await self.chat_updates.put((label, display_text, style))

                        # Set agent state to waiting_for_user when agent sends a response
                        if style == "agent" and display_text:
                            # Only transition to waiting if no tasks are running
                            if not self._has_running_work() and self._agent_state == "working":
                                self._agent_state = "waiting_for_user"
                                status = self._generate_status_message()
                                if status != self._status_message:
                                    self._status_message = status
                                    await self.status_updates.put(status)

                # Remove streams from cache AFTER processing task_end
                for sid in streams_to_remove:
                    self._cached_streams.pop(sid, None)

                # Check for GUI mode transitions
                current_gui_mode = STATE.gui_mode
                if self._last_gui_mode and not current_gui_mode:
                    # GUI mode just ended
                    self.signal_gui_mode_end()
                self._last_gui_mode = current_gui_mode

                await asyncio.sleep(0.05)

        except asyncio.CancelledError:  # pragma: no cover
            raise

    async def _handle_action_event(
        self, kind: str, message: str, *, style: str = "action", stream_task_id: str = ""
    ) -> None:
        """Handle action panel events with simplified flat structure.

        Uses a flat list of ActionItems (tasks + actions) with unique IDs.
        Matches action_end to action_start by searching RUNNING actions by name.

        Args:
            kind: Event kind (task_start, action_start, etc.)
            message: Display message for the event
            style: Style for formatting
            stream_task_id: Task ID from stream (used for task grouping)
        """
        # Extract action name from message
        if kind in {"action_start", "GUI action start"} and message.startswith("Running "):
            action_name = message[8:]  # "Running X" -> "X"
        elif kind in {"action_end", "GUI action end"} and " → " in message:
            action_name = message.split(" → ")[0]  # "X → completed" -> "X"
        else:
            action_name = message

        # ─────────────────────────────────────────────────────────────────────
        # TASK START (handles both task_started and task_start events)
        # ─────────────────────────────────────────────────────────────────────
        if kind in {"task_start", "task_started"}:
            self._agent_state = "working"

            # Extract clean task name from message
            task_name = message
            if message.startswith("Task started: "):
                task_name = message[14:]
            elif message.startswith("Started task: "):
                task_name = message[14:]
            elif message.startswith("Created task: '") and message.endswith("'"):
                task_name = message[15:-1]
            elif message.startswith("Created task: "):
                task_name = message[14:]

            # Use stream_task_id as task_id (should be UUID for task streams)
            task_id = stream_task_id

            logger.debug(f"[TUI task_start] stream_task_id={stream_task_id!r}, task_name={task_name!r}")

            # If no stream_task_id (from main stream), skip - the task stream will have the event
            if not task_id:
                return

            # Check if task already exists by ID (placeholder created by action_start)
            if task_id in self._action_items:
                # Update the existing item's display_name (could be a placeholder)
                self._action_items[task_id].display_name = task_name
                self._action_items[task_id].status = "running"
                await self.action_updates.put(ActionPanelUpdate("update", self._action_items[task_id]))
            else:
                # Create new task item
                item = ActionItem(
                    id=task_id,
                    display_name=task_name,
                    item_type="task",
                    status="running",
                    task_id=None,
                    created_at=time.time(),
                )
                self._action_items[task_id] = item
                self._action_order.append(task_id)
                await self.action_updates.put(ActionPanelUpdate("add", item))

        # ─────────────────────────────────────────────────────────────────────
        # TASK END (handles both task_ended and task_end events)
        # ─────────────────────────────────────────────────────────────────────
        elif kind in {"task_end", "task_ended"}:
            found_task_id = None

            # Method 1: Direct lookup by stream_task_id (task_id == session_id now)
            if stream_task_id and stream_task_id in self._action_items:
                found_task_id = stream_task_id

            # Method 2: Extract task name from message and find by display_name
            if not found_task_id:
                task_name = message
                if message.startswith("Task ended: "):
                    task_name = message[12:]
                elif message.startswith("Task completed: "):
                    task_name = message[16:]

                for item_id, item in self._action_items.items():
                    if item.item_type == "task" and item.display_name == task_name:
                        found_task_id = item_id
                        break

            # NOTE: Removed fallback "Method 4" that marked "most recent running task"
            # as it would incorrectly mark the wrong task in parallel task scenarios.

            # Update task status to completed
            if found_task_id and found_task_id in self._action_items:
                self._action_items[found_task_id].status = "completed"
                await self.action_updates.put(ActionPanelUpdate("update", self._action_items[found_task_id]))

            # Only set to idle if no other tasks or actions are running
            if not self._has_running_work():
                self._agent_state = "idle"

        # ─────────────────────────────────────────────────────────────────────
        # ACTION START
        # ─────────────────────────────────────────────────────────────────────
        elif kind in {"action_start", "GUI action start"}:
            self._agent_state = "working"
            task_id = stream_task_id

            # Skip internal/hidden actions (don't display in UI)
            # Extract the base action name BEFORE normalization
            # Message format: "Running action {name} with input: {...}." or "Running {display_name}"
            base_action_name = action_name
            if action_name.lower().startswith("action "):
                # "action task_start with input:..." → extract "task_start"
                parts = action_name.split(" ")
                if len(parts) >= 2:
                    base_action_name = parts[1]  # "task_start"
            else:
                # "task_start with input:..." → extract "task_start"
                base_action_name = action_name.split(" with ")[0]

            # Normalize for comparison (handle underscores/spaces)
            base_action_name_lower = base_action_name.lower().replace(" ", "_")
            if base_action_name_lower in self.HIDDEN_ACTIONS:
                return

            # If there's a task_id but no task item yet, create a placeholder
            # (this handles the case where action_start arrives before task_start event)
            if task_id and task_id not in self._action_items:
                task_item = ActionItem(
                    id=task_id,
                    display_name="Starting task...",  # Placeholder, will be updated by task_start
                    item_type="task",
                    status="running",
                    task_id=None,
                    created_at=time.time(),
                )
                self._action_items[task_id] = task_item
                self._action_order.append(task_id)
                await self.action_updates.put(ActionPanelUpdate("add", task_item))

            # Create action item with unique ID
            action_id = f"{task_id or 'main'}:{action_name}:{time.time()}"
            item = ActionItem(
                id=action_id,
                display_name=action_name,
                item_type="action",
                status="running",
                task_id=task_id,
                created_at=time.time(),
            )
            self._action_items[action_id] = item
            self._action_order.append(action_id)
            await self.action_updates.put(ActionPanelUpdate("add", item))

        # ─────────────────────────────────────────────────────────────────────
        # ACTION END
        # ─────────────────────────────────────────────────────────────────────
        elif kind in {"action_end", "GUI action end"}:
            # Find running action by name (simple linear search among running actions)
            found_item = None
            for item_id, item in self._action_items.items():
                if item.item_type == "action" and item.status == "running":
                    if item.display_name == action_name:
                        found_item = item
                        break

            if found_item:
                # Determine status from message
                if message and (" → error" in message or " → failed" in message):
                    found_item.status = "error"
                else:
                    found_item.status = "completed"
                await self.action_updates.put(ActionPanelUpdate("update", found_item))

            # Check if all work completed - transition to idle
            if not self._has_running_work() and self._agent_state == "working":
                self._agent_state = "idle"

        # ─────────────────────────────────────────────────────────────────────
        # WAITING FOR USER
        # ─────────────────────────────────────────────────────────────────────
        elif kind == "waiting_for_user":
            self._agent_state = "waiting_for_user"

        # Update status display
        status = self._generate_status_message()
        if status != self._status_message:
            self._status_message = status
            await self.status_updates.put(status)

    def _has_running_work(self) -> bool:
        """Check if there are any running tasks or actions."""
        for item in self._action_items.values():
            if item.status == "running":
                return True
        return False

    def _generate_status_message(self) -> str:
        """Generate status message based on agent state."""
        loading_icon = CraftApp.ICON_LOADING_FRAMES[self._loading_frame_index % len(CraftApp.ICON_LOADING_FRAMES)]

        # Check for running tasks to determine actual state
        running_tasks = [
            item for item in self._action_items.values()
            if item.item_type == "task" and item.status == "running"
        ]

        # If there are running tasks, we're working regardless of _agent_state
        if running_tasks:
            if len(running_tasks) == 1:
                return f"{loading_icon} Working on: {running_tasks[0].display_name}"
            else:
                task_names = ", ".join(t.display_name for t in running_tasks[:2])
                if len(running_tasks) > 2:
                    return f"{loading_icon} Working on: {task_names} (+{len(running_tasks) - 2} more)"
                return f"{loading_icon} Working on: {task_names}"

        if self._agent_state == "idle":
            return "Agent is idle"
        elif self._agent_state == "working":
            return f"{loading_icon} Agent is working..."
        elif self._agent_state == "waiting_for_user":
            return "⏸ Waiting for your response"
        else:
            return "Agent is idle"

    def get_actions_for_task(self, task_id: str) -> List[ActionItem]:
        """Get all actions belonging to a specific task.

        Args:
            task_id: The task ID to get actions for.

        Returns:
            List of ActionItems that are actions (not tasks) with the given task_id.
        """
        return [
            item for item in self._action_items.values()
            if item.item_type == "action" and item.task_id == task_id
        ]

    def get_task_items(self) -> List[ActionItem]:
        """Get only task items (not actions) in display order.

        Returns:
            List of ActionItems that are tasks, in the order they were created.
        """
        return [
            self._action_items[item_id]
            for item_id in self._action_order
            if item_id in self._action_items
            and self._action_items[item_id].item_type == "task"
        ]

    def _format_labelled_entry(
        self,
        label_text: str,
        message: Text | str,
        *,
        colour: str,
        label_width: int,
    ) -> Table:
        table = Table.grid(padding=(0, 1))
        table.expand = True
        table.add_column(
            "label",
            width=label_width,
            min_width=label_width,
            max_width=label_width,
            style=colour,
            no_wrap=True,
            justify="left",
        )
        table.add_column("message", ratio=1)

        label_cell = Text(label_text, style=colour, no_wrap=True)
        message_text = message if isinstance(message, Text) else Text(str(message))
        message_text.no_wrap = False
        message_text.overflow = "fold"

        table.add_row(label_cell, message_text)
        return table

    def format_chat_entry(self, label: str, message: str, style: str) -> RenderableType:
        colour = self._STYLE_COLORS.get(style, self._STYLE_COLORS["info"])
        label_text = f"{label}:"
        return self._format_labelled_entry(
            label_text,
            message,
            colour=colour,
            label_width=self._CHAT_LABEL_WIDTH,
        )

    def format_action_item(self, item: ActionItem) -> RenderableType:
        """Format an ActionItem for display in the action panel."""
        # Choose status icon based on status
        if item.status == "completed":
            status_icon = CraftApp.ICON_COMPLETED
        elif item.status == "error":
            status_icon = CraftApp.ICON_ERROR
        else:  # running
            status_icon = CraftApp.ICON_LOADING_FRAMES[self._loading_frame_index % len(CraftApp.ICON_LOADING_FRAMES)]

        # Task items are bold orange, actions are gray with indentation
        if item.item_type == "task":
            label_text = f"[{status_icon}]"
            colour = "bold #ff4f18"
            message = item.display_name
        else:
            label_text = f"[{status_icon}]"
            colour = "bold #a0a0a0"
            # Indent actions under their parent task
            message = f"    {item.display_name}" if item.task_id else item.display_name

        return self._format_labelled_entry(
            label_text,
            message,
            colour=colour,
            label_width=self._ACTION_LABEL_WIDTH,
        )

    def _style_for_event(self, kind: str, severity: str) -> str:
        if severity.upper() == "ERROR":
            return "error"
        if kind == "system":
            return "system"
        if kind.startswith("task"):
            return "task"
        # Include both CLI and GUI action events
        if kind in {"action", "action_start", "action_end", "waiting_for_user",
                    "GUI action start", "GUI action end"}:
            return "action"
        if kind in {"screen", "info", "note"}:
            return "info"
        # Match user messages with or without platform info
        if kind in {"user", "user message"} or kind.startswith("user message"):
            return "user"
        # Match agent messages with or without platform info
        if kind in {"agent", "agent message"} or kind.startswith("agent message"):
            return "agent"
        return "agent"

    def _label_for_style(self, style: str, kind: str) -> str:
        if style == "agent":
            # Use agent name from onboarding config
            from app.onboarding import onboarding_manager
            return onboarding_manager.state.agent_name or "Agent"
        if style == "system":
            return "System"
        if style == "user":
            return "You"
        if style == "error":
            return "Error"
        if style == "task":
            return kind.replace("_", " ").title()
        if style == "info":
            return kind.replace("_", " ").title()
        return kind.title()
