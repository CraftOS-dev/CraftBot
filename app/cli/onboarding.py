# -*- coding: utf-8 -*-
"""
CLI implementation of hard onboarding using sequential prompts.
"""

import asyncio
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.cli.formatter import CLIFormatter
from app.onboarding.interfaces.base import OnboardingInterface
from app.onboarding.interfaces.steps import (
    ProviderStep,
    ApiKeyStep,
    AgentNameStep,
    MCPStep,
    SkillsStep,
)
from app.onboarding import onboarding_manager
from app.tui.settings import save_settings_to_json
from app.logger import logger

if TYPE_CHECKING:
    from app.cli.interface import CLIInterface


class CLIHardOnboarding(OnboardingInterface):
    """
    CLI implementation of hard onboarding using sequential prompts.

    Presents a step-by-step wizard via stdin/stdout:
    1. LLM Provider selection
    2. API Key input
    3. Agent name (optional)
    4. MCP server selection (optional)
    5. Skills selection (optional)

    Note: User name is collected during soft onboarding (conversational interview).
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

    async def _select_multiple(
        self, step, current_selections: List[str] = None
    ) -> List[str]:
        """Present a multi-select menu and return selections."""
        options = step.get_options()
        if not options:
            return []

        if current_selections is None:
            current_selections = []

        print(f"\n{step.title}:")
        print(f"{step.description}\n")

        selections = set(current_selections)

        for i, opt in enumerate(options, 1):
            marker = "x" if opt.value in selections else " "
            print(f"  {i}. [{marker}] {opt.label}")

        print("\nEnter numbers to toggle (comma-separated), or press Enter to continue:")

        try:
            choice = await self._async_input("> ")
        except (EOFError, KeyboardInterrupt):
            return list(selections)

        choice = choice.strip()
        if not choice:
            return list(selections)

        # Parse comma-separated numbers
        for part in choice.split(","):
            part = part.strip()
            try:
                idx = int(part) - 1
                if 0 <= idx < len(options):
                    opt_value = options[idx].value
                    if opt_value in selections:
                        selections.discard(opt_value)
                    else:
                        selections.add(opt_value)
            except ValueError:
                continue

        return list(selections)

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

            # Step 3: Agent name (optional)
            agent_name_step = AgentNameStep()
            agent_name = await self._input_text(
                agent_name_step, agent_name_step.get_default()
            )
            self._collected_data["agent_name"] = agent_name or "Agent"

            # Step 4: MCP servers (optional)
            mcp_step = MCPStep()
            mcp_options = mcp_step.get_options()
            if mcp_options:
                print("\nWould you like to configure MCP servers? (y/N)")
                try:
                    configure_mcp = await self._async_input("> ")
                except (EOFError, KeyboardInterrupt):
                    configure_mcp = "n"

                if configure_mcp.lower().startswith("y"):
                    mcp_servers = await self._select_multiple(mcp_step)
                    self._collected_data["mcp_servers"] = mcp_servers
                else:
                    self._collected_data["mcp_servers"] = []
            else:
                self._collected_data["mcp_servers"] = []

            # Step 5: Skills (optional)
            skills_step = SkillsStep()
            skills_options = skills_step.get_options()
            if skills_options:
                print("\nWould you like to configure skills? (y/N)")
                try:
                    configure_skills = await self._async_input("> ")
                except (EOFError, KeyboardInterrupt):
                    configure_skills = "n"

                if configure_skills.lower().startswith("y"):
                    skills = await self._select_multiple(skills_step)
                    self._collected_data["skills"] = skills
                else:
                    self._collected_data["skills"] = []
            else:
                self._collected_data["skills"] = []

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

        # Mark hard onboarding as complete
        agent_name = self._collected_data.get("agent_name", "Agent")
        onboarding_manager.mark_hard_complete(agent_name=agent_name)

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

        Uses the agent's trigger_soft_onboarding method which properly creates
        the task and fires a trigger to start it.
        """
        if not self._cli._agent:
            logger.warning("[CLI ONBOARDING] Cannot trigger soft onboarding: no agent reference")
            return

        agent = self._cli._agent
        task_id = await agent.trigger_soft_onboarding()
        if task_id:
            logger.info(f"[CLI ONBOARDING] Soft onboarding triggered after hard onboarding: {task_id}")

    async def trigger_soft_onboarding(self) -> Optional[str]:
        """Trigger soft onboarding by creating the interview task."""
        if not self._cli._agent:
            logger.warning(
                "[CLI ONBOARDING] Cannot trigger soft onboarding: no agent reference"
            )
            return None

        from app.onboarding.soft.task_creator import create_soft_onboarding_task

        task_id = create_soft_onboarding_task(self._cli._agent.task_manager)
        logger.info(f"[CLI ONBOARDING] Created soft onboarding task: {task_id}")
        return task_id

    def is_hard_onboarding_complete(self) -> bool:
        """Check if hard onboarding is complete."""
        return onboarding_manager.state.hard_completed

    def is_soft_onboarding_complete(self) -> bool:
        """Check if soft onboarding is complete."""
        return onboarding_manager.state.soft_completed
