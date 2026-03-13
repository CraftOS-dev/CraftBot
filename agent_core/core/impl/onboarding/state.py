# -*- coding: utf-8 -*-
"""
Onboarding state persistence and management.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import json

from agent_core.core.impl.onboarding.config import get_onboarding_config_file
from agent_core.utils.logger import logger


@dataclass
class OnboardingState:
    """
    Tracks the completion state of onboarding phases.

    Attributes:
        hard_completed: Whether hard (UI wizard) onboarding is complete
        soft_completed: Whether soft (conversational) onboarding is complete
        hard_completed_at: ISO timestamp when hard onboarding completed
        soft_completed_at: ISO timestamp when soft onboarding completed
        user_name: User's name collected during onboarding
        agent_name: Agent's name configured during onboarding
    """
    hard_completed: bool = False
    soft_completed: bool = False
    hard_completed_at: Optional[str] = None
    soft_completed_at: Optional[str] = None
    user_name: Optional[str] = None
    agent_name: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        """Check if both onboarding phases are complete."""
        return self.hard_completed and self.soft_completed

    @property
    def needs_hard_onboarding(self) -> bool:
        """Check if hard onboarding is required."""
        return not self.hard_completed

    @property
    def needs_soft_onboarding(self) -> bool:
        """Check if soft onboarding is required (after hard is done)."""
        return self.hard_completed and not self.soft_completed

    def to_dict(self) -> dict:
        """Serialize state to dictionary for JSON storage."""
        return {
            "hard_completed": self.hard_completed,
            "soft_completed": self.soft_completed,
            "hard_completed_at": self.hard_completed_at,
            "soft_completed_at": self.soft_completed_at,
            "user_name": self.user_name,
            "agent_name": self.agent_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OnboardingState":
        """Deserialize state from dictionary."""
        return cls(
            hard_completed=data.get("hard_completed", False),
            soft_completed=data.get("soft_completed", False),
            hard_completed_at=data.get("hard_completed_at"),
            soft_completed_at=data.get("soft_completed_at"),
            user_name=data.get("user_name"),
            agent_name=data.get("agent_name"),
        )


def load_state(state_file: Optional[Path] = None) -> OnboardingState:
    """
    Load onboarding state from JSON file.

    Args:
        state_file: Path to the state file (defaults to configured path)

    Returns:
        OnboardingState object (empty state if file doesn't exist or is invalid)
    """
    if state_file is None:
        state_file = get_onboarding_config_file()

    if not state_file.exists():
        logger.debug("[ONBOARDING] No state file found, returning fresh state")
        return OnboardingState()

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        state = OnboardingState.from_dict(data)
        logger.debug(f"[ONBOARDING] Loaded state: hard={state.hard_completed}, soft={state.soft_completed}")
        return state
    except Exception as e:
        logger.warning(f"[ONBOARDING] Failed to load state: {e}, returning fresh state")
        return OnboardingState()


def save_state(state: OnboardingState, state_file: Optional[Path] = None) -> bool:
    """
    Save onboarding state to JSON file.

    Args:
        state: OnboardingState object to save
        state_file: Path to the state file (defaults to configured path)

    Returns:
        True if save succeeded, False otherwise
    """
    if state_file is None:
        state_file = get_onboarding_config_file()

    try:
        # Ensure parent directory exists
        state_file.parent.mkdir(parents=True, exist_ok=True)

        # Write state as formatted JSON
        state_file.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        logger.debug(f"[ONBOARDING] Saved state: hard={state.hard_completed}, soft={state.soft_completed}")
        return True
    except Exception as e:
        logger.error(f"[ONBOARDING] Failed to save state: {e}")
        return False
