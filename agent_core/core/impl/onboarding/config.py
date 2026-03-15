# -*- coding: utf-8 -*-
"""
Configuration constants for the onboarding module.
"""

from pathlib import Path
from typing import Optional

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
# Note: User name is collected during soft onboarding (conversational interview)
HARD_ONBOARDING_STEPS = [
    {"id": "provider", "required": True, "title": "LLM Provider"},
    {"id": "api_key", "required": True, "title": "API Key"},
    {"id": "agent_name", "required": False, "title": "Agent Name"},
    {"id": "mcp", "required": False, "title": "MCP Servers"},
    {"id": "skills", "required": False, "title": "Skills"},
]

# Soft onboarding interview questions template
# Questions are grouped to reduce conversation turns
SOFT_ONBOARDING_QUESTIONS = [
    # Batch 1: Identity (asked together)
    "name",                        # What should I call you?
    "job",                         # What do you do for work?
    "location",                    # Where are you located? (timezone inferred from this)
    # Batch 2: Preferences (asked together)
    "tone",                        # How would you like me to communicate?
    "proactivity",                 # Should I be proactive or wait for instructions?
    "approval",                    # What actions need your approval?
    # Batch 3: Messaging
    "preferred_messaging_platform",  # Where should I send notifications? (telegram/whatsapp/discord/slack/tui)
    # Batch 4: Life goals
    "life_goals",                  # What are your life goals and what do you want help with?
]
