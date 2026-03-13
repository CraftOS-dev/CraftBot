from agent_core import action


@action(
    name="recurring_update_task",
    description="Update an existing recurring task in PROACTIVE.md. Can update task properties or add execution outcomes. Use this to enable/disable tasks, change instructions, or record task execution results.",
    action_sets=["proactive"],
    input_schema={
        "task_id": {
            "type": "string",
            "description": "ID of the task to update",
            "example": "daily_morning_briefing"
        },
        "updates": {
            "type": "object",
            "description": "Fields to update. Can include: enabled, priority, permission_tier, instruction, time, day",
            "example": {"enabled": False, "priority": 30}
        },
        "add_outcome": {
            "type": "object",
            "description": "Optional outcome to add to task history. Include 'result' (string) and optionally 'success' (boolean, default true)",
            "example": {"result": "Task completed successfully", "success": True}
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise"
        },
        "task": {
            "type": "object",
            "description": "The updated task details"
        },
        "message": {
            "type": "string",
            "description": "Confirmation message"
        }
    }
)
def recurring_update_task(input_data: dict) -> dict:
    """Update an existing recurring task."""
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

        updates = input_data.get("updates", {})
        add_outcome = input_data.get("add_outcome")

        # Validate updates
        allowed_update_fields = [
            "enabled", "priority", "permission_tier", "instruction",
            "time", "day", "name"
        ]
        invalid_fields = [k for k in updates.keys() if k not in allowed_update_fields]
        if invalid_fields:
            return {
                "status": "error",
                "error": f"Cannot update fields: {', '.join(invalid_fields)}. "
                        f"Allowed: {', '.join(allowed_update_fields)}"
            }

        # Validate permission_tier if being updated
        if "permission_tier" in updates:
            tier = updates["permission_tier"]
            if not isinstance(tier, int) or tier < 0 or tier > 3:
                return {
                    "status": "error",
                    "error": "permission_tier must be an integer from 0 to 3"
                }

        # Update the task
        task = manager.update_task(
            task_id=task_id,
            updates=updates if updates else None,
            add_outcome=add_outcome
        )

        if task is None:
            return {
                "status": "error",
                "error": f"Task not found: {task_id}"
            }

        # Build response
        task_dict = {
            "id": task.id,
            "name": task.name,
            "frequency": task.frequency,
            "enabled": task.enabled,
            "priority": task.priority,
            "permission_tier": task.permission_tier,
            "run_count": task.run_count,
        }
        if task.last_run:
            task_dict["last_run"] = task.last_run.isoformat()

        # Build message
        messages = []
        if updates:
            messages.append(f"Updated fields: {', '.join(updates.keys())}")
        if add_outcome:
            messages.append("Recorded execution outcome")

        return {
            "status": "ok",
            "task": task_dict,
            "message": ". ".join(messages) if messages else "Task retrieved (no changes)"
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
