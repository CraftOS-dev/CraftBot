"""Provider command implementation."""

from __future__ import annotations

import os
from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.tui.settings import save_settings_to_json, get_current_provider, get_api_key_for_provider


class ProviderCommand(Command):
    """Manage LLM provider settings."""

    PROVIDERS = {
        "openai": ("OPENAI_API_KEY", "OpenAI"),
        "gemini": ("GOOGLE_API_KEY", "Google Gemini"),
        "anthropic": ("ANTHROPIC_API_KEY", "Anthropic"),
        "byteplus": ("BYTEPLUS_API_KEY", "BytePlus"),
        "remote": (None, "Ollama (Local)"),
    }

    @property
    def name(self) -> str:
        return "/provider"

    @property
    def description(self) -> str:
        return "View or change LLM provider"

    @property
    def usage(self) -> str:
        return "/provider [name] [api_key]"

    @property
    def help_text(self) -> str:
        return """Manage LLM provider settings.

Usage:
  /provider                    - Show current provider
  /provider <name>             - Switch to provider
  /provider <name> <api_key>   - Set provider and API key

Providers:
  openai     - OpenAI GPT models
  gemini     - Google Gemini models
  anthropic  - Anthropic Claude models
  byteplus   - BytePlus Kimi models
  remote     - Ollama (local models)

Examples:
  /provider
  /provider openai
  /provider openai sk-xxx"""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the provider command."""
        if not args:
            return await self._show_current_provider()

        provider = args[0].lower()
        if provider not in self.PROVIDERS:
            providers_list = ", ".join(self.PROVIDERS.keys())
            return CommandResult(
                success=False,
                message=f"Unknown provider: {provider}\nAvailable: {providers_list}",
            )

        api_key = args[1] if len(args) > 1 else ""
        return await self._set_provider(provider, api_key)

    async def _show_current_provider(self) -> CommandResult:
        """Show the current provider configuration."""
        current = get_current_provider()
        env_key, display_name = self.PROVIDERS.get(current, (None, current))

        lines = [f"Current provider: {display_name} ({current})"]

        if env_key:
            api_key = get_api_key_for_provider(current)
            if api_key:
                masked = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
                lines.append(f"API key: {masked}")
            else:
                lines.append("API key: Not configured")
        else:
            lines.append("No API key required (local model)")

        return CommandResult(success=True, message="\n".join(lines))

    async def _set_provider(self, provider: str, api_key: str) -> CommandResult:
        """Set the provider and optionally the API key."""
        env_key, display_name = self.PROVIDERS[provider]

        # Save to settings.json (also syncs to os.environ)
        save_settings_to_json(provider, api_key)

        # Reinitialize the LLM
        try:
            self._controller.agent.reinitialize_llm()
            message = f"Provider changed to {display_name}"
            if api_key:
                message += " with new API key"
            return CommandResult(success=True, message=message)
        except Exception as e:
            return CommandResult(
                success=False,
                message=f"Provider changed but LLM reinitialization failed: {e}",
            )
