from agent_core import action


@action(
    name="cron_job_remove",
    description="Remove a cron job from PROACTIVE.md. It will no longer run. Use this to clean up jobs that are no longer needed.",
    action_sets=["proactive"],
    input_schema={
        "job_id": {
            "type": "string",
            "required": True,
            "description": "ID of the job to remove",
            "example": "daily_morning_briefing",
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise",
        },
        "removed": {
            "type": "boolean",
            "description": "True if the job was removed, False if not found",
        },
        "message": {"type": "string", "description": "Status message"},
    },
)
def cron_job_remove(input_data: dict) -> dict:
    """Remove a cron job."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {"status": "error", "error": "Proactive manager not initialized"}

    try:
        job_id = input_data.get("job_id")
        if not job_id:
            return {"status": "error", "error": "job_id is required"}

        job = manager.get_job(job_id)
        job_name = job.name if job else job_id

        if manager.remove_job(job_id):
            return {
                "status": "ok",
                "removed": True,
                "message": f"Cron job '{job_name}' (ID: {job_id}) has been removed.",
            }
        return {
            "status": "error",
            "removed": False,
            "message": f"Cron job not found: {job_id}",
        }

    except Exception as e:
        return {"status": "error", "removed": False, "error": str(e)}
