from agent_core import action


@action(
    name="send_whatsapp_web_text_message",
    description="Send a text message via WhatsApp Web.",
    action_sets=["whatsapp"],
    input_schema={
        "to": {
            "type": "string",
            "description": "Recipient phone number (e.g. '1234567890') OR the exact `number` / `id` value returned by search_whatsapp_contact (e.g. '185628603977847@lid'). Pass the value verbatim — do NOT strip the '@lid' or '@c.us' suffix.",
            "example": "1234567890",
        },
        "message": {
            "type": "string",
            "description": "Message text.",
            "example": "Hello!",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_whatsapp_web_text_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import (
        record_outgoing_message,
        run_client,
    )

    # Record to conversation history BEFORE sending (ensures correct ordering)
    record_outgoing_message("WhatsApp", input_data["to"], input_data["message"])
    return await run_client(
        "whatsapp_web",
        "send_message",
        recipient=input_data["to"],
        text=input_data["message"],
    )


@action(
    name="send_whatsapp_web_media_message",
    description="Send a media message via WhatsApp Web.",
    action_sets=["whatsapp"],
    input_schema={
        "to": {
            "type": "string",
            "description": "Recipient phone number (e.g. '1234567890') OR the exact `number` / `id` value returned by search_whatsapp_contact (e.g. '185628603977847@lid'). Pass the value verbatim — do NOT strip the '@lid' or '@c.us' suffix.",
            "example": "1234567890",
        },
        "media_path": {
            "type": "string",
            "description": "Local media path.",
            "example": "/path/to/img.jpg",
        },
        "caption": {
            "type": "string",
            "description": "Optional caption.",
            "example": "Caption",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_whatsapp_web_media_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "send_media",
        recipient=input_data["to"],
        media_path=input_data["media_path"],
        caption=input_data.get("caption"),
    )


@action(
    name="get_whatsapp_chat_history",
    description="Get chat history (WhatsApp Web).",
    action_sets=["whatsapp"],
    input_schema={
        "phone_number": {
            "type": "string",
            "description": "Phone number.",
            "example": "1234567890",
        },
        "limit": {"type": "integer", "description": "Limit.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_chat_history(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "get_chat_messages",
        phone_number=input_data["phone_number"],
        limit=input_data.get("limit", 50),
    )


@action(
    name="get_whatsapp_unread_chats",
    description="Get unread chats (WhatsApp Web).",
    action_sets=["whatsapp"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_unread_chats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("whatsapp_web", "get_unread_chats")


@action(
    name="search_whatsapp_contact",
    description="Search contact by name (WhatsApp Web).",
    action_sets=["whatsapp"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Contact name.",
            "example": "John Doe",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_whatsapp_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("whatsapp_web", "search_contact", name=input_data["name"])


@action(
    name="get_whatsapp_web_session_status",
    description="Get WhatsApp Web session status.",
    action_sets=["whatsapp"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_web_session_status(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("whatsapp_web", "get_session_status")
