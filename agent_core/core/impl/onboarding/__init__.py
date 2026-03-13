# -*- coding: utf-8 -*-
"""
Onboarding module for first-time setup and user profile configuration.

Provides:
- Hard onboarding: UI-driven multi-step wizard for initial configuration
- Soft onboarding: Conversational Q&A interview for user profile
- Modular interface abstraction for different UI implementations
"""

from agent_core.core.impl.onboarding.config import (
    get_onboarding_config_file,
    HARD_ONBOARDING_STEPS,
    DEFAULT_AGENT_NAME,
    SOFT_ONBOARDING_QUESTIONS,
)
from agent_core.core.impl.onboarding.state import (
    OnboardingState,
    load_state,
    save_state,
)
from agent_core.core.impl.onboarding.manager import (
    OnboardingManager,
    onboarding_manager,
)

__all__ = [
    # Config
    "get_onboarding_config_file",
    "HARD_ONBOARDING_STEPS",
    "DEFAULT_AGENT_NAME",
    "SOFT_ONBOARDING_QUESTIONS",
    # State
    "OnboardingState",
    "load_state",
    "save_state",
    # Manager
    "OnboardingManager",
    "onboarding_manager",
]
