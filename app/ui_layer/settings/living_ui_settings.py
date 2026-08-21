"""Living UI settings management for UI layer.

Provides functions for managing Living UI project settings
that can be used by any interface adapter (Browser, CLI).
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
            # Backup status (spec living-ui-backups-plan Phase 4): sidecar
            # last-run state + store totals. Fail-open — a status hiccup
            # must not blank the settings page.
            backup_status: Dict[str, Any] = {}
            try:
                from app.factory.host_craftbot import get_factory_host

                state = get_factory_host().backup_state(project.id)
                backup_status = {
                    "lastAt": state["last_at"],
                    "lastError": state["last_error"],
                    "count": len(manager.backups.store.list_backups(project.id)),
                    "totalSize": manager.backups.store.total_size(project.id),
                }
            except Exception:
                backup_status = {}
            projects.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "status": project.status,
                    "port": project.port,
                    "backendPort": project.backend_port,
                    "path": project.path,
                    "projectType": getattr(project, "project_type", "native"),
                    "autoLaunch": project.auto_launch,
                    "logCleanup": project.log_cleanup,
                    "backupsEnabled": project.backups_enabled,
                    "backupInterval": project.backup_interval,
                    "backupKeep": project.backup_keep,
                    "backupStatus": backup_status,
                }
            )

        # Orphan backup dirs (project deleted, archives kept — D5): listed
        # for manual cleanup, never auto-reaped. {id, name} — the name comes
        # from the meta.json sidecar so the user sees the app, not its id.
        orphans = []
        try:
            orphans = manager.backups.store.orphan_info(manager.projects.keys())
        except Exception:
            pass

        return {"success": True, "projects": projects, "backupOrphans": orphans}
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
        elif setting == "backupsEnabled":
            project.backups_enabled = bool(value)
        elif setting == "backupInterval":
            if value not in ("hourly", "6h", "daily", "weekly"):
                return {"success": False, "error": f"Invalid interval: {value!r}"}
            project.backup_interval = value
        elif setting == "backupKeep":
            try:
                keep = int(value)
            except (TypeError, ValueError):
                return {"success": False, "error": f"Invalid keep count: {value!r}"}
            if not 1 <= keep <= 30:
                return {"success": False, "error": "Keep count must be 1-30"}
            project.backup_keep = keep
            # Shrinking retention applies immediately, not at the next backup.
            try:
                manager.backups.store.prune(project_id, "scheduled", keep)
            except Exception:
                pass
        else:
            return {"success": False, "error": f"Unknown setting: {setting}"}

        manager._save_projects()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
