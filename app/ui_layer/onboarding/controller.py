"""Onboarding flow controller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type
from dataclasses import dataclass, field

from app.onboarding.interfaces.steps import (
    ProviderStep,
    ApiKeyStep,
    AgentNameStep,
    UserProfileStep,
    IntegrationStep,
    SkillsStep,
    HardOnboardingStep,
    StepOption,
)
from app.onboarding import onboarding_manager
from app.ui_layer.settings.provider_settings import save_settings_to_json
from agent_core.utils.logger import logger

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
        UserProfileStep,
        SkillsStep,
        IntegrationStep,
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
        data = self._state.collected_data
        provider = data.get("provider", "openai")
        api_key, proxied_via, submitted_or_model = self._parse_api_key(
            data.get("api_key", "")
        )
        agent_name = self._parse_agent_name(data.get("agent_name", "Agent"))
        selected_skills = data.get("skills", [])

        # Persist the provider + key (may reassign provider, e.g. a
        # geo-restricted provider routed via OpenRouter), then activate it on
        # the live LLM/VLM and image-gen interfaces.
        provider = self._save_provider(
            provider, api_key, proxied_via, submitted_or_model
        )
        self._activate_provider(provider)

        # Update controller state if available
        if self._controller:
            self._controller.state_store.dispatch("SET_PROVIDER", provider)

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

    @staticmethod
    def _parse_api_key(raw: Any) -> tuple[str, str, str]:
        """Normalize the api_key step value.

        Proxied providers (moonshot/minimax) submit a dict
        ``{api_key, via, or_model?}``; everyone else submits a plain string.
        Returns ``(api_key, proxied_via, submitted_or_model)``.
        """
        if isinstance(raw, dict):
            return (
                raw.get("api_key", ""),
                raw.get("via", "openrouter"),
                raw.get("or_model", ""),
            )
        return raw, "direct", ""

    @staticmethod
    def _subscription_connected(provider: str) -> bool:
        """True when an OAuth subscription credential is stored for ``provider``."""
        try:
            from app.ui_layer.settings.provider_settings import get_subscription_status

            return bool(get_subscription_status(provider).get("connected"))
        except Exception:
            return False

    @staticmethod
    def _parse_agent_name(raw: Any) -> str:
        """The agent-name step is a form (dict); accept plain strings too."""
        if isinstance(raw, dict):
            return raw.get("agent_name") or "Agent"
        return raw or "Agent"

    def _save_provider(
        self, provider: str, api_key: str, proxied_via: str, submitted_or_model: str
    ) -> str:
        """Persist the chosen provider + key to settings.json.

        Returns the effective provider, which differs from the input only when
        a geo-restricted provider (moonshot/minimax) is routed via OpenRouter.
        """
        if provider == "remote":
            # api_key holds the Ollama base URL for the remote provider.
            from app.ui_layer.settings.provider_settings import save_remote_endpoint

            save_remote_endpoint(api_key or "http://localhost:11434")
            return provider

        if provider in ApiKeyStep.OPENROUTER_PROXIED and api_key:
            if proxied_via != "openrouter":
                # Direct access — save the key under the native provider.
                save_settings_to_json(provider, api_key)
                return provider
            # Routed via OpenRouter — save the key as openrouter + set the slug.
            or_model = submitted_or_model or self._default_openrouter_model(provider)
            save_settings_to_json("openrouter", api_key)
            from app.ui_layer.settings.model_settings import update_model_settings

            update_model_settings(llm_model=or_model, vlm_model=or_model)
            return "openrouter"

        if provider and api_key:
            save_settings_to_json(provider, api_key)
        elif provider and self._subscription_connected(provider):
            # Subscription OAuth (ChatGPT Plus/Pro, SuperGrok) authorizes this
            # provider without an API key. Persist the provider selection so it
            # sticks even if the OAuth connect handler's own activation didn't
            # run (e.g. headless / no live agent). The OAuth bearer is sourced
            # by the factory; no key is written.
            save_settings_to_json(provider, "")
        return provider

    @staticmethod
    def _default_openrouter_model(provider: str) -> str:
        """Map a native provider's default LLM to its OpenRouter slug."""
        from agent_core.core.models.factory import _to_openrouter_slug, _OR_MODEL_MAP
        from app.models import MODEL_REGISTRY, InterfaceType

        native_model = MODEL_REGISTRY.get(provider, {}).get(InterfaceType.LLM, "")
        return _OR_MODEL_MAP.get(provider, {}).get(native_model) or _to_openrouter_slug(
            provider, native_model
        )

    def _activate_provider(self, provider: str) -> None:
        """Activate the provider on the live interfaces: reinitialize LLM/VLM,
        and point image generation at it when the provider can generate images.

        Settings persistence happens here too (image_gen_provider) so it applies
        even when no agent is attached (e.g. headless); the reinitialize calls
        are skipped without an agent.
        """
        if not provider:
            return
        agent = self._controller.agent if self._controller else None

        if agent:
            try:
                if agent.reinitialize_llm(provider):
                    logger.info(
                        f"[ONBOARDING] Reinitialized LLM with provider: {provider}"
                    )
                else:
                    logger.warning(
                        f"[ONBOARDING] Failed to reinitialize LLM with provider: {provider}"
                    )
            except Exception as e:
                logger.warning(f"[ONBOARDING] Error reinitializing LLM: {e}")

        # Point image generation at the chosen provider when it can generate
        # images (OpenAI/Gemini), reusing the key just entered — so image gen
        # works out of the box instead of being stranded on the default with no
        # key. Image-incapable providers (Anthropic, DeepSeek, Ollama, …) are
        # left on the existing image-gen default.
        try:
            from app.models import MODEL_REGISTRY, InterfaceType

            if MODEL_REGISTRY.get(provider, {}).get(InterfaceType.IMAGE_GEN):
                from app.ui_layer.settings.model_settings import update_model_settings

                update_model_settings(image_gen_provider=provider)
                if agent:
                    agent.reinitialize_image_gen(provider)
                logger.info(
                    f"[ONBOARDING] Image generation set to provider: {provider}"
                )
        except Exception as e:
            logger.warning(f"[ONBOARDING] Error configuring image gen: {e}")

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
