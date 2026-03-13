# -*- coding: utf-8 -*-
"""
Onboarding module - re-exports from agent_core.

All onboarding implementations are now in agent_core.
"""

# Re-export from agent_core
from agent_core import (
    OnboardingState,
    OnboardingManager,
    onboarding_manager,
    HARD_ONBOARDING_STEPS,
    DEFAULT_AGENT_NAME,
    load_onboarding_state as load_state,
    save_onboarding_state as save_state,
)
from agent_core.core.impl.onboarding import (
    get_onboarding_config_file,
    SOFT_ONBOARDING_QUESTIONS,
)

# For backward compatibility, expose ONBOARDING_CONFIG_FILE as a property
# that calls the function (since it depends on workspace root)
def _get_config_file():
    return get_onboarding_config_file()


# Create a module-level property for backward compatibility
ONBOARDING_CONFIG_FILE = property(lambda self: get_onboarding_config_file())

__all__ = [
    "get_onboarding_config_file",
    "HARD_ONBOARDING_STEPS",
    "DEFAULT_AGENT_NAME",
    "SOFT_ONBOARDING_QUESTIONS",
    "OnboardingState",
    "load_state",
    "save_state",
    "OnboardingManager",
    "onboarding_manager",
]
