from agent_core import action

@action(
    name="remove_scheduled_task",
    description="Remove a scheduled task from the scheduler by its ID.",
    action_sets=["scheduler", "core", "proactive"],
    input_schema={
        "schedule_id": {
            "type": "string",
            "description": "The ID of the schedule to remove",
            "example": "memory-processing"
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise"
        },
        "removed": {
            "type": "boolean",
            "description": "True if the schedule was removed, False if not found"
        }
    }
)
def remove_scheduled_task(input_data: dict) -> dict:
    """Remove a scheduled task."""
    import app.internal_action_interface as iai

    scheduler = iai.InternalActionInterface.scheduler
    if scheduler is None:
        return {
            "status": "error",
            "error": "Scheduler not initialized"
        }

    try:
        schedule_id = input_data.get("schedule_id")

        if not schedule_id:
            return {"status": "error", "error": "schedule_id is required"}

        removed = scheduler.remove_schedule(schedule_id)

        if removed:
            return {
                "status": "ok",
                "removed": True,
                "message": f"Schedule '{schedule_id}' has been removed"
            }
        else:
            return {
                "status": "ok",
                "removed": False,
                "message": f"Schedule '{schedule_id}' not found"
            }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
