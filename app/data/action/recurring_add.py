from agent_core import action


@action(
    name="recurring_add",
    description="Add a new recurring task to PROACTIVE.md. The task will be executed by the heartbeat processor at the specified frequency. IMPORTANT: Only add recurring tasks with user consent - ask the user first before adding recurring tasks.",
    action_sets=["proactive"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Human-readable task name (e.g., 'Morning Briefing', 'Weekly Review')",
            "example": "Morning Briefing"
        },
        "frequency": {
            "type": "string",
            "description": "Execution frequency: 'hourly', 'daily', 'weekly', 'monthly'",
            "example": "daily"
        },
        "instruction": {
            "type": "string",
            "description": "What the agent should do when this task fires. Be specific and actionable.",
            "example": "Check the weather and prepare a morning briefing with today's calendar and priority tasks."
        },
        "time": {
            "type": "string",
            "description": "Time of day for daily/weekly/monthly tasks in HH:MM format (24-hour). Optional for hourly.",
            "example": "07:00"
        },
        "day": {
            "type": "string",
            "description": "Day of week for weekly tasks (e.g., 'sunday', 'monday'). Optional for other frequencies.",
            "example": "sunday"
        },
        "priority": {
            "type": "integer",
            "description": "Task priority (lower = higher priority). Default is 50.",
            "example": 50
        },
        "permission_tier": {
            "type": "integer",
            "description": "Permission level 0-4. 0=silent, 1=suggest, 2=low-risk, 3=high-risk, 4=prohibited. Default is 1.",
            "example": 1
        },
        "enabled": {
            "type": "boolean",
            "description": "Whether to enable the task immediately. Default is true.",
            "example": True
        },
        "conditions": {
            "type": "array",
            "description": "Optional list of conditions for task execution. Each condition has a 'type' field.",
            "example": [{"type": "market_hours_only"}]
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise"
        },
        "task_id": {
            "type": "string",
            "description": "The ID of the created task"
        },
        "message": {
            "type": "string",
            "description": "Confirmation message"
        }
    }
)
def recurring_add(input_data: dict) -> dict:
    """Add a new recurring task."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {
            "status": "error",
            "error": "Proactive manager not initialized"
        }

    try:
        # Validate required fields
        name = input_data.get("name")
        frequency = input_data.get("frequency")
        instruction = input_data.get("instruction")

        if not name:
            return {"status": "error", "error": "name is required"}
        if not frequency:
            return {"status": "error", "error": "frequency is required"}
        if not instruction:
            return {"status": "error", "error": "instruction is required"}

        # Validate frequency
        valid_frequencies = ["hourly", "daily", "weekly", "monthly"]
        if frequency not in valid_frequencies:
            return {
                "status": "error",
                "error": f"Invalid frequency. Must be one of: {', '.join(valid_frequencies)}"
            }

        # Validate permission_tier
        permission_tier = input_data.get("permission_tier", 1)
        if not isinstance(permission_tier, int) or permission_tier < 0 or permission_tier > 3:
            return {
                "status": "error",
                "error": "permission_tier must be an integer from 0 to 3"
            }

        # Create the task
        task = manager.add_task(
            name=name,
            frequency=frequency,
            instruction=instruction,
            time=input_data.get("time"),
            day=input_data.get("day"),
            priority=input_data.get("priority", 50),
            permission_tier=permission_tier,
            enabled=input_data.get("enabled", True),
            conditions=input_data.get("conditions"),
        )

        return {
            "status": "ok",
            "task_id": task.id,
            "message": f"Recurring task '{name}' created with ID: {task.id}. "
                      f"It will run {frequency} with permission tier {permission_tier}."
        }

    except ValueError as e:
        return {
            "status": "error",
            "error": str(e)
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
