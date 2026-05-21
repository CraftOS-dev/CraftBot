"""Living UI settings management for UI layer.

Provides functions for managing Living UI project settings
that can be used by any interface adapter (Browser, TUI, CLI).
"""

from typing import Dict, Any


def get_living_ui_projects() -> Dict[str, Any]:
    """Get all Living UI projects with their settings.

    Returns:
        Dict with 'success' and 'projects' list
    """
    try:
        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {"success": True, "projects": []}

        projects = []
        for project in manager.list_projects():
            projects.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "status": project.status,
                    "port": project.port,
                    "backendPort": project.backend_port,
                    "path": project.path,
                    "autoLaunch": project.auto_launch,
                    "logCleanup": project.log_cleanup,
                }
            )

        return {"success": True, "projects": projects}
    except Exception as e:
        return {"success": False, "error": str(e), "projects": []}


def update_project_setting(project_id: str, setting: str, value: Any) -> Dict[str, Any]:
    """Update a per-project setting.

    Args:
        project_id: The project ID
        setting: Setting name ('autoLaunch', 'logCleanup')
        value: New value

    Returns:
        Dict with 'success' and optional 'error'
    """
    try:
        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {"success": False, "error": "Living UI manager not initialized"}

        project = manager.get_project(project_id)
        if not project:
            return {"success": False, "error": f"Project not found: {project_id}"}

        if setting == "autoLaunch":
            project.auto_launch = bool(value)
        elif setting == "logCleanup":
            project.log_cleanup = bool(value)
        else:
            return {"success": False, "error": f"Unknown setting: {setting}"}

        manager._save_projects()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
