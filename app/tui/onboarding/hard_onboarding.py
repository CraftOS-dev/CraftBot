# -*- coding: utf-8 -*-
"""
TUI implementation of hard onboarding using Textual.
"""

from typing import Any, Dict, Optional, TYPE_CHECKING

from app.onboarding.interfaces.base import OnboardingInterface
from app.onboarding.interfaces.steps import (
    ProviderStep,
    ApiKeyStep,
    AgentNameStep,
    MCPStep,
    SkillsStep,
)
from app.onboarding import onboarding_manager
from app.tui.settings import save_settings_to_env
from app.logger import logger

if TYPE_CHECKING:
    from app.tui.app import CraftApp


class TUIHardOnboarding(OnboardingInterface):
    """
    TUI implementation of hard onboarding using Textual widgets.

    Presents a step-by-step wizard for initial configuration:
    1. LLM Provider selection
    2. API Key input
    3. Agent name (optional)
    4. MCP server selection (optional)
    5. Skills selection (optional)

    Note: User name is collected during soft onboarding (conversational interview).
    """

    def __init__(self, app: "CraftApp"):
        self._app = app
        self._collected_data: Dict[str, Any] = {}
        self._current_step = 0
        self._steps = [
            ProviderStep(),
            None,  # ApiKeyStep - created dynamically based on provider
            AgentNameStep(),
            MCPStep(),
            SkillsStep(),
        ]

    async def run_hard_onboarding(self) -> Dict[str, Any]:
        """
        Execute the hard onboarding wizard.

        This is called by the TUI app when onboarding is needed.
        The actual wizard UI is handled by the OnboardingWizardScreen.

        Returns:
            Dictionary with collected configuration data.
        """
        from app.tui.onboarding.widgets import OnboardingWizardScreen

        # Create and push the wizard screen
        screen = OnboardingWizardScreen(self)

        # The screen will call on_complete when done
        await self._app.push_screen(screen)

        return self._collected_data

    def get_step(self, index: int) -> Any:
        """Get step by index, creating ApiKeyStep dynamically if needed."""
        if index == 1:
            # Create ApiKeyStep with current provider
            provider = self._collected_data.get("provider", "openai")
            return ApiKeyStep(provider)
        return self._steps[index]

    def get_step_count(self) -> int:
        """Get total number of steps."""
        return len(self._steps)

    def set_step_data(self, step_name: str, value: Any) -> None:
        """Store data collected from a step."""
        self._collected_data[step_name] = value
        logger.debug(f"[ONBOARDING] Step {step_name} = {value if step_name != 'api_key' else '***'}")

    def get_collected_data(self) -> Dict[str, Any]:
        """Get all collected data."""
        return self._collected_data.copy()

    def on_complete(self, cancelled: bool = False) -> None:
        """
        Called when the wizard completes.

        Saves the configuration and marks hard onboarding as complete.
        """
        if cancelled:
            self._collected_data["completed"] = False
            logger.info("[ONBOARDING] Hard onboarding cancelled by user")
            return

        self._collected_data["completed"] = True

        # Save provider and API key to .env
        provider = self._collected_data.get("provider", "openai")
        api_key = self._collected_data.get("api_key", "")

        if provider and api_key:
            save_settings_to_env(provider, api_key)
            logger.info(f"[ONBOARDING] Saved provider={provider} to .env")

        # Update the app's provider and api_key
        self._app._provider = provider
        self._app._api_key = api_key
        self._app._saved_api_keys[provider] = api_key

        # Mark hard onboarding as complete
        agent_name = self._collected_data.get("agent_name", "Agent")
        onboarding_manager.mark_hard_complete(agent_name=agent_name)

        logger.info("[ONBOARDING] Hard onboarding completed successfully")

    async def trigger_soft_onboarding(self) -> Optional[str]:
        """
        Trigger soft onboarding by creating the interview task.

        Returns:
            Task ID if created successfully, None otherwise.
        """
        if not self._app._interface or not self._app._interface._agent:
            logger.warning("[ONBOARDING] Cannot trigger soft onboarding: no agent reference")
            return None

        from app.onboarding.soft.task_creator import create_soft_onboarding_task

        task_id = create_soft_onboarding_task(self._app._interface._agent.task_manager)
        logger.info(f"[ONBOARDING] Created soft onboarding task: {task_id}")
        return task_id

    def is_hard_onboarding_complete(self) -> bool:
        """Check if hard onboarding is complete."""
        return onboarding_manager.state.hard_completed

    def is_soft_onboarding_complete(self) -> bool:
        """Check if soft onboarding is complete."""
        return onboarding_manager.state.soft_completed
