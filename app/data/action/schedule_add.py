"""
schedule_add action

Add a new scheduled task or queue an immediate trigger for execution.
Used by heartbeat-processor to spawn complex proactive tasks.
"""

from agent_core import action


@action(
    name="schedule_add",
    description="Add a new scheduled task or queue an immediate trigger for execution. Use schedule='immediate' to queue a task that fires right away (useful for spawning complex proactive tasks from heartbeat-processor).",
    action_sets=["scheduler"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Human-readable name for the schedule/task",
            "example": "Morning Briefing"
        },
        "instruction": {
            "type": "string",
            "description": "What the agent should do when this schedule fires",
            "example": "Prepare and send the daily morning briefing"
        },
        "schedule": {
            "type": "string",
            "description": "Schedule expression. Use 'immediate' for instant execution, or 'every day at 7am', 'every monday at 9am', 'every 3 hours', 'every 30 minutes', or cron expressions like '0 7 * * *'",
            "example": "immediate"
        },
        "priority": {
            "type": "integer",
            "description": "Trigger priority (lower = higher priority). Default is 50.",
            "example": 50
        },
        "mode": {
            "type": "string",
            "description": "Task mode: 'simple' for quick tasks, 'complex' for multi-step tasks. Default is 'simple'.",
            "example": "complex"
        },
        "enabled": {
            "type": "boolean",
            "description": "Whether to enable the schedule immediately. Default is true. Ignored for 'immediate' schedules.",
            "example": True
        },
        "action_sets": {
            "type": "array",
            "description": "Action sets to enable for the task. If empty, will be auto-selected by LLM.",
            "example": ["file_operations", "web_research"]
        },
        "skills": {
            "type": "array",
            "description": "Skills to load for the task.",
            "example": ["day-planner"]
        },
        "payload": {
            "type": "object",
            "description": "Additional payload data to pass to the task.",
            "example": {"source": "proactive", "task_id": "daily_morning_briefing"}
        }
    },
    output_schema={
        "schedule_id": {
            "type": "string",
            "description": "The ID of the created schedule (for immediate tasks, this is the session_id)"
        },
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise"
        },
        "scheduled_for": {
            "type": "string",
            "description": "'immediate' or next fire time in ISO format"
        }
    }
)
def schedule_add(input_data: dict) -> dict:
    """Add a new scheduled task or queue an immediate trigger."""
    import app.internal_action_interface as iai
    from datetime import datetime

    scheduler = iai.InternalActionInterface.scheduler
    if scheduler is None:
        return {
            "status": "error",
            "error": "Scheduler not initialized"
        }

    try:
        name = input_data.get("name")
        instruction = input_data.get("instruction")
        schedule_expr = input_data.get("schedule")
        priority = input_data.get("priority", 50)
        mode = input_data.get("mode", "simple")
        enabled = input_data.get("enabled", True)
        action_sets = input_data.get("action_sets", [])
        skills = input_data.get("skills", [])
        payload = input_data.get("payload", {})

        if not name:
            return {"status": "error", "error": "name is required"}
        if not instruction:
            return {"status": "error", "error": "instruction is required"}
        if not schedule_expr:
            return {"status": "error", "error": "schedule is required"}

        # Handle immediate execution
        if schedule_expr.lower() == "immediate":
            return _add_immediate_trigger(
                scheduler=scheduler,
                name=name,
                instruction=instruction,
                priority=priority,
                mode=mode,
                action_sets=action_sets,
                skills=skills,
                payload=payload
            )

        # Regular scheduled task
        schedule_id = scheduler.add_schedule(
            name=name,
            instruction=instruction,
            schedule_expression=schedule_expr,
            priority=priority,
            mode=mode,
            enabled=enabled,
            action_sets=action_sets,
            skills=skills,
            payload=payload,
        )

        # Get next fire time
        schedule = scheduler.get_schedule(schedule_id)
        next_run = None
        if schedule and schedule.next_run:
            next_run = datetime.fromtimestamp(schedule.next_run).isoformat()

        return {
            "status": "ok",
            "schedule_id": schedule_id,
            "name": name,
            "scheduled_for": next_run or "unknown",
            "message": f"Schedule '{name}' created with ID: {schedule_id}"
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def _add_immediate_trigger(
    scheduler,
    name: str,
    instruction: str,
    priority: int,
    mode: str,
    action_sets: list,
    skills: list,
    payload: dict
) -> dict:
    """
    Queue a trigger for immediate execution.

    This creates a new session and queues it to the TriggerQueue
    for immediate processing by the scheduler.
    """
    import asyncio
    import time
    import uuid
    from agent_core import Trigger

    # Generate unique session ID
    session_id = f"immediate_{uuid.uuid4().hex[:8]}_{int(time.time())}"

    # Build trigger payload (matching the format used by _fire_schedule)
    trigger_payload = {
        "type": "scheduled",
        "schedule_id": f"immediate_{uuid.uuid4().hex[:8]}",
        "schedule_name": name,
        "instruction": instruction,
        "mode": mode,
        "action_sets": action_sets,
        "skills": skills,
        **payload
    }

    # Create trigger
    trigger = Trigger(
        fire_at=time.time(),  # Fire immediately
        priority=priority,
        next_action_description=f"[Immediate] {name}: {instruction}",
        payload=trigger_payload,
        session_id=session_id,
    )

    # Queue the trigger
    trigger_queue = scheduler._trigger_queue
    if trigger_queue is None:
        return {
            "status": "error",
            "error": "Trigger queue not initialized"
        }

    # Try to queue using running event loop, or create new one
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context, use create_task
        asyncio.create_task(trigger_queue.put(trigger))
    except RuntimeError:
        # No running event loop, use asyncio.run
        asyncio.run(trigger_queue.put(trigger))

    return {
        "status": "ok",
        "schedule_id": session_id,
        "name": name,
        "scheduled_for": "immediate",
        "message": f"Task '{name}' queued for immediate execution (session: {session_id})"
    }
