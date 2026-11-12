from agent_core import action


@action(
    name="cron_job_update",
    description="Update a cron job in PROACTIVE.md: enable/disable it or change its instruction, frequency, time, day or priority. Re-enabling a job or changing its schedule restarts it from now. Each run is stamped automatically when the job fires; record what a run did with add_outcome.",
    action_sets=["proactive"],
    input_schema={
        "job_id": {
            "type": "string",
            "required": True,
            "description": "ID of the job to update",
            "example": "daily_morning_briefing",
        },
        "updates": {
            "type": "object",
            "required": False,
            "description": "Fields to update. Can include: enabled, priority, permission_tier, instruction, frequency, time, day, name",
            "example": {"enabled": False, "priority": 30},
        },
        "add_outcome": {
            "type": "object",
            "required": False,
            "description": "Optional outcome to add to the job's history. Include 'result' (string) and optionally 'success' (boolean, default true). Does not change when the job runs next.",
            "example": {
                "result": "Sent the morning briefing",
                "success": True,
            },
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise",
        },
        "job": {"type": "object", "description": "The updated job details"},
        "message": {"type": "string", "description": "Confirmation message"},
    },
)
def cron_job_update(input_data: dict) -> dict:
    """Update a cron job."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {"status": "error", "error": "Proactive manager not initialized"}

    try:
        job_id = input_data.get("job_id")
        if not job_id:
            return {"status": "error", "error": "job_id is required"}

        updates = input_data.get("updates", {})
        add_outcome = input_data.get("add_outcome")

        allowed_update_fields = [
            "enabled",
            "priority",
            "permission_tier",
            "instruction",
            "frequency",
            "time",
            "day",
            "name",
        ]
        invalid_fields = [k for k in updates.keys() if k not in allowed_update_fields]
        if invalid_fields:
            return {
                "status": "error",
                "error": f"Cannot update fields: {', '.join(invalid_fields)}. "
                f"Allowed: {', '.join(allowed_update_fields)}",
            }

        if "permission_tier" in updates:
            tier = updates["permission_tier"]
            if not isinstance(tier, int) or tier < 0 or tier > 1:
                return {
                    "status": "error",
                    "error": "permission_tier must be 0 (silent) or 1 (notify)",
                }

        job = manager.update_job(
            job_id=job_id,
            updates=updates if updates else None,
            add_outcome=add_outcome,
        )
        if job is None:
            return {"status": "error", "error": f"Cron job not found: {job_id}"}

        job_dict = {
            "id": job.id,
            "name": job.name,
            "frequency": job.frequency,
            "enabled": job.enabled,
            "priority": job.priority,
            "permission_tier": job.permission_tier,
            "run_count": job.run_count,
        }
        if job.last_run:
            job_dict["last_run"] = job.last_run.isoformat()

        messages = []
        if updates:
            messages.append(f"Updated fields: {', '.join(updates.keys())}")
        if add_outcome:
            messages.append("Recorded the note")

        return {
            "status": "ok",
            "job": job_dict,
            "message": ". ".join(messages) if messages else "No changes",
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
