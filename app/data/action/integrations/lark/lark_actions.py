from agent_core import action


# ═══════════════════════════════════════════════════════════════════════════════
# Messages — send / get / edit / delete / reply / forward / list / reactions / pins
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="send_lark_message",
    description="Send a plain text message in Lark. receive_id_type: open_id | user_id | email | chat_id | union_id.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "receive_id": {"type": "string", "description": "Recipient identifier.", "example": ""},
        "text": {"type": "string", "description": "Message text.", "example": ""},
        "receive_id_type": {"type": "string", "description": "open_id | user_id | email | chat_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "send_text",
        receive_id=input_data["receive_id"],
        text=input_data["text"],
        receive_id_type=input_data.get("receive_id_type", "open_id"),
    )


@action(
    name="reply_lark_message",
    description="Reply to a Lark message by message_id.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Parent message ID (om_...).", "example": ""},
        "text": {"type": "string", "description": "Reply text.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def reply_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "reply_text",
        message_id=input_data["message_id"],
        text=input_data["text"],
    )


@action(
    name="send_lark_rich_message",
    description="Send a generic Lark message. msg_type: text | post | image | file | audio | media | sticker | interactive | share_chat | share_user. content is the per-type dict (this action JSON-encodes it for you).",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "receive_id": {"type": "string", "description": "Recipient ID.", "example": ""},
        "msg_type": {"type": "string", "description": "Message type.", "example": "interactive"},
        "content": {"type": "object", "description": "Per-type content dict.", "example": {}},
        "receive_id_type": {"type": "string", "description": "open_id | user_id | email | chat_id | union_id.", "example": "open_id"},
        "uuid": {"type": "string", "description": "Idempotency UUID (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_lark_rich_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "send_message",
        receive_id=input_data["receive_id"],
        msg_type=input_data["msg_type"],
        content=input_data["content"],
        receive_id_type=input_data.get("receive_id_type", "open_id"),
        uuid=input_data.get("uuid") or None,
    )


@action(
    name="send_lark_image",
    description="Send an image (use upload_lark_image first to get image_key).",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "receive_id": {"type": "string", "description": "Recipient ID.", "example": ""},
        "image_key": {"type": "string", "description": "Image key from upload_lark_image.", "example": ""},
        "receive_id_type": {"type": "string", "description": "open_id | chat_id | etc.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_lark_image(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "send_image_message",
        receive_id=input_data["receive_id"],
        image_key=input_data["image_key"],
        receive_id_type=input_data.get("receive_id_type", "open_id"),
    )


@action(
    name="send_lark_file",
    description="Send a file (use upload_lark_im_file first to get file_key).",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "receive_id": {"type": "string", "description": "Recipient ID.", "example": ""},
        "file_key": {"type": "string", "description": "File key from upload_lark_im_file.", "example": ""},
        "receive_id_type": {"type": "string", "description": "open_id | chat_id | etc.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_lark_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "send_file_message",
        receive_id=input_data["receive_id"],
        file_key=input_data["file_key"],
        receive_id_type=input_data.get("receive_id_type", "open_id"),
    )


@action(
    name="send_lark_card",
    description="Send an interactive card (Lark's Block Kit equivalent). card is the card schema dict.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "receive_id": {"type": "string", "description": "Recipient ID.", "example": ""},
        "card": {"type": "object", "description": "Card schema.", "example": {}},
        "receive_id_type": {"type": "string", "description": "open_id | chat_id | etc.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_lark_card(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "send_card_message",
        receive_id=input_data["receive_id"],
        card=input_data["card"],
        receive_id_type=input_data.get("receive_id_type", "open_id"),
    )


@action(
    name="send_lark_post",
    description="Send a rich-text 'post' message (multi-line, styled). post is Lark's post schema: {zh_cn: {title, content: [[{tag,text}]]}}.",
    action_sets=["lark_messages"],
    input_schema={
        "receive_id": {"type": "string", "description": "Recipient ID.", "example": ""},
        "post": {"type": "object", "description": "Post schema.", "example": {}},
        "receive_id_type": {"type": "string", "description": "open_id | chat_id | etc.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_lark_post(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "send_post_message",
        receive_id=input_data["receive_id"],
        post=input_data["post"],
        receive_id_type=input_data.get("receive_id_type", "open_id"),
    )


@action(
    name="reply_lark_rich_message",
    description="Reply with non-text content (image / file / card / etc.). reply_in_thread starts a thread off the parent.",
    action_sets=["lark_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Parent message ID.", "example": ""},
        "msg_type": {"type": "string", "description": "Message type.", "example": "image"},
        "content": {"type": "object", "description": "Per-type content dict.", "example": {}},
        "reply_in_thread": {"type": "boolean", "description": "Start a thread off the parent.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def reply_lark_rich_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "reply_message",
        message_id=input_data["message_id"],
        msg_type=input_data["msg_type"],
        content=input_data["content"],
        reply_in_thread=bool(input_data.get("reply_in_thread", False)),
    )


@action(
    name="get_lark_message",
    description="Get a single Lark message by ID.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "get_message", message_id=input_data["message_id"])


@action(
    name="delete_lark_message",
    description="Recall (delete) a message the bot sent.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "delete_message", message_id=input_data["message_id"])


@action(
    name="update_lark_message",
    description="Edit a previously-sent Lark message. Only text/interactive types are editable.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "msg_type": {"type": "string", "description": "text | interactive.", "example": "text"},
        "content": {"type": "object", "description": "New content dict.", "example": {"text": "Updated"}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "update_message",
        message_id=input_data["message_id"],
        msg_type=input_data["msg_type"],
        content=input_data["content"],
    )


@action(
    name="forward_lark_message",
    description="Forward a message to another recipient.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "receive_id": {"type": "string", "description": "Destination ID.", "example": ""},
        "receive_id_type": {"type": "string", "description": "open_id | chat_id | etc.", "example": "open_id"},
        "uuid": {"type": "string", "description": "Idempotency UUID (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def forward_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "forward_message",
        message_id=input_data["message_id"],
        receive_id=input_data["receive_id"],
        receive_id_type=input_data.get("receive_id_type", "open_id"),
        uuid=input_data.get("uuid") or None,
    )


@action(
    name="list_lark_chat_messages",
    description="List a chat's message history. container_id is usually a chat_id; start_time/end_time are unix seconds as strings.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "container_id": {"type": "string", "description": "Chat/thread ID.", "example": ""},
        "container_id_type": {"type": "string", "description": "chat (default) | thread.", "example": "chat"},
        "start_time": {"type": "string", "description": "Unix seconds (optional).", "example": ""},
        "end_time": {"type": "string", "description": "Unix seconds (optional).", "example": ""},
        "sort_type": {"type": "string", "description": "ByCreateTimeAsc | ByCreateTimeDesc.", "example": "ByCreateTimeAsc"},
        "page_size": {"type": "integer", "description": "Max 50.", "example": 50},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_chat_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_messages",
        container_id=input_data["container_id"],
        container_id_type=input_data.get("container_id_type", "chat"),
        start_time=input_data.get("start_time") or None,
        end_time=input_data.get("end_time") or None,
        sort_type=input_data.get("sort_type", "ByCreateTimeAsc"),
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="list_lark_message_read_users",
    description="See who has read a message (returns user IDs + read timestamps).",
    action_sets=["lark_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
        "page_size": {"type": "integer", "description": "Max results.", "example": 100},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_message_read_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_message_read_users",
        message_id=input_data["message_id"],
        user_id_type=input_data.get("user_id_type", "open_id"),
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="add_lark_reaction",
    description="Add an emoji reaction to a message. emoji_type is Lark's emoji code (e.g. 'SMILE', 'THUMBSUP', 'HEART').",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "emoji_type": {"type": "string", "description": "Lark emoji code.", "example": "SMILE"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_lark_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "add_reaction",
        message_id=input_data["message_id"],
        emoji_type=input_data["emoji_type"],
    )


@action(
    name="remove_lark_reaction",
    description="Remove a reaction by reaction_id.",
    action_sets=["lark_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "reaction_id": {"type": "string", "description": "Reaction ID (from add or list).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_lark_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "remove_reaction",
        message_id=input_data["message_id"],
        reaction_id=input_data["reaction_id"],
    )


@action(
    name="list_lark_reactions",
    description="List reactions on a message.",
    action_sets=["lark_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "emoji_type": {"type": "string", "description": "Filter by emoji (optional).", "example": ""},
        "page_size": {"type": "integer", "description": "Max results.", "example": 100},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_reactions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_reactions",
        message_id=input_data["message_id"],
        emoji_type=input_data.get("emoji_type") or None,
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


@action(
    name="pin_lark_message",
    description="Pin a message in its chat.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def pin_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "pin_message", message_id=input_data["message_id"])


@action(
    name="unpin_lark_message",
    description="Unpin a previously-pinned message.",
    action_sets=["lark_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unpin_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "unpin_message", message_id=input_data["message_id"])


@action(
    name="list_lark_pinned_messages",
    description="List pinned messages in a chat.",
    action_sets=["lark_messages"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "page_size": {"type": "integer", "description": "Max.", "example": 50},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_pinned_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_pinned_messages",
        chat_id=input_data["chat_id"],
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="send_lark_urgent",
    description="Escalate a message to selected users. urgent_type: app (in-app push) | sms | phone (call). Use sparingly — sms/phone require special permission.",
    action_sets=["lark_messages"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "user_id_list": {"type": "array", "description": "Users to escalate to.", "example": []},
        "urgent_type": {"type": "string", "description": "app | sms | phone.", "example": "app"},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_lark_urgent(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "send_urgent",
        message_id=input_data["message_id"],
        user_id_list=input_data["user_id_list"],
        urgent_type=input_data.get("urgent_type", "app"),
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


@action(
    name="batch_send_lark_message",
    description="Broadcast the same message to many recipients in one call.",
    action_sets=["lark_messages"],
    input_schema={
        "msg_type": {"type": "string", "description": "Message type.", "example": "text"},
        "content": {"type": "object", "description": "Per-type content dict.", "example": {"text": "Hi"}},
        "open_ids": {"type": "array", "description": "Open IDs (optional).", "example": []},
        "user_ids": {"type": "array", "description": "User IDs (optional).", "example": []},
        "department_ids": {"type": "array", "description": "Department IDs (optional).", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def batch_send_lark_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "batch_send_message",
        msg_type=input_data["msg_type"],
        content=input_data["content"],
        open_ids=input_data.get("open_ids") or None,
        user_ids=input_data.get("user_ids") or None,
        department_ids=input_data.get("department_ids") or None,
    )


# ----- Resources (image / file upload + download) -----

@action(
    name="upload_lark_image",
    description="Upload a local image to Lark. Returns image_key for use in send_lark_image / cards / etc. image_type: message (default) | avatar.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "file_path": {"type": "string", "description": "Local image path.", "example": ""},
        "image_type": {"type": "string", "description": "message | avatar.", "example": "message"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def upload_lark_image(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "upload_image",
        file_path=input_data["file_path"],
        image_type=input_data.get("image_type", "message"),
    )


@action(
    name="upload_lark_im_file",
    description="Upload a local file to Lark IM. Returns file_key for send_lark_file. file_type: opus | mp4 | pdf | doc | xls | ppt | stream (default).",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "file_path": {"type": "string", "description": "Local file path.", "example": ""},
        "file_type": {"type": "string", "description": "opus | mp4 | pdf | doc | xls | ppt | stream.", "example": "stream"},
        "file_name": {"type": "string", "description": "Override name (optional).", "example": ""},
        "duration": {"type": "integer", "description": "Duration in seconds for audio/video (optional).", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def upload_lark_im_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    dur = input_data.get("duration")
    return await run_client(
        "lark", "upload_im_file",
        file_path=input_data["file_path"],
        file_type=input_data.get("file_type", "stream"),
        file_name=input_data.get("file_name") or None,
        duration=dur if dur else None,
    )


@action(
    name="download_lark_message_resource",
    description="Download an attached image/file/audio from a Lark message to a local path. file_key comes from the message content.",
    action_sets=["lark_messages", "lark"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID containing the resource.", "example": ""},
        "file_key": {"type": "string", "description": "File key from message content.", "example": ""},
        "dest_path": {"type": "string", "description": "Local destination path.", "example": ""},
        "resource_type": {"type": "string", "description": "image | file.", "example": "file"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def download_lark_message_resource(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "download_message_resource",
        message_id=input_data["message_id"],
        file_key=input_data["file_key"],
        dest_path=input_data["dest_path"],
        resource_type=input_data.get("resource_type", "file"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Chats — CRUD + members + announcement + search + moderation
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="list_lark_chats",
    description="List groups the bot is a member of.",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "page_size": {"type": "integer", "description": "Max 100.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_chats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_chats",
        page_size=input_data.get("page_size", 50),
    )


@action(
    name="create_lark_chat",
    description="Create a group chat. chat_mode: group | topic. chat_type: public | private.",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "name": {"type": "string", "description": "Chat name.", "example": "Project X"},
        "description": {"type": "string", "description": "Description.", "example": ""},
        "owner_id": {"type": "string", "description": "Owner ID (optional, defaults to bot).", "example": ""},
        "user_id_list": {"type": "array", "description": "Initial user IDs.", "example": []},
        "bot_id_list": {"type": "array", "description": "Initial bot IDs.", "example": []},
        "chat_mode": {"type": "string", "description": "group | topic.", "example": "group"},
        "chat_type": {"type": "string", "description": "public | private.", "example": "private"},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "create_chat",
        name=input_data["name"],
        description=input_data.get("description", ""),
        owner_id=input_data.get("owner_id") or None,
        user_id_list=input_data.get("user_id_list") or None,
        bot_id_list=input_data.get("bot_id_list") or None,
        chat_mode=input_data.get("chat_mode", "group"),
        chat_type=input_data.get("chat_type", "private"),
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


@action(
    name="get_lark_chat",
    description="Get info about a Lark chat (members, owner, settings).",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "get_chat",
        chat_id=input_data["chat_id"],
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


@action(
    name="update_lark_chat",
    description="Update a chat's settings.",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "name": {"type": "string", "description": "New name (optional).", "example": ""},
        "description": {"type": "string", "description": "New description (optional).", "example": ""},
        "avatar": {"type": "string", "description": "Avatar image_key (optional).", "example": ""},
        "add_member_permission": {"type": "string", "description": "all_members | only_owner (optional).", "example": ""},
        "share_card_permission": {"type": "string", "description": "allowed | not_allowed (optional).", "example": ""},
        "at_all_permission": {"type": "string", "description": "all_members | only_owner (optional).", "example": ""},
        "edit_permission": {"type": "string", "description": "all_members | only_owner (optional).", "example": ""},
        "chat_type": {"type": "string", "description": "Convert public | private (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "update_chat",
        chat_id=input_data["chat_id"],
        name=input_data.get("name") or None,
        description=input_data["description"] if "description" in input_data else None,
        avatar=input_data.get("avatar") or None,
        add_member_permission=input_data.get("add_member_permission") or None,
        share_card_permission=input_data.get("share_card_permission") or None,
        at_all_permission=input_data.get("at_all_permission") or None,
        edit_permission=input_data.get("edit_permission") or None,
        chat_type=input_data.get("chat_type") or None,
    )


@action(
    name="dissolve_lark_chat",
    description="Dissolve a chat (delete the group). Only the owner can.",
    action_sets=["lark_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def dissolve_lark_chat(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "dissolve_chat", chat_id=input_data["chat_id"])


@action(
    name="list_lark_chat_members",
    description="List members of a chat.",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "member_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
        "page_size": {"type": "integer", "description": "Max 100.", "example": 100},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_chat_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_chat_members",
        chat_id=input_data["chat_id"],
        member_id_type=input_data.get("member_id_type", "open_id"),
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="add_lark_chat_members",
    description="Add members to a chat. succeed_type: 0=fail on any error | 1=partial success | 2=skip existing.",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "id_list": {"type": "array", "description": "User IDs to add.", "example": []},
        "member_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
        "succeed_type": {"type": "integer", "description": "0 | 1 | 2.", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_lark_chat_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "add_chat_members",
        chat_id=input_data["chat_id"],
        id_list=input_data["id_list"],
        member_id_type=input_data.get("member_id_type", "open_id"),
        succeed_type=input_data.get("succeed_type", 0),
    )


@action(
    name="remove_lark_chat_members",
    description="Remove members from a chat.",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "id_list": {"type": "array", "description": "User IDs to remove.", "example": []},
        "member_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_lark_chat_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "remove_chat_members",
        chat_id=input_data["chat_id"],
        id_list=input_data["id_list"],
        member_id_type=input_data.get("member_id_type", "open_id"),
    )


@action(
    name="search_lark_chats",
    description="Search chats by name.",
    action_sets=["lark_chats", "lark"],
    input_schema={
        "query": {"type": "string", "description": "Search query.", "example": ""},
        "page_size": {"type": "integer", "description": "Max 100.", "example": 50},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_lark_chats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "search_chats",
        query=input_data["query"],
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_chat_announcement",
    description="Get the announcement (pinned doc) on a chat.",
    action_sets=["lark_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_chat_announcement(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "get_chat_announcement", chat_id=input_data["chat_id"])


@action(
    name="update_lark_chat_announcement",
    description="Update a chat's announcement. requests uses Lark block-update structures (same as Docx).",
    action_sets=["lark_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "revision": {"type": "string", "description": "Current revision number (from get).", "example": ""},
        "requests": {"type": "array", "description": "Block-update operations.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_chat_announcement(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "update_chat_announcement",
        chat_id=input_data["chat_id"],
        revision=input_data["revision"],
        requests=input_data["requests"],
    )


@action(
    name="set_lark_chat_moderation",
    description="Set who can send messages in a chat. moderation_setting: all_members | only_owner | specific_users.",
    action_sets=["lark_chats"],
    input_schema={
        "chat_id": {"type": "string", "description": "Chat ID.", "example": ""},
        "moderation_setting": {"type": "string", "description": "all_members | only_owner | specific_users.", "example": "all_members"},
        "user_id_list": {"type": "array", "description": "Allowed users (only if specific_users).", "example": []},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def set_lark_chat_moderation(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "update_chat_moderation",
        chat_id=input_data["chat_id"],
        moderation_setting=input_data["moderation_setting"],
        user_id_list=input_data.get("user_id_list") or None,
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Contacts — users + departments
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="get_lark_user",
    description="Get a single Lark user by ID.",
    action_sets=["lark_contacts", "lark"],
    input_schema={
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
        "department_id_type": {"type": "string", "description": "open_department_id | department_id.", "example": "open_department_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "get_user",
        user_id=input_data["user_id"],
        user_id_type=input_data.get("user_id_type", "open_id"),
        department_id_type=input_data.get("department_id_type", "open_department_id"),
    )


@action(
    name="batch_get_lark_users",
    description="Get multiple Lark users by ID in one call.",
    action_sets=["lark_contacts"],
    input_schema={
        "user_ids": {"type": "array", "description": "User IDs.", "example": []},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def batch_get_lark_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "batch_get_users",
        user_ids=input_data["user_ids"],
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


@action(
    name="get_lark_user_by_email",
    description="Resolve a single user's open_id from a company email.",
    action_sets=["lark_contacts", "lark"],
    input_schema={
        "email": {"type": "string", "description": "Email.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_user_by_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "get_user_by_email", email=input_data["email"])


@action(
    name="batch_lookup_lark_users",
    description="Resolve multiple emails / mobiles to user IDs in one call.",
    action_sets=["lark_contacts", "lark"],
    input_schema={
        "emails": {"type": "array", "description": "Emails to look up (optional).", "example": []},
        "mobiles": {"type": "array", "description": "Mobiles to look up (optional).", "example": []},
        "user_id_type": {"type": "string", "description": "Return ID type.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def batch_lookup_lark_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "batch_get_user_ids",
        emails=input_data.get("emails") or None,
        mobiles=input_data.get("mobiles") or None,
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


@action(
    name="search_lark_users_by_name",
    description="Search Lark users by name (visibility depends on app scope grants).",
    action_sets=["lark_contacts", "lark"],
    input_schema={
        "query": {"type": "string", "description": "Search query.", "example": ""},
        "page_size": {"type": "integer", "description": "Max 50.", "example": 50},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_lark_users_by_name(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "search_users_by_name",
        query=input_data["query"],
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="list_lark_department_users",
    description="List users in a department.",
    action_sets=["lark_contacts"],
    input_schema={
        "department_id": {"type": "string", "description": "Department ID.", "example": ""},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
        "department_id_type": {"type": "string", "description": "open_department_id | department_id.", "example": "open_department_id"},
        "page_size": {"type": "integer", "description": "Max 50.", "example": 50},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_department_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_department_users",
        department_id=input_data["department_id"],
        user_id_type=input_data.get("user_id_type", "open_id"),
        department_id_type=input_data.get("department_id_type", "open_department_id"),
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_department",
    description="Get info about a department.",
    action_sets=["lark_contacts"],
    input_schema={
        "department_id": {"type": "string", "description": "Department ID.", "example": ""},
        "department_id_type": {"type": "string", "description": "open_department_id | department_id.", "example": "open_department_id"},
        "user_id_type": {"type": "string", "description": "open_id | user_id | union_id.", "example": "open_id"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_department(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "get_department",
        department_id=input_data["department_id"],
        department_id_type=input_data.get("department_id_type", "open_department_id"),
        user_id_type=input_data.get("user_id_type", "open_id"),
    )


@action(
    name="list_lark_department_children",
    description="List child departments under a parent.",
    action_sets=["lark_contacts"],
    input_schema={
        "parent_department_id": {"type": "string", "description": "Parent ID (use '0' for top-level).", "example": "0"},
        "department_id_type": {"type": "string", "description": "open_department_id | department_id.", "example": "open_department_id"},
        "fetch_child": {"type": "boolean", "description": "Fetch all descendants.", "example": False},
        "page_size": {"type": "integer", "description": "Max 50.", "example": 50},
        "page_token": {"type": "string", "description": "Cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_department_children(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark", "list_department_children",
        parent_department_id=input_data["parent_department_id"],
        department_id_type=input_data.get("department_id_type", "open_department_id"),
        fetch_child=bool(input_data.get("fetch_child", False)),
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Bot info
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="get_lark_bot_info",
    description="Get info about the connected Lark bot (app_name, open_id, etc.).",
    action_sets=["lark"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_bot_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark", "get_bot_info")


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Topic / thread CRUD (/im/v1/threads)
#     Lark's thread feature is in flux; reply_in_thread on reply_lark_rich_message
#     covers the realistic "thread reply" use case.
# - Encryption / message-encryption events
#     Lark's encrypted event mode is a server-side webhook configuration
#     not actionable per-call.
# - Workplace card / open_app cards
#     Niche app-distribution surfaces.
# - Approval / Calendar / Helpdesk / Sheets-as-form integrations
#     Each is a separate Lark sub-product; out of scope for this messaging
#     integration. Add as new integrations if needed.
# - Long-running file uploads (multipart for >30MB IM files)
#     Single-shot upload_lark_im_file covers the realistic interactive case.
# - User CRUD (create/delete users, update profile)
#     Admin-only; the contact API exposed here is lookup-only by design.
