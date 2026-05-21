from agent_core import action


@action(
    name="list_lark_calendars",
    description="List the bot's accessible Lark calendars (its own primary plus any shared with it).",
    action_sets=["lark_calendar"],
    input_schema={
        "page_size": {
            "type": "integer",
            "description": "Max calendars to return (capped at 1000).",
            "example": 20,
        },
        "page_token": {
            "type": "string",
            "description": "Pagination cursor from a previous response.",
            "example": "",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def list_lark_calendars(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "list_calendars",
        page_size=input_data.get("page_size", 20),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_primary_calendar",
    description="Get the bot's primary Lark calendar — useful for finding the calendar_id to pass to other Calendar actions.",
    action_sets=["lark_calendar"],
    input_schema={},
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def get_lark_primary_calendar(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("lark_calendar", "get_primary_calendar")


@action(
    name="list_lark_calendar_events",
    description="List events on a Lark calendar between two Unix timestamps (seconds).",
    action_sets=["lark_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar id. Use list_lark_calendars or get_lark_primary_calendar to find it.",
            "example": "primary",
        },
        "start_time": {
            "type": "integer",
            "description": "Window start as Unix timestamp in seconds.",
            "example": 1730000000,
        },
        "end_time": {
            "type": "integer",
            "description": "Window end as Unix timestamp in seconds.",
            "example": 1730086400,
        },
        "page_size": {
            "type": "integer",
            "description": "Max events to return (capped at 1000).",
            "example": 50,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def list_lark_calendar_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "list_events",
        calendar_id=input_data["calendar_id"],
        start_time=input_data["start_time"],
        end_time=input_data["end_time"],
        page_size=input_data.get("page_size", 50),
    )


@action(
    name="get_lark_calendar_event",
    description="Fetch a single Lark calendar event by id.",
    action_sets=["lark_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar id holding the event.",
            "example": "primary",
        },
        "event_id": {
            "type": "string",
            "description": "Event id.",
            "example": "0123abcd-...",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def get_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "get_event",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
    )


@action(
    name="create_lark_calendar_event",
    description="Create a new event on a Lark calendar. To invite attendees, call add_lark_event_attendees afterwards with the returned event_id.",
    action_sets=["lark_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar id to create the event in.",
            "example": "primary",
        },
        "summary": {
            "type": "string",
            "description": "Event title.",
            "example": "Q2 planning",
        },
        "start_time": {
            "type": "integer",
            "description": "Start as Unix timestamp in seconds.",
            "example": 1730000000,
        },
        "end_time": {
            "type": "integer",
            "description": "End as Unix timestamp in seconds.",
            "example": 1730003600,
        },
        "description": {
            "type": "string",
            "description": "Event body / agenda.",
            "example": "Review last quarter and align on Q2 goals.",
        },
        "location": {
            "type": "string",
            "description": "Physical or virtual location label.",
            "example": "Conf Room A",
        },
        "with_video_meeting": {
            "type": "boolean",
            "description": "If true, Lark auto-attaches a Lark Meeting URL.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def create_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "create_event",
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
    action_sets=["lark_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar id holding the event.",
            "example": "primary",
        },
        "event_id": {
            "type": "string",
            "description": "Event id to update.",
            "example": "0123abcd-...",
        },
        "summary": {
            "type": "string",
            "description": "New event title (omit to keep).",
            "example": "Q2 planning (rescheduled)",
        },
        "description": {
            "type": "string",
            "description": "New description (omit to keep).",
            "example": "",
        },
        "start_time": {
            "type": "integer",
            "description": "New start as Unix seconds (omit to keep).",
            "example": 1730086400,
        },
        "end_time": {
            "type": "integer",
            "description": "New end as Unix seconds (omit to keep).",
            "example": 1730090000,
        },
        "location": {
            "type": "string",
            "description": "New location (omit to keep).",
            "example": "",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def update_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "update_event",
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
    action_sets=["lark_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar id holding the event.",
            "example": "primary",
        },
        "event_id": {
            "type": "string",
            "description": "Event id to delete.",
            "example": "0123abcd-...",
        },
        "need_notification": {
            "type": "boolean",
            "description": "Email attendees about the cancellation.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def delete_lark_calendar_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "delete_event",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        need_notification=input_data.get("need_notification", True),
    )


@action(
    name="search_lark_calendar_events",
    description="Full-text search over event titles and descriptions in a Lark calendar.",
    action_sets=["lark_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar id to search.",
            "example": "primary",
        },
        "query": {
            "type": "string",
            "description": "Search query.",
            "example": "planning",
        },
        "start_time": {
            "type": "integer",
            "description": "Optional window start as Unix seconds.",
            "example": 1730000000,
        },
        "end_time": {
            "type": "integer",
            "description": "Optional window end as Unix seconds.",
            "example": 1732000000,
        },
        "page_size": {
            "type": "integer",
            "description": "Max results (capped at 100).",
            "example": 20,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def search_lark_calendar_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "search_events",
        calendar_id=input_data["calendar_id"],
        query=input_data["query"],
        start_time=input_data.get("start_time"),
        end_time=input_data.get("end_time"),
        page_size=input_data.get("page_size", 20),
    )


@action(
    name="add_lark_event_attendees",
    description="Invite attendees to a Lark calendar event. Pass user_ids (open_ids), emails (for external attendees), or chat_ids (invites everyone in a group).",
    action_sets=["lark_calendar"],
    input_schema={
        "calendar_id": {
            "type": "string",
            "description": "Calendar id holding the event.",
            "example": "primary",
        },
        "event_id": {
            "type": "string",
            "description": "Event id.",
            "example": "0123abcd-...",
        },
        "user_ids": {
            "type": "array",
            "description": "Lark open_ids (ou_...) to invite.",
            "example": ["ou_abc"],
        },
        "emails": {
            "type": "array",
            "description": "Email addresses to invite as external attendees.",
            "example": ["alice@example.com"],
        },
        "chat_ids": {
            "type": "array",
            "description": "Lark group chat_ids (oc_...) — every member gets invited.",
            "example": [],
        },
        "need_notification": {
            "type": "boolean",
            "description": "Email/notify the attendees about the invite.",
            "example": True,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def add_lark_event_attendees(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "add_event_attendees",
        calendar_id=input_data["calendar_id"],
        event_id=input_data["event_id"],
        user_ids=input_data.get("user_ids"),
        emails=input_data.get("emails"),
        chat_ids=input_data.get("chat_ids"),
        need_notification=input_data.get("need_notification", True),
    )


@action(
    name="check_lark_free_busy",
    description="Bulk free/busy query — returns each user's busy intervals over a time window. Useful for finding a meeting slot that works for everyone.",
    action_sets=["lark_calendar"],
    input_schema={
        "user_ids": {
            "type": "array",
            "description": "List of Lark open_ids (ou_...) to query.",
            "example": ["ou_abc", "ou_def"],
        },
        "start_time": {
            "type": "integer",
            "description": "Window start as Unix timestamp in seconds.",
            "example": 1730000000,
        },
        "end_time": {
            "type": "integer",
            "description": "Window end as Unix timestamp in seconds.",
            "example": 1730086400,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def check_lark_free_busy(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_calendar",
        "check_free_busy",
        user_ids=input_data["user_ids"],
        start_time=input_data["start_time"],
        end_time=input_data["end_time"],
    )
