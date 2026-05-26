"""Onboarding flow controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type
from dataclasses import dataclass, field

from app.onboarding.interfaces.steps import (
    ProviderStep,
    ApiKeyStep,
    AgentNameStep,
    UserProfileStep,
    MCPStep,
    SkillsStep,
    HardOnboardingStep,
    StepOption,
)
from app.onboarding import onboarding_manager
from app.ui_layer.settings.provider_settings import save_settings_to_json

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
    across CLI and Browser interfaces.

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
        UserProfileStep,
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
        raw_api_key_value = self._state.collected_data.get("api_key", "")
        # Proxied providers (moonshot/minimax) submit {api_key, via, or_model?}
        if isinstance(raw_api_key_value, dict):
            api_key = raw_api_key_value.get("api_key", "")
            submitted_or_model = raw_api_key_value.get("or_model", "")
            proxied_via = raw_api_key_value.get("via", "openrouter")
        else:
            api_key = raw_api_key_value
            submitted_or_model = ""
            proxied_via = "direct"
        agent_name_data = self._state.collected_data.get("agent_name", "Agent")
        # Agent name step is a form step, so the collected value is a dict.
        # Accept plain strings too for backward compatibility.
        if isinstance(agent_name_data, dict):
            agent_name = agent_name_data.get("agent_name") or "Agent"
        else:
            agent_name = agent_name_data or "Agent"
        selected_mcp_servers = self._state.collected_data.get("mcp", [])
        selected_skills = self._state.collected_data.get("skills", [])

        # Save provider configuration to settings.json
        from app.onboarding.interfaces.steps import ApiKeyStep

        if provider == "remote":
            # api_key holds the Ollama base URL for the remote provider
            remote_url = api_key or "http://localhost:11434"
            from app.ui_layer.settings.provider_settings import save_remote_endpoint

            save_remote_endpoint(remote_url)
        elif provider == "bedrock":
            # Bedrock has no api_key at the onboarding step (boto3 credential
            # chain). Still set the active provider so the agent reinitializes
            # against bedrock — explicit creds (if needed) are entered later
            # under Settings → Model → AWS Bedrock.
            save_settings_to_json("bedrock", "")
        elif provider in ApiKeyStep.OPENROUTER_PROXIED and api_key:
            if proxied_via == "openrouter":
                # User chose to go via OpenRouter — save key as openrouter and set model slug.
                if submitted_or_model:
                    or_model = submitted_or_model
                else:
                    from agent_core.core.models.factory import (
                        _to_openrouter_slug,
                        _OR_MODEL_MAP,
                    )
                    from app.models import MODEL_REGISTRY, InterfaceType

                    native_model = MODEL_REGISTRY.get(provider, {}).get(
                        InterfaceType.LLM, ""
                    )
                    or_model = _OR_MODEL_MAP.get(provider, {}).get(
                        native_model
                    ) or _to_openrouter_slug(provider, native_model)
                save_settings_to_json("openrouter", api_key)
                from app.ui_layer.settings.model_settings import update_model_settings

                update_model_settings(llm_model=or_model, vlm_model=or_model)
                provider = "openrouter"
            else:
                # User has direct access — save key under the native provider.
                save_settings_to_json(provider, api_key)
        elif provider and api_key:
            save_settings_to_json(provider, api_key)

        if provider:
            # Reinitialize the LLM with the new provider settings
            if self._controller and self._controller.agent:
                try:
                    success = self._controller.agent.reinitialize_llm(provider)
                    if success:
                        from agent_core.utils.logger import logger

                        logger.info(
                            f"[ONBOARDING] Reinitialized LLM with provider: {provider}"
                        )
                    else:
                        from agent_core.utils.logger import logger

                        logger.warning(
                            f"[ONBOARDING] Failed to reinitialize LLM with provider: {provider}"
                        )
                except Exception as e:
                    from agent_core.utils.logger import logger

                    logger.warning(f"[ONBOARDING] Error reinitializing LLM: {e}")

        # Update controller state if available
        if self._controller:
            self._controller.state_store.dispatch("SET_PROVIDER", provider)

        # Apply MCP server selections
        if selected_mcp_servers:
            from app.ui_layer.settings.mcp_settings import enable_mcp_server

            for server_name in selected_mcp_servers:
                enable_mcp_server(server_name)

        # Apply skill selections
        if selected_skills:
            from app.ui_layer.settings.skill_settings import enable_skill

            for skill_name in selected_skills:
                enable_skill(skill_name)

        # Write user profile data to USER.md (replaces _initialize_user_language)
        user_profile = self._state.collected_data.get("user_profile", {})
        if user_profile:
            from app.onboarding.profile_writer import write_profile_to_user_md

            write_profile_to_user_md(user_profile)
        else:
            # Fallback: initialize language from OS locale if profile step was skipped
            self._initialize_user_language()

        # Mark hard onboarding complete. The profile picture is already
        # persisted via the immediate-upload websocket handler; the
        # authoritative value is onboarding_manager.state.agent_profile_picture.
        user_name = user_profile.get("user_name") if user_profile else None
        success = onboarding_manager.mark_hard_complete(
            user_name=user_name,
            agent_name=agent_name,
            agent_profile_picture=onboarding_manager.state.agent_profile_picture,
        )
        if not success:
            from agent_core.utils.logger import logger

            logger.error(
                "[ONBOARDING] Failed to persist hard onboarding state — "
                "onboarding will re-trigger on next launch. "
                "Check disk space or file permissions."
            )

        # Trigger soft onboarding now that hard onboarding is done
        # This is needed because the soft onboarding check in agent.run() happens
        # before interface starts (and thus before hard onboarding completes)
        if onboarding_manager.needs_soft_onboarding and self._controller:
            import asyncio

            asyncio.create_task(self._trigger_soft_onboarding_async())

    async def _trigger_soft_onboarding_async(self) -> None:
        """
        Async helper to trigger soft onboarding after hard onboarding completes.

        Uses the agent's trigger_soft_onboarding method which properly creates
        the task and fires a trigger to start it.
        """
        if not self._controller:
            return

        agent = self._controller.agent
        task_id = await agent.trigger_soft_onboarding()
        if task_id:
            from agent_core.utils.logger import logger

            logger.info(
                f"[ONBOARDING] Soft onboarding triggered after hard onboarding: {task_id}"
            )

    def _initialize_user_language(self) -> None:
        """
        Initialize USER.md language from OS locale on first launch.

        Detects the system language, saves it to settings.json as os_language,
        and updates USER.md with the detected language.
        """
        from app.config import detect_and_save_os_language, AGENT_FILE_SYSTEM_PATH
        import re

        # Detect and save OS language
        os_lang = detect_and_save_os_language()

        # Update USER.md with the detected language
        user_md_path = AGENT_FILE_SYSTEM_PATH / "USER.md"
        if user_md_path.exists():
            try:
                content = user_md_path.read_text(encoding="utf-8")
                # Replace the Language field value
                # Pattern: - **Language**: <value>
                updated_content = re.sub(
                    r"(\*\*Language\*\*:\s*)\S+", f"\\1{os_lang}", content
                )
                user_md_path.write_text(updated_content, encoding="utf-8")
                from agent_core.utils.logger import logger

                logger.info(f"[ONBOARDING] Initialized USER.md language to: {os_lang}")
            except Exception as e:
                from agent_core.utils.logger import logger

                logger.warning(f"[ONBOARDING] Failed to update USER.md language: {e}")

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
            Dictionary with step metadata, options, progress, and form_fields
        """
        step = self.get_current_step()
        info = {
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

        # Include form fields if the step has them (e.g., UserProfileStep)
        form_fields = getattr(step, "get_form_fields", lambda: [])()
        if form_fields:
            info["form_fields"] = [
                {
                    "name": f.name,
                    "label": f.label,
                    "field_type": f.field_type,
                    "options": [
                        {
                            "value": o.value,
                            "label": o.label,
                            "description": o.description,
                            "default": o.default,
                        }
                        for o in f.options
                    ],
                    "default": f.default,
                    "placeholder": f.placeholder,
                }
                for f in form_fields
            ]

        return info
