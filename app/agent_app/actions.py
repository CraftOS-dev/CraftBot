"""Async operations on Agent App projects exposed to agent actions."""

from ._state import get_agent_app_manager


async def restart_agent_app(project_id: str) -> dict:
    """Restart a running Agent App project (backend + frontend).

    Stops the entire project and relaunches via the pipeline.
    Returns detailed errors if any step fails.
    """
    manager = get_agent_app_manager()
    if manager is None:
        return {"status": "error", "message": "Agent App manager not initialized"}

    project = manager.get_project(project_id)
    if project is None:
        return {"status": "error", "message": f"Project '{project_id}' not found"}

    # Stop the entire project (backend + frontend)
    await manager.stop_project(project_id)

    # Relaunch via the full pipeline
    result = await manager.launch_and_verify(project_id)

    if result["status"] == "success":
        return {
            "status": "success",
            "message": f"Agent App '{project_id}' restarted",
            "url": result.get("url"),
            "backend_url": result.get("backend_url"),
        }

    errors = result.get("errors", [])
    errors_str = "\n".join(errors[:10])
    return {
        "status": "error",
        "message": f"Restart failed at step: {result.get('step', 'unknown')}",
        "test_errors": errors[:10],
        "details": f"Fix these errors and call agent_app_restart again:\n{errors_str}",
    }
