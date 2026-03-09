"""Settings module for UI layer.

Provides centralized settings management functions that can be used by
any interface adapter (Browser, TUI, CLI).

Re-exports settings from their original locations for backwards compatibility.
"""

# Re-export from existing modules
from app.tui.mcp_settings import (
    list_mcp_servers,
    add_mcp_server,
    add_mcp_server_from_json,
    remove_mcp_server,
    enable_mcp_server,
    disable_mcp_server,
    get_server_env_vars,
    update_mcp_server_env,
)

from app.tui.skill_settings import (
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

from app.tui.integration_settings import (
    list_integrations,
    get_integration_info,
    get_integration_accounts,
    connect_integration_token,
    connect_integration_oauth,
    disconnect_integration,
    get_integration_auth_type,
    get_integration_fields,
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
    # Proactive tasks
    get_proactive_tasks,
    add_proactive_task,
    update_proactive_task,
    remove_proactive_task,
    toggle_proactive_task,
    reset_proactive_tasks,
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
)

# Model settings
from app.ui_layer.settings.model_settings import (
    get_available_providers,
    get_model_settings,
    update_model_settings,
    test_connection,
    validate_can_save,
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
    "disconnect_integration",
    "get_integration_auth_type",
    "get_integration_fields",
    # General settings
    "read_agent_file",
    "write_agent_file",
    "restore_agent_file",
    "reset_agent_state",
    "get_general_settings",
    "update_general_settings",
    # Proactive mode control
    "is_proactive_enabled",
    "get_proactive_mode",
    "set_proactive_mode",
    # Proactive/scheduler settings
    "get_scheduler_config",
    "update_scheduler_config",
    "toggle_schedule",
    "toggle_schedule_runtime",
    "get_proactive_tasks",
    "add_proactive_task",
    "update_proactive_task",
    "remove_proactive_task",
    "toggle_proactive_task",
    "reset_proactive_tasks",
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
    "clear_unprocessed_events",
    "get_memory_stats",
    # Model settings
    "get_available_providers",
    "get_model_settings",
    "update_model_settings",
    "test_connection",
    "validate_can_save",
]
