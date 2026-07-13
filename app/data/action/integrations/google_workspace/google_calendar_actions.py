from agent_core import action


def _lean_gcal_event(ev: dict) -> dict:
    """Reduce a raw Calendar Event resource to the fields an agent acts on.

    NOTE: action handlers run via exec() on extracted source, so handlers
    import this by full module path inside the function body (module-level
    names are not in scope at handler runtime).
    """
    out = {
        k: ev.get(k)
        for k in (
            "id",
            "summary",
            "description",
            "location",
            "start",
            "end",
            "status",
            "recurrence",
            "recurringEventId",
            "htmlLink",
            "hangoutLink",
        )
        if ev.get(k) is not None
    }
    attendees = ev.get("attendees")
    if attendees:
        out["attendees"] = [
            {
                k: a.get(k)
                for k in ("email", "displayName", "responseStatus", "organizer")
                if a.get(k) is not None
            }
            for a in attendees
            if isinstance(a, dict)
        ]
    return out


# ------------------------------------------------------------------
# Convenience helpers (kept as-is for backwards-compat)
# ------------------------------------------------------------------


@action(
    name="create_google_meet",
    description="Create a Google Calendar event with a Google Meet link. Returns id, hangoutLink + key fields.",
    action_sets=["google_calendar_events", "google_calendar"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "example": {"id": "...", "hangoutLink": "https://meet.google.com/..."},
        },
    },
)
def create_google_meet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client_sync

    res = run_client_sync(
        "google_calendar",
        "create_meet_event",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create event.",
        calendar_id=input_data.get("calendar_id", "primary"),
        event_data=input_data.get("event_data"),
    )
    return pick_result(
        res, ["id", "summary", "start", "end", "htmlLink", "hangoutLink", "status"]
    )


@action(
    name="check_calendar_availability",
    description="Check Google Calendar free/busy availability.",
    action_sets=["google_calendar_events", "google_calendar"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def check_calendar_availability(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "check_availability",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to check availability.",
        calendar_id=input_data.get("calendar_id", "primary"),
        time_min=input_data.get("time_min"),
        time_max=input_data.get("time_max"),
    )


@action(
    name="check_availability_and_schedule",
    description="Schedule meeting if free.",
    action_sets=["google_calendar_events", "google_calendar"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def check_availability_and_schedule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    import uuid
    from datetime import datetime

    try:
        start_time = datetime.fromisoformat(input_data["start_time"])
        end_time = datetime.fromisoformat(input_data["end_time"])
    except Exception as e:
        return {"status": "error", "message": str(e)}

    account = input_data.get("account")
    avail = run_client_sync(
        "google_calendar",
        "check_availability",
        account=account,
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
        account=account,
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
    event = result.get("result", result)
    if isinstance(event, dict):
        event = {
            k: event.get(k)
            for k in ("id", "hangoutLink", "htmlLink", "start", "end")
            if event.get(k) is not None
        }
    return {
        "status": "success",
        "reason": "Meeting scheduled successfully.",
        "event": event,
    }


# ------------------------------------------------------------------
# Events — daily-driver event operations
# ------------------------------------------------------------------


@action(
    name="list_google_calendar_events",
    description="List events on a calendar between time_min and time_max. Returns expanded single events sorted by start time. Lean event fields by default (id, summary, description, location, start, end, status, attendees, recurrence, htmlLink, hangoutLink); set include_metadata for raw Event resources.",
    action_sets=["google_calendar_events", "google_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "time_min": {
            "type": "string",
            "description": "ISO 8601 lower bound (optional).",
            "example": "2026-05-20T00:00:00Z",
        },
        "time_max": {
            "type": "string",
            "description": "ISO 8601 upper bound (optional).",
            "example": "2026-05-27T00:00:00Z",
        },
        "max_results": {
            "type": "integer",
            "description": "Max events to return.",
            "example": 50,
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        "include_metadata": {
            "type": "boolean",
            "description": "Return full raw Event resources (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_google_calendar_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.data.action.integrations.google_workspace.google_calendar_actions import (
        _lean_gcal_event,
    )

    res = run_client_sync(
        "google_calendar",
        "list_events",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list events.",
        calendar_id=input_data.get("calendar_id", "primary"),
        time_min=input_data.get("time_min"),
        time_max=input_data.get("time_max"),
        max_results=input_data.get("max_results", 50),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        items = res.get("result")
        if isinstance(items, list):
            res = {
                **res,
                "result": [
                    _lean_gcal_event(e) for e in items if isinstance(e, dict)
                ],
            }
    return res


@action(
    name="get_google_calendar_event",
    description="Get a single event by ID. Lean event fields by default; set include_metadata for the raw Event resource.",
    action_sets=["google_calendar_events", "google_calendar"],
    input_schema={
        "event_id": {"type": "string", "description": "Event ID.", "example": ""},
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        "include_metadata": {
            "type": "boolean",
            "description": "Return the full raw Event resource (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.data.action.integrations.google_workspace.google_calendar_actions import (
        _lean_gcal_event,
    )

    res = run_client_sync(
        "google_calendar",
        "get_event",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get event.",
        event_id=input_data["event_id"],
        calendar_id=input_data.get("calendar_id", "primary"),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        ev = res.get("result")
        if isinstance(ev, dict):
            res = {**res, "result": _lean_gcal_event(ev)}
    return res


@action(
    name="create_google_calendar_event",
    description="Create a calendar event. event_data is the full Event resource (summary, start, end, attendees, etc.). Use create_google_meet for events with a Meet link. Returns id + key fields.",
    action_sets=["google_calendar_events", "google_calendar"],
    input_schema={
        "event_data": {
            "type": "object",
            "description": "Event resource: summary, description, start, end, attendees, recurrence, etc.",
            "example": {},
        },
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "send_updates": {
            "type": "string",
            "description": "none, all, or externalOnly — who gets notified.",
            "example": "none",
        },
        "supports_attachments": {
            "type": "boolean",
            "description": "Set true if event_data includes attachments.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client_sync

    res = run_client_sync(
        "google_calendar",
        "insert_event",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create event.",
        calendar_id=input_data.get("calendar_id", "primary"),
        event_data=input_data["event_data"],
        send_updates=input_data.get("send_updates", "none"),
        supports_attachments=bool(input_data.get("supports_attachments", False)),
    )
    return pick_result(
        res, ["id", "summary", "start", "end", "htmlLink", "hangoutLink", "status"]
    )


@action(
    name="update_google_calendar_event",
    description="Replace an event entirely (PUT). For partial updates use patch_google_calendar_event. Returns id + key fields.",
    action_sets=["google_calendar_events", "google_calendar"],
    input_schema={
        "event_id": {"type": "string", "description": "Event ID.", "example": ""},
        "event_data": {
            "type": "object",
            "description": "Full Event resource — replaces existing.",
            "example": {},
        },
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "send_updates": {
            "type": "string",
            "description": "none, all, externalOnly.",
            "example": "none",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client_sync

    res = run_client_sync(
        "google_calendar",
        "update_event",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to update event.",
        calendar_id=input_data.get("calendar_id", "primary"),
        event_id=input_data["event_id"],
        event_data=input_data["event_data"],
        send_updates=input_data.get("send_updates", "none"),
    )
    return pick_result(
        res, ["id", "summary", "start", "end", "htmlLink", "hangoutLink", "status"]
    )


@action(
    name="patch_google_calendar_event",
    description="Patch (partial update) an event. event_data contains ONLY the fields to change. Returns id + key fields.",
    action_sets=["google_calendar_events", "google_calendar"],
    input_schema={
        "event_id": {"type": "string", "description": "Event ID.", "example": ""},
        "event_data": {
            "type": "object",
            "description": "Partial event fields to update.",
            "example": {"summary": "New title"},
        },
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "send_updates": {
            "type": "string",
            "description": "none, all, externalOnly.",
            "example": "none",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def patch_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client_sync

    res = run_client_sync(
        "google_calendar",
        "patch_event",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to patch event.",
        calendar_id=input_data.get("calendar_id", "primary"),
        event_id=input_data["event_id"],
        event_data=input_data["event_data"],
        send_updates=input_data.get("send_updates", "none"),
    )
    return pick_result(
        res, ["id", "summary", "start", "end", "htmlLink", "hangoutLink", "status"]
    )


@action(
    name="delete_google_calendar_event",
    description="Delete a calendar event.",
    action_sets=["google_calendar_events", "google_calendar"],
    input_schema={
        "event_id": {"type": "string", "description": "Event ID.", "example": ""},
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "delete_event",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to delete event.",
        event_id=input_data["event_id"],
        calendar_id=input_data.get("calendar_id", "primary"),
    )


@action(
    name="move_google_calendar_event",
    description="Move an event from one calendar to another. Returns id + key fields.",
    action_sets=["google_calendar_events"],
    input_schema={
        "event_id": {"type": "string", "description": "Event ID.", "example": ""},
        "calendar_id": {
            "type": "string",
            "description": "Current calendar ID.",
            "example": "primary",
        },
        "destination_calendar_id": {
            "type": "string",
            "description": "Target calendar ID.",
            "example": "",
        },
        "send_updates": {
            "type": "string",
            "description": "none, all, externalOnly.",
            "example": "none",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def move_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client_sync

    res = run_client_sync(
        "google_calendar",
        "move_event",
        unwrap_envelope=True,
        fail_message="Failed to move event.",
        event_id=input_data["event_id"],
        calendar_id=input_data.get("calendar_id", "primary"),
        destination_calendar_id=input_data["destination_calendar_id"],
        send_updates=input_data.get("send_updates", "none"),
    )
    return pick_result(
        res, ["id", "summary", "start", "end", "htmlLink", "hangoutLink", "status"]
    )


@action(
    name="quick_add_google_calendar_event",
    description="Create an event from a natural-language string (e.g. 'Lunch with Alice tomorrow at noon'). Returns id + key fields.",
    action_sets=["google_calendar_events", "google_calendar"],
    input_schema={
        "text": {
            "type": "string",
            "description": "Natural-language event description.",
            "example": "Lunch with Alice tomorrow at noon",
        },
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "send_updates": {
            "type": "string",
            "description": "none, all, externalOnly.",
            "example": "none",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def quick_add_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client_sync

    res = run_client_sync(
        "google_calendar",
        "quick_add_event",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to quick-add event.",
        calendar_id=input_data.get("calendar_id", "primary"),
        text=input_data["text"],
        send_updates=input_data.get("send_updates", "none"),
    )
    return pick_result(
        res, ["id", "summary", "start", "end", "htmlLink", "hangoutLink", "status"]
    )


@action(
    name="list_google_calendar_event_instances",
    description="Expand a recurring event into its individual instances. Lean event fields by default; set include_metadata for raw Event resources.",
    action_sets=["google_calendar_events"],
    input_schema={
        "event_id": {
            "type": "string",
            "description": "Recurring event ID.",
            "example": "",
        },
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "time_min": {
            "type": "string",
            "description": "ISO 8601 lower bound (optional).",
            "example": "",
        },
        "time_max": {
            "type": "string",
            "description": "ISO 8601 upper bound (optional).",
            "example": "",
        },
        "max_results": {
            "type": "integer",
            "description": "Max instances.",
            "example": 50,
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return full raw Event resources (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_google_calendar_event_instances(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.data.action.integrations.google_workspace.google_calendar_actions import (
        _lean_gcal_event,
    )

    res = run_client_sync(
        "google_calendar",
        "list_event_instances",
        unwrap_envelope=True,
        fail_message="Failed to list instances.",
        calendar_id=input_data.get("calendar_id", "primary"),
        event_id=input_data["event_id"],
        time_min=input_data.get("time_min"),
        time_max=input_data.get("time_max"),
        max_results=input_data.get("max_results", 50),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        result = res.get("result")
        if isinstance(result, dict) and isinstance(result.get("instances"), list):
            res = {
                **res,
                "result": {
                    "instances": [
                        _lean_gcal_event(e)
                        for e in result["instances"]
                        if isinstance(e, dict)
                    ]
                },
            }
    return res


@action(
    name="import_google_calendar_event",
    description="Import a pre-existing event (with its own iCal UID) into a calendar — preserves identity across calendars. Distinct from create. Returns id + key fields.",
    action_sets=["google_calendar_events"],
    input_schema={
        "event_data": {
            "type": "object",
            "description": "Event resource including iCalUID.",
            "example": {},
        },
        "calendar_id": {
            "type": "string",
            "description": "Target calendar ID.",
            "example": "primary",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def import_google_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client_sync

    res = run_client_sync(
        "google_calendar",
        "import_event",
        unwrap_envelope=True,
        fail_message="Failed to import event.",
        calendar_id=input_data.get("calendar_id", "primary"),
        event_data=input_data["event_data"],
    )
    return pick_result(
        res, ["id", "summary", "start", "end", "htmlLink", "hangoutLink", "status"]
    )


# ------------------------------------------------------------------
# Calendars (the calendar resources themselves)
# ------------------------------------------------------------------


@action(
    name="list_google_calendars",
    description="List calendars the user has access to (from their calendarList).",
    action_sets=["google_calendar_admin", "google_calendar"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_google_calendars(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "list_calendars",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list calendars.",
    )


@action(
    name="get_google_calendar",
    description="Get metadata for a single calendar (summary, timezone, description).",
    action_sets=["google_calendar_admin", "google_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "get_calendar",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get calendar.",
        calendar_id=input_data.get("calendar_id", "primary"),
    )


@action(
    name="create_google_calendar",
    description="Create a new (secondary) calendar owned by the authenticated user.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "summary": {
            "type": "string",
            "description": "Calendar name.",
            "example": "Team events",
        },
        "description": {
            "type": "string",
            "description": "Description (optional).",
            "example": "",
        },
        "time_zone": {
            "type": "string",
            "description": "IANA tz (optional, e.g. Asia/Tokyo).",
            "example": "UTC",
        },
        "location": {
            "type": "string",
            "description": "Default location (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "create_calendar",
        unwrap_envelope=True,
        fail_message="Failed to create calendar.",
        summary=input_data["summary"],
        description=input_data.get("description") or None,
        time_zone=input_data.get("time_zone") or None,
        location=input_data.get("location") or None,
    )


@action(
    name="update_google_calendar",
    description="Replace a calendar's metadata (PUT). For partial updates use patch_google_calendar.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar ID.", "example": ""},
        "summary": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "description": {
            "type": "string",
            "description": "New description (optional).",
            "example": "",
        },
        "time_zone": {
            "type": "string",
            "description": "New IANA tz (optional).",
            "example": "",
        },
        "location": {
            "type": "string",
            "description": "New location (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "update_calendar",
        unwrap_envelope=True,
        fail_message="Failed to update calendar.",
        calendar_id=input_data["calendar_id"],
        summary=input_data.get("summary") or None,
        description=input_data["description"] if "description" in input_data else None,
        time_zone=input_data.get("time_zone") or None,
        location=input_data["location"] if "location" in input_data else None,
    )


@action(
    name="patch_google_calendar",
    description="Patch (partial update) a calendar's metadata.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar ID.", "example": ""},
        "summary": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "description": {
            "type": "string",
            "description": "New description (optional).",
            "example": "",
        },
        "time_zone": {
            "type": "string",
            "description": "New IANA tz (optional).",
            "example": "",
        },
        "location": {
            "type": "string",
            "description": "New location (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def patch_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "patch_calendar",
        unwrap_envelope=True,
        fail_message="Failed to patch calendar.",
        calendar_id=input_data["calendar_id"],
        summary=input_data.get("summary") or None,
        description=input_data["description"] if "description" in input_data else None,
        time_zone=input_data.get("time_zone") or None,
        location=input_data["location"] if "location" in input_data else None,
    )


@action(
    name="delete_google_calendar",
    description="DELETE a secondary calendar. Cannot be used on the primary calendar.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID to delete.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "delete_calendar",
        unwrap_envelope=True,
        fail_message="Failed to delete calendar.",
        calendar_id=input_data["calendar_id"],
    )


@action(
    name="clear_google_calendar",
    description="Delete ALL events on the user's PRIMARY calendar. Irreversible. No-op on secondary calendars.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Must be 'primary'.",
            "example": "primary",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def clear_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "clear_calendar",
        unwrap_envelope=True,
        fail_message="Failed to clear calendar.",
        calendar_id=input_data.get("calendar_id", "primary"),
    )


# ------------------------------------------------------------------
# CalendarList (the user's view of calendars: subscriptions, colors, visibility)
# ------------------------------------------------------------------


@action(
    name="get_google_calendar_list_entry",
    description="Get the user's per-calendar settings (color, visibility, summary override).",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_calendar_list_entry(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "get_calendar_list_entry",
        unwrap_envelope=True,
        fail_message="Failed to get calendar list entry.",
        calendar_id=input_data["calendar_id"],
    )


@action(
    name="subscribe_google_calendar",
    description="Subscribe to (add to the user's calendar list) an existing calendar by ID.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID to subscribe to.",
            "example": "",
        },
        "color_id": {
            "type": "string",
            "description": "Color ID from get_google_calendar_colors (optional).",
            "example": "",
        },
        "summary_override": {
            "type": "string",
            "description": "User-side display name (optional).",
            "example": "",
        },
        "selected": {
            "type": "boolean",
            "description": "Show in UI (optional).",
            "example": True,
        },
        "hidden": {
            "type": "boolean",
            "description": "Hide from UI (optional).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def subscribe_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "subscribe_calendar",
        unwrap_envelope=True,
        fail_message="Failed to subscribe to calendar.",
        calendar_id=input_data["calendar_id"],
        color_id=input_data.get("color_id") or None,
        summary_override=input_data.get("summary_override") or None,
        selected=input_data["selected"] if "selected" in input_data else None,
        hidden=input_data["hidden"] if "hidden" in input_data else None,
    )


@action(
    name="update_google_calendar_list_entry",
    description="Update the user's per-calendar settings (color, visibility, display name).",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar ID.", "example": ""},
        "color_id": {
            "type": "string",
            "description": "Color ID (optional).",
            "example": "",
        },
        "summary_override": {
            "type": "string",
            "description": "Display name (optional).",
            "example": "",
        },
        "selected": {
            "type": "boolean",
            "description": "Show in UI (optional).",
            "example": True,
        },
        "hidden": {
            "type": "boolean",
            "description": "Hide from UI (optional).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_google_calendar_list_entry(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "update_calendar_list_entry",
        unwrap_envelope=True,
        fail_message="Failed to update calendar list entry.",
        calendar_id=input_data["calendar_id"],
        color_id=input_data.get("color_id") or None,
        summary_override=input_data["summary_override"]
        if "summary_override" in input_data
        else None,
        selected=input_data["selected"] if "selected" in input_data else None,
        hidden=input_data["hidden"] if "hidden" in input_data else None,
    )


@action(
    name="unsubscribe_google_calendar",
    description="Remove a calendar from the user's calendar list. Does NOT delete the calendar itself.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID to unsubscribe from.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unsubscribe_google_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "unsubscribe_calendar",
        unwrap_envelope=True,
        fail_message="Failed to unsubscribe.",
        calendar_id=input_data["calendar_id"],
    )


# ------------------------------------------------------------------
# ACL (per-calendar sharing)
# ------------------------------------------------------------------


@action(
    name="list_google_calendar_acl",
    description="List ACL rules (who has what access) on a calendar.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_google_calendar_acl(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "list_calendar_acl",
        unwrap_envelope=True,
        fail_message="Failed to list ACL.",
        calendar_id=input_data.get("calendar_id", "primary"),
    )


@action(
    name="get_google_calendar_acl_rule",
    description="Get a single ACL rule by ID.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID.",
            "example": "primary",
        },
        "rule_id": {"type": "string", "description": "ACL rule ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_calendar_acl_rule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "get_calendar_acl_rule",
        unwrap_envelope=True,
        fail_message="Failed to get ACL rule.",
        calendar_id=input_data.get("calendar_id", "primary"),
        rule_id=input_data["rule_id"],
    )


@action(
    name="add_google_calendar_acl_rule",
    description="Grant calendar access. scope_type: user/group/domain/default. role: none/freeBusyReader/reader/writer/owner.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID (default: primary).",
            "example": "primary",
        },
        "scope_type": {
            "type": "string",
            "description": "user, group, domain, or default.",
            "example": "user",
        },
        "scope_value": {
            "type": "string",
            "description": "Email, group address, or domain (empty for 'default').",
            "example": "alice@example.com",
        },
        "role": {
            "type": "string",
            "description": "none, freeBusyReader, reader, writer, or owner.",
            "example": "reader",
        },
        "send_notifications": {
            "type": "boolean",
            "description": "Email the grantee.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_google_calendar_acl_rule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "add_calendar_acl_rule",
        unwrap_envelope=True,
        fail_message="Failed to add ACL rule.",
        calendar_id=input_data.get("calendar_id", "primary"),
        scope_type=input_data["scope_type"],
        scope_value=input_data.get("scope_value", ""),
        role=input_data["role"],
        send_notifications=bool(input_data.get("send_notifications", True)),
    )


@action(
    name="update_google_calendar_acl_rule",
    description="Change the role of an existing ACL rule.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID.",
            "example": "primary",
        },
        "rule_id": {"type": "string", "description": "ACL rule ID.", "example": ""},
        "role": {"type": "string", "description": "New role.", "example": "writer"},
        "scope_type": {
            "type": "string",
            "description": "New scope type (optional).",
            "example": "",
        },
        "scope_value": {
            "type": "string",
            "description": "New scope value (optional).",
            "example": "",
        },
        "send_notifications": {
            "type": "boolean",
            "description": "Email the grantee.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_google_calendar_acl_rule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "update_calendar_acl_rule",
        unwrap_envelope=True,
        fail_message="Failed to update ACL rule.",
        calendar_id=input_data.get("calendar_id", "primary"),
        rule_id=input_data["rule_id"],
        role=input_data["role"],
        scope_type=input_data.get("scope_type") or None,
        scope_value=input_data.get("scope_value") or None,
        send_notifications=bool(input_data.get("send_notifications", True)),
    )


@action(
    name="delete_google_calendar_acl_rule",
    description="Revoke access by deleting an ACL rule.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar ID.",
            "example": "primary",
        },
        "rule_id": {"type": "string", "description": "ACL rule ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_calendar_acl_rule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "delete_calendar_acl_rule",
        unwrap_envelope=True,
        fail_message="Failed to delete ACL rule.",
        calendar_id=input_data.get("calendar_id", "primary"),
        rule_id=input_data["rule_id"],
    )


# ------------------------------------------------------------------
# Settings & colors
# ------------------------------------------------------------------


@action(
    name="list_google_calendar_settings",
    description="List the authenticated user's Calendar settings (timezone, locale, weekStart, etc.) as a dict.",
    action_sets=["google_calendar_admin"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_google_calendar_settings(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "list_calendar_settings",
        unwrap_envelope=True,
        fail_message="Failed to list settings.",
    )


@action(
    name="get_google_calendar_setting",
    description="Get a single user setting by ID. Common IDs: timezone, locale, autoAddHangouts, weekStart.",
    action_sets=["google_calendar_admin"],
    input_schema={
        "setting_id": {
            "type": "string",
            "description": "Setting ID.",
            "example": "timezone",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_calendar_setting(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "get_calendar_setting",
        unwrap_envelope=True,
        fail_message="Failed to get setting.",
        setting_id=input_data["setting_id"],
    )


@action(
    name="get_google_calendar_colors",
    description="Get the color palette available for calendars and events (color_id → hex map).",
    action_sets=["google_calendar_admin"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_calendar_colors(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_calendar",
        "get_calendar_colors",
        unwrap_envelope=True,
        fail_message="Failed to get colors.",
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Push notifications / watch endpoints (events.watch, calendarList.watch, ...)
#     Server-side webhook setup for incremental sync. Not a per-interaction action;
#     the host environment would own webhook plumbing if needed.
# - Conference data providers beyond hangoutsMeet
#     Add-on/3rd-party conference data (Zoom/Webex via add-ons) is configured in
#     the event_data payload by the agent — no separate endpoint needed.
# - Events.instances pagination tokens
#     Single-call instances() with maxResults covers the realistic agent use
#     case; full pagination can be added if/when needed.
