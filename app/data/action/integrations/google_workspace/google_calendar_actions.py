from agent_core import action


@action(
    name="create_google_meet",
    description="Create a Google Calendar event with a Google Meet link.",
    action_sets=["google_calendar"],
    input_schema={
        "event_data": {
            "type": "object",
            "description": "Calendar event data with summary, start, end, conferenceData.",
            "example": {},
        },
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def create_google_meet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "create_meet_event",
        unwrap_envelope=True,
        fail_message="Failed to create event.",
        calendar_id=input_data.get("calendar_id", "primary"),
        event_data=input_data.get("event_data"),
    )


@action(
    name="check_calendar_availability",
    description="Check Google Calendar free/busy availability.",
    action_sets=["google_calendar"],
    input_schema={
        "time_min": {
            "type": "string",
            "description": "Start time in ISO 8601 format.",
            "example": "2024-01-15T09:00:00Z",
        },
        "time_max": {
            "type": "string",
            "description": "End time in ISO 8601 format.",
            "example": "2024-01-15T17:00:00Z",
        },
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def check_calendar_availability(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "check_availability",
        unwrap_envelope=True,
        fail_message="Failed to check availability.",
        calendar_id=input_data.get("calendar_id", "primary"),
        time_min=input_data.get("time_min"),
        time_max=input_data.get("time_max"),
    )


@action(
    name="check_availability_and_schedule",
    description="Schedule meeting if free.",
    action_sets=["google_calendar"],
    input_schema={
        "start_time": {
            "type": "string",
            "description": "Start time.",
            "example": "2024-01-01T10:00:00",
        },
        "end_time": {
            "type": "string",
            "description": "End time.",
            "example": "2024-01-01T11:00:00",
        },
        "summary": {"type": "string", "description": "Summary.", "example": "Meeting"},
        "description": {
            "type": "string",
            "description": "Description.",
            "example": "Details",
        },
        "attendees": {
            "type": "array",
            "description": "Attendees.",
            "example": ["a@b.com"],
        },
        "from_email": {
            "type": "string",
            "description": "Sender.",
            "example": "me@example.com",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def check_availability_and_schedule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    """Two client calls + branching ("busy" early-exit) + custom result shape."""
    import uuid
    from datetime import datetime

    try:
        start_time = datetime.fromisoformat(input_data["start_time"])
        end_time = datetime.fromisoformat(input_data["end_time"])
    except Exception as e:
        return {"status": "error", "message": str(e)}

    avail = run_client_sync(
        "google_calendar",
        "check_availability",
        unwrap_envelope=True,
        fail_message="Google Calendar FreeBusy API error",
        calendar_id="primary",
        time_min=start_time.isoformat() + "Z",
        time_max=end_time.isoformat() + "Z",
    )
    if avail["status"] == "error":
        return {
            "status": "error",
            "reason": "Google Calendar FreeBusy API error",
            "details": avail,
        }

    busy_slots = (
        avail.get("result", {}).get("calendars", {}).get("primary", {}).get("busy", [])
    )
    if busy_slots:
        return {
            "status": "busy",
            "reason": "Time slot is already occupied",
            "conflicting_events": busy_slots,
        }

    attendees = input_data.get("attendees") or []
    event_payload = {
        "summary": input_data["summary"],
        "description": input_data.get("description", ""),
        "start": {"dateTime": start_time.isoformat() + "Z", "timeZone": "UTC"},
        "end": {"dateTime": end_time.isoformat() + "Z", "timeZone": "UTC"},
        "attendees": [{"email": a} for a in attendees],
        "conferenceData": {
            "createRequest": {
                "requestId": f"meet-{uuid.uuid4()}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    result = run_client_sync(
        "google_calendar",
        "create_meet_event",
        unwrap_envelope=True,
        fail_message="Google Calendar API error",
        calendar_id="primary",
        event_data=event_payload,
    )
    if result["status"] == "error":
        return {
            "status": "error",
            "reason": "Google Calendar API error",
            "details": result,
        }
    return {
        "status": "success",
        "reason": "Meeting scheduled successfully.",
        "event": result.get("result", result),
    }
