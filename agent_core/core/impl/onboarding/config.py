# -*- coding: utf-8 -*-
"""
Configuration constants for the onboarding module.
"""

from pathlib import Path

from agent_core.core.config import get_workspace_root

# Default onboarding config file path relative to workspace
DEFAULT_ONBOARDING_CONFIG_FILENAME = "app/config/onboarding_config.json"


def get_onboarding_config_file() -> Path:
    """Get the path to the onboarding config file."""
    workspace = get_workspace_root()
    return Path(workspace) / DEFAULT_ONBOARDING_CONFIG_FILENAME


# Convenience for backward compatibility (computed when needed)
def _get_config_file() -> Path:
    return get_onboarding_config_file()


# Default values
DEFAULT_AGENT_NAME: str = "Agent"

# Hard onboarding steps configuration
# Each step has: id, required (must complete), title (display name)
# The user_profile step collects only the user's name; location/language are
# derived silently. Keep this list in sync with the active flow defined by
# OnboardingFlowController.STEP_CLASSES.
HARD_ONBOARDING_STEPS = [
    {"id": "intro", "required": True, "title": "Welcome"},
    {"id": "provider", "required": True, "title": "LLM Provider"},
    {"id": "api_key", "required": True, "title": "API Key"},
    {"id": "user_profile", "required": False, "title": "Your Name"},
    {"id": "agent_name", "required": False, "title": "Agent Name"},
]

# Soft onboarding interview questions template
# Identity/preferences are now collected in hard onboarding.
# Soft onboarding focuses on job/role and deep life goals exploration.
SOFT_ONBOARDING_QUESTIONS = [
    "job",  # What do you do for work?
    "life_goals",  # Deep life goals exploration (multiple rounds)
]
