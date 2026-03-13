from agent_core import action

@action(
    name="schedule_task_toggle",
    description="Enable or disable a scheduled task by its ID.",
    action_sets=["scheduler", "proactive"],
    input_schema={
        "schedule_id": {
            "type": "string",
            "description": "The ID of the schedule to toggle",
            "example": "memory-processing"
        },
        "enabled": {
            "type": "boolean",
            "description": "True to enable, False to disable",
            "example": True
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise"
        },
        "enabled": {
            "type": "boolean",
            "description": "The new enabled state of the schedule"
        }
    }
)
def schedule_task_toggle(input_data: dict) -> dict:
    """Enable or disable a scheduled task."""
    import app.internal_action_interface as iai

    scheduler = iai.InternalActionInterface.scheduler
    if scheduler is None:
        return {
            "status": "error",
            "error": "Scheduler not initialized"
        }

    try:
        schedule_id = input_data.get("schedule_id")
        enabled = input_data.get("enabled")

        if not schedule_id:
            return {"status": "error", "error": "schedule_id is required"}
        if enabled is None:
            return {"status": "error", "error": "enabled is required (true or false)"}

        # Get the schedule to verify it exists
        schedule = scheduler.get_schedule(schedule_id)
        if schedule is None:
            return {
                "status": "error",
                "error": f"Schedule '{schedule_id}' not found"
            }

        # Toggle the schedule
        if enabled:
            success = scheduler.enable_schedule(schedule_id)
        else:
            success = scheduler.disable_schedule(schedule_id)

        if success:
            action_word = "enabled" if enabled else "disabled"
            return {
                "status": "ok",
                "enabled": enabled,
                "message": f"Schedule '{schedule_id}' has been {action_word}"
            }
        else:
            return {
                "status": "error",
                "error": f"Failed to update schedule '{schedule_id}'"
            }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
