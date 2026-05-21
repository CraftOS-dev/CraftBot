from agent_core import action


# ------------------------------------------------------------------
# Calendars — list, get, create, update, delete, search, subscribe
# Sub-set: lark_calendar_calendars
# ------------------------------------------------------------------

@action(
    name="list_lark_calendars",
    description="List the bot's accessible Lark calendars (its own primary plus any shared with it).",
    action_sets=["lark_calendar_calendars", "lark_calendar"],
    input_schema={
        "page_size": {"type": "integer", "description": "Max calendars to return (capped at 1000).", "example": 20},
        "page_token": {"type": "string", "description": "Pagination cursor from a previous response.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def list_lark_calendars(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "list_calendars",
        page_size=input_data.get("page_size", 20),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_primary_calendar",
    description="Get the bot's primary Lark calendar — useful for finding the calendar_id to pass to other Calendar actions.",
    action_sets=["lark_calendar_calendars", "lark_calendar"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def get_lark_primary_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_calendar", "get_primary_calendar")


@action(
    name="get_lark_calendar",
    description="Fetch metadata for a specific Lark calendar.",
    action_sets=["lark_calendar_calendars"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "feishu.cn_abc..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def get_lark_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_calendar", "get_calendar", calendar_id=input_data["calendar_id"])


@action(
    name="create_lark_calendar",
    description="Create a new secondary Lark calendar owned by the bot.",
    action_sets=["lark_calendar_calendars", "lark_calendar"],
    input_schema={
        "summary": {"type": "string", "description": "Calendar name (max 255 chars).", "example": "Project X"},
        "description": {"type": "string", "description": "Optional description.", "example": ""},
        "permissions": {"type": "string", "description": "private | show_only_free_busy | public.", "example": "private"},
        "color": {"type": "integer", "description": "Optional RGB int32 (Lark encoding). -1 for default.", "example": -1},
        "summary_alias": {"type": "string", "description": "Optional alias / short name.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def create_lark_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "create_calendar",
        summary=input_data["summary"],
        description=input_data.get("description", ""),
        permissions=input_data.get("permissions", "private"),
        color=input_data.get("color"),
        summary_alias=input_data.get("summary_alias", ""),
    )


@action(
    name="update_lark_calendar",
    description="Patch fields on an existing Lark calendar. Only fields you supply are changed.",
    action_sets=["lark_calendar_calendars"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "feishu.cn_abc..."},
        "summary": {"type": "string", "description": "New name.", "example": ""},
        "description": {"type": "string", "description": "New description.", "example": ""},
        "permissions": {"type": "string", "description": "private | show_only_free_busy | public.", "example": ""},
        "color": {"type": "integer", "description": "RGB int32.", "example": -1},
        "summary_alias": {"type": "string", "description": "Alias.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def update_lark_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "update_calendar",
        calendar_id=input_data["calendar_id"],
        summary=input_data.get("summary") or None,
        description=input_data.get("description") if input_data.get("description") is not None else None,
        permissions=input_data.get("permissions") or None,
        color=input_data.get("color"),
        summary_alias=input_data.get("summary_alias") if input_data.get("summary_alias") is not None else None,
    )


@action(
    name="delete_lark_calendar",
    description="Delete a Lark calendar the bot owns.",
    action_sets=["lark_calendar_calendars"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "feishu.cn_abc..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_calendar", "delete_calendar", calendar_id=input_data["calendar_id"])


@action(
    name="search_lark_calendars",
    description="Search calendars the bot can see by name.",
    action_sets=["lark_calendar_calendars"],
    input_schema={
        "query": {"type": "string", "description": "Search query.", "example": "Project X"},
        "page_size": {"type": "integer", "description": "Max results.", "example": 20},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def search_lark_calendars(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "search_calendars",
        query=input_data["query"],
        page_size=input_data.get("page_size", 20),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="subscribe_to_lark_calendar",
    description="Subscribe to a shared Lark calendar so it appears in list_lark_calendars.",
    action_sets=["lark_calendar_calendars"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id to subscribe to.", "example": "feishu.cn_abc..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def subscribe_to_lark_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_calendar", "subscribe_calendar", calendar_id=input_data["calendar_id"])


@action(
    name="unsubscribe_from_lark_calendar",
    description="Unsubscribe from a shared Lark calendar.",
    action_sets=["lark_calendar_calendars"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "feishu.cn_abc..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def unsubscribe_from_lark_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_calendar", "unsubscribe_calendar", calendar_id=input_data["calendar_id"])


# ------------------------------------------------------------------
# Events — list, get, create, update, delete, search, RSVP, instances
# Sub-set: lark_calendar_events
# ------------------------------------------------------------------

@action(
    name="list_lark_calendar_events",
    description="List events on a Lark calendar between two Unix timestamps (seconds).",
    action_sets=["lark_calendar_events", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id. Use list_lark_calendars or get_lark_primary_calendar to find it.", "example": "primary"},
        "start_time": {"type": "integer", "description": "Window start as Unix timestamp in seconds.", "example": 1730000000},
        "end_time": {"type": "integer", "description": "Window end as Unix timestamp in seconds.", "example": 1730086400},
        "page_size": {"type": "integer", "description": "Max events to return (capped at 1000).", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def list_lark_calendar_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "list_events",
        calendar_id=input_data["calendar_id"],
        start_time=input_data["start_time"],
        end_time=input_data["end_time"],
        page_size=input_data.get("page_size", 50),
    )


@action(
    name="get_lark_calendar_event",
    description="Fetch a single Lark calendar event by id.",
    action_sets=["lark_calendar_events", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id holding the event.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id.", "example": "0123abcd-..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def get_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "get_event",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
    )


@action(
    name="create_lark_calendar_event",
    description="Create a new event on a Lark calendar. To invite attendees, call add_lark_event_attendees afterwards with the returned event_id.",
    action_sets=["lark_calendar_events", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id to create the event in.", "example": "primary"},
        "summary": {"type": "string", "description": "Event title.", "example": "Q2 planning"},
        "start_time": {"type": "integer", "description": "Start as Unix timestamp in seconds.", "example": 1730000000},
        "end_time": {"type": "integer", "description": "End as Unix timestamp in seconds.", "example": 1730003600},
        "description": {"type": "string", "description": "Event body / agenda.", "example": "Review last quarter and align on Q2 goals."},
        "location": {"type": "string", "description": "Physical or virtual location label.", "example": "Conf Room A"},
        "with_video_meeting": {"type": "boolean", "description": "If true, Lark auto-attaches a Lark Meeting URL.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def create_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "create_event",
        calendar_id=input_data["calendar_id"],
        summary=input_data["summary"],
        start_time=input_data["start_time"],
        end_time=input_data["end_time"],
        description=input_data.get("description", ""),
        location=input_data.get("location", ""),
        with_video_meeting=input_data.get("with_video_meeting", False),
    )


@action(
    name="update_lark_calendar_event",
    description="Patch fields on an existing Lark calendar event. Only fields you supply are changed.",
    action_sets=["lark_calendar_events", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id holding the event.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id to update.", "example": "0123abcd-..."},
        "summary": {"type": "string", "description": "New event title (omit to keep).", "example": "Q2 planning (rescheduled)"},
        "description": {"type": "string", "description": "New description (omit to keep).", "example": ""},
        "start_time": {"type": "integer", "description": "New start as Unix seconds (omit to keep).", "example": 1730086400},
        "end_time": {"type": "integer", "description": "New end as Unix seconds (omit to keep).", "example": 1730090000},
        "location": {"type": "string", "description": "New location (omit to keep).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def update_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "update_event",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        summary=input_data.get("summary"),
        description=input_data.get("description"),
        start_time=input_data.get("start_time"),
        end_time=input_data.get("end_time"),
        location=input_data.get("location"),
    )


@action(
    name="delete_lark_calendar_event",
    description="Delete a Lark calendar event by id.",
    action_sets=["lark_calendar_events", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id holding the event.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id to delete.", "example": "0123abcd-..."},
        "need_notification": {"type": "boolean", "description": "Email attendees about the cancellation.", "example": True},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "delete_event",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        need_notification=input_data.get("need_notification", True),
    )


@action(
    name="search_lark_calendar_events",
    description="Full-text search over event titles and descriptions in a Lark calendar.",
    action_sets=["lark_calendar_events", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id to search.", "example": "primary"},
        "query": {"type": "string", "description": "Search query.", "example": "planning"},
        "start_time": {"type": "integer", "description": "Optional window start as Unix seconds.", "example": 1730000000},
        "end_time": {"type": "integer", "description": "Optional window end as Unix seconds.", "example": 1732000000},
        "page_size": {"type": "integer", "description": "Max results (capped at 100).", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def search_lark_calendar_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "search_events",
        calendar_id=input_data["calendar_id"],
        query=input_data["query"],
        start_time=input_data.get("start_time"),
        end_time=input_data.get("end_time"),
        page_size=input_data.get("page_size", 20),
    )


@action(
    name="rsvp_lark_calendar_event",
    description="RSVP to a Lark calendar event invitation (accept / decline / tentative).",
    action_sets=["lark_calendar_events", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id holding the event.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id.", "example": "0123abcd-..."},
        "rsvp_status": {"type": "string", "description": "accept | decline | tentative.", "example": "accept"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def rsvp_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "reply_event",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        rsvp_status=input_data["rsvp_status"],
    )


@action(
    name="list_lark_event_instances",
    description="List the concrete occurrences of a recurring Lark event within a time window.",
    action_sets=["lark_calendar_events"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "primary"},
        "event_id": {"type": "string", "description": "Master recurring event id.", "example": "0123abcd-..."},
        "start_time": {"type": "integer", "description": "Window start as Unix seconds.", "example": 1730000000},
        "end_time": {"type": "integer", "description": "Window end as Unix seconds.", "example": 1735689600},
        "page_size": {"type": "integer", "description": "Max instances.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def list_lark_event_instances(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "list_event_instances",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        start_time=input_data["start_time"],
        end_time=input_data["end_time"],
        page_size=input_data.get("page_size", 50),
    )


# ------------------------------------------------------------------
# Attendees — add, list, batch-delete, chat-members, meeting rooms
# Sub-set: lark_calendar_attendees
# ------------------------------------------------------------------

@action(
    name="add_lark_event_attendees",
    description="Invite attendees to a Lark calendar event. Pass user_ids (open_ids), emails (for external attendees), or chat_ids (invites everyone in a group).",
    action_sets=["lark_calendar_attendees", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id holding the event.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id.", "example": "0123abcd-..."},
        "user_ids": {"type": "array", "description": "Lark open_ids (ou_...) to invite.", "example": ["ou_abc"]},
        "emails": {"type": "array", "description": "Email addresses to invite as external attendees.", "example": ["alice@example.com"]},
        "chat_ids": {"type": "array", "description": "Lark group chat_ids (oc_...) — every member gets invited.", "example": []},
        "need_notification": {"type": "boolean", "description": "Email/notify the attendees about the invite.", "example": True},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def add_lark_event_attendees(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "add_event_attendees",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        user_ids=input_data.get("user_ids"),
        emails=input_data.get("emails"),
        chat_ids=input_data.get("chat_ids"),
        need_notification=input_data.get("need_notification", True),
    )


@action(
    name="list_lark_event_attendees",
    description="List the current attendees on a Lark calendar event.",
    action_sets=["lark_calendar_attendees", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id.", "example": "0123abcd-..."},
        "page_size": {"type": "integer", "description": "Max attendees per page (cap 200).", "example": 100},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def list_lark_event_attendees(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "list_event_attendees",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="remove_lark_event_attendees",
    description="Remove one or more attendees from a Lark event in a single call.",
    action_sets=["lark_calendar_attendees"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id.", "example": "0123abcd-..."},
        "attendee_ids": {"type": "array", "description": "List of attendee_id values to remove.", "example": ["att_abc"]},
        "need_notification": {"type": "boolean", "description": "Notify removed attendees.", "example": True},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def remove_lark_event_attendees(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "batch_delete_event_attendees",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        attendee_ids=input_data["attendee_ids"],
        need_notification=input_data.get("need_notification", True),
    )


@action(
    name="list_lark_event_chat_attendee_members",
    description="List the underlying chat members for a chat-type attendee on a Lark event.",
    action_sets=["lark_calendar_attendees"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id.", "example": "0123abcd-..."},
        "attendee_id": {"type": "string", "description": "Chat-type attendee id.", "example": "att_chat_..."},
        "page_size": {"type": "integer", "description": "Max members per page (cap 200).", "example": 100},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def list_lark_event_chat_attendee_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "list_event_attendee_chat_members",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        attendee_id=input_data["attendee_id"],
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="book_lark_meeting_room",
    description="Attach a meeting room to a Lark calendar event as a resource attendee (effectively booking it).",
    action_sets=["lark_calendar_attendees", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id holding the event.", "example": "primary"},
        "event_id": {"type": "string", "description": "Event id.", "example": "0123abcd-..."},
        "meeting_room_id": {"type": "string", "description": "Meeting room (room_id).", "example": "omm_..."},
        "need_notification": {"type": "boolean", "description": "Notify meeting room owners.", "example": True},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def book_lark_meeting_room(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "add_meeting_room_to_event",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        meeting_room_id=input_data["meeting_room_id"],
        need_notification=input_data.get("need_notification", True),
    )


# ------------------------------------------------------------------
# Sharing / ACL — list, create, delete
# Sub-set: lark_calendar_sharing
# ------------------------------------------------------------------

@action(
    name="list_lark_calendar_acls",
    description="List the access-control entries (sharing permissions) on a Lark calendar.",
    action_sets=["lark_calendar_sharing"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "primary"},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def list_lark_calendar_acls(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_calendar", "list_calendar_acls", calendar_id=input_data["calendar_id"])


@action(
    name="share_lark_calendar_with_user",
    description="Share a Lark calendar with a user by granting them a role (owner / reader / writer / free_busy_reader).",
    action_sets=["lark_calendar_sharing", "lark_calendar"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "primary"},
        "user_id": {"type": "string", "description": "Lark user open_id (ou_...).", "example": "ou_abc"},
        "role": {"type": "string", "description": "owner | reader | writer | free_busy_reader.", "example": "reader"},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
    parallelizable=False,
)
async def share_lark_calendar_with_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "create_calendar_acl",
        calendar_id=input_data["calendar_id"],
        user_id=input_data["user_id"],
        role=input_data.get("role", "reader"),
    )


@action(
    name="revoke_lark_calendar_share",
    description="Revoke a previously granted calendar share (ACL entry).",
    action_sets=["lark_calendar_sharing"],
    input_schema={
        "calendar_id": {"type": "string", "description": "Calendar id.", "example": "primary"},
        "acl_id": {"type": "string", "description": "ACL entry id (from list_lark_calendar_acls).", "example": "user_..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def revoke_lark_calendar_share(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "delete_calendar_acl",
        calendar_id=input_data["calendar_id"],
        acl_id=input_data["acl_id"],
    )


# ------------------------------------------------------------------
# Free/busy
# Sub-set: lark_calendar_freebusy
# ------------------------------------------------------------------

@action(
    name="check_lark_free_busy",
    description="Bulk free/busy query — returns each user's busy intervals over a time window. Useful for finding a meeting slot that works for everyone.",
    action_sets=["lark_calendar_freebusy", "lark_calendar"],
    input_schema={
        "user_ids": {"type": "array", "description": "List of Lark open_ids (ou_...) to query.", "example": ["ou_abc", "ou_def"]},
        "start_time": {"type": "integer", "description": "Window start as Unix timestamp in seconds.", "example": 1730000000},
        "end_time": {"type": "integer", "description": "Window end as Unix timestamp in seconds.", "example": 1730086400},
    },
    output_schema={"status": {"type": "string", "example": "success"}, "result": {"type": "object"}},
)
async def check_lark_free_busy(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_calendar", "check_free_busy",
        user_ids=input_data["user_ids"],
        start_time=input_data["start_time"],
        end_time=input_data["end_time"],
    )
