# -*- coding: utf-8 -*-
"""
Agent Core - Core library for CraftBot.

This package provides core functionality shared between agent implementations,
including action framework, state management, LLM interfaces, and integrations.
"""

__version__ = "0.1.0"

# Re-export key classes for convenient imports
from agent_core.core.state import (
    StateProvider,
    StateRegistry,
    get_state,
    get_state_or_none,
    AgentProperties,
    ReasoningResult,
    MainState,
    DEFAULT_MAX_ACTIONS_PER_TASK,
    DEFAULT_MAX_TOKEN_PER_TASK,
)
from agent_core.core.models import (
    InterfaceType,
    MODEL_REGISTRY,
    ProviderConfig,
    PROVIDER_CONFIG,
    ModelFactory,
    test_provider_connection,
)
from agent_core.core.embedding_interface import EmbeddingInterface
from agent_core.core.vlm_interface import VLMInterface
from agent_core.core.image_gen_interface import ImageGenInterface
from agent_core.core.database_interface import DatabaseInterface
from agent_core.core.trigger import Trigger
from agent_core.core.session import (
    Session,
    SessionType,
    TodoItem,
    TodoStatus,
    MAIN_SESSION_ID,
)
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
from agent_core.core.llm.google_gemini_client import GeminiClient, GeminiAPIError
from agent_core.core.impl.llm.cache import (
    CacheConfig,
    get_cache_config,
    CacheMetrics,
    CacheMetricsEntry,
    get_cache_metrics,
    BytePlusCacheManager,
    BytePlusContextOverflowError,
    BYTEPLUS_MAX_INPUT_TOKENS,
    GeminiCacheManager,
)
from agent_core.core.action import Action, Observe
from agent_core.core.event_stream import Event, EventRecord
from agent_core.decorators import (
    profile,
    profile_loop,
    profiler,
    OperationCategory,
    ProfileContext,
    enable_profiling,
    disable_profiling,
    log_events,
)
from agent_core.core.credentials import (
    get_credential,
    get_credentials,
    has_embedded_credentials,
    run_oauth_flow,
    run_oauth_flow_async,
)
from agent_core.core.config import (
    ConfigRegistry,
    get_workspace_root,
    get_config,
    get_credential_client,
    register_credential_client,
)
from agent_core.core.registry import (
    ComponentRegistry,
    # Database
    DatabaseRegistry,
    get_database,
    get_database_or_none,
    # Action
    ActionExecutorRegistry,
    ActionManagerRegistry,
    get_action_executor,
    get_action_executor_or_none,
    get_action_manager,
    get_action_manager_or_none,
    # Memory
    MemoryRegistry,
    get_memory_manager,
    get_memory_manager_or_none,
    # LLM
    LLMInterfaceRegistry,
    get_llm_interface,
    get_llm_interface_or_none,
    # Event stream
    EventStreamRegistry,
    EventStreamManagerRegistry,
    get_event_stream,
    get_event_stream_or_none,
    get_event_stream_manager,
    get_event_stream_manager_or_none,
    # Session manager
    SessionManagerRegistry,
    get_session_manager,
    get_session_manager_or_none,
    # State manager
    StateManagerRegistry,
    get_state_manager,
    get_state_manager_or_none,
    # Context engine
    ContextEngineRegistry,
    get_context_engine,
    get_context_engine_or_none,
)
from agent_core.core.hooks import (
    OnActionStartHook,
    OnActionEndHook,
    OnEventLoggedHook,
    GetSkipEventTypesHook,
    # Token/State hooks
    GetTokenCountHook,
    SetTokenCountHook,
    # Usage reporting hooks
    UsageEventData,
    ReportUsageHook,
)

# Implementations
from agent_core.core.impl.action import (
    ActionExecutor,
    ActionLibrary,
    ActionRouter,
    ActionManager,
)
from agent_core.core.impl.memory import (
    MemoryManager,
    MemoryFileWatcher,
    MemoryPointer,
    MemoryChunk,
)
from agent_core.core.impl.llm import LLMCallType
from agent_core.core.impl.trigger import SessionTriggerQueue, QueueClosed
from agent_core.core.impl.event_stream import (
    EventStream,
    EventStreamManager,
)

# Prompts
from agent_core.core.prompts import (
    # Registry
    PromptRegistry,
    prompt_registry,
    get_prompt,
    register_prompt,
    # Event stream
    EVENT_STREAM_SUMMARIZATION_PROMPT,
    # Action prompts
    SELECT_ACTION_PROMPT,
    # Context prompts
    AGENT_ROLE_PROMPT,
    AGENT_INFO_PROMPT,
    POLICY_PROMPT,
    USER_PROFILE_PROMPT,
    ENVIRONMENTAL_CONTEXT_PROMPT,
    AGENT_FILE_SYSTEM_CONTEXT_PROMPT,
)

# MCP
from agent_core.core.impl.mcp import (
    MCPServerConfig,
    MCPConfig,
    MCPTool,
    MCPServerConnection,
    MCPClient,
    mcp_client,
    MCPActionAdapter,
    set_client_info as set_mcp_client_info,
)

# Skill
from agent_core.core.impl.skill import (
    Skill,
    SkillMetadata,
    SkillsConfig,
    SkillLoader,
    SkillManager,
    skill_manager,
)

# Onboarding
from agent_core.core.impl.onboarding import (
    OnboardingState,
    OnboardingManager,
    onboarding_manager,
    HARD_ONBOARDING_STEPS,
    DEFAULT_AGENT_NAME,
    load_state as load_onboarding_state,
    save_state as save_onboarding_state,
)

# Settings
from agent_core.core.impl.settings import (
    SettingsManager,
    settings_manager,
)

# Config Watcher
from agent_core.core.impl.config import (
    ConfigWatcher,
    config_watcher,
)

__all__ = [
    # Version
    "__version__",
    # State management
    "StateProvider",
    "StateRegistry",
    "get_state",
    "get_state_or_none",
    "AgentProperties",
    "ReasoningResult",
    "MainState",
    "DEFAULT_MAX_ACTIONS_PER_TASK",
    "DEFAULT_MAX_TOKEN_PER_TASK",
    # Model factory and types
    "InterfaceType",
    "MODEL_REGISTRY",
    "ProviderConfig",
    "PROVIDER_CONFIG",
    "ModelFactory",
    "test_provider_connection",
    # Interfaces
    "EmbeddingInterface",
    "VLMInterface",
    "ImageGenInterface",
    "DatabaseInterface",
    "GeminiClient",
    "GeminiAPIError",
    # Cache
    "CacheConfig",
    "get_cache_config",
    "CacheMetrics",
    "CacheMetricsEntry",
    "get_cache_metrics",
    "BytePlusCacheManager",
    "BytePlusContextOverflowError",
    "BYTEPLUS_MAX_INPUT_TOKENS",
    "GeminiCacheManager",
    # Action framework
    "Action",
    "Observe",
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
    # Session management
    "Session",
    "SessionType",
    "TodoItem",
    "TodoStatus",
    "MAIN_SESSION_ID",
    # Event stream
    "Event",
    "EventRecord",
    # Trigger
    "Trigger",
    # Profiling
    "profile",
    "profile_loop",
    "profiler",
    "OperationCategory",
    "ProfileContext",
    "enable_profiling",
    "disable_profiling",
    "log_events",
    # Credentials
    "get_credential",
    "get_credentials",
    "has_embedded_credentials",
    "run_oauth_flow",
    "run_oauth_flow_async",
    # Config
    "ConfigRegistry",
    "get_workspace_root",
    "get_config",
    "get_credential_client",
    "register_credential_client",
    # Component registry
    "ComponentRegistry",
    # Registries
    "DatabaseRegistry",
    "get_database",
    "get_database_or_none",
    "ActionExecutorRegistry",
    "ActionManagerRegistry",
    "get_action_executor",
    "get_action_executor_or_none",
    "get_action_manager",
    "get_action_manager_or_none",
    "MemoryRegistry",
    "get_memory_manager",
    "get_memory_manager_or_none",
    "LLMInterfaceRegistry",
    "get_llm_interface",
    "get_llm_interface_or_none",
    "EventStreamRegistry",
    "EventStreamManagerRegistry",
    "get_event_stream",
    "get_event_stream_or_none",
    "get_event_stream_manager",
    "get_event_stream_manager_or_none",
    "SessionManagerRegistry",
    "get_session_manager",
    "get_session_manager_or_none",
    "StateManagerRegistry",
    "get_state_manager",
    "get_state_manager_or_none",
    "ContextEngineRegistry",
    "get_context_engine",
    "get_context_engine_or_none",
    # Implementations
    "ActionExecutor",
    "ActionLibrary",
    "ActionRouter",
    "ActionManager",
    "MemoryManager",
    "MemoryFileWatcher",
    "MemoryPointer",
    "MemoryChunk",
    "LLMCallType",
    "SessionTriggerQueue",
    "QueueClosed",
    "EventStream",
    "EventStreamManager",
    # Prompts - Registry
    "PromptRegistry",
    "prompt_registry",
    "get_prompt",
    "register_prompt",
    # Prompts - Event stream
    "EVENT_STREAM_SUMMARIZATION_PROMPT",
    # Prompts - Action
    "SELECT_ACTION_PROMPT",
    # Prompts - Context
    "AGENT_ROLE_PROMPT",
    "AGENT_INFO_PROMPT",
    "POLICY_PROMPT",
    "USER_PROFILE_PROMPT",
    "ENVIRONMENTAL_CONTEXT_PROMPT",
    "AGENT_FILE_SYSTEM_CONTEXT_PROMPT",
    # Hooks
    "OnActionStartHook",
    "OnActionEndHook",
    "OnEventLoggedHook",
    "GetSkipEventTypesHook",
    # Token/State hooks
    "GetTokenCountHook",
    "SetTokenCountHook",
    # Usage reporting hooks
    "UsageEventData",
    "ReportUsageHook",
    # MCP
    "MCPServerConfig",
    "MCPConfig",
    "MCPTool",
    "MCPServerConnection",
    "MCPClient",
    "mcp_client",
    "MCPActionAdapter",
    "set_mcp_client_info",
    # Skill
    "Skill",
    "SkillMetadata",
    "SkillsConfig",
    "SkillLoader",
    "SkillManager",
    "skill_manager",
    # Onboarding
    "OnboardingState",
    "OnboardingManager",
    "onboarding_manager",
    "HARD_ONBOARDING_STEPS",
    "DEFAULT_AGENT_NAME",
    "load_onboarding_state",
    "save_onboarding_state",
    # Settings
    "SettingsManager",
    "settings_manager",
    # Config Watcher
    "ConfigWatcher",
    "config_watcher",
]
