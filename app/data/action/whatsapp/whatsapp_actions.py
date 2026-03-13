from agent_core import action


@action(
    name="send_whatsapp_web_text_message",
    description="Send a text message via WhatsApp Web.",
    action_sets=["whatsapp"],
    input_schema={
        "to": {"type": "string", "description": "Recipient phone number.", "example": "1234567890"},
        "message": {"type": "string", "description": "Message text.", "example": "Hello!"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_whatsapp_web_text_message(input_data: dict) -> dict:
    from app.external_comms.registry import get_client
    try:
        client = get_client("whatsapp_web")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No WhatsApp credential. Please log into whatsapp first."}
        result = await client.send_message(
            recipient=input_data["to"],
            text=input_data["message"],
        )
        return {"status": result.get("status", "success"), "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_whatsapp_web_media_message",
    description="Send a media message via WhatsApp Web.",
    action_sets=["whatsapp"],
    input_schema={
        "to": {"type": "string", "description": "Recipient phone number.", "example": "1234567890"},
        "media_path": {"type": "string", "description": "Local media path.", "example": "/path/to/img.jpg"},
        "caption": {"type": "string", "description": "Optional caption.", "example": "Caption"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_whatsapp_web_media_message(input_data: dict) -> dict:
    from app.external_comms.registry import get_client
    try:
        client = get_client("whatsapp_web")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No WhatsApp credential. Please log into whatsapp first."}
        result = await client.send_media(
            recipient=input_data["to"],
            media_path=input_data["media_path"],
            caption=input_data.get("caption"),
        )
        return {"status": result.get("status", "success"), "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_whatsapp_chat_history",
    description="Get chat history (WhatsApp Web).",
    action_sets=["whatsapp"],
    input_schema={
        "phone_number": {"type": "string", "description": "Phone number.", "example": "1234567890"},
        "limit": {"type": "integer", "description": "Limit.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_chat_history(input_data: dict) -> dict:
    from app.external_comms.registry import get_client
    try:
        client = get_client("whatsapp_web")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No WhatsApp credential. Please log into whatsapp first."}
        result = await client.get_chat_messages(
            phone_number=input_data["phone_number"],
            limit=input_data.get("limit", 50),
        )
        return {"status": result.get("status", "success"), "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_whatsapp_unread_chats",
    description="Get unread chats (WhatsApp Web).",
    action_sets=["whatsapp"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_unread_chats(input_data: dict) -> dict:
    from app.external_comms.registry import get_client
    try:
        client = get_client("whatsapp_web")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No WhatsApp credential. Please log into whatsapp first."}
        result = await client.get_unread_chats()
        return {"status": result.get("status", "success"), "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="search_whatsapp_contact",
    description="Search contact by name (WhatsApp Web).",
    action_sets=["whatsapp"],
    input_schema={
        "name": {"type": "string", "description": "Contact name.", "example": "John Doe"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_whatsapp_contact(input_data: dict) -> dict:
    from app.external_comms.registry import get_client
    try:
        client = get_client("whatsapp_web")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No WhatsApp credential. Please log into whatsapp first."}
        result = await client.search_contact(name=input_data["name"])
        return {"status": result.get("status", "success"), "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_whatsapp_web_session_status",
    description="Get WhatsApp Web session status.",
    action_sets=["whatsapp"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_web_session_status(input_data: dict) -> dict:
    from app.external_comms.registry import get_client
    try:
        client = get_client("whatsapp_web")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No WhatsApp credential. Please log into whatsapp first."}
        result = await client.get_session_status()
        return {"status": result.get("status", "success"), "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
