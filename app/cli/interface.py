# -*- coding: utf-8 -*-
"""
Main CLI interface class for agent interaction.

This is the CLI equivalent of TUIInterface, using simple print/input
for interaction instead of Textual widgets.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Awaitable, Callable, Optional, Tuple, TYPE_CHECKING

from app.cli.formatter import CLIFormatter
from app.logger import logger
from app.state.agent_state import STATE
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


class CLIInterface:
    """
    Asynchronous CLI driver that feeds user prompts to the agent.

    This is the CLI equivalent of TUIInterface, using simple print/input
    for interaction instead of Textual widgets.
    """

    def __init__(
        self, agent: "AgentBase", *, default_provider: str, default_api_key: str
    ) -> None:
        self._agent = agent
        self._running: bool = False
        self._tracked_sessions: set[str] = set()
        self._seen_events: set[Tuple[str, str, str]] = set()

        # Track current task and action states
        self._current_task_name: Optional[str] = None
        self._agent_state: str = "idle"

        # Track last output type for proper spacing
        # Types: "chat", "action", "task", "none"
        self._last_output_type: str = "none"

        self._default_provider = default_provider
        self._default_api_key = default_api_key

        self._command_handlers: dict[str, Callable[[], Awaitable[None]]] = {}
        self._register_commands()

        # Initialize color support
        CLIFormatter.init()

    def _register_commands(self) -> None:
        """Register built-in command handlers."""
        self._command_handlers = {
            "/exit": self._handle_exit_command,
            "/clear": self._handle_clear_command,
            "/reset": self._handle_reset_command,
            "/menu": self._handle_menu_command,
            "/help": self._handle_help_command,
        }

    async def start(self) -> None:
        """Start the CLI session with background event consumer."""
        if self._running:
            return

        self._running = True
        logger.debug("Starting CLI interface. Press Ctrl+C to exit.")

        # Check for onboarding
        from app.onboarding import onboarding_manager

        if onboarding_manager.needs_hard_onboarding:
            await self._run_hard_onboarding()

        # Print welcome message with logo
        CLIFormatter.print_logo()
        print("Type /help for commands, /exit to quit.\n")

        # Note: Soft onboarding is triggered by the agent in run() before
        # the interface starts. Interfaces should not contain agent logic.

        # Start background tasks
        trigger_consumer = asyncio.create_task(self._consume_triggers())
        event_task = asyncio.create_task(self._watch_events())

        try:
            await self._input_loop()
        except (KeyboardInterrupt, EOFError):
            print("\n" + CLIFormatter.format_info("Session interrupted."))
        finally:
            self._running = False
            self._agent.is_running = False

            trigger_consumer.cancel()
            try:
                await trigger_consumer
            except asyncio.CancelledError:
                pass

            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass

    async def _run_hard_onboarding(self) -> None:
        """Run hard onboarding if needed."""
        from app.cli.onboarding import CLIHardOnboarding

        onboarding = CLIHardOnboarding(self)
        result = await onboarding.run_hard_onboarding()

        if result.get("completed"):
            # Apply provider configuration
            provider = result.get("provider", "openai")
            api_key = result.get("api_key", "")
            self.configure_provider(provider, api_key)

            # Reinitialize LLM with new settings
            if self._agent._deferred_init:
                self._agent._deferred_init = False
                await self._agent._initialize_llm()

    async def _input_loop(self) -> None:
        """Main input loop using async input."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # Get user input asynchronously
                user_input = await loop.run_in_executor(None, self._read_input)

                if user_input is None:
                    # EOF received
                    await self.request_shutdown()
                    break

                user_input = user_input.strip()
                if user_input:
                    # Clear the echoed input line (will be replaced by "You: ..." from event)
                    CLIFormatter.clear_previous_line()
                    await self.submit_user_message(user_input)

            except (EOFError, KeyboardInterrupt):
                await self.request_shutdown()
                break
            except Exception as e:
                logger.error(f"[CLI] Input error: {e}")

    def _read_input(self) -> Optional[str]:
        """Read input from stdin, handling EOF gracefully."""
        try:
            return input()
        except EOFError:
            return None

    async def submit_user_message(self, message: str) -> None:
        """Handle user input and route to agent."""
        if not message:
            return

        # Check for commands first
        if await self._maybe_handle_command(message):
            return

        # Set state to working when user submits a message
        self._agent_state = "working"

        # Send to agent
        payload = {
            "text": message,
            "sender": {"id": "cli_user", "type": "user"},
            "gui_mode": False,
        }
        await self._agent._handle_chat_message(payload)

    async def _consume_triggers(self) -> None:
        """Continuously consume triggers and hand them to the agent."""
        try:
            while self._agent.is_running:
                trigger = await self._agent.triggers.get()
                if trigger.session_id:
                    self._tracked_sessions.add(trigger.session_id)
                # Run react() in a separate thread with its own event loop
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._run_react_in_thread,
                    trigger,
                )
        except asyncio.CancelledError:
            raise

    def _run_react_in_thread(self, trigger) -> None:
        """Run agent.react() in a dedicated thread with its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._agent.react(trigger))
        except Exception as e:
            logger.error(f"[CLI] Error in react(): {e}")
        finally:
            loop.close()

    async def _watch_events(self) -> None:
        """Watch and display agent events to stdout."""
        try:
            while self._running and self._agent.is_running:
                stream = self._agent.event_stream_manager.get_stream()
                if not stream:
                    await asyncio.sleep(0.05)
                    continue

                for event in stream.as_list():
                    key = (event.iso_ts, event.kind, event.message)
                    if key in self._seen_events:
                        continue
                    self._seen_events.add(key)

                    # Skip screen events in CLI
                    if event.kind == "screen":
                        continue

                    self._display_event(event)

                await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            raise

    def _ensure_blank_line_before(self) -> None:
        """Print a blank line if the last output wasn't already a blank line."""
        if self._last_output_type != "blank":
            print()
            self._last_output_type = "blank"

    def _display_event(self, event) -> None:
        """Display an event to stdout with appropriate formatting."""
        kind = event.kind
        message = event.display_text()
        severity = event.severity

        if not message:
            return

        # Handle task events
        if kind == "task_start":
            self._ensure_blank_line_before()
            print(CLIFormatter.format_task_start(message))
            self._last_output_type = "task"
            self._current_task_name = message
            self._agent_state = "working"
            return

        if kind == "task_end":
            # Ensure blank line before task completion
            self._ensure_blank_line_before()
            success = severity.upper() != "ERROR"
            print(CLIFormatter.format_task_end(message, success))
            self._last_output_type = "task"
            self._current_task_name = None
            self._agent_state = "idle"
            return

        # Handle action events (both CLI and GUI modes)
        if kind in {"action_start", "GUI action start"}:
            action_name = message[8:] if message.startswith("Running ") else message
            # Skip hidden actions
            if CLIFormatter.is_hidden_action(action_name):
                self._agent_state = "working"
                return
            is_sub = bool(self._current_task_name)
            print(CLIFormatter.format_action_start(action_name, is_sub))
            self._last_output_type = "action"
            self._agent_state = "working"
            return

        if kind in {"action_end", "GUI action end"}:
            parts = message.split(" → ")
            action_name = parts[0]
            # Skip hidden actions
            if CLIFormatter.is_hidden_action(action_name):
                if not self._current_task_name:
                    self._agent_state = "idle"
                return
            success = True
            if len(parts) > 1:
                status_part = parts[1].lower()
                success = "error" not in status_part and "failed" not in status_part
            is_sub = bool(self._current_task_name)
            print(CLIFormatter.format_action_end(action_name, success, is_sub))
            self._last_output_type = "action"

            if not self._current_task_name:
                self._agent_state = "idle"
            return

        # Handle chat events - ensure exactly one blank line before
        if kind in {"user", "user message"}:
            self._ensure_blank_line_before()
            print(CLIFormatter.format_chat("You", message, "user"))
            self._last_output_type = "chat"
            return

        if kind in {"agent", "agent message"}:
            from app.onboarding import onboarding_manager
            agent_name = onboarding_manager.state.agent_name or "Agent"
            self._ensure_blank_line_before()
            print(CLIFormatter.format_chat(agent_name, message, "agent"))
            self._last_output_type = "chat"
            self._agent_state = "idle"
            return

        # Handle system events
        if kind == "system":
            self._ensure_blank_line_before()
            print(CLIFormatter.format_chat("System", message, "system"))
            self._last_output_type = "chat"
            return

        # Handle errors
        if severity.upper() == "ERROR":
            print(CLIFormatter.format_error(message))
            self._last_output_type = "error"
            return

        # Handle info/note events
        if kind in {"info", "note"}:
            print(CLIFormatter.format_info(message))
            self._last_output_type = "info"
            return

    # =====================================
    # Command Handling
    # =====================================

    async def _maybe_handle_command(self, message: str) -> bool:
        """Process slash commands, return True if handled."""
        parts = message.split()
        if not parts:
            return False

        command = parts[0].lower()

        # Handle /provider command (also handles API key)
        if command == "/provider":
            await self._handle_provider_command(parts[1:])
            return True

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
        integration_name = command.lstrip("/")
        if integration_name in INTEGRATION_HANDLERS:
            await self._handle_integration_command(integration_name, parts[1:])
            return True

        # Built-in commands
        handler = self._command_handlers.get(command)
        if handler:
            await handler()
            return True

        # Agent-provided commands
        agent_cmds = self._agent.get_commands() if self._agent else {}
        if command in agent_cmds:
            cmd_obj = agent_cmds[command]
            try:
                result = await cmd_obj.handler()
                if result:
                    print(CLIFormatter.format_chat("System", result, "system"))
            except Exception as e:
                logger.error(f"[CLI] Command {command} failed: {e}")
                print(CLIFormatter.format_error(f"Command failed: {e}"))
            return True

        # Unknown slash command - show helpful message
        if command.startswith("/"):
            available = list(self._command_handlers.keys()) + list(agent_cmds.keys())
            print(CLIFormatter.format_chat(
                "System",
                f"Unknown command: {command}\nUse /help to see available commands.",
                "system"
            ))
            return True

        return False

    async def _handle_exit_command(self) -> None:
        """Handle /exit command."""
        print(CLIFormatter.format_chat("System", "Session terminated by user.", "system"))
        await self.request_shutdown()

    async def _handle_clear_command(self) -> None:
        """Handle /clear command."""
        CLIFormatter.clear_screen()
        print(CLIFormatter.format_chat("System", "Screen cleared.", "system"))

    async def _handle_reset_command(self) -> None:
        """Handle /reset command."""
        # Show message before reset starts (flush to ensure immediate display)
        print(CLIFormatter.format_chat("System", "Resetting agent... please wait.", "system"))
        sys.stdout.flush()

        response: str | None = None
        reset_command = self._agent.get_commands().get("/reset")
        if reset_command:
            response = await reset_command.handler()

        self._tracked_sessions.clear()
        self._seen_events.clear()
        self._agent_state = "idle"
        self._current_task_name = None

        print(CLIFormatter.format_chat("System", response or "Agent reset. Starting fresh.", "system"))

    async def _handle_menu_command(self) -> None:
        """Handle /menu command - not applicable in CLI mode."""
        print(CLIFormatter.format_chat("System", "Menu is not available in CLI mode. Use /help to see available commands.", "system"))

    async def _handle_help_command(self) -> None:
        """Handle /help command."""
        help_text = self._build_help_text()
        print(CLIFormatter.format_chat("System", help_text, "system"))

    def _build_help_text(self) -> str:
        """Build help text for CLI."""
        intro = (
            "I am a computer-use AI agent. I can perform computer-based tasks autonomously "
            "for you with simple instructions."
        )

        builtin = {
            "/help": "Show this help message.",
            "/clear": "Clear the screen.",
            "/reset": "Reset the agent and clear state.",
            "/exit": "Exit the session.",
            "/provider": "Set LLM provider and API key.",
            "/mcp": "Manage MCP servers (list, add, remove, enable, disable).",
            "/skill": "Manage skills (list, info, enable, disable, reload).",
            "/cred": "Manage credentials (list, status, integrations).",
        }

        lines: list[str] = [intro, "", "Available commands:"]

        for cmd in sorted(builtin.keys()):
            lines.append(f"  {cmd}  - {builtin[cmd]}")

        # Agent-provided commands
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

    # =====================================
    # Provider Command
    # =====================================

    async def _handle_provider_command(self, args: list[str]) -> None:
        """Handle /provider command to show or set LLM provider and API key.

        Usage:
            /provider                    - Show current provider and API key status
            /provider <name>             - Set provider (uses existing API key if available)
            /provider <name> <apikey>    - Set provider and API key
        """
        import os
        from app.tui.settings import save_settings_to_env

        valid_providers = ["openai", "gemini", "anthropic", "byteplus", "remote"]
        key_lookup = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "byteplus": "BYTEPLUS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }

        if not args:
            # Show current provider and API key status
            current = os.getenv("LLM_PROVIDER", "openai")
            key_env = key_lookup.get(current, "")
            current_key = os.getenv(key_env, "") if key_env else ""

            lines = [f"Current provider: {current}"]

            if current == "remote":
                lines.append("API key: Not required (Ollama)")
            elif current_key:
                masked = current_key[:4] + "..." + current_key[-4:] if len(current_key) > 8 else "****"
                lines.append(f"API key: {masked}")
            else:
                lines.append("API key: Not configured")

            lines.extend([
                "",
                "Available providers:",
                "  openai    - OpenAI (GPT-4, etc.)",
                "  gemini    - Google Gemini",
                "  anthropic - Anthropic Claude",
                "  byteplus  - BytePlus",
                "  remote    - Ollama (local, no API key needed)",
                "",
                "Usage:",
                "  /provider <name>            - Set provider",
                "  /provider <name> <apikey>   - Set provider and API key",
            ])
            print(CLIFormatter.format_chat("System", "\n".join(lines), "system"))
            return

        new_provider = args[0].lower()
        if new_provider not in valid_providers:
            print(CLIFormatter.format_chat(
                "System",
                f"Invalid provider '{new_provider}'. Valid options: {', '.join(valid_providers)}",
                "system"
            ))
            return

        # Check if API key is provided as second argument
        new_api_key = args[1] if len(args) > 1 else None

        # Get existing API key for the new provider (if no new key provided)
        if new_api_key:
            api_key = new_api_key
        elif new_provider in key_lookup:
            api_key = os.getenv(key_lookup[new_provider], "")
        else:
            api_key = ""

        # Update environment
        os.environ["LLM_PROVIDER"] = new_provider
        if new_provider in key_lookup and api_key:
            os.environ[key_lookup[new_provider]] = api_key

        # Save to .env
        save_settings_to_env(new_provider, api_key)

        # Reinitialize LLM with new provider
        try:
            await self._agent._initialize_llm()

            # Build confirmation message
            if new_provider == "remote":
                message = f"Provider set to '{new_provider}' (Ollama). No API key required."
            elif api_key:
                if new_api_key:
                    message = f"Provider set to '{new_provider}'. API key has been saved."
                else:
                    message = f"Provider set to '{new_provider}'. Using existing API key."
            else:
                message = (
                    f"Provider set to '{new_provider}'.\n"
                    f"Warning: No API key configured. Use /provider {new_provider} <apikey> to set one."
                )

            print(CLIFormatter.format_chat("System", message, "system"))

        except Exception as e:
            print(CLIFormatter.format_chat(
                "System",
                f"Provider set to '{new_provider}', but initialization failed: {e}",
                "system"
            ))

    # =====================================
    # MCP Commands
    # =====================================

    async def _handle_mcp_command(self, args: list[str]) -> None:
        """Handle /mcp command with subcommands."""
        if not args:
            help_text = self._build_mcp_help_text()
            print(CLIFormatter.format_chat("System", help_text, "system"))
            return

        subcommand = args[0].lower()

        if subcommand == "list":
            await self._mcp_list()
        elif subcommand == "add":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /mcp add <template> or /mcp add <name> --transport <type> ...", "system"))
            elif "--transport" in args:
                # Custom server: /mcp add <name> --transport <type> ...
                await self._mcp_add_custom(args[1:])
            else:
                # Template: /mcp add <template>
                await self._mcp_add(args[1])
        elif subcommand == "add-json":
            if len(args) < 3:
                print(CLIFormatter.format_chat("System", "Usage: /mcp add-json <name> '<json>'", "system"))
            else:
                name = args[1]
                json_str = " ".join(args[2:])
                await self._mcp_add_json(name, json_str)
        elif subcommand == "remove":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /mcp remove <name>", "system"))
            else:
                await self._mcp_remove(args[1])
        elif subcommand == "enable":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /mcp enable <name>", "system"))
            else:
                await self._mcp_enable(args[1])
        elif subcommand == "disable":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /mcp disable <name>", "system"))
            else:
                await self._mcp_disable(args[1])
        elif subcommand == "templates":
            await self._mcp_templates()
        elif subcommand == "env":
            if len(args) < 4:
                print(CLIFormatter.format_chat("System", "Usage: /mcp env <name> <key> <value>", "system"))
            else:
                await self._mcp_set_env(args[1], args[2], " ".join(args[3:]))
        else:
            print(CLIFormatter.format_chat("System", f"Unknown /mcp subcommand: {subcommand}. Type /mcp for help.", "system"))

    async def _mcp_list(self) -> None:
        """List configured MCP servers."""
        servers = list_mcp_servers()
        if not servers:
            print(CLIFormatter.format_chat("System", "No MCP servers configured.", "system"))
            return

        lines = ["Configured MCP Servers:", ""]
        for server in servers:
            status = "[+]" if server["enabled"] else "[-]"
            lines.append(f"  {status} {server['name']}")
        print(CLIFormatter.format_chat("System", "\n".join(lines), "system"))

    async def _mcp_add(self, template: str) -> None:
        """Add an MCP server from template."""
        success, message = add_mcp_server_from_template(template)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _mcp_remove(self, name: str) -> None:
        """Remove an MCP server."""
        success, message = remove_mcp_server(name)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _mcp_enable(self, name: str) -> None:
        """Enable an MCP server."""
        success, message = enable_mcp_server(name)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _mcp_disable(self, name: str) -> None:
        """Disable an MCP server."""
        success, message = disable_mcp_server(name)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _mcp_templates(self) -> None:
        """List available MCP templates."""
        templates = get_available_templates()
        if not templates:
            print(CLIFormatter.format_chat("System", "No MCP templates available.", "system"))
            return

        lines = ["Available MCP Templates:", ""]
        for tpl in templates:
            lines.append(f"  {tpl['name']}: {tpl.get('description', 'MCP server')}")
        print(CLIFormatter.format_chat("System", "\n".join(lines), "system"))

    async def _mcp_add_custom(self, args: list[str]) -> None:
        """Add a custom MCP server.

        Parse: <name> --transport <type> [--env KEY=VAL]... [-- <command> [args]] or [<url>]
        """
        if not args:
            print(CLIFormatter.format_chat("System", "Usage: /mcp add <name> --transport <type> [--env KEY=VAL] [-- <command> [args]]", "system"))
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
            print(CLIFormatter.format_chat("System", "stdio transport requires a command. Use: /mcp add <name> --transport stdio -- <command> [args]", "system"))
            return
        if transport in ("http", "sse", "websocket") and not url:
            print(CLIFormatter.format_chat("System", f"{transport} transport requires a URL.", "system"))
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
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _mcp_add_json(self, name: str, json_str: str) -> None:
        """Add an MCP server from JSON configuration."""
        success, message = add_mcp_server_from_json(name, json_str)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _mcp_set_env(self, server_name: str, env_key: str, env_value: str) -> None:
        """Set an environment variable for an MCP server."""
        success, message = update_mcp_server_env(server_name, env_key, env_value)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

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
  /mcp add-json test '{"transport":"http","url":"http://localhost:8080"}'
  /mcp env github GITHUB_PERSONAL_ACCESS_TOKEN sk-xxx"""

    # =====================================
    # Skill Commands
    # =====================================

    async def _handle_skill_command(self, args: list[str]) -> None:
        """Handle /skill command with subcommands."""
        if not args:
            help_text = self._build_skill_help_text()
            print(CLIFormatter.format_chat("System", help_text, "system"))
            return

        subcommand = args[0].lower()

        if subcommand == "list":
            await self._skill_list()
        elif subcommand == "info":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /skill info <name>", "system"))
            else:
                await self._skill_info(args[1])
        elif subcommand == "install":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /skill install <path-or-url>", "system"))
            else:
                await self._skill_install(args[1])
        elif subcommand == "create":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /skill create <name> [description]", "system"))
            else:
                name = args[1]
                description = " ".join(args[2:]) if len(args) > 2 else ""
                await self._skill_create(name, description)
        elif subcommand == "remove":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /skill remove <name>", "system"))
            else:
                await self._skill_remove(args[1])
        elif subcommand == "enable":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /skill enable <name>", "system"))
            else:
                await self._skill_enable(args[1])
        elif subcommand == "disable":
            if len(args) < 2:
                print(CLIFormatter.format_chat("System", "Usage: /skill disable <name>", "system"))
            else:
                await self._skill_disable(args[1])
        elif subcommand == "reload":
            await self._skill_reload()
        elif subcommand == "dirs":
            await self._skill_dirs()
        else:
            print(CLIFormatter.format_chat("System", f"Unknown /skill subcommand: {subcommand}. Type /skill for help.", "system"))

    async def _skill_list(self) -> None:
        """List all discovered skills."""
        skills = list_skills()
        if not skills:
            dirs = get_skill_search_directories()
            dirs_text = ", ".join(dirs) if dirs else "none configured"
            print(CLIFormatter.format_chat("System", f"No skills discovered.\nSearch directories: {dirs_text}", "system"))
            return

        lines = ["Discovered Skills:", ""]
        for skill in skills:
            status = "[+]" if skill["enabled"] else "[-]"
            lines.append(f"  {status} {skill['name']}: {skill['description']}")
        print(CLIFormatter.format_chat("System", "\n".join(lines), "system"))

    async def _skill_info(self, name: str) -> None:
        """Show detailed information about a skill."""
        info = get_skill_info(name)
        if not info:
            print(CLIFormatter.format_chat("System", f"Skill '{name}' not found.", "system"))
            return

        lines = [
            f"Skill: {info['name']}",
            f"Description: {info['description']}",
            f"Enabled: {'Yes' if info['enabled'] else 'No'}",
        ]
        if info.get("action_sets"):
            lines.append(f"Action Sets: {', '.join(info['action_sets'])}")
        print(CLIFormatter.format_chat("System", "\n".join(lines), "system"))

    async def _skill_enable(self, name: str) -> None:
        """Enable a skill."""
        success, message = enable_skill(name)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _skill_disable(self, name: str) -> None:
        """Disable a skill."""
        success, message = disable_skill(name)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _skill_reload(self) -> None:
        """Reload skills from disk."""
        success, message = reload_skills()
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _skill_dirs(self) -> None:
        """Show skill search directories."""
        dirs = get_skill_search_directories()
        if not dirs:
            print(CLIFormatter.format_chat("System", "No skill directories configured.", "system"))
            return

        lines = ["Skill Search Directories:", ""]
        for d in dirs:
            lines.append(f"  {d}")
        print(CLIFormatter.format_chat("System", "\n".join(lines), "system"))

    async def _skill_install(self, source: str) -> None:
        """Install a skill from local path or Git URL."""
        # Determine if it's a URL or local path
        if source.startswith(("http://", "https://", "git@", "github.com", "gitlab.com")):
            print(CLIFormatter.format_chat("System", f"Cloning skill from {source}...", "system"))
            success, message = install_skill_from_git(source)
        else:
            success, message = install_skill_from_path(source)

        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _skill_create(self, name: str, description: str = "") -> None:
        """Create a new skill with template."""
        success, message = create_skill_scaffold(name, description)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    async def _skill_remove(self, name: str) -> None:
        """Remove an installed skill."""
        success, message = remove_skill(name)
        style = "system" if success else "error"
        print(CLIFormatter.format_chat("System", message, style))

    def _build_skill_help_text(self) -> str:
        """Build help text for /skill command."""
        return """Skill Management Commands:

  /skill list                   - List all discovered skills
  /skill info <name>            - Show skill details
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
  /skill remove my-skill

Invoking Skills:
  Skills can be invoked directly using /<skill-name> in the chat.
  For example: /research-weather or /web-search"""

    # =====================================
    # Credential Commands
    # =====================================

    async def _handle_cred_command(self, args: list[str]) -> None:
        """Handle /cred command."""
        if not args:
            print(CLIFormatter.format_chat("System", "Usage: /cred <list|status|integrations>", "system"))
            return

        sub = args[0].lower()
        if sub == "list":
            from app.tui.credential_commands import list_all_credentials
            _, msg = list_all_credentials()
            print(CLIFormatter.format_chat("System", msg, "system"))
        elif sub == "status":
            lines = ["Integration Status:", ""]
            for name, handler in INTEGRATION_HANDLERS.items():
                try:
                    _, s = await handler.status()
                    lines.append(f"  {s.split(chr(10))[0]}")
                except Exception as e:
                    lines.append(f"  {name}: Error ({e})")
            print(CLIFormatter.format_chat("System", "\n".join(lines), "system"))
        elif sub == "integrations":
            from app.tui.credential_commands import list_integrations
            _, msg = list_integrations()
            print(CLIFormatter.format_chat("System", msg, "system"))
        else:
            print(CLIFormatter.format_chat("System", f"Unknown /cred subcommand: {sub}", "error"))

    async def _handle_integration_command(self, name: str, args: list[str]) -> None:
        """Handle integration-specific commands."""
        handler = INTEGRATION_HANDLERS[name]
        if not args:
            subs = handler.subcommands
            print(CLIFormatter.format_chat("System", f"Usage: /{name} <{'|'.join(subs)}>", "system"))
            return

        sub = args[0].lower()
        ok, msg = await handler.handle(sub, args[1:])
        style = "system" if ok else "error"
        print(CLIFormatter.format_chat("System", msg, style))

    # =====================================
    # Utility Methods
    # =====================================

    def configure_provider(self, provider: str, api_key: str) -> None:
        """Configure environment variables for the selected provider."""
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

    async def request_shutdown(self) -> None:
        """Stop the interface."""
        if not self._running:
            return

        self._running = False
        self._agent.is_running = False
