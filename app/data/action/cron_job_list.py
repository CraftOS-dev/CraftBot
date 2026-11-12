from agent_core import action


@action(
    name="cron_job_list",
    description="List the cron jobs in PROACTIVE.md with their schedule, state, next run and recent outcomes. Use it to see what is configured before adding or changing a job.",
    action_sets=["proactive"],
    input_schema={
        "frequency": {
            "type": "string",
            "required": False,
            "description": "Filter by frequency: 'all', 'hourly', 'daily', 'weekly', 'monthly'. Use 'all' to get all jobs.",
            "example": "daily",
        },
        "enabled_only": {
            "type": "boolean",
            "required": False,
            "description": "Only return enabled jobs. Default is true.",
            "example": True,
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise",
        },
        "jobs": {
            "type": "array",
            "description": "Cron jobs with id, name, frequency, instruction, enabled, priority, permission_tier, time, day, last_run, next_run, run_count, recent_outcomes",
        },
        "total_count": {
            "type": "integer",
            "description": "Total number of jobs (before filtering)",
        },
    },
)
def cron_job_list(input_data: dict) -> dict:
    """List cron jobs."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {"status": "error", "error": "Proactive manager not initialized"}

    try:
        frequency = input_data.get("frequency", "all")
        enabled_only = input_data.get("enabled_only", True)

        total_count = len(manager.data.jobs)
        jobs = manager.get_jobs(
            frequency=None if frequency == "all" else frequency,
            enabled_only=enabled_only,
        )

        job_list = []
        for job in jobs:
            next_run = job.calculate_next_run()
            job_dict = {
                "id": job.id,
                "name": job.name,
                "frequency": job.frequency,
                "instruction": job.instruction,
                "enabled": job.enabled,
                "priority": job.priority,
                "permission_tier": job.permission_tier,
                "session_id": job.session_id,
                "run_count": job.run_count,
            }
            if job.time:
                job_dict["time"] = job.time
            if job.day:
                job_dict["day"] = job.day
            if job.last_run:
                job_dict["last_run"] = job.last_run.isoformat()
            if next_run:
                job_dict["next_run"] = next_run.isoformat()
            if job.conditions:
                job_dict["conditions"] = [c.to_dict() for c in job.conditions]
            if job.outcome_history:
                job_dict["recent_outcomes"] = [
                    {
                        "timestamp": o.timestamp.isoformat(),
                        "result": o.result,
                        "success": o.success,
                    }
                    for o in job.outcome_history[-3:]
                ]
            job_list.append(job_dict)

        return {
            "status": "ok",
            "jobs": job_list,
            "total_count": total_count,
            "filtered_count": len(job_list),
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
