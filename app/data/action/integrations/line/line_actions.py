from agent_core import action


@action(
    name="send_line_message",
    description="Send a text message via LINE to a user, group, or room ID. Use this ONLY when the agent needs to push a message via LINE.",
    action_sets=["line"],
    input_schema={
        "to": {
            "type": "string",
            "description": "LINE user ID, group ID, or room ID. Starts with U, C, or R.",
            "example": "U4af4980629...",
        },
        "text": {
            "type": "string",
            "description": "Message text to send.",
            "example": "Hello from CraftBot!",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def send_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import (
        record_outgoing_message,
        run_client,
    )

    record_outgoing_message("LINE", input_data["to"], input_data["text"])
    return await run_client(
        "line",
        "push_text",
        to=input_data["to"],
        text=input_data["text"],
    )


@action(
    name="reply_line_message",
    description="Reply to a LINE webhook event using its reply token (valid for ~1 minute after the event arrives). Free of quota; prefer over push when a reply token is available.",
    action_sets=["line"],
    input_schema={
        "reply_token": {
            "type": "string",
            "description": "Reply token from the inbound LINE webhook event.",
            "example": "nHuyWi...",
        },
        "text": {"type": "string", "description": "Reply text.", "example": "Got it!"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def reply_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "line",
        "reply_text",
        reply_token=input_data["reply_token"],
        text=input_data["text"],
    )


@action(
    name="multicast_line_message",
    description="Send the same LINE text message to up to 500 user IDs in a single call. Counts against the monthly push quota for each recipient.",
    action_sets=["line"],
    input_schema={
        "to": {
            "type": "array",
            "description": "List of LINE user IDs (max 500).",
            "example": ["U4af4980629...", "Ub1234..."],
        },
        "text": {
            "type": "string",
            "description": "Message text.",
            "example": "Heads up team",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def multicast_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "line",
        "multicast_text",
        to=input_data["to"],
        text=input_data["text"],
    )


@action(
    name="broadcast_line_message",
    description="Broadcast a LINE text message to every user that has the bot as a friend. Counts heavily against the monthly push quota — use sparingly.",
    action_sets=["line"],
    input_schema={
        "text": {
            "type": "string",
            "description": "Message text.",
            "example": "Service announcement",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def broadcast_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("line", "broadcast_text", text=input_data["text"])


@action(
    name="get_line_profile",
    description="Fetch a LINE user's display name and picture URL by user ID.",
    action_sets=["line"],
    input_schema={
        "user_id": {
            "type": "string",
            "description": "LINE user ID (starts with U).",
            "example": "U4af4980629...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_line_profile(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("line", "get_profile", user_id=input_data["user_id"])


@action(
    name="get_line_bot_info",
    description="Get the connected LINE bot's own profile (userId, displayName, picture).",
    action_sets=["line"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_line_bot_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("line", "get_bot_info")


@action(
    name="get_line_quota",
    description="Get the LINE bot's remaining monthly push-message quota.",
    action_sets=["line"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_line_quota(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("line", "get_quota")
