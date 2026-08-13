"""Settings module for UI layer.

Provides centralized settings management functions that can be used by
any interface adapter (Browser, CLI).
"""

from app.ui_layer.settings.mcp_settings import (
    list_mcp_servers,
    add_mcp_server,
    add_mcp_server_from_json,
    remove_mcp_server,
    enable_mcp_server,
    disable_mcp_server,
    get_server_env_vars,
    update_mcp_server_env,
)

from app.ui_layer.settings.skill_settings import (
    list_skills,
    get_skill_info,
    enable_skill,
    disable_skill,
    reload_skills,
    get_skill_search_directories,
    install_skill_from_path,
    install_skill_from_git,
    create_skill_scaffold,
    get_skill_template,
    remove_skill,
)

from craftos_integrations import (
    connect_token as connect_integration_token,
    connect_oauth as connect_integration_oauth,
    connect_interactive as connect_integration_interactive,
    disconnect as disconnect_integration,
    get_integration_accounts,
    get_integration_auth_type,
    get_integration_fields,
    get_integration_info_sync as get_integration_info,
    list_integrations_sync as list_integrations,
)
from craftos_integrations.integrations.whatsapp_web import (
    start_qr_session as start_whatsapp_qr_session,
    check_qr_session_status as check_whatsapp_session_status,
    cancel_qr_session as cancel_whatsapp_session,
)

# General settings
from app.ui_layer.settings.general_settings import (
    read_agent_file,
    write_agent_file,
    restore_agent_file,
    reset_agent_state,
    get_general_settings,
    update_general_settings,
)

# Agent profile bundle (import/export)
from app.ui_layer.settings.profile_bundle import (
    export_profile,
    inspect_bundle,
    import_profile,
)

# Proactive/scheduler settings
from app.ui_layer.settings.proactive_settings import (
    # Proactive mode control
    is_proactive_enabled,
    get_proactive_mode,
    set_proactive_mode,
    # Scheduler config
    get_scheduler_config,
    update_scheduler_config,
    toggle_schedule,
    toggle_schedule_runtime,
    # Recurring tasks
    get_recurring_tasks,
    add_recurring_task,
    update_recurring_task,
    remove_recurring_task,
    toggle_recurring_task,
    reset_recurring_tasks,
    reload_proactive_manager,
)

# Memory settings
from app.ui_layer.settings.memory_settings import (
    # Memory mode control
    is_memory_enabled,
    get_memory_mode,
    set_memory_mode,
    # Memory items
    get_memory_items,
    add_memory_item,
    update_memory_item,
    remove_memory_item,
    reset_memory,
    clear_unprocessed_events,
    get_memory_stats,
    # Indexed files
    get_memory_indexed_files,
    set_memory_indexed_files,
    list_indexable_candidates,
)

# Model settings
from app.ui_layer.settings.model_settings import (
    get_available_providers,
    get_model_settings,
    update_model_settings,
    test_connection,
    validate_can_save,
    get_ollama_models,
)

# Subscription OAuth (ChatGPT Plus/Pro, SuperGrok). Anthropic is excluded
# by design — Pro/Max OAuth in third-party tools is banned by Anthropic ToS.
from app.ui_layer.settings.provider_settings import (
    complete_subscription,
    connect_subscription,
    connect_subscription_async,
    disconnect_subscription,
    get_subscription_status,
    prepare_subscription_async,
)

__all__ = [
    # MCP settings
    "list_mcp_servers",
    "add_mcp_server",
    "add_mcp_server_from_json",
    "remove_mcp_server",
    "enable_mcp_server",
    "disable_mcp_server",
    "get_server_env_vars",
    "update_mcp_server_env",
    # Skill settings
    "list_skills",
    "get_skill_info",
    "enable_skill",
    "disable_skill",
    "reload_skills",
    "get_skill_search_directories",
    "install_skill_from_path",
    "install_skill_from_git",
    "create_skill_scaffold",
    "get_skill_template",
    "remove_skill",
    # Integration settings
    "list_integrations",
    "get_integration_info",
    "get_integration_accounts",
    "connect_integration_token",
    "connect_integration_oauth",
    "connect_integration_interactive",
    "disconnect_integration",
    "get_integration_auth_type",
    "get_integration_fields",
    # WhatsApp QR code flow
    "start_whatsapp_qr_session",
    "check_whatsapp_session_status",
    "cancel_whatsapp_session",
    # General settings
    "read_agent_file",
    "write_agent_file",
    "restore_agent_file",
    "reset_agent_state",
    "get_general_settings",
    "update_general_settings",
    # Agent profile bundle
    "export_profile",
    "inspect_bundle",
    "import_profile",
    # Proactive mode control
    "is_proactive_enabled",
    "get_proactive_mode",
    "set_proactive_mode",
    # Proactive/scheduler settings
    "get_scheduler_config",
    "update_scheduler_config",
    "toggle_schedule",
    "toggle_schedule_runtime",
    # Recurring tasks
    "get_recurring_tasks",
    "add_recurring_task",
    "update_recurring_task",
    "remove_recurring_task",
    "toggle_recurring_task",
    "reset_recurring_tasks",
    "reload_proactive_manager",
    # Memory mode control
    "is_memory_enabled",
    "get_memory_mode",
    "set_memory_mode",
    # Memory settings
    "get_memory_items",
    "add_memory_item",
    "update_memory_item",
    "remove_memory_item",
    "reset_memory",
    "get_memory_indexed_files",
    "set_memory_indexed_files",
    "list_indexable_candidates",
    "clear_unprocessed_events",
    "get_memory_stats",
    # Model settings
    "get_available_providers",
    "get_model_settings",
    "update_model_settings",
    "test_connection",
    "validate_can_save",
    "get_ollama_models",
    # Subscription OAuth
    "connect_subscription",
    "connect_subscription_async",
    "disconnect_subscription",
    "get_subscription_status",
    "prepare_subscription_async",
    "complete_subscription",
]
