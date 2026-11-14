from agent_core import action


@action(
    name="cron_job_add",
    description="Add a cron job to PROACTIVE.md. It runs at its own slot (hourly at :MM, daily at HH:MM, weekly on a day at HH:MM, monthly on a date at HH:MM) as a run in this chat, the one adding it. If this chat is deleted, the job is kept but does not run. A slot missed while CraftBot was off runs once, late, when it is back. IMPORTANT: Only add cron jobs with user consent - ask the user first.",
    action_sets=["proactive"],
    input_schema={
        "name": {
            "type": "string",
            "required": True,
            "description": "Human-readable job name (e.g., 'Morning Briefing', 'Weekly Review')",
            "example": "Morning Briefing",
        },
        "frequency": {
            "type": "string",
            "required": True,
            "description": "Execution frequency: 'hourly', 'daily', 'weekly', 'monthly'",
            "example": "daily",
        },
        "instruction": {
            "type": "string",
            "required": True,
            "description": "What the agent should do when this job runs. Be specific and actionable.",
            "example": "Check the weather and prepare a morning briefing with today's calendar and priority tasks.",
        },
        "time": {
            "type": "string",
            "required": False,
            "description": "Slot time in HH:MM format (24-hour); defaults to 00:00. Hourly jobs use only the minute (e.g. '00:15' runs at :15 every hour).",
            "example": "07:00",
        },
        "day": {
            "type": "string",
            "required": False,
            "description": "Weekday for weekly jobs (e.g., 'sunday'; default monday), or day of month 1-31 for monthly jobs (default 1; clamped to the month's last day).",
            "example": "sunday",
        },
        "priority": {
            "type": "integer",
            "required": False,
            "description": "Job priority (lower = higher priority). Default is 50.",
            "example": 50,
        },
        "permission_tier": {
            "type": "integer",
            "required": False,
            "description": "Permission level: 0 = silent (report only when something needs attention), 1 = notify (report the result). Default is 1.",
            "example": 1,
        },
        "enabled": {
            "type": "boolean",
            "required": False,
            "description": "Whether to enable the job immediately. Default is true.",
            "example": True,
        },
        "conditions": {
            "type": "array",
            "required": False,
            "description": "Optional list of conditions for running the job. Each condition has a 'type' field.",
            "example": [{"type": "market_hours_only"}],
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise",
        },
        "job_id": {"type": "string", "description": "The ID of the created job"},
        "message": {"type": "string", "description": "Confirmation message"},
    },
)
def cron_job_add(input_data: dict) -> dict:
    """Add a cron job."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {"status": "error", "error": "Proactive manager not initialized"}

    try:
        name = input_data.get("name")
        frequency = input_data.get("frequency")
        instruction = input_data.get("instruction")

        if not name:
            return {"status": "error", "error": "name is required"}
        if not frequency:
            return {"status": "error", "error": "frequency is required"}
        if not instruction:
            return {"status": "error", "error": "instruction is required"}

        valid_frequencies = ["hourly", "daily", "weekly", "monthly"]
        if frequency not in valid_frequencies:
            return {
                "status": "error",
                "error": f"Invalid frequency. Must be one of: {', '.join(valid_frequencies)}",
            }

        permission_tier = input_data.get("permission_tier", 1)
        if (
            not isinstance(permission_tier, int)
            or permission_tier < 0
            or permission_tier > 1
        ):
            return {
                "status": "error",
                "error": "permission_tier must be 0 (silent) or 1 (notify)",
            }

        job = manager.add_job(
            name=name,
            frequency=frequency,
            instruction=instruction,
            time=input_data.get("time"),
            day=input_data.get("day"),
            priority=input_data.get("priority", 50),
            permission_tier=permission_tier,
            enabled=input_data.get("enabled", True),
            conditions=input_data.get("conditions"),
            # The job runs in the chat that adds it.
            session_id=input_data.get("_session_id") or "main",
        )

        return {
            "status": "ok",
            "job_id": job.id,
            "message": f"Cron job '{name}' created with ID: {job.id}. "
            f"It will run {frequency} with permission tier {permission_tier}.",
        }

    except ValueError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}
