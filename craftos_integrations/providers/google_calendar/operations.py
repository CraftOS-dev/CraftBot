"""Google Calendar operations — ported from google_calendar_actions.py.

NOTE: no operation declares an ``account`` input — the host adapter
injects it on every generated action and the core resolves it centrally
(conformance-enforced).

The actions post-process results (``pick_result`` key reduction on
writes, lean-event reduction on reads); ``_with_post`` reproduces that on
top of the declarative ``client_op`` so ported operations return dicts
identical to what agents already expect.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Dict, List, Sequence

from ...contracts import Operation
from .._shared import STATUS_OUTPUT, client_op, shape_result

# The id + key fields writes return (agents fetch the full object with the
# matching get_* operation) — mirrors the pick_result key list.
KEY_EVENT_FIELDS = (
    "id",
    "summary",
    "start",
    "end",
    "htmlLink",
    "hangoutLink",
    "status",
)


def _lean_event(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a raw Calendar Event resource to the fields an agent acts on."""
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


def _pick_result(res: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    """Reduce a successful result to the named top-level keys (client
    pick_result: non-dict results, errors, and missing keys pass through)."""
    if res.get("status") == "success" and isinstance(res.get("result"), dict):
        r = res["result"]
        picked = {k: r.get(k) for k in keys if r.get(k) is not None}
        if picked:
            res = {**res, "result": picked}
    return res


def _with_post(
    op: Operation,
    post: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
) -> Operation:
    """Wrap an operation's fn with a (result, input_data) post-processor."""
    inner = op.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return post(await inner(client, input_data), input_data)

    return replace(op, fn=fn)


def _pick_event(op: Operation) -> Operation:
    return _with_post(op, lambda res, _d: _pick_result(res, KEY_EVENT_FIELDS))


def _lean_list_post(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    if not input_data.get("include_metadata") and res.get("status") == "success":
        items = res.get("result")
        if isinstance(items, list):
            res = {
                **res,
                "result": [_lean_event(e) for e in items if isinstance(e, dict)],
            }
    return res


def _lean_single_post(
    res: Dict[str, Any], input_data: Dict[str, Any]
) -> Dict[str, Any]:
    if not input_data.get("include_metadata") and res.get("status") == "success":
        ev = res.get("result")
        if isinstance(ev, dict):
            res = {**res, "result": _lean_event(ev)}
    return res


def _lean_instances_post(
    res: Dict[str, Any], input_data: Dict[str, Any]
) -> Dict[str, Any]:
    if not input_data.get("include_metadata") and res.get("status") == "success":
        result = res.get("result")
        if isinstance(result, dict) and isinstance(result.get("instances"), list):
            res = {
                **res,
                "result": {
                    "instances": [
                        _lean_event(e)
                        for e in result["instances"]
                        if isinstance(e, dict)
                    ]
                },
            }
    return res


# ── composite: check_availability_and_schedule ──────────────────────────


async def _check_availability_and_schedule(
    client: Any, input_data: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        start_time = datetime.fromisoformat(input_data["start_time"])
        end_time = datetime.fromisoformat(input_data["end_time"])
    except Exception as e:
        return {"status": "error", "message": str(e)}

    try:
        raw = await asyncio.to_thread(
            client.check_availability,
            calendar_id="primary",
            time_min=start_time.isoformat() + "Z",
            time_max=end_time.isoformat() + "Z",
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}
    avail = shape_result(
        raw, unwrap_envelope=True, fail_message="Google Calendar FreeBusy API error"
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
    try:
        raw = await asyncio.to_thread(
            client.create_meet_event, calendar_id="primary", event_data=event_payload
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}
    result = shape_result(
        raw, unwrap_envelope=True, fail_message="Google Calendar API error"
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


# ── shared schema fragments ─────────────────────────────────────────────

_CAL_ID_DEFAULT = {
    "type": "string",
    "description": "Calendar ID (default: primary).",
    "example": "primary",
}
_SEND_UPDATES = {
    "type": "string",
    "description": "none, all, externalOnly.",
    "example": "none",
}


def build_operations() -> List[Operation]:
    return [
        # ── Convenience helpers ─────────────────────────────────────────
        _pick_event(
            client_op(
                "create_google_meet",
                "create_meet_event",
                description=(
                    "Create a Google Calendar event with a Google Meet link. "
                    "Returns id, hangoutLink + key fields."
                ),
                tags=("google_calendar_events", "google_calendar"),
                unwrap_envelope=True,
                fail_message="Failed to create event.",
                input_schema={
                    "event_data": {
                        "type": "object",
                        "description": (
                            "Calendar event data with summary, start, end, "
                            "conferenceData."
                        ),
                        "example": {},
                    },
                    "calendar_id": dict(_CAL_ID_DEFAULT),
                },
                output_schema={
                    "status": {"type": "string", "example": "success"},
                    "result": {
                        "type": "object",
                        "example": {
                            "id": "...",
                            "hangoutLink": "https://meet.google.com/...",
                        },
                    },
                },
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "event_data": d.get("event_data"),
                },
            )
        ),
        client_op(
            "check_calendar_availability",
            "check_availability",
            description="Check Google Calendar free/busy availability.",
            tags=("google_calendar_events", "google_calendar"),
            unwrap_envelope=True,
            fail_message="Failed to check availability.",
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
                "calendar_id": dict(_CAL_ID_DEFAULT),
            },
            arg_map=lambda d: {
                "calendar_id": d.get("calendar_id", "primary"),
                "time_min": d.get("time_min"),
                "time_max": d.get("time_max"),
            },
        ),
        Operation(
            name="check_availability_and_schedule",
            description="Schedule meeting if free.",
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
                "summary": {
                    "type": "string",
                    "description": "Summary.",
                    "example": "Meeting",
                },
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
            output_schema=dict(STATUS_OUTPUT),
            fn=_check_availability_and_schedule,
            tags=("google_calendar_events", "google_calendar"),
        ),
        # ── Events ──────────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_google_calendar_events",
                "list_events",
                description=(
                    "List events on a calendar between time_min and time_max. "
                    "Returns expanded single events sorted by start time. Lean "
                    "event fields by default (id, summary, description, "
                    "location, start, end, status, attendees, recurrence, "
                    "htmlLink, hangoutLink); set include_metadata for raw "
                    "Event resources."
                ),
                tags=("google_calendar_events", "google_calendar"),
                unwrap_envelope=True,
                fail_message="Failed to list events.",
                input_schema={
                    "calendar_id": dict(_CAL_ID_DEFAULT),
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
                    "include_metadata": {
                        "type": "boolean",
                        "description": (
                            "Return full raw Event resources (default false = lean)."
                        ),
                        "example": False,
                    },
                },
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "time_min": d.get("time_min"),
                    "time_max": d.get("time_max"),
                    "max_results": d.get("max_results", 50),
                },
            ),
            _lean_list_post,
        ),
        _with_post(
            client_op(
                "get_google_calendar_event",
                "get_event",
                description=(
                    "Get a single event by ID. Lean event fields by default; "
                    "set include_metadata for the raw Event resource."
                ),
                tags=("google_calendar_events", "google_calendar"),
                unwrap_envelope=True,
                fail_message="Failed to get event.",
                input_schema={
                    "event_id": {
                        "type": "string",
                        "description": "Event ID.",
                        "example": "",
                    },
                    "calendar_id": dict(_CAL_ID_DEFAULT),
                    "include_metadata": {
                        "type": "boolean",
                        "description": (
                            "Return the full raw Event resource (default false = lean)."
                        ),
                        "example": False,
                    },
                },
                arg_map=lambda d: {
                    "event_id": d["event_id"],
                    "calendar_id": d.get("calendar_id", "primary"),
                },
            ),
            _lean_single_post,
        ),
        _pick_event(
            client_op(
                "create_google_calendar_event",
                "insert_event",
                description=(
                    "Create a calendar event. event_data is the full Event "
                    "resource (summary, start, end, attendees, etc.). Use "
                    "create_google_meet for events with a Meet link. Returns "
                    "id + key fields."
                ),
                parallelizable=False,
                tags=("google_calendar_events", "google_calendar"),
                unwrap_envelope=True,
                fail_message="Failed to create event.",
                input_schema={
                    "event_data": {
                        "type": "object",
                        "description": (
                            "Event resource: summary, description, start, end, "
                            "attendees, recurrence, etc."
                        ),
                        "example": {},
                    },
                    "calendar_id": dict(_CAL_ID_DEFAULT),
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
                },
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "event_data": d["event_data"],
                    "send_updates": d.get("send_updates", "none"),
                    "supports_attachments": bool(d.get("supports_attachments", False)),
                },
            )
        ),
        _pick_event(
            client_op(
                "update_google_calendar_event",
                "update_event",
                description=(
                    "Replace an event entirely (PUT). For partial updates use "
                    "patch_google_calendar_event. Returns id + key fields."
                ),
                parallelizable=False,
                tags=("google_calendar_events", "google_calendar"),
                unwrap_envelope=True,
                fail_message="Failed to update event.",
                input_schema={
                    "event_id": {
                        "type": "string",
                        "description": "Event ID.",
                        "example": "",
                    },
                    "event_data": {
                        "type": "object",
                        "description": "Full Event resource — replaces existing.",
                        "example": {},
                    },
                    "calendar_id": dict(_CAL_ID_DEFAULT),
                    "send_updates": dict(_SEND_UPDATES),
                },
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "event_id": d["event_id"],
                    "event_data": d["event_data"],
                    "send_updates": d.get("send_updates", "none"),
                },
            )
        ),
        _pick_event(
            client_op(
                "patch_google_calendar_event",
                "patch_event",
                description=(
                    "Patch (partial update) an event. event_data contains ONLY "
                    "the fields to change. Returns id + key fields."
                ),
                parallelizable=False,
                tags=("google_calendar_events", "google_calendar"),
                unwrap_envelope=True,
                fail_message="Failed to patch event.",
                input_schema={
                    "event_id": {
                        "type": "string",
                        "description": "Event ID.",
                        "example": "",
                    },
                    "event_data": {
                        "type": "object",
                        "description": "Partial event fields to update.",
                        "example": {"summary": "New title"},
                    },
                    "calendar_id": dict(_CAL_ID_DEFAULT),
                    "send_updates": dict(_SEND_UPDATES),
                },
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "event_id": d["event_id"],
                    "event_data": d["event_data"],
                    "send_updates": d.get("send_updates", "none"),
                },
            )
        ),
        client_op(
            "delete_google_calendar_event",
            "delete_event",
            description="Delete a calendar event.",
            destructive=True,
            parallelizable=False,
            tags=("google_calendar_events", "google_calendar"),
            unwrap_envelope=True,
            fail_message="Failed to delete event.",
            input_schema={
                "event_id": {
                    "type": "string",
                    "description": "Event ID.",
                    "example": "",
                },
                "calendar_id": dict(_CAL_ID_DEFAULT),
            },
            arg_map=lambda d: {
                "event_id": d["event_id"],
                "calendar_id": d.get("calendar_id", "primary"),
            },
        ),
        _pick_event(
            client_op(
                "move_google_calendar_event",
                "move_event",
                description=(
                    "Move an event from one calendar to another. Returns id + "
                    "key fields."
                ),
                parallelizable=False,
                tags=("google_calendar_events",),
                unwrap_envelope=True,
                fail_message="Failed to move event.",
                input_schema={
                    "event_id": {
                        "type": "string",
                        "description": "Event ID.",
                        "example": "",
                    },
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
                    "send_updates": dict(_SEND_UPDATES),
                },
                arg_map=lambda d: {
                    "event_id": d["event_id"],
                    "calendar_id": d.get("calendar_id", "primary"),
                    "destination_calendar_id": d["destination_calendar_id"],
                    "send_updates": d.get("send_updates", "none"),
                },
            )
        ),
        _pick_event(
            client_op(
                "quick_add_google_calendar_event",
                "quick_add_event",
                description=(
                    "Create an event from a natural-language string (e.g. "
                    "'Lunch with Alice tomorrow at noon'). Returns id + key "
                    "fields."
                ),
                parallelizable=False,
                tags=("google_calendar_events", "google_calendar"),
                unwrap_envelope=True,
                fail_message="Failed to quick-add event.",
                input_schema={
                    "text": {
                        "type": "string",
                        "description": "Natural-language event description.",
                        "example": "Lunch with Alice tomorrow at noon",
                    },
                    "calendar_id": dict(_CAL_ID_DEFAULT),
                    "send_updates": dict(_SEND_UPDATES),
                },
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "text": d["text"],
                    "send_updates": d.get("send_updates", "none"),
                },
            )
        ),
        _with_post(
            client_op(
                "list_google_calendar_event_instances",
                "list_event_instances",
                description=(
                    "Expand a recurring event into its individual instances. "
                    "Lean event fields by default; set include_metadata for "
                    "raw Event resources."
                ),
                tags=("google_calendar_events",),
                unwrap_envelope=True,
                fail_message="Failed to list instances.",
                input_schema={
                    "event_id": {
                        "type": "string",
                        "description": "Recurring event ID.",
                        "example": "",
                    },
                    "calendar_id": dict(_CAL_ID_DEFAULT),
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
                        "description": (
                            "Return full raw Event resources (default false = lean)."
                        ),
                        "example": False,
                    },
                },
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "event_id": d["event_id"],
                    "time_min": d.get("time_min"),
                    "time_max": d.get("time_max"),
                    "max_results": d.get("max_results", 50),
                },
            ),
            _lean_instances_post,
        ),
        _pick_event(
            client_op(
                "import_google_calendar_event",
                "import_event",
                description=(
                    "Import a pre-existing event (with its own iCal UID) into "
                    "a calendar — preserves identity across calendars. "
                    "Distinct from create. Returns id + key fields."
                ),
                parallelizable=False,
                tags=("google_calendar_events",),
                unwrap_envelope=True,
                fail_message="Failed to import event.",
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
                arg_map=lambda d: {
                    "calendar_id": d.get("calendar_id", "primary"),
                    "event_data": d["event_data"],
                },
            )
        ),
        # ── Calendars (the calendar resources themselves) ───────────────
        client_op(
            "list_google_calendars",
            "list_calendars",
            description=(
                "List calendars the user has access to (from their calendarList)."
            ),
            tags=("google_calendar_admin", "google_calendar"),
            unwrap_envelope=True,
            fail_message="Failed to list calendars.",
            input_schema={},
            arg_map=lambda d: {},
        ),
        client_op(
            "get_google_calendar",
            "get_calendar",
            description=(
                "Get metadata for a single calendar (summary, timezone, description)."
            ),
            tags=("google_calendar_admin", "google_calendar"),
            unwrap_envelope=True,
            fail_message="Failed to get calendar.",
            input_schema={
                "calendar_id": dict(_CAL_ID_DEFAULT),
            },
            arg_map=lambda d: {"calendar_id": d.get("calendar_id", "primary")},
        ),
        client_op(
            "create_google_calendar",
            "create_calendar",
            description=(
                "Create a new (secondary) calendar owned by the authenticated user."
            ),
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to create calendar.",
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
            arg_map=lambda d: {
                "summary": d["summary"],
                "description": d.get("description") or None,
                "time_zone": d.get("time_zone") or None,
                "location": d.get("location") or None,
            },
        ),
        client_op(
            "update_google_calendar",
            "update_calendar",
            description=(
                "Replace a calendar's metadata (PUT). For partial updates use "
                "patch_google_calendar."
            ),
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to update calendar.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID.",
                    "example": "",
                },
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
            arg_map=lambda d: {
                "calendar_id": d["calendar_id"],
                "summary": d.get("summary") or None,
                "description": d["description"] if "description" in d else None,
                "time_zone": d.get("time_zone") or None,
                "location": d["location"] if "location" in d else None,
            },
        ),
        client_op(
            "patch_google_calendar",
            "patch_calendar",
            description="Patch (partial update) a calendar's metadata.",
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to patch calendar.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID.",
                    "example": "",
                },
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
            arg_map=lambda d: {
                "calendar_id": d["calendar_id"],
                "summary": d.get("summary") or None,
                "description": d["description"] if "description" in d else None,
                "time_zone": d.get("time_zone") or None,
                "location": d["location"] if "location" in d else None,
            },
        ),
        client_op(
            "delete_google_calendar",
            "delete_calendar",
            description=(
                "DELETE a secondary calendar. Cannot be used on the primary calendar."
            ),
            destructive=True,
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to delete calendar.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to delete.",
                    "example": "",
                },
            },
            arg_map=lambda d: {"calendar_id": d["calendar_id"]},
        ),
        client_op(
            "clear_google_calendar",
            "clear_calendar",
            description=(
                "Delete ALL events on the user's PRIMARY calendar. "
                "Irreversible. No-op on secondary calendars."
            ),
            destructive=True,
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to clear calendar.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Must be 'primary'.",
                    "example": "primary",
                },
            },
            arg_map=lambda d: {"calendar_id": d.get("calendar_id", "primary")},
        ),
        # ── CalendarList (subscriptions, colors, visibility) ────────────
        client_op(
            "get_google_calendar_list_entry",
            "get_calendar_list_entry",
            description=(
                "Get the user's per-calendar settings (color, visibility, "
                "summary override)."
            ),
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to get calendar list entry.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID.",
                    "example": "",
                },
            },
            arg_map=lambda d: {"calendar_id": d["calendar_id"]},
        ),
        client_op(
            "subscribe_google_calendar",
            "subscribe_calendar",
            description=(
                "Subscribe to (add to the user's calendar list) an existing "
                "calendar by ID."
            ),
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to subscribe to calendar.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to subscribe to.",
                    "example": "",
                },
                "color_id": {
                    "type": "string",
                    "description": (
                        "Color ID from get_google_calendar_colors (optional)."
                    ),
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
            arg_map=lambda d: {
                "calendar_id": d["calendar_id"],
                "color_id": d.get("color_id") or None,
                "summary_override": d.get("summary_override") or None,
                "selected": d["selected"] if "selected" in d else None,
                "hidden": d["hidden"] if "hidden" in d else None,
            },
        ),
        client_op(
            "update_google_calendar_list_entry",
            "update_calendar_list_entry",
            description=(
                "Update the user's per-calendar settings (color, visibility, "
                "display name)."
            ),
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to update calendar list entry.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID.",
                    "example": "",
                },
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
            arg_map=lambda d: {
                "calendar_id": d["calendar_id"],
                "color_id": d.get("color_id") or None,
                "summary_override": d["summary_override"]
                if "summary_override" in d
                else None,
                "selected": d["selected"] if "selected" in d else None,
                "hidden": d["hidden"] if "hidden" in d else None,
            },
        ),
        client_op(
            "unsubscribe_google_calendar",
            "unsubscribe_calendar",
            description=(
                "Remove a calendar from the user's calendar list. Does NOT "
                "delete the calendar itself."
            ),
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to unsubscribe.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to unsubscribe from.",
                    "example": "",
                },
            },
            arg_map=lambda d: {"calendar_id": d["calendar_id"]},
        ),
        # ── ACL (per-calendar sharing) ──────────────────────────────────
        client_op(
            "list_google_calendar_acl",
            "list_calendar_acl",
            description="List ACL rules (who has what access) on a calendar.",
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to list ACL.",
            input_schema={
                "calendar_id": dict(_CAL_ID_DEFAULT),
            },
            arg_map=lambda d: {"calendar_id": d.get("calendar_id", "primary")},
        ),
        client_op(
            "get_google_calendar_acl_rule",
            "get_calendar_acl_rule",
            description="Get a single ACL rule by ID.",
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to get ACL rule.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID.",
                    "example": "primary",
                },
                "rule_id": {
                    "type": "string",
                    "description": "ACL rule ID.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "calendar_id": d.get("calendar_id", "primary"),
                "rule_id": d["rule_id"],
            },
        ),
        client_op(
            "add_google_calendar_acl_rule",
            "add_calendar_acl_rule",
            description=(
                "Grant calendar access. scope_type: user/group/domain/default. "
                "role: none/freeBusyReader/reader/writer/owner."
            ),
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to add ACL rule.",
            input_schema={
                "calendar_id": dict(_CAL_ID_DEFAULT),
                "scope_type": {
                    "type": "string",
                    "description": "user, group, domain, or default.",
                    "example": "user",
                },
                "scope_value": {
                    "type": "string",
                    "description": (
                        "Email, group address, or domain (empty for 'default')."
                    ),
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
            arg_map=lambda d: {
                "calendar_id": d.get("calendar_id", "primary"),
                "scope_type": d["scope_type"],
                "scope_value": d.get("scope_value", ""),
                "role": d["role"],
                "send_notifications": bool(d.get("send_notifications", True)),
            },
        ),
        client_op(
            "update_google_calendar_acl_rule",
            "update_calendar_acl_rule",
            description="Change the role of an existing ACL rule.",
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to update ACL rule.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID.",
                    "example": "primary",
                },
                "rule_id": {
                    "type": "string",
                    "description": "ACL rule ID.",
                    "example": "",
                },
                "role": {
                    "type": "string",
                    "description": "New role.",
                    "example": "writer",
                },
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
            arg_map=lambda d: {
                "calendar_id": d.get("calendar_id", "primary"),
                "rule_id": d["rule_id"],
                "role": d["role"],
                "scope_type": d.get("scope_type") or None,
                "scope_value": d.get("scope_value") or None,
                "send_notifications": bool(d.get("send_notifications", True)),
            },
        ),
        client_op(
            "delete_google_calendar_acl_rule",
            "delete_calendar_acl_rule",
            description="Revoke access by deleting an ACL rule.",
            destructive=True,
            parallelizable=False,
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to delete ACL rule.",
            input_schema={
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID.",
                    "example": "primary",
                },
                "rule_id": {
                    "type": "string",
                    "description": "ACL rule ID.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "calendar_id": d.get("calendar_id", "primary"),
                "rule_id": d["rule_id"],
            },
        ),
        # ── Settings & colors ───────────────────────────────────────────
        client_op(
            "list_google_calendar_settings",
            "list_calendar_settings",
            description=(
                "List the authenticated user's Calendar settings (timezone, "
                "locale, weekStart, etc.) as a dict."
            ),
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to list settings.",
            input_schema={},
            arg_map=lambda d: {},
        ),
        client_op(
            "get_google_calendar_setting",
            "get_calendar_setting",
            description=(
                "Get a single user setting by ID. Common IDs: timezone, "
                "locale, autoAddHangouts, weekStart."
            ),
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to get setting.",
            input_schema={
                "setting_id": {
                    "type": "string",
                    "description": "Setting ID.",
                    "example": "timezone",
                },
            },
            arg_map=lambda d: {"setting_id": d["setting_id"]},
        ),
        client_op(
            "get_google_calendar_colors",
            "get_calendar_colors",
            description=(
                "Get the color palette available for calendars and events "
                "(color_id → hex map)."
            ),
            tags=("google_calendar_admin",),
            unwrap_envelope=True,
            fail_message="Failed to get colors.",
            input_schema={},
            arg_map=lambda d: {},
        ),
    ]
