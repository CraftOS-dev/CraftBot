from agent_core import action


# ═══════════════════════════════════════════════════════════════════════════════
# Messages — send / edit / delete / reply / forward / react / star / download
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="send_whatsapp_web_text_message",
    irreversible=True,
    description="Send a text message via WhatsApp Web.",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "to": {
            "type": "string",
            "description": "Recipient phone number (e.g. '1234567890') OR the exact `number` / `id` value returned by search_whatsapp_contact (e.g. '185628603977847@lid'). Pass the value verbatim — do NOT strip the '@lid' or '@c.us' suffix. Pass `user` (or `me` / `owner` / `self`) to send to your own (the owner's) number — use this to reply to the user on a WhatsApp-originated task.",
            "example": "1234567890",
        },
        "message": {
            "type": "string",
            "description": "Message text.",
            "example": "Hello!",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_whatsapp_web_text_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import (
        record_outgoing_message,
        run_client,
    )

    res = await run_client(
        "whatsapp_web",
        "send_message",
        recipient=input_data["to"],
        text=input_data["message"],
    )
    if res.get("status") == "success":
        record_outgoing_message("WhatsApp", input_data["to"], input_data["message"])
    return res


@action(
    name="send_whatsapp_web_media_message",
    irreversible=True,
    description="Send a media file (image / video / audio / document) via WhatsApp Web. Set send_as_sticker / send_as_voice / send_as_document to override the default mode.",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "to": {
            "type": "string",
            "description": "Recipient phone number OR the `number` / `id` from search_whatsapp_contact.",
            "example": "1234567890",
        },
        "media_path": {
            "type": "string",
            "description": "Absolute local path to the media file.",
            "example": "C:/Users/me/photo.jpg",
        },
        "caption": {
            "type": "string",
            "description": "Optional caption.",
            "example": "",
        },
        "send_as_sticker": {
            "type": "boolean",
            "description": "Send image as sticker.",
            "example": False,
        },
        "send_as_voice": {
            "type": "boolean",
            "description": "Send audio as voice note.",
            "example": False,
        },
        "send_as_document": {
            "type": "boolean",
            "description": "Send as document (preserves filename).",
            "example": False,
        },
        "quoted_message_id": {
            "type": "string",
            "description": "Quote-reply to this message ID (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_whatsapp_web_media_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "send_media",
        recipient=input_data["to"],
        media_path=input_data["media_path"],
        caption=input_data.get("caption"),
        send_as_sticker=bool(input_data.get("send_as_sticker", False)),
        send_as_voice=bool(input_data.get("send_as_voice", False)),
        send_as_document=bool(input_data.get("send_as_document", False)),
        quoted_message_id=input_data.get("quoted_message_id") or None,
    )


@action(
    name="send_whatsapp_location",
    irreversible=True,
    description="Send a location pin via WhatsApp Web.",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "latitude": {"type": "number", "description": "Latitude.", "example": 37.7749},
        "longitude": {
            "type": "number",
            "description": "Longitude.",
            "example": -122.4194,
        },
        "description": {
            "type": "string",
            "description": "Optional label.",
            "example": "Meeting spot",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_whatsapp_location(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "send_location",
        recipient=input_data["to"],
        latitude=input_data["latitude"],
        longitude=input_data["longitude"],
        description=input_data.get("description", ""),
    )


@action(
    name="reply_whatsapp_message",
    irreversible=True,
    description="Quote-reply to a specific WhatsApp message.",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "to": {
            "type": "string",
            "description": "Recipient (usually the chat ID where the original message is).",
            "example": "",
        },
        "text": {"type": "string", "description": "Reply text.", "example": ""},
        "quoted_message_id": {
            "type": "string",
            "description": "Message ID being quoted.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def reply_whatsapp_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "send_reply",
        recipient=input_data["to"],
        text=input_data["text"],
        quoted_message_id=input_data["quoted_message_id"],
    )


@action(
    name="edit_whatsapp_message",
    description="Edit a previously-sent WhatsApp message (within WhatsApp's edit window, ~15 min).",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "new_body": {
            "type": "string",
            "description": "New message text.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def edit_whatsapp_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "edit_message",
        message_id=input_data["message_id"],
        new_body=input_data["new_body"],
    )


@action(
    name="delete_whatsapp_message",
    description="Delete a WhatsApp message. everyone=true uses 'Delete for everyone' (within WhatsApp's recall window).",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "everyone": {
            "type": "boolean",
            "description": "Delete for everyone (vs only me).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_whatsapp_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "delete_message",
        message_id=input_data["message_id"],
        everyone=bool(input_data.get("everyone", False)),
    )


@action(
    name="forward_whatsapp_message",
    irreversible=True,
    description="Forward a message to another chat.",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "to": {
            "type": "string",
            "description": "Destination chat ID or phone number.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def forward_whatsapp_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "forward_message",
        message_id=input_data["message_id"],
        recipient=input_data["to"],
    )


@action(
    name="react_to_whatsapp_message",
    description="Add (or remove with empty emoji) an emoji reaction to a WhatsApp message.",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "emoji": {
            "type": "string",
            "description": "Unicode emoji ('' to remove).",
            "example": "👍",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def react_to_whatsapp_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "react_message",
        message_id=input_data["message_id"],
        emoji=input_data.get("emoji", ""),
    )


@action(
    name="star_whatsapp_message",
    description="Star or unstar a WhatsApp message.",
    action_sets=["whatsapp_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "starred": {
            "type": "boolean",
            "description": "True=star, False=unstar.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def star_whatsapp_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "star_message",
        message_id=input_data["message_id"],
        starred=bool(input_data.get("starred", True)),
    )


@action(
    name="download_whatsapp_message_media",
    description="Download an attached image/video/audio/document from a WhatsApp message to a local path.",
    action_sets=["whatsapp_messages", "whatsapp"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "dest_path": {
            "type": "string",
            "description": "Local destination path.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def download_whatsapp_message_media(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "download_message_media",
        message_id=input_data["message_id"],
        dest_path=input_data["dest_path"],
    )


@action(
    name="get_whatsapp_quoted_message",
    description="If a message is a reply, get the message it's quoting.",
    action_sets=["whatsapp_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_quoted_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "get_quoted_message",
        message_id=input_data["message_id"],
    )


@action(
    name="send_whatsapp_typing_state",
    description="Show typing/recording state in a chat (sends presence). state: typing | recording | clear.",
    action_sets=["whatsapp_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "state": {
            "type": "string",
            "description": "typing | recording | clear.",
            "example": "typing",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_whatsapp_typing_state(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "send_typing_state",
        chat_id=input_data["chat_id"],
        state=input_data.get("state", "typing"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Chats — history / mark-read / archive / pin / mute / clear / delete
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="get_whatsapp_chat_history",
    description="Get chat message history. Lean messages by default; include_metadata=true returns the raw message list.",
    action_sets=["whatsapp_chats", "whatsapp"],
    input_schema={
        "phone_number": {
            "type": "string",
            "description": "Phone number or chat ID.",
            "example": "1234567890",
        },
        "limit": {"type": "integer", "description": "Max messages.", "example": 50},
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw message objects (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {messages: [{id, from, to?, body, timestamp, from_me, has_media, type?}]}.",
        },
    },
)
async def get_whatsapp_chat_history(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "whatsapp_web",
        "get_chat_messages",
        phone_number=input_data["phone_number"],
        limit=input_data.get("limit", 50),
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
        return res
    lean = []
    for m in result["messages"]:
        if not isinstance(m, dict):
            continue
        item = {
            "id": m.get("id"),
            "from": m.get("from"),
            "body": m.get("body"),
            "timestamp": m.get("timestamp"),
            "from_me": m.get("from_me"),
            "has_media": bool(m.get("has_media")),
        }
        if m.get("to") is not None:
            item["to"] = m.get("to")
        if m.get("type") and m.get("type") != "chat":
            item["type"] = m.get("type")
        lean.append(item)
    return {**res, "result": {**result, "messages": lean}}


@action(
    name="get_whatsapp_unread_chats",
    description="List chats with unread messages.",
    action_sets=["whatsapp_chats", "whatsapp"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_unread_chats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("whatsapp_web", "get_unread_chats")


@action(
    name="mark_whatsapp_chat_read",
    description="Mark a WhatsApp chat as read (clears unread badge + sends read receipts).",
    action_sets=["whatsapp_chats", "whatsapp"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def mark_whatsapp_chat_read(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "mark_chat_read", chat_id=input_data["chat_id"]
    )


@action(
    name="mark_whatsapp_chat_unread",
    description="Mark a chat as unread (flag for follow-up without replying).",
    action_sets=["whatsapp_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def mark_whatsapp_chat_unread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "mark_chat_unread", chat_id=input_data["chat_id"]
    )


@action(
    name="archive_whatsapp_chat",
    description="Archive (archive=true) or unarchive (archive=false) a chat.",
    action_sets=["whatsapp_chats", "whatsapp"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "archive": {
            "type": "boolean",
            "description": "True=archive, False=unarchive.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def archive_whatsapp_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "archive_chat",
        chat_id=input_data["chat_id"],
        archive=bool(input_data.get("archive", True)),
    )


@action(
    name="pin_whatsapp_chat",
    description="Pin (pin=true) or unpin (pin=false) a chat.",
    action_sets=["whatsapp_chats", "whatsapp"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "pin": {
            "type": "boolean",
            "description": "True=pin, False=unpin.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def pin_whatsapp_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "pin_chat",
        chat_id=input_data["chat_id"],
        pin=bool(input_data.get("pin", True)),
    )


@action(
    name="mute_whatsapp_chat",
    description="Mute (mute=true, optionally until unmute_date unix-seconds) or unmute a chat.",
    action_sets=["whatsapp_chats", "whatsapp"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "mute": {
            "type": "boolean",
            "description": "True=mute, False=unmute.",
            "example": True,
        },
        "unmute_date": {
            "type": "integer",
            "description": "Unix seconds when mute expires (optional, omit for forever).",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def mute_whatsapp_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    ud = input_data.get("unmute_date")
    return await run_client(
        "whatsapp_web",
        "mute_chat",
        chat_id=input_data["chat_id"],
        mute=bool(input_data.get("mute", True)),
        unmute_date=ud if ud else None,
    )


@action(
    name="clear_whatsapp_chat_messages",
    description="Clear all messages in a chat (the chat itself stays). Local only — doesn't delete for other party.",
    action_sets=["whatsapp_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def clear_whatsapp_chat_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "clear_chat_messages", chat_id=input_data["chat_id"]
    )


@action(
    name="delete_whatsapp_chat",
    description="Delete a chat entirely (local). For groups, you must leave_whatsapp_group first.",
    action_sets=["whatsapp_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_whatsapp_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "delete_chat", chat_id=input_data["chat_id"]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Groups — create / members / subject / description / invite / leave
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="create_whatsapp_group",
    description="Create a WhatsApp group. participants can be phone numbers (digits) or JIDs.",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Group name.",
            "example": "Project X",
        },
        "participants": {
            "type": "array",
            "description": "Phone numbers or JIDs.",
            "example": ["1234567890"],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_whatsapp_group(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "create_group",
        name=input_data["name"],
        participants=input_data["participants"],
    )


@action(
    name="add_whatsapp_group_participants",
    description="Add participants to a group (requires admin).",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "participants": {
            "type": "array",
            "description": "Participant JIDs.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_whatsapp_group_participants(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "group_add_participants",
        group_id=input_data["group_id"],
        participants=input_data["participants"],
    )


@action(
    name="remove_whatsapp_group_participants",
    description="Remove participants from a group (requires admin).",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "participants": {
            "type": "array",
            "description": "Participant JIDs to remove.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_whatsapp_group_participants(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "group_remove_participants",
        group_id=input_data["group_id"],
        participants=input_data["participants"],
    )


@action(
    name="promote_whatsapp_group_participants",
    description="Promote participants to admin (requires admin).",
    action_sets=["whatsapp_groups"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "participants": {
            "type": "array",
            "description": "Participant JIDs.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def promote_whatsapp_group_participants(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "group_promote_participants",
        group_id=input_data["group_id"],
        participants=input_data["participants"],
    )


@action(
    name="demote_whatsapp_group_participants",
    description="Remove admin status from participants (requires admin).",
    action_sets=["whatsapp_groups"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "participants": {
            "type": "array",
            "description": "Participant JIDs.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def demote_whatsapp_group_participants(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "group_demote_participants",
        group_id=input_data["group_id"],
        participants=input_data["participants"],
    )


@action(
    name="set_whatsapp_group_subject",
    description="Change a group's name/subject (requires admin or 'all members can edit info').",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "subject": {"type": "string", "description": "New name.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def set_whatsapp_group_subject(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "group_set_subject",
        group_id=input_data["group_id"],
        subject=input_data["subject"],
    )


@action(
    name="set_whatsapp_group_description",
    description="Change a group's description.",
    action_sets=["whatsapp_groups"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "description": {
            "type": "string",
            "description": "New description.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def set_whatsapp_group_description(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "group_set_description",
        group_id=input_data["group_id"],
        description=input_data["description"],
    )


@action(
    name="get_whatsapp_group_info",
    description="Get group info: name, description, owner, participants (with admin flags).",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_group_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "group_get_info", group_id=input_data["group_id"]
    )


@action(
    name="leave_whatsapp_group",
    description="Leave a WhatsApp group.",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def leave_whatsapp_group(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "group_leave", group_id=input_data["group_id"]
    )


@action(
    name="get_whatsapp_group_invite_code",
    description="Get a group's invite code + chat.whatsapp.com URL (requires admin).",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_group_invite_code(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "group_invite_code", group_id=input_data["group_id"]
    )


@action(
    name="revoke_whatsapp_group_invite",
    description="Invalidate the current invite link and generate a new one (requires admin).",
    action_sets=["whatsapp_groups"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def revoke_whatsapp_group_invite(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "group_revoke_invite", group_id=input_data["group_id"]
    )


@action(
    name="accept_whatsapp_group_invite",
    description="Join a WhatsApp group by invite code (or full chat.whatsapp.com URL).",
    action_sets=["whatsapp_groups", "whatsapp"],
    input_schema={
        "invite_code": {
            "type": "string",
            "description": "Invite code or full URL.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def accept_whatsapp_group_invite(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "accept_group_invite", invite_code=input_data["invite_code"]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Contacts — search / block / profile pic / about / get all / check number
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="search_whatsapp_contact",
    description="Search contact by name (WhatsApp Web).",
    action_sets=["whatsapp_contacts", "whatsapp"],
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
    name="get_whatsapp_contact",
    description="Get full contact details (name, pushname, business flag, about/status, etc.).",
    action_sets=["whatsapp_contacts", "whatsapp"],
    input_schema={
        "contact_id": {"type": "string", "description": "Contact JID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "get_contact", contact_id=input_data["contact_id"]
    )


@action(
    name="get_whatsapp_all_contacts",
    description="List all contacts. By default filters to 'my contacts' (saved in phonebook). Set my_contacts_only=false to include everyone the user has ever interacted with. Lean contacts by default; include_metadata=true returns the raw contact list.",
    action_sets=["whatsapp_contacts", "whatsapp"],
    input_schema={
        "my_contacts_only": {
            "type": "boolean",
            "description": "Filter to saved contacts.",
            "example": True,
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 500},
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw contact objects (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {contacts: [{id, number, name?, pushname?, is_business?, is_my_contact?}], count}.",
        },
    },
)
async def get_whatsapp_all_contacts(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    res = await run_client(
        "whatsapp_web",
        "get_all_contacts",
        my_contacts_only=bool(input_data.get("my_contacts_only", True)),
        limit=input_data.get("limit", 500),
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("contacts"), list):
        return res
    lean = []
    for c in result["contacts"]:
        if not isinstance(c, dict):
            continue
        item = {"id": c.get("id"), "number": c.get("number")}
        if c.get("name"):
            item["name"] = c.get("name")
        if c.get("pushname"):
            item["pushname"] = c.get("pushname")
        if c.get("is_business"):
            item["is_business"] = True
        if c.get("is_my_contact") is False:
            item["is_my_contact"] = False
        lean.append(item)
    return {**res, "result": {**result, "contacts": lean}}


@action(
    name="get_whatsapp_profile_pic_url",
    description="Get a contact's profile picture URL (empty string if none / privacy restricted).",
    action_sets=["whatsapp_contacts", "whatsapp"],
    input_schema={
        "contact_id": {"type": "string", "description": "Contact JID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_profile_pic_url(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "get_profile_pic_url", contact_id=input_data["contact_id"]
    )


@action(
    name="block_whatsapp_contact",
    description="Block (block=true) or unblock (block=false) a contact.",
    action_sets=["whatsapp_contacts", "whatsapp"],
    input_schema={
        "contact_id": {"type": "string", "description": "Contact JID.", "example": ""},
        "block": {
            "type": "boolean",
            "description": "True=block, False=unblock.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def block_whatsapp_contact(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web",
        "block_contact",
        contact_id=input_data["contact_id"],
        block=bool(input_data.get("block", True)),
    )


@action(
    name="check_number_on_whatsapp",
    description="Check whether a phone number is registered on WhatsApp. Returns canonical JID if so.",
    action_sets=["whatsapp_contacts", "whatsapp"],
    input_schema={
        "number": {
            "type": "string",
            "description": "Phone number.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def check_number_on_whatsapp(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "whatsapp_web", "check_number_on_whatsapp", number=input_data["number"]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Session
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="get_whatsapp_web_session_status",
    description="Get WhatsApp Web session status (connected/waiting/disconnected).",
    action_sets=["whatsapp"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_whatsapp_web_session_status(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("whatsapp_web", "get_session_status")


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Polls / Buttons / Lists / Interactive messages
#     Mostly business-API features; whatsapp-web.js support is partial
#     and unstable across WhatsApp Web protocol changes.
# - Channels (newsletters / one-way broadcast)
#     Heavy WhatsApp-side feature with limited library coverage today.
# - Broadcast lists / status updates
#     Niche; better tooling exists outside the bot context.
# - Set my profile pic / name / about (user-side)
#     Account admin, rarely needed mid-task.
# - Group icon (setPicture)
#     Requires MessageMedia; deferred (action could be added if needed).
# - End-to-end encrypted backup / device list management
#     Account security plumbing, not per-interaction.
# - Read more than 50 contacts at a time via getContacts on huge accounts
#     Wrapped with a 500-default cap to avoid Puppeteer protocolTimeout.
