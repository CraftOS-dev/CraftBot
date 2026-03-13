"""Onboarding flow controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type
from dataclasses import dataclass, field

from app.onboarding.interfaces.steps import (
    ProviderStep,
    ApiKeyStep,
    AgentNameStep,
    MCPStep,
    SkillsStep,
    HardOnboardingStep,
    StepOption,
)
from app.onboarding import onboarding_manager
from app.tui.settings import save_settings_to_env

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController


@dataclass
class OnboardingState:
    """
    Current state of the onboarding flow.

    Attributes:
        current_step: Index of the current step
        collected_data: Data collected from all steps
        completed: Whether onboarding is complete
        cancelled: Whether onboarding was cancelled
    """

    current_step: int = 0
    collected_data: Dict[str, Any] = field(default_factory=dict)
    completed: bool = False
    cancelled: bool = False


class OnboardingFlowController:
    """
    Controls the onboarding flow independent of UI.

    Interfaces implement the presentation layer and call this controller
    for the business logic. This ensures consistent onboarding behavior
    across CLI, TUI, and Browser interfaces.

    Example:
        controller = OnboardingFlowController(ui_controller)

        if controller.needs_hard_onboarding:
            # Get current step
            step = controller.get_current_step()
            options = controller.get_step_options()

            # User selects/enters value
            if controller.submit_step_value(user_value):
                if not controller.next_step():
                    # Onboarding complete
                    pass
    """

    # Steps in order of execution
    STEP_CLASSES: List[Type] = [
        ProviderStep,
        ApiKeyStep,
        AgentNameStep,
        MCPStep,
        SkillsStep,
    ]

    def __init__(self, controller: Optional["UIController"] = None) -> None:
        """
        Initialize the onboarding controller.

        Args:
            controller: Optional UI controller instance
        """
        self._controller = controller
        self._state = OnboardingState()

    @property
    def needs_hard_onboarding(self) -> bool:
        """Check if hard onboarding is needed."""
        return onboarding_manager.needs_hard_onboarding

    @property
    def needs_soft_onboarding(self) -> bool:
        """Check if soft onboarding is needed."""
        return onboarding_manager.needs_soft_onboarding

    @property
    def current_step_index(self) -> int:
        """Get the current step index (0-based)."""
        return self._state.current_step

    @property
    def total_steps(self) -> int:
        """Get the total number of steps."""
        return len(self.STEP_CLASSES)

    @property
    def is_complete(self) -> bool:
        """Check if onboarding is complete."""
        return self._state.completed

    @property
    def is_cancelled(self) -> bool:
        """Check if onboarding was cancelled."""
        return self._state.cancelled

    def get_current_step(self) -> HardOnboardingStep:
        """
        Get the current step instance.

        Returns:
            The current step instance
        """
        step_class = self.STEP_CLASSES[self._state.current_step]

        # ApiKeyStep needs the provider
        if step_class == ApiKeyStep:
            provider = self._state.collected_data.get("provider", "openai")
            return step_class(provider)

        return step_class()

    def get_step_options(self) -> List[StepOption]:
        """
        Get options for the current step.

        Returns:
            List of available options, or empty list for free-form input
        """
        return self.get_current_step().get_options()

    def get_step_default(self) -> Any:
        """
        Get the default value for the current step.

        Returns:
            Default value for the step
        """
        return self.get_current_step().get_default()

    def validate_step_value(self, value: Any) -> tuple[bool, Optional[str]]:
        """
        Validate a value for the current step.

        Args:
            value: The value to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        return self.get_current_step().validate(value)

    def submit_step_value(self, value: Any) -> bool:
        """
        Submit a value for the current step.

        Args:
            value: The value to submit

        Returns:
            True if the value is valid and was stored, False if validation failed
        """
        step = self.get_current_step()
        is_valid, error = step.validate(value)

        if not is_valid:
            return False

        # Store the value
        self._state.collected_data[step.name] = value
        return True

    def next_step(self) -> bool:
        """
        Move to the next step.

        Returns:
            True if there are more steps, False if onboarding is complete
        """
        self._state.current_step += 1

        if self._state.current_step >= len(self.STEP_CLASSES):
            self._complete()
            return False

        return True

    def previous_step(self) -> bool:
        """
        Move to the previous step.

        Returns:
            True if we moved back, False if already at the first step
        """
        if self._state.current_step <= 0:
            return False

        self._state.current_step -= 1
        return True

    def skip_step(self) -> bool:
        """
        Skip the current step (if not required).

        Returns:
            True if the step was skipped, False if the step is required
        """
        step = self.get_current_step()
        if step.required:
            return False

        return self.next_step()

    def cancel(self) -> None:
        """Cancel onboarding."""
        self._state.cancelled = True
        self._state.completed = False

    def reset(self) -> None:
        """Reset the onboarding state to start over."""
        self._state = OnboardingState()

    def get_collected_data(self) -> Dict[str, Any]:
        """
        Get all collected data.

        Returns:
            Dictionary of step name -> value
        """
        return self._state.collected_data.copy()

    def _complete(self) -> None:
        """Complete the onboarding flow."""
        self._state.completed = True

        # Extract collected data
        provider = self._state.collected_data.get("provider", "openai")
        api_key = self._state.collected_data.get("api_key", "")
        agent_name = self._state.collected_data.get("agent_name", "Agent")
        selected_mcp_servers = self._state.collected_data.get("mcp", [])
        selected_skills = self._state.collected_data.get("skills", [])

        # Save provider configuration
        if provider and api_key:
            save_settings_to_env(provider, api_key)

        # Update controller state if available
        if self._controller:
            self._controller.state_store.dispatch("SET_PROVIDER", provider)

        # Apply MCP server selections
        if selected_mcp_servers:
            from app.tui.mcp_settings import enable_mcp_server
            for server_name in selected_mcp_servers:
                enable_mcp_server(server_name)

        # Apply skill selections
        if selected_skills:
            from app.tui.skill_settings import enable_skill
            for skill_name in selected_skills:
                enable_skill(skill_name)

        # Mark hard onboarding complete
        onboarding_manager.mark_hard_complete(agent_name=agent_name)

    def get_progress_text(self) -> str:
        """
        Get a text representation of progress.

        Returns:
            Progress string like "Step 2 of 5"
        """
        return f"Step {self._state.current_step + 1} of {len(self.STEP_CLASSES)}"

    def get_step_info(self) -> Dict[str, Any]:
        """
        Get comprehensive information about the current step.

        Returns:
            Dictionary with step metadata, options, and progress
        """
        step = self.get_current_step()
        return {
            "name": step.name,
            "title": step.title,
            "description": step.description,
            "required": step.required,
            "options": self.get_step_options(),
            "default": self.get_step_default(),
            "current_index": self._state.current_step,
            "total_steps": len(self.STEP_CLASSES),
            "progress": self.get_progress_text(),
        }
