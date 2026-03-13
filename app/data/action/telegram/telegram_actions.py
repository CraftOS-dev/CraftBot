from agent_core import action


# =====================================================================
# Bot API actions
# =====================================================================


@action(
    name="send_telegram_bot_message",
    description="Send a text message to a Telegram chat via bot. Use this ONLY when replying to Telegram Bot messages.",
    action_sets=["telegram_bot"],
    input_schema={
        "chat_id": {"type": "string", "description": "Telegram chat ID or @username.", "example": "123456789"},
        "text": {"type": "string", "description": "Message text to send.", "example": "Hello!"},
        "parse_mode": {"type": "string", "description": "Optional parse mode: HTML or Markdown.", "example": "HTML"},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "message": {"type": "string", "example": "Message sent"},
    },
)
async def send_telegram_bot_message(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.send_message(
            input_data["chat_id"],
            input_data["text"],
            parse_mode=input_data.get("parse_mode"),
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_telegram_photo",
    description="Send a photo to a Telegram chat via bot.",
    action_sets=["telegram_bot"],
    input_schema={
        "chat_id": {"type": "string", "description": "Telegram chat ID.", "example": "123456789"},
        "photo": {"type": "string", "description": "URL or file_id of the photo.", "example": "https://example.com/photo.jpg"},
        "caption": {"type": "string", "description": "Optional photo caption.", "example": "Check this out"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_telegram_photo(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.send_photo(
            input_data["chat_id"],
            input_data["photo"],
            caption=input_data.get("caption"),
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_telegram_updates",
    description="Get incoming updates (messages) for the Telegram bot.",
    action_sets=["telegram_bot"],
    input_schema={
        "limit": {"type": "integer", "description": "Max number of updates to retrieve.", "example": 10},
        "offset": {"type": "integer", "description": "Update offset for pagination.", "example": 0},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "updates": {"type": "array", "description": "List of update objects."},
    },
)
async def get_telegram_updates(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.get_updates(
            offset=input_data.get("offset"),
            limit=input_data.get("limit", 100),
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_telegram_chat",
    description="Get information about a Telegram chat via bot.",
    action_sets=["telegram_bot"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID or @username.", "example": "123456789"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chat(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.get_chat(input_data["chat_id"])
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="search_telegram_contact",
    description="Search for a Telegram contact by name from bot's recent chat history.",
    action_sets=["telegram_bot"],
    input_schema={
        "name": {"type": "string", "description": "Contact name to search for.", "example": "John"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_telegram_contact(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.search_contact(input_data["name"])
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_telegram_document",
    description="Send a document to a Telegram chat via bot.",
    action_sets=["telegram_bot"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "document": {"type": "string", "description": "File ID or URL.", "example": "https://example.com/doc.pdf"},
        "caption": {"type": "string", "description": "Caption.", "example": "Here is the file"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_telegram_document(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.send_document(
            input_data["chat_id"],
            input_data["document"],
            caption=input_data.get("caption"),
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="forward_telegram_message",
    description="Forward a message via bot.",
    action_sets=["telegram_bot"],
    input_schema={
        "chat_id": {"type": "string", "description": "Dest Chat ID.", "example": "123"},
        "from_chat_id": {"type": "string", "description": "Source Chat ID.", "example": "456"},
        "message_id": {"type": "integer", "description": "Message ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def forward_telegram_message(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.forward_message(
            input_data["chat_id"],
            input_data["from_chat_id"],
            input_data["message_id"],
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_telegram_bot_info",
    description="Get bot info.",
    action_sets=["telegram_bot"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_bot_info(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.get_me()
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_telegram_chat_members_count",
    description="Get chat members count via bot.",
    action_sets=["telegram_bot"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chat_members_count(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_bot import TelegramBotClient
    try:
        client = TelegramBotClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram bot credential. Use /telegram login first."}
        result = await client.get_chat_members_count(input_data["chat_id"])
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =====================================================================
# MTProto actions
# =====================================================================


@action(
    name="get_telegram_chats",
    description="Get chats via Telegram user account.",
    action_sets=["telegram_user"],
    input_schema={
        "limit": {"type": "integer", "description": "Limit.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chats(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_user import TelegramUserClient
    try:
        client = TelegramUserClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram user credential. Use /telegram login first."}
        result = await client.get_dialogs(limit=input_data.get("limit", 50))
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="read_telegram_messages",
    description="Read messages via Telegram user account.",
    action_sets=["telegram_user"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "limit": {"type": "integer", "description": "Limit.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def read_telegram_messages(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_user import TelegramUserClient
    try:
        client = TelegramUserClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram user credential. Use /telegram login first."}
        result = await client.get_messages(
            input_data["chat_id"],
            limit=input_data.get("limit", 50),
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_telegram_user_message",
    description="Send a text message via Telegram user account. Use this when replying to Telegram User messages.",
    action_sets=["telegram_user"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "text": {"type": "string", "description": "Text.", "example": "Hi"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_telegram_user_message(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_user import TelegramUserClient
    try:
        client = TelegramUserClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram user credential. Use /telegram login first."}
        result = await client.send_message(
            input_data["chat_id"],
            input_data["text"],
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_telegram_user_file",
    description="Send a file via Telegram user account.",
    action_sets=["telegram_user"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "file_path": {"type": "string", "description": "Path.", "example": "/path/to/file"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_telegram_user_file(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_user import TelegramUserClient
    try:
        client = TelegramUserClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram user credential. Use /telegram login first."}
        result = await client.send_file(
            input_data["chat_id"],
            input_data["file_path"],
        )
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="search_telegram_user_contacts",
    description="Search contacts via Telegram user account.",
    action_sets=["telegram_user"],
    input_schema={
        "query": {"type": "string", "description": "Query.", "example": "John"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_telegram_user_contacts(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_user import TelegramUserClient
    try:
        client = TelegramUserClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram user credential. Use /telegram login first."}
        result = await client.search_contacts(input_data["query"])
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_telegram_user_account_info",
    description="Get account info via Telegram user account.",
    action_sets=["telegram_user"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_user_account_info(input_data: dict) -> dict:
    from app.external_comms.platforms.telegram_user import TelegramUserClient
    try:
        client = TelegramUserClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Telegram user credential. Use /telegram login first."}
        result = await client.get_me()
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
