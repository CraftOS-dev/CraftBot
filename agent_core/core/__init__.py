# -*- coding: utf-8 -*-
"""Core modules for agent functionality."""

from agent_core.core.models import (
    InterfaceType,
    MODEL_REGISTRY,
    ProviderConfig,
    PROVIDER_CONFIG,
    ModelFactory,
)
from agent_core.core.embedding_interface import EmbeddingInterface
from agent_core.core.vlm_interface import VLMInterface
from agent_core.core.database_interface import DatabaseInterface
from agent_core.core.trigger import Trigger
from agent_core.core.task import Task, TodoItem, TodoStatus
from agent_core.core.action_framework import (
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
from agent_core.core.llm import (
    GeminiClient,
    GeminiAPIError,
    CacheConfig,
    get_cache_config,
    CacheMetrics,
    get_cache_metrics,
)

__all__ = [
    # Model types and factory
    "InterfaceType",
    "MODEL_REGISTRY",
    "ProviderConfig",
    "PROVIDER_CONFIG",
    "ModelFactory",
    # Interfaces
    "EmbeddingInterface",
    "VLMInterface",
    "DatabaseInterface",
    # LLM clients
    "GeminiClient",
    "GeminiAPIError",
    # Cache
    "CacheConfig",
    "get_cache_config",
    "CacheMetrics",
    "get_cache_metrics",
    # Trigger
    "Trigger",
    # Task
    "Task",
    "TodoItem",
    "TodoStatus",
    # Action framework
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
