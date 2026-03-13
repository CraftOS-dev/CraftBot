from agent_core import action


@action(
    name="create_google_meet",
    description="Create a Google Calendar event with a Google Meet link.",
    action_sets=["google_workspace"],
    input_schema={
        "event_data": {"type": "object", "description": "Calendar event data with summary, start, end, conferenceData.", "example": {}},
        "calendar_id": {"type": "string", "description": "Calendar ID (default: primary).", "example": "primary"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def create_google_meet(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.create_meet_event(
            calendar_id=input_data.get("calendar_id", "primary"),
            event_data=input_data.get("event_data"),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to create event.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="check_calendar_availability",
    description="Check Google Calendar free/busy availability.",
    action_sets=["google_workspace"],
    input_schema={
        "time_min": {"type": "string", "description": "Start time in ISO 8601 format.", "example": "2024-01-15T09:00:00Z"},
        "time_max": {"type": "string", "description": "End time in ISO 8601 format.", "example": "2024-01-15T17:00:00Z"},
        "calendar_id": {"type": "string", "description": "Calendar ID (default: primary).", "example": "primary"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def check_calendar_availability(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.check_availability(
            calendar_id=input_data.get("calendar_id", "primary"),
            time_min=input_data.get("time_min"),
            time_max=input_data.get("time_max"),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to check availability.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="check_availability_and_schedule",
    description="Schedule meeting if free.",
    action_sets=["google_workspace"],
    input_schema={
        "start_time": {"type": "string", "description": "Start time.", "example": "2024-01-01T10:00:00"},
        "end_time": {"type": "string", "description": "End time.", "example": "2024-01-01T11:00:00"},
        "summary": {"type": "string", "description": "Summary.", "example": "Meeting"},
        "description": {"type": "string", "description": "Description.", "example": "Details"},
        "attendees": {"type": "array", "description": "Attendees.", "example": ["a@b.com"]},
        "from_email": {"type": "string", "description": "Sender.", "example": "me@example.com"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def check_availability_and_schedule(input_data: dict) -> dict:
    try:
        import uuid
        from datetime import datetime
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}

        start_time = datetime.fromisoformat(input_data["start_time"])
        end_time = datetime.fromisoformat(input_data["end_time"])

        # Step 1: Check availability
        avail = client.check_availability(
            calendar_id="primary",
            time_min=start_time.isoformat() + "Z",
            time_max=end_time.isoformat() + "Z",
        )

        if "error" in avail:
            return {
                "status": "error",
                "reason": "Google Calendar FreeBusy API error",
                "details": avail,
            }

        busy_slots = (
            avail.get("result", {})
            .get("calendars", {})
            .get("primary", {})
            .get("busy", [])
        )

        if busy_slots:
            return {
                "status": "busy",
                "reason": "Time slot is already occupied",
                "conflicting_events": busy_slots,
            }

        # Step 2: Schedule the meeting
        attendees = input_data.get("attendees") or []
        formatted_attendees = [{"email": a} for a in attendees]

        event_payload = {
            "summary": input_data["summary"],
            "description": input_data.get("description", ""),
            "start": {
                "dateTime": start_time.isoformat() + "Z",
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_time.isoformat() + "Z",
                "timeZone": "UTC",
            },
            "attendees": formatted_attendees,
            "conferenceData": {
                "createRequest": {
                    "requestId": f"meet-{uuid.uuid4()}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        result = client.create_meet_event(
            calendar_id="primary",
            event_data=event_payload,
        )

        if "error" in result:
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
    except Exception as e:
        return {"status": "error", "message": str(e)}
