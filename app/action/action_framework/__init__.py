# -*- coding: utf-8 -*-
"""Action framework - re-exports from agent_core."""

from agent_core import (
    ActionRegistry,
    ActionMetadata,
    RegisteredAction,
    action,
    registry_instance,
    load_actions_from_directories,
    PLATFORM_ALL,
    PLATFORM_LINUX,
    PLATFORM_WINDOWS,
    PLATFORM_DARWIN,
)

__all__ = [
    "ActionRegistry",
    "ActionMetadata",
    "RegisteredAction",
    "action",
    "registry_instance",
    "load_actions_from_directories",
    "PLATFORM_ALL",
    "PLATFORM_LINUX",
    "PLATFORM_WINDOWS",
    "PLATFORM_DARWIN",
]
