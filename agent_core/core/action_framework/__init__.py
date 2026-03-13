# -*- coding: utf-8 -*-
"""Action framework for registering and discovering actions."""

from agent_core.core.action_framework.registry import (
    ActionRegistry,
    ActionMetadata,
    RegisteredAction,
    action,
    registry_instance,
    install_all_action_requirements,
    PLATFORM_ALL,
    PLATFORM_LINUX,
    PLATFORM_WINDOWS,
    PLATFORM_DARWIN,
)
from agent_core.core.action_framework.loader import (
    load_actions_from_directories,
    DEFAULT_ACTION_PATHS,
)

__all__ = [
    # Registry classes
    "ActionRegistry",
    "ActionMetadata",
    "RegisteredAction",
    # Decorator
    "action",
    # Singleton instance
    "registry_instance",
    # Utilities
    "install_all_action_requirements",
    "load_actions_from_directories",
    "DEFAULT_ACTION_PATHS",
    # Platform constants
    "PLATFORM_ALL",
    "PLATFORM_LINUX",
    "PLATFORM_WINDOWS",
    "PLATFORM_DARWIN",
]
