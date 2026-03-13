from agent_core import action


@action(
    name="recurring_read",
    description="Read and parse recurring tasks from PROACTIVE.md. Returns tasks filtered by frequency. Use this to understand what recurring tasks are configured and their current state.",
    action_sets=["proactive"],
    input_schema={
        "frequency": {
            "type": "string",
            "description": "Filter by frequency: 'all', 'hourly', 'daily', 'weekly', 'monthly'. Use 'all' to get all tasks.",
            "example": "daily"
        },
        "enabled_only": {
            "type": "boolean",
            "description": "Only return enabled tasks. Default is true.",
            "example": True
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise"
        },
        "tasks": {
            "type": "array",
            "description": "List of recurring task objects with id, name, frequency, instruction, enabled, priority, permission_tier, last_run, next_run, run_count"
        },
        "planner_outputs": {
            "type": "object",
            "description": "Current planner outputs (day, week, month)"
        },
        "total_count": {
            "type": "integer",
            "description": "Total number of tasks (before filtering)"
        }
    }
)
def recurring_read(input_data: dict) -> dict:
    """Read recurring tasks from PROACTIVE.md."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {
            "status": "error",
            "error": "Proactive manager not initialized"
        }

    try:
        frequency = input_data.get("frequency", "all")
        enabled_only = input_data.get("enabled_only", True)

        # Get all tasks for count
        all_tasks = manager.data.tasks
        total_count = len(all_tasks)

        # Filter by frequency
        if frequency == "all":
            tasks = manager.get_tasks(frequency=None, enabled_only=enabled_only)
        else:
            tasks = manager.get_tasks(frequency=frequency, enabled_only=enabled_only)

        # Convert tasks to dictionaries
        task_list = []
        for task in tasks:
            task_dict = {
                "id": task.id,
                "name": task.name,
                "frequency": task.frequency,
                "instruction": task.instruction,
                "enabled": task.enabled,
                "priority": task.priority,
                "permission_tier": task.permission_tier,
                "run_count": task.run_count,
            }
            if task.time:
                task_dict["time"] = task.time
            if task.day:
                task_dict["day"] = task.day
            if task.last_run:
                task_dict["last_run"] = task.last_run.isoformat()
            if task.next_run:
                task_dict["next_run"] = task.next_run.isoformat()
            if task.conditions:
                task_dict["conditions"] = [c.to_dict() for c in task.conditions]
            if task.outcome_history:
                task_dict["recent_outcomes"] = [
                    {
                        "timestamp": o.timestamp.isoformat(),
                        "result": o.result,
                        "success": o.success
                    }
                    for o in task.outcome_history[-3:]  # Last 3 outcomes
                ]
            task_list.append(task_dict)

        return {
            "status": "ok",
            "tasks": task_list,
            "planner_outputs": manager.data.planner_outputs,
            "total_count": total_count,
            "filtered_count": len(task_list)
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
