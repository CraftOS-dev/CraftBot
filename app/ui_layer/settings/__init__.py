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
    add_mcp_server_from_template,
    remove_mcp_server,
    enable_mcp_server,
    disable_mcp_server,
    get_available_templates,
    get_template_env_vars,
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
    remove_skill,
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

__all__ = [
    # MCP settings
    "list_mcp_servers",
    "add_mcp_server",
    "add_mcp_server_from_json",
    "add_mcp_server_from_template",
    "remove_mcp_server",
    "enable_mcp_server",
    "disable_mcp_server",
    "get_available_templates",
    "get_template_env_vars",
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
    "remove_skill",
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
]
