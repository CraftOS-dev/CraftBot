# -*- coding: utf-8 -*-
"""
Onboarding manager singleton for coordinating onboarding lifecycle.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from agent_core.core.impl.onboarding.state import OnboardingState, load_state, save_state
from agent_core.core.impl.onboarding.config import DEFAULT_AGENT_NAME
from agent_core.utils.logger import logger

if TYPE_CHECKING:
    pass


class OnboardingManager:
    """
    Singleton manager for onboarding lifecycle.

    Handles:
    - Loading/saving onboarding state
    - Determining if onboarding is needed
    - Triggering soft onboarding task creation
    - Coordinating between hard and soft onboarding phases

    Usage:
        from agent_core.core.impl.onboarding import onboarding_manager

        if onboarding_manager.needs_hard_onboarding:
            # Show hard onboarding wizard
            ...

        if onboarding_manager.needs_soft_onboarding:
            # Trigger conversational interview
            task_id = onboarding_manager.create_soft_onboarding_task(task_manager)
    """

    _instance: Optional["OnboardingManager"] = None

    def __new__(cls) -> "OnboardingManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        # Lazy initialization - state will be loaded on first access
        self._state: Optional[OnboardingState] = None
        self._agent = None
        self._initialized = True

    def _ensure_state_loaded(self) -> OnboardingState:
        """Lazily load state on first access."""
        if self._state is None:
            self._state = load_state()
            logger.info(f"[ONBOARDING] Manager initialized: hard={self._state.hard_completed}, soft={self._state.soft_completed}")
        return self._state

    def set_agent(self, agent) -> None:
        """Set agent reference for task creation."""
        self._agent = agent

    @property
    def state(self) -> OnboardingState:
        """Get current onboarding state."""
        return self._ensure_state_loaded()

    @property
    def needs_hard_onboarding(self) -> bool:
        """Check if hard onboarding wizard is needed."""
        return self._ensure_state_loaded().needs_hard_onboarding

    @property
    def needs_soft_onboarding(self) -> bool:
        """Check if soft onboarding interview is needed."""
        return self._ensure_state_loaded().needs_soft_onboarding

    @property
    def is_complete(self) -> bool:
        """Check if all onboarding is complete."""
        return self._ensure_state_loaded().is_complete

    def mark_hard_complete(
        self,
        user_name: Optional[str] = None,
        agent_name: Optional[str] = None
    ) -> None:
        """
        Mark hard onboarding as complete.

        Args:
            user_name: User's name collected during onboarding
            agent_name: Agent's name configured during onboarding
        """
        state = self._ensure_state_loaded()
        state.hard_completed = True
        state.hard_completed_at = datetime.utcnow().isoformat()
        if user_name:
            state.user_name = user_name
        if agent_name:
            state.agent_name = agent_name
        save_state(state)
        logger.info("[ONBOARDING] Hard onboarding marked complete")

    def mark_soft_complete(self) -> None:
        """Mark soft onboarding as complete."""
        state = self._ensure_state_loaded()
        state.soft_completed = True
        state.soft_completed_at = datetime.utcnow().isoformat()
        save_state(state)
        logger.info("[ONBOARDING] Soft onboarding marked complete")

    def reset_soft_onboarding(self) -> None:
        """
        Reset soft onboarding to allow re-run via /onboarding command.
        Does not affect hard onboarding state.
        """
        state = self._ensure_state_loaded()
        state.soft_completed = False
        state.soft_completed_at = None
        save_state(state)
        logger.info("[ONBOARDING] Soft onboarding reset for re-run")

    def reset_all(self) -> None:
        """
        Reset all onboarding state (for testing/debugging).
        """
        self._state = OnboardingState()
        save_state(self._state)
        logger.info("[ONBOARDING] All onboarding state reset")

    def reload_state(self) -> None:
        """Reload state from disk (useful after external modifications)."""
        self._state = load_state()
        logger.debug("[ONBOARDING] State reloaded from disk")


# Global singleton instance
onboarding_manager = OnboardingManager()
