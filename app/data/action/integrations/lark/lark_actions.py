from agent_core import action


@action(
    name="send_lark_message",
    description="Send a text message via Lark to a user (by open_id), group chat (by chat_id), or company email. Use this when the agent needs to push a message via Lark.",
    action_sets=["lark"],
    input_schema={
        "to": {
            "type": "string",
            "description": "Recipient identifier — Lark open_id (ou_...), user_id, group chat_id (oc_...), or company email.",
            "example": "ou_abcdef0123456789",
        },
        "text": {
            "type": "string",
            "description": "Message text.",
            "example": "Hello from CraftBot!",
        },
        "receive_id_type": {
            "type": "string",
            "description": "How to interpret 'to': 'open_id' (default), 'user_id', 'email', 'chat_id', or 'union_id'.",
            "example": "open_id",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def send_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import (
        record_outgoing_message,
        run_client,
    )

    record_outgoing_message("Lark", input_data["to"], input_data["text"])
    return await run_client(
        "lark",
        "send_text",
        receive_id=input_data["to"],
        text=input_data["text"],
        receive_id_type=input_data.get("receive_id_type") or "open_id",
    )


@action(
    name="reply_lark_message",
    description="Reply to a Lark message in-thread, using the original message id (om_...).",
    action_sets=["lark"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "The original Lark message id (starts with 'om_').",
            "example": "om_abcdef0123",
        },
        "text": {"type": "string", "description": "Reply text.", "example": "Got it"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def reply_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark",
        "reply_text",
        message_id=input_data["message_id"],
        text=input_data["text"],
    )


@action(
    name="get_lark_user_by_email",
    description="Look up a Lark user's open_id from their company email. Useful for 'message alice@example.com' workflows where only the email is known.",
    action_sets=["lark"],
    input_schema={
        "email": {
            "type": "string",
            "description": "Company email address.",
            "example": "alice@example.com",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_user_by_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("lark", "get_user_by_email", email=input_data["email"])


@action(
    name="list_lark_chats",
    description="List Lark group chats the bot is a member of.",
    action_sets=["lark"],
    input_schema={
        "page_size": {
            "type": "integer",
            "description": "Max chats to return (capped at 100).",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_chats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark", "list_chats", page_size=input_data.get("page_size", 50)
    )


@action(
    name="get_lark_bot_info",
    description="Get the connected Lark bot's profile (app name, open_id).",
    action_sets=["lark"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_bot_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("lark", "get_bot_info")
