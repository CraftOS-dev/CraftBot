from agent_core import action


# =====================================================================
# Bot API — Messages (text lifecycle, forward/copy/pin/reactions)
# Sub-set: telegram_messages
# =====================================================================


@action(
    name="send_telegram_bot_message",
    irreversible=True,
    description="Send a text message to a Telegram chat via bot. Use this ONLY when replying to Telegram Bot messages.",
    action_sets=["telegram_messages", "telegram"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Telegram chat ID or @username.",
            "example": "123456789",
        },
        "text": {
            "type": "string",
            "description": "Message text to send.",
            "example": "Hello!",
        },
        "parse_mode": {
            "type": "string",
            "description": "Optional parse mode: HTML or MarkdownV2.",
            "example": "HTML",
        },
        "reply_to_message_id": {
            "type": "integer",
            "description": "Optional message to reply to.",
            "example": 42,
        },
        "disable_web_page_preview": {
            "type": "boolean",
            "description": "Disable link previews.",
            "example": False,
        },
        "reply_markup": {
            "type": "object",
            "description": "Optional reply markup (inline keyboard etc.).",
            "example": {},
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_bot_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import (
        pick_result,
        record_outgoing_message,
        run_client,
    )

    record_outgoing_message("Telegram", input_data["chat_id"], input_data["text"])
    res = await run_client(
        "telegram_bot",
        "send_message",
        recipient=input_data["chat_id"],
        text=input_data["text"],
        parse_mode=input_data.get("parse_mode"),
        reply_to_message_id=input_data.get("reply_to_message_id"),
        disable_web_page_preview=input_data.get("disable_web_page_preview"),
        reply_markup=input_data.get("reply_markup"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_text_message",
    irreversible=True,
    description="Send a text message via Telegram bot (alias for sendMessage with full options).",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Chat ID or @username.",
            "example": "123456789",
        },
        "text": {"type": "string", "description": "Message text.", "example": "Hi"},
        "parse_mode": {
            "type": "string",
            "description": "HTML or MarkdownV2.",
            "example": "HTML",
        },
        "reply_to_message_id": {
            "type": "integer",
            "description": "Reply target message id.",
            "example": 42,
        },
        "disable_web_page_preview": {
            "type": "boolean",
            "description": "Disable preview.",
            "example": False,
        },
        "disable_notification": {
            "type": "boolean",
            "description": "Send silently.",
            "example": False,
        },
        "reply_markup": {
            "type": "object",
            "description": "Reply markup.",
            "example": {},
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_text_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_text_message",
        chat_id=input_data["chat_id"],
        text=input_data["text"],
        parse_mode=input_data.get("parse_mode"),
        reply_to_message_id=input_data.get("reply_to_message_id"),
        disable_web_page_preview=input_data.get("disable_web_page_preview"),
        disable_notification=input_data.get("disable_notification"),
        reply_markup=input_data.get("reply_markup"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="edit_telegram_message_text",
    description="Edit the text of a message sent by the bot.",
    action_sets=["telegram_messages", "telegram"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {"type": "integer", "description": "Message ID.", "example": 42},
        "text": {"type": "string", "description": "New text.", "example": "Edited"},
        "parse_mode": {
            "type": "string",
            "description": "Parse mode.",
            "example": "HTML",
        },
        "reply_markup": {
            "type": "object",
            "description": "New reply markup.",
            "example": {},
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def edit_telegram_message_text(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "edit_message_text",
        chat_id=input_data["chat_id"],
        message_id=input_data["message_id"],
        text=input_data["text"],
        parse_mode=input_data.get("parse_mode"),
        reply_markup=input_data.get("reply_markup"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="edit_telegram_message_caption",
    description="Edit the caption of a media message.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {"type": "integer", "description": "Message ID.", "example": 42},
        "caption": {
            "type": "string",
            "description": "New caption.",
            "example": "New caption",
        },
        "parse_mode": {
            "type": "string",
            "description": "Parse mode.",
            "example": "HTML",
        },
        "reply_markup": {
            "type": "object",
            "description": "Reply markup.",
            "example": {},
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def edit_telegram_message_caption(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "edit_message_caption",
        chat_id=input_data["chat_id"],
        message_id=input_data["message_id"],
        caption=input_data.get("caption"),
        parse_mode=input_data.get("parse_mode"),
        reply_markup=input_data.get("reply_markup"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="edit_telegram_message_reply_markup",
    description="Edit only the reply markup of a message.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {"type": "integer", "description": "Message ID.", "example": 42},
        "reply_markup": {
            "type": "object",
            "description": "Reply markup.",
            "example": {},
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def edit_telegram_message_reply_markup(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "edit_message_reply_markup",
        chat_id=input_data["chat_id"],
        message_id=input_data["message_id"],
        reply_markup=input_data.get("reply_markup"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="delete_telegram_message",
    description="Delete a single message sent by or visible to the bot.",
    action_sets=["telegram_messages", "telegram"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {"type": "integer", "description": "Message ID.", "example": 42},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def delete_telegram_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "delete_message",
        chat_id=input_data["chat_id"],
        message_id=input_data["message_id"],
    )


@action(
    name="delete_telegram_messages",
    description="Delete multiple messages in a chat in one call.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_ids": {
            "type": "array",
            "description": "List of message IDs.",
            "example": [1, 2, 3],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def delete_telegram_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "delete_messages",
        chat_id=input_data["chat_id"],
        message_ids=input_data["message_ids"],
    )


@action(
    name="copy_telegram_message",
    description="Copy a message to another chat (does not include the 'forwarded from' header).",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Destination chat.",
            "example": "123",
        },
        "from_chat_id": {
            "type": "string",
            "description": "Source chat.",
            "example": "456",
        },
        "message_id": {
            "type": "integer",
            "description": "Source message ID.",
            "example": 42,
        },
        "caption": {
            "type": "string",
            "description": "Optional new caption.",
            "example": "Copied",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def copy_telegram_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "copy_message",
        chat_id=input_data["chat_id"],
        from_chat_id=input_data["from_chat_id"],
        message_id=input_data["message_id"],
        caption=input_data.get("caption"),
    )


@action(
    name="forward_telegram_message",
    irreversible=True,
    description="Forward a message via bot.",
    action_sets=["telegram_messages", "telegram"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Destination chat.",
            "example": "123",
        },
        "from_chat_id": {
            "type": "string",
            "description": "Source chat.",
            "example": "456",
        },
        "message_id": {"type": "integer", "description": "Message ID.", "example": 1},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def forward_telegram_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "forward_message",
        chat_id=input_data["chat_id"],
        from_chat_id=input_data["from_chat_id"],
        message_id=input_data["message_id"],
    )
    return pick_result(res, ["message_id"])


@action(
    name="forward_telegram_messages",
    irreversible=True,
    description="Forward multiple messages of any kind.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Destination chat.",
            "example": "123",
        },
        "from_chat_id": {
            "type": "string",
            "description": "Source chat.",
            "example": "456",
        },
        "message_ids": {
            "type": "array",
            "description": "List of message IDs.",
            "example": [1, 2, 3],
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_ids": [43, 44]}},
    },
)
async def forward_telegram_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "telegram_bot",
        "forward_messages",
        chat_id=input_data["chat_id"],
        from_chat_id=input_data["from_chat_id"],
        message_ids=input_data["message_ids"],
    )
    if res.get("status") == "success" and isinstance(res.get("result"), list):
        res = {
            **res,
            "result": {
                "message_ids": [
                    m.get("message_id")
                    for m in res["result"]
                    if isinstance(m, dict) and m.get("message_id") is not None
                ]
            },
        }
    return res


@action(
    name="pin_telegram_message",
    description="Pin a message in a chat.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {"type": "integer", "description": "Message ID.", "example": 42},
        "disable_notification": {
            "type": "boolean",
            "description": "Silent pin.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def pin_telegram_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "pin_message",
        chat_id=input_data["chat_id"],
        message_id=input_data["message_id"],
        disable_notification=input_data.get("disable_notification"),
    )


@action(
    name="unpin_telegram_message",
    description="Unpin a specific message (or the most recent if omitted).",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {
            "type": "integer",
            "description": "Optional message ID.",
            "example": 42,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def unpin_telegram_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "unpin_message",
        chat_id=input_data["chat_id"],
        message_id=input_data.get("message_id"),
    )


@action(
    name="unpin_all_telegram_messages",
    description="Clear the list of pinned messages in a chat.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def unpin_all_telegram_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "unpin_all_messages",
        chat_id=input_data["chat_id"],
    )


@action(
    name="set_telegram_message_reaction",
    description="Set or remove emoji reactions on a message.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {"type": "integer", "description": "Message ID.", "example": 42},
        "reactions": {
            "type": "array",
            "description": "Array of reaction objects, e.g. [{type:'emoji', emoji:'👍'}].",
            "example": [{"type": "emoji", "emoji": "👍"}],
        },
        "is_big": {
            "type": "boolean",
            "description": "Animated big reaction.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_message_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_message_reaction",
        chat_id=input_data["chat_id"],
        message_id=input_data["message_id"],
        reactions=input_data.get("reactions"),
        is_big=input_data.get("is_big"),
    )


@action(
    name="send_telegram_chat_action",
    description="Show 'typing', 'upload_photo', etc. indicators to the user.",
    action_sets=["telegram_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "action_type": {
            "type": "string",
            "description": "typing | upload_photo | record_video | upload_video | record_voice | upload_voice | upload_document | choose_sticker | find_location | record_video_note | upload_video_note.",
            "example": "typing",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_telegram_chat_action(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "send_chat_action",
        chat_id=input_data["chat_id"],
        action=input_data["action_type"],
    )


# =====================================================================
# Bot API — Media (photo/video/audio/voice/document/poll/etc.)
# Sub-set: telegram_media
# =====================================================================


@action(
    name="send_telegram_photo",
    irreversible=True,
    description="Send a photo to a Telegram chat via bot.",
    action_sets=["telegram_media", "telegram"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "photo": {
            "type": "string",
            "description": "URL or file_id.",
            "example": "https://example.com/p.jpg",
        },
        "caption": {"type": "string", "description": "Caption.", "example": "Cool pic"},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_photo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_photo",
        chat_id=input_data["chat_id"],
        photo=input_data["photo"],
        caption=input_data.get("caption"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_document",
    irreversible=True,
    description="Send a document to a Telegram chat via bot.",
    action_sets=["telegram_media", "telegram"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "document": {
            "type": "string",
            "description": "File ID or URL.",
            "example": "https://example.com/doc.pdf",
        },
        "caption": {
            "type": "string",
            "description": "Caption.",
            "example": "Here is the file",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_document(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_document",
        chat_id=input_data["chat_id"],
        document=input_data["document"],
        caption=input_data.get("caption"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_video",
    irreversible=True,
    description="Send a video file via bot.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "video": {
            "type": "string",
            "description": "File ID or URL.",
            "example": "https://example.com/v.mp4",
        },
        "caption": {"type": "string", "description": "Caption.", "example": ""},
        "duration": {
            "type": "integer",
            "description": "Duration in seconds.",
            "example": 30,
        },
        "supports_streaming": {
            "type": "boolean",
            "description": "Streaming-capable.",
            "example": True,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_video(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_video",
        chat_id=input_data["chat_id"],
        video=input_data["video"],
        caption=input_data.get("caption"),
        duration=input_data.get("duration"),
        supports_streaming=input_data.get("supports_streaming"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_audio",
    irreversible=True,
    description="Send an audio file (music) via bot.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "audio": {
            "type": "string",
            "description": "File ID or URL.",
            "example": "https://example.com/a.mp3",
        },
        "caption": {"type": "string", "description": "Caption.", "example": ""},
        "title": {"type": "string", "description": "Track title.", "example": "Song"},
        "performer": {"type": "string", "description": "Artist.", "example": "Artist"},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_audio(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_audio",
        chat_id=input_data["chat_id"],
        audio=input_data["audio"],
        caption=input_data.get("caption"),
        title=input_data.get("title"),
        performer=input_data.get("performer"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_voice",
    irreversible=True,
    description="Send a voice message (OGG opus) via bot.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "voice": {
            "type": "string",
            "description": "File ID or URL.",
            "example": "https://example.com/v.ogg",
        },
        "caption": {"type": "string", "description": "Caption.", "example": ""},
        "duration": {
            "type": "integer",
            "description": "Duration in seconds.",
            "example": 10,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_voice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_voice",
        chat_id=input_data["chat_id"],
        voice=input_data["voice"],
        caption=input_data.get("caption"),
        duration=input_data.get("duration"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_video_note",
    irreversible=True,
    description="Send a rounded square video note (short circular video).",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "video_note": {
            "type": "string",
            "description": "File ID or URL.",
            "example": "https://example.com/note.mp4",
        },
        "duration": {
            "type": "integer",
            "description": "Duration in seconds.",
            "example": 10,
        },
        "length": {"type": "integer", "description": "Side length.", "example": 240},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_video_note(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_video_note",
        chat_id=input_data["chat_id"],
        video_note=input_data["video_note"],
        duration=input_data.get("duration"),
        length=input_data.get("length"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_animation",
    irreversible=True,
    description="Send an animation (GIF or H.264/MPEG-4 without sound).",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "animation": {
            "type": "string",
            "description": "File ID or URL.",
            "example": "https://example.com/anim.gif",
        },
        "caption": {"type": "string", "description": "Caption.", "example": ""},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_animation(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_animation",
        chat_id=input_data["chat_id"],
        animation=input_data["animation"],
        caption=input_data.get("caption"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_sticker",
    irreversible=True,
    description="Send a sticker (.webp / .tgs / .webm).",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "sticker": {
            "type": "string",
            "description": "File ID or URL or emoji.",
            "example": "CAACAgQA...",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_sticker(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_sticker",
        chat_id=input_data["chat_id"],
        sticker=input_data["sticker"],
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_location",
    irreversible=True,
    description="Send a geographic location.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "latitude": {"type": "number", "description": "Latitude.", "example": 37.7749},
        "longitude": {
            "type": "number",
            "description": "Longitude.",
            "example": -122.4194,
        },
        "live_period": {
            "type": "integer",
            "description": "Live location duration in seconds.",
            "example": 60,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_location(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_location",
        chat_id=input_data["chat_id"],
        latitude=input_data["latitude"],
        longitude=input_data["longitude"],
        live_period=input_data.get("live_period"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_venue",
    irreversible=True,
    description="Send a venue with name and address.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "latitude": {"type": "number", "description": "Latitude.", "example": 37.7749},
        "longitude": {
            "type": "number",
            "description": "Longitude.",
            "example": -122.4194,
        },
        "title": {"type": "string", "description": "Venue name.", "example": "Cafe X"},
        "address": {
            "type": "string",
            "description": "Venue address.",
            "example": "1 Main St",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_venue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_venue",
        chat_id=input_data["chat_id"],
        latitude=input_data["latitude"],
        longitude=input_data["longitude"],
        title=input_data["title"],
        address=input_data["address"],
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_contact",
    irreversible=True,
    description="Send a phone contact card.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "phone_number": {
            "type": "string",
            "description": "Phone number.",
            "example": "+15551234567",
        },
        "first_name": {
            "type": "string",
            "description": "First name.",
            "example": "John",
        },
        "last_name": {"type": "string", "description": "Last name.", "example": "Doe"},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_contact",
        chat_id=input_data["chat_id"],
        phone_number=input_data["phone_number"],
        first_name=input_data["first_name"],
        last_name=input_data.get("last_name"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_dice",
    irreversible=True,
    description="Send an animated dice / emoji-game (🎲 🎯 🏀 ⚽ 🎳 🎰).",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "emoji": {
            "type": "string",
            "description": "One of 🎲 🎯 🏀 ⚽ 🎳 🎰.",
            "example": "🎲",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_dice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_dice",
        chat_id=input_data["chat_id"],
        emoji=input_data.get("emoji"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="send_telegram_poll",
    irreversible=True,
    description="Send a poll to a chat.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "question": {
            "type": "string",
            "description": "Poll question.",
            "example": "Best language?",
        },
        "options": {
            "type": "array",
            "description": "Poll option strings.",
            "example": ["Python", "Go", "Rust"],
        },
        "is_anonymous": {
            "type": "boolean",
            "description": "Anonymous poll.",
            "example": True,
        },
        "type": {
            "type": "string",
            "description": "quiz | regular.",
            "example": "regular",
        },
        "allows_multiple_answers": {
            "type": "boolean",
            "description": "Allow multi-select.",
            "example": False,
        },
        "correct_option_id": {
            "type": "integer",
            "description": "Quiz correct option index.",
            "example": 0,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_id": 42}},
    },
)
async def send_telegram_poll(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "telegram_bot",
        "send_poll",
        chat_id=input_data["chat_id"],
        question=input_data["question"],
        options=input_data["options"],
        is_anonymous=input_data.get("is_anonymous"),
        type=input_data.get("type"),
        allows_multiple_answers=input_data.get("allows_multiple_answers"),
        correct_option_id=input_data.get("correct_option_id"),
    )
    return pick_result(res, ["message_id"])


@action(
    name="stop_telegram_poll",
    description="Stop an active poll.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "message_id": {
            "type": "integer",
            "description": "Poll message ID.",
            "example": 42,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def stop_telegram_poll(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "stop_poll",
        chat_id=input_data["chat_id"],
        message_id=input_data["message_id"],
    )


@action(
    name="send_telegram_media_group",
    irreversible=True,
    description="Send a group of photos/videos/audios/documents as an album.",
    action_sets=["telegram_media"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "media": {
            "type": "array",
            "description": "Array of InputMedia objects (type, media, caption).",
            "example": [
                {"type": "photo", "media": "https://example.com/1.jpg"},
                {"type": "photo", "media": "https://example.com/2.jpg"},
            ],
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object", "example": {"message_ids": [43, 44]}},
    },
)
async def send_telegram_media_group(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "telegram_bot",
        "send_media_group",
        chat_id=input_data["chat_id"],
        media=input_data["media"],
    )
    if res.get("status") == "success" and isinstance(res.get("result"), list):
        res = {
            **res,
            "result": {
                "message_ids": [
                    m.get("message_id")
                    for m in res["result"]
                    if isinstance(m, dict) and m.get("message_id") is not None
                ]
            },
        }
    return res


@action(
    name="get_telegram_file",
    description="Get file metadata (including file_path) for a file_id.",
    action_sets=["telegram_media"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": "AgAC..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_file",
        file_id=input_data["file_id"],
    )


@action(
    name="download_telegram_file",
    description="Resolve a file_id and stream the bytes to a local path.",
    action_sets=["telegram_media"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": "AgAC..."},
        "dest_path": {
            "type": "string",
            "description": "Local file path to save to.",
            "example": "/tmp/file.bin",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def download_telegram_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "download_file",
        file_id=input_data["file_id"],
        dest_path=input_data["dest_path"],
    )


# =====================================================================
# Bot API — Chats (info, members, admin, invite links)
# Sub-set: telegram_chats
# =====================================================================


@action(
    name="get_telegram_chat",
    description="Get information about a Telegram chat via bot.",
    action_sets=["telegram_chats", "telegram"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Chat ID or @username.",
            "example": "123456789",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("telegram_bot", "get_chat", chat_id=input_data["chat_id"])


@action(
    name="get_telegram_chat_members_count",
    description="Get chat members count via bot.",
    action_sets=["telegram_chats", "telegram"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chat_members_count(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_chat_members_count",
        chat_id=input_data["chat_id"],
    )


@action(
    name="get_telegram_chat_administrators",
    description="List the administrators of a chat.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chat_administrators(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_chat_administrators",
        chat_id=input_data["chat_id"],
    )


@action(
    name="ban_telegram_chat_member",
    description="Ban a user from a group/supergroup/channel.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {"type": "integer", "description": "User ID.", "example": 987654321},
        "until_date": {
            "type": "integer",
            "description": "Unix timestamp ban-until (0 = forever).",
            "example": 0,
        },
        "revoke_messages": {
            "type": "boolean",
            "description": "Delete all messages from user.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def ban_telegram_chat_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "ban_chat_member",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
        until_date=input_data.get("until_date"),
        revoke_messages=input_data.get("revoke_messages"),
    )


@action(
    name="unban_telegram_chat_member",
    description="Unban a previously banned user.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {"type": "integer", "description": "User ID.", "example": 987654321},
        "only_if_banned": {
            "type": "boolean",
            "description": "Only if currently banned.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def unban_telegram_chat_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "unban_chat_member",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
        only_if_banned=input_data.get("only_if_banned"),
    )


@action(
    name="restrict_telegram_chat_member",
    description="Restrict a user in a supergroup with specific ChatPermissions.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {"type": "integer", "description": "User ID.", "example": 987654321},
        "permissions": {
            "type": "object",
            "description": "ChatPermissions object.",
            "example": {"can_send_messages": False},
        },
        "until_date": {
            "type": "integer",
            "description": "Unix timestamp restrict-until.",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def restrict_telegram_chat_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "restrict_chat_member",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
        permissions=input_data["permissions"],
        until_date=input_data.get("until_date"),
    )


@action(
    name="promote_telegram_chat_member",
    description="Promote or demote a user. Pass False to remove a privilege.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {"type": "integer", "description": "User ID.", "example": 987654321},
        "is_anonymous": {
            "type": "boolean",
            "description": "Anonymous admin.",
            "example": False,
        },
        "can_manage_chat": {
            "type": "boolean",
            "description": "Manage chat privilege.",
            "example": True,
        },
        "can_delete_messages": {
            "type": "boolean",
            "description": "Delete messages.",
            "example": True,
        },
        "can_manage_video_chats": {
            "type": "boolean",
            "description": "Manage video chats.",
            "example": False,
        },
        "can_restrict_members": {
            "type": "boolean",
            "description": "Restrict members.",
            "example": True,
        },
        "can_promote_members": {
            "type": "boolean",
            "description": "Promote members.",
            "example": False,
        },
        "can_change_info": {
            "type": "boolean",
            "description": "Change chat info.",
            "example": False,
        },
        "can_invite_users": {
            "type": "boolean",
            "description": "Invite users.",
            "example": True,
        },
        "can_post_messages": {
            "type": "boolean",
            "description": "Channel post.",
            "example": False,
        },
        "can_edit_messages": {
            "type": "boolean",
            "description": "Channel edit.",
            "example": False,
        },
        "can_pin_messages": {
            "type": "boolean",
            "description": "Pin messages.",
            "example": False,
        },
        "can_manage_topics": {
            "type": "boolean",
            "description": "Manage forum topics.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def promote_telegram_chat_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "promote_chat_member",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
        is_anonymous=input_data.get("is_anonymous"),
        can_manage_chat=input_data.get("can_manage_chat"),
        can_delete_messages=input_data.get("can_delete_messages"),
        can_manage_video_chats=input_data.get("can_manage_video_chats"),
        can_restrict_members=input_data.get("can_restrict_members"),
        can_promote_members=input_data.get("can_promote_members"),
        can_change_info=input_data.get("can_change_info"),
        can_invite_users=input_data.get("can_invite_users"),
        can_post_messages=input_data.get("can_post_messages"),
        can_edit_messages=input_data.get("can_edit_messages"),
        can_pin_messages=input_data.get("can_pin_messages"),
        can_manage_topics=input_data.get("can_manage_topics"),
    )


@action(
    name="set_telegram_chat_administrator_custom_title",
    description="Set a custom title for an administrator.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {
            "type": "integer",
            "description": "Admin user ID.",
            "example": 987654321,
        },
        "custom_title": {
            "type": "string",
            "description": "Custom title (max 16 chars).",
            "example": "Owner",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_chat_administrator_custom_title(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_chat_administrator_custom_title",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
        custom_title=input_data["custom_title"],
    )


@action(
    name="set_telegram_chat_permissions",
    description="Set default chat permissions for all non-admin members.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "permissions": {
            "type": "object",
            "description": "ChatPermissions object.",
            "example": {"can_send_messages": True},
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_chat_permissions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_chat_permissions",
        chat_id=input_data["chat_id"],
        permissions=input_data["permissions"],
    )


@action(
    name="set_telegram_chat_title",
    description="Change the title of a chat.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "title": {
            "type": "string",
            "description": "New title (1-128 chars).",
            "example": "New Chat Name",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_chat_title(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_chat_title",
        chat_id=input_data["chat_id"],
        title=input_data["title"],
    )


@action(
    name="set_telegram_chat_description",
    description="Change the description of a group/supergroup/channel.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "description": {
            "type": "string",
            "description": "New description (0-255 chars).",
            "example": "About this chat",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_chat_description(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_chat_description",
        chat_id=input_data["chat_id"],
        description=input_data.get("description"),
    )


@action(
    name="delete_telegram_chat_photo",
    description="Delete the photo of a group/supergroup/channel.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def delete_telegram_chat_photo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "delete_chat_photo",
        chat_id=input_data["chat_id"],
    )


@action(
    name="leave_telegram_chat",
    description="Make the bot leave a chat.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def leave_telegram_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "leave_chat",
        chat_id=input_data["chat_id"],
    )


@action(
    name="get_telegram_chat_member",
    description="Get information about a member of a chat.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {"type": "integer", "description": "User ID.", "example": 987654321},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chat_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_chat_member",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="export_telegram_chat_invite_link",
    description="Generate a new primary invite link, revoking previous primary.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def export_telegram_chat_invite_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "export_chat_invite_link",
        chat_id=input_data["chat_id"],
    )


@action(
    name="create_telegram_chat_invite_link",
    description="Create an additional invite link (does not revoke the primary).",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "name": {"type": "string", "description": "Invite name.", "example": "VIP"},
        "expire_date": {
            "type": "integer",
            "description": "Unix timestamp expire.",
            "example": 1735689600,
        },
        "member_limit": {
            "type": "integer",
            "description": "Max members 1-99999.",
            "example": 10,
        },
        "creates_join_request": {
            "type": "boolean",
            "description": "Require admin approval.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def create_telegram_chat_invite_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "create_chat_invite_link",
        chat_id=input_data["chat_id"],
        name=input_data.get("name"),
        expire_date=input_data.get("expire_date"),
        member_limit=input_data.get("member_limit"),
        creates_join_request=input_data.get("creates_join_request"),
    )


@action(
    name="edit_telegram_chat_invite_link",
    description="Edit an existing non-primary invite link.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "invite_link": {
            "type": "string",
            "description": "Invite link to edit.",
            "example": "https://t.me/+abc",
        },
        "name": {"type": "string", "description": "Name.", "example": "VIP-renamed"},
        "expire_date": {
            "type": "integer",
            "description": "Unix timestamp.",
            "example": 1735689600,
        },
        "member_limit": {
            "type": "integer",
            "description": "Max members.",
            "example": 20,
        },
        "creates_join_request": {
            "type": "boolean",
            "description": "Approval flow.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def edit_telegram_chat_invite_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "edit_chat_invite_link",
        chat_id=input_data["chat_id"],
        invite_link=input_data["invite_link"],
        name=input_data.get("name"),
        expire_date=input_data.get("expire_date"),
        member_limit=input_data.get("member_limit"),
        creates_join_request=input_data.get("creates_join_request"),
    )


@action(
    name="revoke_telegram_chat_invite_link",
    description="Revoke an invite link.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "invite_link": {
            "type": "string",
            "description": "Invite link.",
            "example": "https://t.me/+abc",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def revoke_telegram_chat_invite_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "revoke_chat_invite_link",
        chat_id=input_data["chat_id"],
        invite_link=input_data["invite_link"],
    )


@action(
    name="approve_telegram_chat_join_request",
    description="Approve a pending chat join request.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {"type": "integer", "description": "User ID.", "example": 987654321},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def approve_telegram_chat_join_request(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "approve_chat_join_request",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="decline_telegram_chat_join_request",
    description="Decline a pending chat join request.",
    action_sets=["telegram_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "user_id": {"type": "integer", "description": "User ID.", "example": 987654321},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def decline_telegram_chat_join_request(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "decline_chat_join_request",
        chat_id=input_data["chat_id"],
        user_id=input_data["user_id"],
    )


# =====================================================================
# Bot API — Bot configuration (commands, descriptions, menu button)
# Sub-set: telegram_bot_config
# =====================================================================


@action(
    name="set_telegram_my_commands",
    description="Set the list of bot commands shown in the Telegram UI.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "commands": {
            "type": "array",
            "description": "List of {command, description} objects.",
            "example": [{"command": "start", "description": "Start the bot"}],
        },
        "scope": {
            "type": "object",
            "description": "BotCommandScope.",
            "example": {"type": "default"},
        },
        "language_code": {
            "type": "string",
            "description": "IETF tag.",
            "example": "en",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_my_commands(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_my_commands",
        commands=input_data["commands"],
        scope=input_data.get("scope"),
        language_code=input_data.get("language_code"),
    )


@action(
    name="get_telegram_my_commands",
    description="Get the current list of bot commands.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "scope": {
            "type": "object",
            "description": "BotCommandScope.",
            "example": {"type": "default"},
        },
        "language_code": {
            "type": "string",
            "description": "IETF tag.",
            "example": "en",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_my_commands(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_my_commands",
        scope=input_data.get("scope"),
        language_code=input_data.get("language_code"),
    )


@action(
    name="delete_telegram_my_commands",
    description="Delete the bot commands list for a given scope.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "scope": {
            "type": "object",
            "description": "BotCommandScope.",
            "example": {"type": "default"},
        },
        "language_code": {
            "type": "string",
            "description": "IETF tag.",
            "example": "en",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def delete_telegram_my_commands(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "delete_my_commands",
        scope=input_data.get("scope"),
        language_code=input_data.get("language_code"),
    )


@action(
    name="set_telegram_my_description",
    description="Set the bot's long description (shown on empty-chat screen).",
    action_sets=["telegram_bot_config"],
    input_schema={
        "description": {
            "type": "string",
            "description": "0-512 chars.",
            "example": "My great bot",
        },
        "language_code": {
            "type": "string",
            "description": "IETF tag.",
            "example": "en",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_my_description(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_my_description",
        description=input_data.get("description"),
        language_code=input_data.get("language_code"),
    )


@action(
    name="get_telegram_my_description",
    description="Get the bot's current description.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "language_code": {
            "type": "string",
            "description": "IETF tag.",
            "example": "en",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_my_description(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_my_description",
        language_code=input_data.get("language_code"),
    )


@action(
    name="set_telegram_my_short_description",
    description="Set the bot's short description (shown on profile page and link previews).",
    action_sets=["telegram_bot_config"],
    input_schema={
        "short_description": {
            "type": "string",
            "description": "0-120 chars.",
            "example": "Helpful AI",
        },
        "language_code": {
            "type": "string",
            "description": "IETF tag.",
            "example": "en",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_my_short_description(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_my_short_description",
        short_description=input_data.get("short_description"),
        language_code=input_data.get("language_code"),
    )


@action(
    name="set_telegram_my_name",
    description="Set the bot's display name.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "name": {"type": "string", "description": "0-64 chars.", "example": "CraftBot"},
        "language_code": {
            "type": "string",
            "description": "IETF tag.",
            "example": "en",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_my_name(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_my_name",
        name=input_data.get("name"),
        language_code=input_data.get("language_code"),
    )


@action(
    name="set_telegram_chat_menu_button",
    description="Set the menu button shown in a specific chat (or default).",
    action_sets=["telegram_bot_config"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Chat ID (omit for default).",
            "example": "123",
        },
        "menu_button": {
            "type": "object",
            "description": "MenuButton object.",
            "example": {"type": "commands"},
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_chat_menu_button(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_chat_menu_button",
        chat_id=input_data.get("chat_id"),
        menu_button=input_data.get("menu_button"),
    )


@action(
    name="get_telegram_chat_menu_button",
    description="Get the menu button for a chat or default.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Chat ID (omit for default).",
            "example": "123",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chat_menu_button(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_chat_menu_button",
        chat_id=input_data.get("chat_id"),
    )


@action(
    name="set_telegram_my_default_administrator_rights",
    description="Set default admin rights requested when bot is added to a group/channel.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "rights": {
            "type": "object",
            "description": "ChatAdministratorRights object.",
            "example": {"is_anonymous": False, "can_manage_chat": True},
        },
        "for_channels": {
            "type": "boolean",
            "description": "True for channels, false/omit for groups.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_my_default_administrator_rights(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_my_default_administrator_rights",
        rights=input_data.get("rights"),
        for_channels=input_data.get("for_channels"),
    )


@action(
    name="get_telegram_my_default_administrator_rights",
    description="Get default admin rights.",
    action_sets=["telegram_bot_config"],
    input_schema={
        "for_channels": {
            "type": "boolean",
            "description": "True for channels.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_my_default_administrator_rights(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "get_my_default_administrator_rights",
        for_channels=input_data.get("for_channels"),
    )


@action(
    name="get_telegram_bot_info",
    description="Get bot info (getMe).",
    action_sets=["telegram_bot_config", "telegram"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_bot_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("telegram_bot", "get_me")


# =====================================================================
# Bot API — Callback queries
# Sub-set: telegram_callbacks
# =====================================================================


@action(
    name="answer_telegram_callback_query",
    description="Answer an inline-keyboard callback query (optional notification text or alert).",
    action_sets=["telegram_callbacks"],
    input_schema={
        "callback_query_id": {
            "type": "string",
            "description": "Callback query ID.",
            "example": "abc123",
        },
        "text": {
            "type": "string",
            "description": "Notification text (0-200 chars).",
            "example": "Got it",
        },
        "show_alert": {
            "type": "boolean",
            "description": "Show as alert dialog.",
            "example": False,
        },
        "url": {
            "type": "string",
            "description": "Open this URL.",
            "example": "https://example.com",
        },
        "cache_time": {
            "type": "integer",
            "description": "Cache seconds.",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def answer_telegram_callback_query(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "answer_callback_query",
        callback_query_id=input_data["callback_query_id"],
        text=input_data.get("text"),
        show_alert=input_data.get("show_alert"),
        url=input_data.get("url"),
        cache_time=input_data.get("cache_time"),
    )


# =====================================================================
# Bot API — Webhooks
# Sub-set: telegram_webhooks
# =====================================================================


@action(
    name="set_telegram_webhook",
    description="Register a webhook URL to receive updates via HTTPS POST.",
    action_sets=["telegram_webhooks"],
    input_schema={
        "url": {
            "type": "string",
            "description": "HTTPS URL.",
            "example": "https://example.com/tg-webhook",
        },
        "secret_token": {
            "type": "string",
            "description": "Header secret 1-256 chars.",
            "example": "topsecret",
        },
        "max_connections": {
            "type": "integer",
            "description": "Max concurrent updates 1-100.",
            "example": 40,
        },
        "allowed_updates": {
            "type": "array",
            "description": "List of update types to receive.",
            "example": ["message", "callback_query"],
        },
        "drop_pending_updates": {
            "type": "boolean",
            "description": "Drop pending updates.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def set_telegram_webhook(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "set_webhook",
        url=input_data["url"],
        secret_token=input_data.get("secret_token"),
        max_connections=input_data.get("max_connections"),
        allowed_updates=input_data.get("allowed_updates"),
        drop_pending_updates=input_data.get("drop_pending_updates"),
    )


@action(
    name="delete_telegram_webhook",
    description="Remove the registered webhook (returns to long polling).",
    action_sets=["telegram_webhooks"],
    input_schema={
        "drop_pending_updates": {
            "type": "boolean",
            "description": "Drop pending updates.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def delete_telegram_webhook(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_bot",
        "delete_webhook",
        drop_pending_updates=input_data.get("drop_pending_updates"),
    )


@action(
    name="get_telegram_webhook_info",
    description="Get current webhook registration info.",
    action_sets=["telegram_webhooks"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_webhook_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("telegram_bot", "get_webhook_info")


# =====================================================================
# Bot API — Updates / utility
# Sub-set: telegram_messages
# =====================================================================


@action(
    name="get_telegram_updates",
    description="Get incoming updates (messages) for the Telegram bot. Returns lean per-update summaries by default; set include_metadata=true for raw Update objects.",
    action_sets=["telegram_messages", "telegram"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max number of updates.",
            "example": 10,
        },
        "offset": {
            "type": "integer",
            "description": "Update offset for pagination.",
            "example": 0,
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw Update objects (default false = lean summaries).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "array",
            "description": "Lean: [{update_id, message_id, chat_id, from, text, date, type?}]. Raw Updates with include_metadata=true.",
        },
    },
)
async def get_telegram_updates(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "telegram_bot",
        "get_updates",
        offset=input_data.get("offset"),
        limit=input_data.get("limit", 100),
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    updates = res.get("result")
    if not isinstance(updates, list):
        return res
    lean = []
    for u in updates:
        if not isinstance(u, dict):
            continue
        item = {"update_id": u.get("update_id")}
        kind = next((k for k in u if k != "update_id"), None)
        if kind and kind != "message":
            item["type"] = kind
        payload = u.get(kind) if kind else None
        msg = payload if isinstance(payload, dict) else {}
        if kind == "callback_query":
            item["callback_query_id"] = msg.get("id")
            if msg.get("data") is not None:
                item["data"] = msg.get("data")
            sender = msg.get("from") or {}
            msg = msg.get("message") or {}
        else:
            sender = msg.get("from") or {}
        if msg:
            item["message_id"] = msg.get("message_id")
            chat = msg.get("chat") or {}
            item["chat_id"] = chat.get("id")
            frm = chat.get("title")
            if not frm:
                frm = " ".join(
                    p for p in (sender.get("first_name"), sender.get("last_name")) if p
                )
                if sender.get("username"):
                    frm = (
                        f"{frm} (@{sender['username']})"
                        if frm
                        else f"@{sender['username']}"
                    )
            if frm:
                item["from"] = frm
            text = msg.get("text")
            if text is None:
                text = msg.get("caption")
            if text is not None:
                item["text"] = text
            if msg.get("date") is not None:
                item["date"] = msg.get("date")
        lean.append(item)
    return {**res, "result": lean}


@action(
    name="search_telegram_contact",
    description="Search for a Telegram contact by name from bot's recent chat history.",
    action_sets=["telegram_chats"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Contact name to search for.",
            "example": "John",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_telegram_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("telegram_bot", "search_contact", name=input_data["name"])


# =====================================================================
# MTProto (user account) actions
# Sub-set: telegram_user
# =====================================================================


@action(
    name="get_telegram_chats",
    description="Get chats via Telegram user account.",
    action_sets=["telegram_user", "telegram"],
    input_schema={
        "limit": {"type": "integer", "description": "Limit.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_chats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_user",
        "get_dialogs",
        limit=input_data.get("limit", 50),
    )


@action(
    name="read_telegram_messages",
    description="Read messages via Telegram user account.",
    action_sets=["telegram_user", "telegram"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "limit": {"type": "integer", "description": "Limit.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def read_telegram_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_user",
        "get_messages",
        chat_id=input_data["chat_id"],
        limit=input_data.get("limit", 50),
    )


@action(
    name="send_telegram_user_message",
    irreversible=True,
    description="Send a text message via Telegram user account. IMPORTANT: Use @username (e.g., '@emadtavana7') NOT numeric ID. Use 'self' or 'user' to message the owner's Saved Messages.",
    action_sets=["telegram_user", "telegram"],
    input_schema={
        "chat_id": {
            "type": "string",
            "description": "Recipient: @username (preferred), phone number, or 'self' for Saved Messages. Do NOT use numeric IDs.",
            "example": "@emadtavana7",
        },
        "text": {"type": "string", "description": "Text.", "example": "Hi"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_telegram_user_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import (
        record_outgoing_message,
        run_client,
    )

    record_outgoing_message("Telegram", input_data["chat_id"], input_data["text"])
    return await run_client(
        "telegram_user",
        "send_message",
        recipient=input_data["chat_id"],
        text=input_data["text"],
    )


@action(
    name="send_telegram_user_file",
    irreversible=True,
    description="Send a file via Telegram user account.",
    action_sets=["telegram_user"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": "123"},
        "file_path": {
            "type": "string",
            "description": "Path.",
            "example": "/path/to/file",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def send_telegram_user_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_user",
        "send_file",
        chat_id=input_data["chat_id"],
        file_path=input_data["file_path"],
    )


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
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "telegram_user",
        "search_contacts",
        query=input_data["query"],
    )


@action(
    name="get_telegram_user_account_info",
    description="Get account info via Telegram user account.",
    action_sets=["telegram_user"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_telegram_user_account_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("telegram_user", "get_me")
