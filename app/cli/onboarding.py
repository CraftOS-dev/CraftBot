# -*- coding: utf-8 -*-
"""
CLI implementation of hard onboarding using sequential prompts.
"""

import asyncio
from typing import Any, Dict, Optional, TYPE_CHECKING

from app.cli.formatter import CLIFormatter
from app.onboarding.interfaces.base import OnboardingInterface
from app.onboarding.interfaces.steps import (
    ProviderStep,
    ApiKeyStep,
    AgentNameStep,
    UserProfileStep,
)
from app.onboarding import onboarding_manager
from app.ui_layer.settings.provider_settings import save_settings_to_json
from app.logger import logger

if TYPE_CHECKING:
    from app.cli.interface import CLIInterface


class CLIHardOnboarding(OnboardingInterface):
    """
    CLI implementation of hard onboarding using sequential prompts.

    Presents a step-by-step wizard via stdin/stdout:
    1. LLM Provider selection
    2. API Key input
    3. Your name (optional)
    4. Agent name (optional)
    """

    def __init__(self, cli_interface: "CLIInterface"):
        self._cli = cli_interface
        self._collected_data: Dict[str, Any] = {}

    async def _async_input(self, prompt: str) -> str:
        """Async-safe input using thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, input, prompt)

    async def _select_single(
        self, step, current_value: Optional[str] = None
    ) -> Optional[str]:
        """Present a single-select menu and return selection."""
        options = step.get_options()
        if not options:
            return None

        print(f"\n{step.title}:")
        print(f"{step.description}\n")

        for i, opt in enumerate(options, 1):
            marker = "*" if opt.value == current_value else " "
            print(f"  {i}. [{marker}] {opt.label} - {opt.description}")

        while True:
            default_text = ""
            if current_value:
                default_text = f" (current: {current_value})"
            try:
                choice = await self._async_input(
                    f"\nEnter number [1-{len(options)}]{default_text}: "
                )
            except (EOFError, KeyboardInterrupt):
                return None

            choice = choice.strip()
            if not choice and current_value:
                return current_value

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return options[idx].value
            except ValueError:
                pass

            print(f"Invalid selection. Please enter 1-{len(options)}.")

    async def _input_text(
        self, step, current_value: str = "", password: bool = False
    ) -> str:
        """Present a text input prompt."""
        print(f"\n{step.title}:")
        print(f"{step.description}")

        default = step.get_default()
        default_display = "(hidden)" if password and default else default

        prompt = "\n> "
        if default_display:
            prompt = f"\n(default: {default_display})\n> "

        while True:
            try:
                if password:
                    # For password input, try to use getpass
                    try:
                        import getpass

                        loop = asyncio.get_event_loop()
                        value = await loop.run_in_executor(
                            None, getpass.getpass, prompt
                        )
                    except Exception:
                        value = await self._async_input(prompt)
                else:
                    value = await self._async_input(prompt)
            except (EOFError, KeyboardInterrupt):
                return default

            value = value.strip()
            if not value:
                value = default

            is_valid, error = step.validate(value)
            if is_valid:
                return value
            else:
                print(f"Error: {error}")

    async def _input_form(self, step) -> Dict[str, Any]:
        """Present a multi-field form and return collected data as a dict."""
        form_fields = step.get_form_fields()
        result: Dict[str, Any] = {}

        print(f"\n{step.title}:")
        print(f"{step.description}\n")

        for f in form_fields:
            # Only text fields are used in hard onboarding (name steps).
            if f.field_type == "text":
                default_display = f.default or ""
                prompt = f"  {f.label}"
                if default_display:
                    prompt += f" (default: {default_display})"
                prompt += ": "
                try:
                    value = await self._async_input(prompt)
                except (EOFError, KeyboardInterrupt):
                    value = ""
                result[f.name] = value.strip() if value.strip() else (f.default or "")

        return result

    async def run_hard_onboarding(self) -> Dict[str, Any]:
        """Execute CLI-based hard onboarding wizard."""
        print(CLIFormatter.format_header("CraftBot Setup"))

        try:
            # Step 1: Provider selection
            provider_step = ProviderStep()
            provider = await self._select_single(
                provider_step, provider_step.get_default()
            )
            if provider is None:
                self._collected_data["completed"] = False
                return self._collected_data
            self._collected_data["provider"] = provider

            # Step 2: API key (skip for remote/Ollama)
            if provider != "remote":
                api_key_step = ApiKeyStep(provider)
                api_key = await self._input_text(
                    api_key_step, api_key_step.get_default(), password=True
                )
                self._collected_data["api_key"] = api_key
            else:
                self._collected_data["api_key"] = ""
                print("\nOllama selected - no API key required.")

            # Step 3: User name (optional). Location/language are derived
            # silently at completion (see UserProfileStep.enrich).
            profile_step = UserProfileStep()
            profile_data = await self._input_form(profile_step)
            self._collected_data["user_profile"] = profile_data

            # Step 4: Agent name (optional)
            agent_name_step = AgentNameStep()
            agent_form = await self._input_form(agent_name_step)
            self._collected_data["agent_name"] = (
                agent_form.get("agent_name") or "Agent"
            )

            self._collected_data["completed"] = True
            self.on_complete()

            print(CLIFormatter.format_success("\nSetup complete!"))
            return self._collected_data

        except Exception as e:
            logger.error(f"[CLI ONBOARDING] Error: {e}")
            self._collected_data["completed"] = False
            return self._collected_data

    def on_complete(self, cancelled: bool = False) -> None:
        """Called when the wizard completes. Saves configuration."""
        if cancelled:
            self._collected_data["completed"] = False
            logger.info("[CLI ONBOARDING] Hard onboarding cancelled by user")
            return

        self._collected_data["completed"] = True

        # Save provider and API key to settings.json
        provider = self._collected_data.get("provider", "openai")
        api_key = self._collected_data.get("api_key", "")

        if provider and api_key:
            # save_settings_to_json also syncs to os.environ for current session
            save_settings_to_json(provider, api_key)
            logger.info(f"[CLI ONBOARDING] Saved provider={provider} to settings.json")

        # Write user profile data to USER.md. The name is the only field
        # collected in the UI; enrich() fills in location (IP), language (OS),
        # and defaults for the rest.
        from app.onboarding.profile_writer import write_profile_to_user_md

        profile_data = UserProfileStep().enrich(
            self._collected_data.get("user_profile", {})
        )
        write_profile_to_user_md(profile_data)

        # Mark hard onboarding as complete
        agent_name = self._collected_data.get("agent_name", "Agent")
        user_name = profile_data.get("user_name") if profile_data else None
        onboarding_manager.mark_hard_complete(
            user_name=user_name, agent_name=agent_name
        )

        logger.info("[CLI ONBOARDING] Hard onboarding completed successfully")

        # Trigger soft onboarding now that hard onboarding is done
        # This is needed because the soft onboarding check in agent.run() happens
        # before interface starts (and thus before hard onboarding completes)
        if onboarding_manager.needs_soft_onboarding:
            import asyncio

            asyncio.create_task(self._trigger_soft_onboarding_async())

    async def _trigger_soft_onboarding_async(self) -> None:
        """
        Async helper to trigger soft onboarding after hard onboarding completes.

        Uses the agent's trigger_soft_onboarding method which fires the
        ONBOARDING trigger in the main session.
        """
        if not self._cli._agent:
            logger.warning(
                "[CLI ONBOARDING] Cannot trigger soft onboarding: no agent reference"
            )
            return

        agent = self._cli._agent
        task_id = await agent.trigger_soft_onboarding()
        if task_id:
            logger.info(
                f"[CLI ONBOARDING] Soft onboarding triggered after hard onboarding: {task_id}"
            )

    async def trigger_soft_onboarding(self) -> Optional[str]:
        """Trigger the soft onboarding interview run in the main session."""
        if not self._cli._agent:
            logger.warning(
                "[CLI ONBOARDING] Cannot trigger soft onboarding: no agent reference"
            )
            return None

        session_id = await self._cli._agent.trigger_soft_onboarding()
        logger.info(f"[CLI ONBOARDING] Triggered soft onboarding: {session_id}")
        return session_id

    def is_hard_onboarding_complete(self) -> bool:
        """Check if hard onboarding is complete."""
        return onboarding_manager.state.hard_completed

    def is_soft_onboarding_complete(self) -> bool:
        """Check if soft onboarding is complete."""
        return onboarding_manager.state.soft_completed
