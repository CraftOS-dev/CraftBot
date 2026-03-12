from agent_core import action
from datetime import datetime

@action(
    name="scheduled_task_list",
    description="List all scheduled tasks configured in the scheduler. Returns details about each schedule including name, schedule expression, enabled status, and next/last run times.",
    action_sets=["scheduler", "core", "proactive"],
    input_schema={},
    output_schema={
        "schedules": {
            "type": "array",
            "description": "List of scheduled tasks with their details"
        },
        "total_count": {
            "type": "integer",
            "description": "Total number of schedules"
        },
        "active_count": {
            "type": "integer",
            "description": "Number of enabled schedules"
        }
    }
)
def scheduled_task_list(input_data: dict) -> dict:
    """List all scheduled tasks."""
    import app.internal_action_interface as iai

    scheduler = iai.InternalActionInterface.scheduler
    if scheduler is None:
        return {
            "status": "error",
            "error": "Scheduler not initialized"
        }

    try:
        schedules = scheduler.list_schedules()

        schedule_data = []
        for s in schedules:
            schedule_data.append({
                "id": s.id,
                "name": s.name,
                "instruction": s.instruction,
                "schedule": s.schedule.raw_expression,
                "enabled": s.enabled,
                "priority": s.priority,
                "mode": s.mode,
                "last_run": datetime.fromtimestamp(s.last_run).isoformat() if s.last_run else None,
                "next_run": datetime.fromtimestamp(s.next_run).isoformat() if s.next_run else None,
                "run_count": s.run_count,
            })

        return {
            "status": "ok",
            "schedules": schedule_data,
            "total_count": len(schedules),
            "active_count": sum(1 for s in schedules if s.enabled)
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
