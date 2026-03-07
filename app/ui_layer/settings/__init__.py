"""Settings module for UI layer.

Re-exports MCP and skill settings from their original locations
for backwards compatibility while providing a centralized access point.
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
]
