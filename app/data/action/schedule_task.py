"""
schedule_task action

Add a new scheduled task for execution. Supports three types:
1. Immediate: Execute right away (schedule='immediate')
2. One-time: Execute once at a specific time (e.g., 'at 3pm', 'tomorrow at 9am', 'in 2 hours')
3. Recurring: Execute on a schedule (e.g., 'every day at 7am', 'every monday at 9am')

One-time scheduled tasks are automatically removed after they fire.
"""

from agent_core import action


@action(
    name="schedule_task",
    description=(
        "Schedule a task for execution. Supports immediate, one-time, and recurring schedules. "
        "One-time tasks are auto-removed after firing.\n"
        "IMPORTANT: The 'schedule' field must use one of these EXACT formats:\n"
        "- Immediate: 'immediate'\n"
        "- One-time: 'at 3pm', 'at 3:30pm', 'at 3:30pm today', 'tomorrow at 9am', 'in 2 hours', 'in 30 minutes'\n"
        "- Recurring: 'every day at 7am', 'every day at 3:30pm', 'every monday at 9am', "
        "'every 3 hours', 'every 30 minutes', or cron like '0 7 * * *'\n"
        "DO NOT use: 'daily at', 'every weekday', 'every morning', 'weekly', or other freeform text. "
        "Only the exact patterns listed above are supported."
    ),
    action_sets=["scheduler", "core", "proactive"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Human-readable name for the schedule/task",
            "example": "Morning Briefing",
        },
        "instruction": {
            "type": "string",
            "description": "What the agent should do when this schedule fires",
            "example": "Prepare and send the daily morning briefing",
        },
        "schedule": {
            "type": "string",
            "description": (
                "Schedule expression. Must match one of these exact patterns:\n"
                "- 'immediate' — execute right now\n"
                "- 'at <time>' — e.g. 'at 3pm', 'at 3:30pm', 'at 3:30pm today'\n"
                "- 'tomorrow at <time>' — e.g. 'tomorrow at 9am'\n"
                "- 'in <N> hours' or 'in <N> minutes' — e.g. 'in 2 hours', 'in 30 minutes'\n"
                "- 'every day at <time>' — e.g. 'every day at 7am', 'every day at 3:30pm'\n"
                "- 'every <weekday> at <time>' — e.g. 'every monday at 9am'\n"
                "- 'every <N> hours' or 'every <N> minutes' — e.g. 'every 3 hours', 'every 30 minutes'\n"
                "- Cron expression — e.g. '0 7 * * *' (5-field cron)\n"
                "Times must include am/pm (e.g. '9am', '3:30pm'). "
                "Do NOT use 'daily', 'weekly', 'every weekday', 'every morning', or other freeform text."
            ),
            "example": "every day at 9am",
        },
        "priority": {
            "type": "integer",
            "description": "Trigger priority (lower = higher priority). Default is 50.",
            "example": 50,
        },
        "mode": {
            "type": "string",
            "description": "Task mode: 'simple' for quick tasks, 'complex' for multi-step tasks. Default is 'simple'.",
            "example": "complex",
        },
        "enabled": {
            "type": "boolean",
            "description": "Whether to enable the schedule immediately. Default is true. Ignored for 'immediate' schedules.",
            "example": True,
        },
        "action_sets": {
            "type": "array",
            "description": "Action sets to enable for the task. If empty, will be auto-selected by LLM.",
            "example": ["file_operations", "web_research"],
        },
        "skills": {
            "type": "array",
            "description": "Skills to load for the task.",
            "example": ["day-planner"],
        },
        "payload": {
            "type": "object",
            "description": "Additional payload data to pass to the task.",
            "example": {"source": "proactive", "task_id": "daily_morning_briefing"},
        },
    },
    output_schema={
        "schedule_id": {
            "type": "string",
            "description": "The ID of the created schedule (for immediate tasks, this is the session_id)",
        },
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise",
        },
        "recurring": {
            "type": "boolean",
            "description": "True for recurring tasks, False for one-time tasks",
        },
        "scheduled_for": {
            "type": "string",
            "description": "'immediate' or next fire time in ISO format",
        },
    },
)
async def schedule_task(input_data: dict) -> dict:
    """Add a new scheduled task or queue an immediate trigger."""
    import app.internal_action_interface as iai
    from datetime import datetime
    import asyncio
    import time
    import uuid
    from agent_core import Trigger

    scheduler = iai.InternalActionInterface.scheduler
    if scheduler is None:
        return {"status": "error", "error": "Scheduler not initialized"}

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

        # Validate schedule expression before doing anything
        if schedule_expr.lower() != "immediate":
            from app.scheduler.parser import ScheduleParser, ScheduleParseError

            try:
                ScheduleParser.parse(schedule_expr)
            except ScheduleParseError as e:
                return {
                    "status": "error",
                    "error": (
                        f"Invalid schedule expression: '{schedule_expr}'. {e} "
                        "Supported formats: 'at 3pm', 'tomorrow at 9am', 'in 2 hours', 'in 30 minutes', "
                        "'every day at 7am', 'every monday at 9am', 'every 3 hours', 'every 30 minutes', "
                        "or a cron expression like '0 7 * * *'."
                    ),
                }

        # Handle immediate execution
        if schedule_expr.lower() == "immediate":
            return await scheduler.queue_immediate_trigger(
                name=name,
                instruction=instruction,
                priority=priority,
                mode=mode,
                action_sets=action_sets,
                skills=skills,
                payload=payload,
            )

            session_id = f"immediate_{uuid.uuid4().hex[:8]}_{int(time.time())}"

            trigger_payload = {
                "type": "scheduled",
                "schedule_id": f"immediate_{uuid.uuid4().hex[:8]}",
                "schedule_name": name,
                "instruction": instruction,
                "mode": mode,
                "action_sets": action_sets,
                "skills": skills,
                **payload,
            }

            # TODO: Should not have to create additional trigger (create using queue_immediate_trigger)
            # Workaround for now
            trigger = Trigger(
                fire_at=time.time(),
                priority=priority,
                next_action_description=f"[Immediate] {name}: {instruction}",
                payload=trigger_payload,
                session_id=session_id,
            )

            trigger_queue = scheduler._trigger_queue
            if trigger_queue is None:
                return {"status": "error", "error": "Trigger queue not initialized"}

            try:
                asyncio.get_running_loop()
                asyncio.create_task(trigger_queue.put(trigger))
            except RuntimeError:
                asyncio.run(trigger_queue.put(trigger))

            return {
                "status": "ok",
                "schedule_id": session_id,
                "name": name,
                "scheduled_for": "immediate",
                "message": f"Task '{name}' queued for immediate execution (session: {session_id})",
            }

        # Parse schedule to determine if it's recurring or one-time
        from app.scheduler.parser import ScheduleParser

        parsed = ScheduleParser.parse(schedule_expr)
        is_recurring = parsed.schedule_type != "once"

        # Add scheduled task
        schedule_id = scheduler.add_schedule(
            name=name,
            instruction=instruction,
            schedule_expression=schedule_expr,
            priority=priority,
            mode=mode,
            enabled=enabled,
            recurring=is_recurring,
            action_sets=action_sets,
            skills=skills,
            payload=payload,
        )

        # Get next fire time
        schedule = scheduler.get_schedule(schedule_id)
        next_run = None
        if schedule and schedule.next_run:
            next_run = datetime.fromtimestamp(schedule.next_run).isoformat()

        task_type = "recurring" if is_recurring else "one-time"
        return {
            "status": "ok",
            "schedule_id": schedule_id,
            "name": name,
            "recurring": is_recurring,
            "scheduled_for": next_run or "unknown",
            "message": f"{task_type.capitalize()} task '{name}' scheduled with ID: {schedule_id}",
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
