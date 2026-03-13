from agent_core import action


@action(
    name="recurring_remove",
    description="Remove a recurring task from PROACTIVE.md. The task will no longer be executed by heartbeat processors. Use this to clean up tasks that are no longer needed.",
    action_sets=["proactive"],
    input_schema={
        "task_id": {
            "type": "string",
            "description": "ID of the task to remove",
            "example": "daily_morning_briefing"
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise"
        },
        "removed": {
            "type": "boolean",
            "description": "True if task was removed, False if not found"
        },
        "message": {
            "type": "string",
            "description": "Status message"
        }
    }
)
def recurring_remove(input_data: dict) -> dict:
    """Remove a recurring task."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {
            "status": "error",
            "error": "Proactive manager not initialized"
        }

    try:
        task_id = input_data.get("task_id")
        if not task_id:
            return {"status": "error", "error": "task_id is required"}

        # Get task name before removal (for message)
        task = manager.get_task(task_id)
        task_name = task.name if task else task_id

        # Remove the task
        removed = manager.remove_task(task_id)

        if removed:
            return {
                "status": "ok",
                "removed": True,
                "message": f"Recurring task '{task_name}' (ID: {task_id}) has been removed."
            }
        else:
            return {
                "status": "error",
                "removed": False,
                "message": f"Task not found: {task_id}"
            }

    except Exception as e:
        return {
            "status": "error",
            "removed": False,
            "error": str(e)
        }
