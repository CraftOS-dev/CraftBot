from agent_core import action


# ═══════════════════════════════════════════════════════════════════════════════
# Messages — text + rich types (image / video / audio / location / sticker /
#                                Flex / template / imagemap) + content download
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="send_line_message",
    description="Push a text message to a LINE user/group/room.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient userId / groupId / roomId.", "example": "U..."},
        "text": {"type": "string", "description": "Message text.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "push_text", to=input_data["to"], text=input_data["text"])


@action(
    name="reply_line_message",
    description="Reply to a LINE message using the reply token (1-minute window).",
    action_sets=["line_messages", "line"],
    input_schema={
        "reply_token": {"type": "string", "description": "Reply token from the webhook event.", "example": ""},
        "text": {"type": "string", "description": "Reply text.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def reply_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "reply_text",
                           reply_token=input_data["reply_token"], text=input_data["text"])


@action(
    name="multicast_line_message",
    description="Send the same text to up to 500 user IDs.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "array", "description": "List of user IDs.", "example": []},
        "text": {"type": "string", "description": "Message text.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def multicast_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "multicast_text", to=input_data["to"], text=input_data["text"])


@action(
    name="broadcast_line_message",
    description="Broadcast a text to all friends.",
    action_sets=["line_messages", "line"],
    input_schema={
        "text": {"type": "string", "description": "Message text.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def broadcast_line_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "broadcast_text", text=input_data["text"])


@action(
    name="push_line_messages",
    description="Push up to 5 LINE message objects to a recipient. messages is a list of LINE-formatted dicts (e.g. {type:'text',text:'...'}, {type:'image',originalContentUrl:'...'}). Use for sending multiple message types in one call or for full control over message shape.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "messages": {"type": "array", "description": "Array of LINE message objects.", "example": []},
        "notification_disabled": {"type": "boolean", "description": "Silent delivery (optional).", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def push_line_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    nd = input_data.get("notification_disabled")
    return run_client_sync(
        "line", "push_messages",
        to=input_data["to"], messages=input_data["messages"],
        notification_disabled=nd if nd is not None else None,
    )


@action(
    name="reply_line_messages",
    description="Reply with up to 5 LINE message objects (rich reply).",
    action_sets=["line_messages", "line"],
    input_schema={
        "reply_token": {"type": "string", "description": "Reply token.", "example": ""},
        "messages": {"type": "array", "description": "Array of LINE message objects.", "example": []},
        "notification_disabled": {"type": "boolean", "description": "Silent delivery (optional).", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def reply_line_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    nd = input_data.get("notification_disabled")
    return run_client_sync(
        "line", "reply_messages",
        reply_token=input_data["reply_token"], messages=input_data["messages"],
        notification_disabled=nd if nd is not None else None,
    )


@action(
    name="multicast_line_messages",
    description="Multicast up to 5 LINE message objects to many users.",
    action_sets=["line_messages"],
    input_schema={
        "to": {"type": "array", "description": "User IDs (max 500).", "example": []},
        "messages": {"type": "array", "description": "Message objects.", "example": []},
        "notification_disabled": {"type": "boolean", "description": "Silent.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def multicast_line_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    nd = input_data.get("notification_disabled")
    return run_client_sync(
        "line", "multicast_messages",
        to=input_data["to"], messages=input_data["messages"],
        notification_disabled=nd if nd is not None else None,
    )


@action(
    name="broadcast_line_messages",
    description="Broadcast up to 5 LINE message objects to all friends.",
    action_sets=["line_messages"],
    input_schema={
        "messages": {"type": "array", "description": "Message objects.", "example": []},
        "notification_disabled": {"type": "boolean", "description": "Silent.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def broadcast_line_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    nd = input_data.get("notification_disabled")
    return run_client_sync(
        "line", "broadcast_messages",
        messages=input_data["messages"],
        notification_disabled=nd if nd is not None else None,
    )


# ----- Convenience builders for common message types -----

@action(
    name="send_line_image",
    description="Push an image. Image must be publicly accessible HTTPS URL.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "original_content_url": {"type": "string", "description": "HTTPS URL to full image.", "example": ""},
        "preview_image_url": {"type": "string", "description": "Preview URL (optional, defaults to original).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_image(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_image",
        to=input_data["to"],
        original_content_url=input_data["original_content_url"],
        preview_image_url=input_data.get("preview_image_url") or None,
    )


@action(
    name="send_line_video",
    description="Push a video (HTTPS URL + preview image).",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "original_content_url": {"type": "string", "description": "HTTPS URL to MP4.", "example": ""},
        "preview_image_url": {"type": "string", "description": "Preview HTTPS URL.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_video(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_video",
        to=input_data["to"],
        original_content_url=input_data["original_content_url"],
        preview_image_url=input_data["preview_image_url"],
    )


@action(
    name="send_line_audio",
    description="Push an audio file. duration_ms is required.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "original_content_url": {"type": "string", "description": "HTTPS URL.", "example": ""},
        "duration_ms": {"type": "integer", "description": "Duration in milliseconds.", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_audio(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_audio",
        to=input_data["to"],
        original_content_url=input_data["original_content_url"],
        duration_ms=input_data["duration_ms"],
    )


@action(
    name="send_line_location",
    description="Push a location pin.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "title": {"type": "string", "description": "Title.", "example": ""},
        "address": {"type": "string", "description": "Address.", "example": ""},
        "latitude": {"type": "number", "description": "Latitude.", "example": 35.6762},
        "longitude": {"type": "number", "description": "Longitude.", "example": 139.6503},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_location(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_location",
        to=input_data["to"], title=input_data["title"], address=input_data["address"],
        latitude=input_data["latitude"], longitude=input_data["longitude"],
    )


@action(
    name="send_line_sticker",
    description="Push a LINE sticker. See https://developers.line.biz/en/docs/messaging-api/sticker-list/ for IDs.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "package_id": {"type": "string", "description": "Sticker package ID.", "example": "446"},
        "sticker_id": {"type": "string", "description": "Sticker ID.", "example": "1988"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_sticker(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_sticker",
        to=input_data["to"],
        package_id=input_data["package_id"], sticker_id=input_data["sticker_id"],
    )


@action(
    name="send_line_flex",
    description="Push a Flex Message — LINE's rich, interactive card format. contents is the Flex container JSON (bubble or carousel).",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "alt_text": {"type": "string", "description": "Fallback text shown on devices without Flex support.", "example": "New notification"},
        "contents": {"type": "object", "description": "Flex container JSON.", "example": {}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_flex(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_flex",
        to=input_data["to"],
        alt_text=input_data["alt_text"],
        contents=input_data["contents"],
    )


@action(
    name="send_line_template",
    description="Push a template message: buttons / confirm / carousel / image_carousel. template is the Template object.",
    action_sets=["line_messages", "line"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "alt_text": {"type": "string", "description": "Fallback text.", "example": ""},
        "template": {"type": "object", "description": "Template object.", "example": {}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_template(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_template",
        to=input_data["to"],
        alt_text=input_data["alt_text"],
        template=input_data["template"],
    )


@action(
    name="send_line_imagemap",
    description="Push an imagemap: a clickable image overlaid with tappable regions. actions is a list of imagemap-action objects.",
    action_sets=["line_messages"],
    input_schema={
        "to": {"type": "string", "description": "Recipient.", "example": ""},
        "base_url": {"type": "string", "description": "Base HTTPS URL of the image set.", "example": ""},
        "alt_text": {"type": "string", "description": "Alt text.", "example": ""},
        "base_width": {"type": "integer", "description": "Base width (px).", "example": 1040},
        "base_height": {"type": "integer", "description": "Base height (px).", "example": 1040},
        "actions": {"type": "array", "description": "Imagemap actions.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_imagemap(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "push_imagemap",
        to=input_data["to"], base_url=input_data["base_url"],
        alt_text=input_data["alt_text"],
        base_width=input_data["base_width"], base_height=input_data["base_height"],
        actions=input_data["actions"],
    )


@action(
    name="download_line_message_content",
    description="Download the binary content of a user-sent image/video/audio/file message to a local path.",
    action_sets=["line_messages", "line"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "dest_path": {"type": "string", "description": "Local destination path.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def download_line_message_content(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "get_message_content",
        message_id=input_data["message_id"],
        dest_path=input_data["dest_path"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Profile + bot info + quota
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="get_line_profile",
    description="Fetch a LINE user's display name + picture URL.",
    action_sets=["line"],
    input_schema={
        "user_id": {"type": "string", "description": "User ID.", "example": "U..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_profile(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_profile", user_id=input_data["user_id"])


@action(
    name="get_line_bot_info",
    description="Get the connected LINE bot's own profile.",
    action_sets=["line"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_bot_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_bot_info")


@action(
    name="get_line_quota",
    description="Get the bot's monthly push-message quota.",
    action_sets=["line"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_quota(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_quota")


# ═══════════════════════════════════════════════════════════════════════════════
# Groups / rooms — info / members / leave
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="get_line_group_summary",
    description="Get a LINE group's name + picture URL.",
    action_sets=["line_groups", "line"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID (starts with 'C').", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_group_summary(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_group_summary", group_id=input_data["group_id"])


@action(
    name="get_line_group_member_count",
    description="Get the member count of a group.",
    action_sets=["line_groups", "line"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_group_member_count(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_group_member_count", group_id=input_data["group_id"])


@action(
    name="list_line_group_members",
    description="List user IDs of group members (paginated via start cursor).",
    action_sets=["line_groups", "line"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "start": {"type": "string", "description": "Pagination cursor (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_line_group_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "list_group_member_user_ids",
        group_id=input_data["group_id"],
        start=input_data.get("start") or None,
    )


@action(
    name="get_line_group_member_profile",
    description="Get a group member's display name + picture URL.",
    action_sets=["line_groups", "line"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_group_member_profile(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "get_group_member_profile",
        group_id=input_data["group_id"], user_id=input_data["user_id"],
    )


@action(
    name="leave_line_group",
    description="Leave a LINE group.",
    action_sets=["line_groups", "line"],
    input_schema={
        "group_id": {"type": "string", "description": "Group ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def leave_line_group(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "leave_group", group_id=input_data["group_id"])


@action(
    name="get_line_room_member_count",
    description="Get a multi-person chat (room)'s member count.",
    action_sets=["line_groups"],
    input_schema={
        "room_id": {"type": "string", "description": "Room ID (starts with 'R').", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_room_member_count(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_room_member_count", room_id=input_data["room_id"])


@action(
    name="list_line_room_members",
    description="List user IDs in a room.",
    action_sets=["line_groups"],
    input_schema={
        "room_id": {"type": "string", "description": "Room ID.", "example": ""},
        "start": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_line_room_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "list_room_member_user_ids",
        room_id=input_data["room_id"],
        start=input_data.get("start") or None,
    )


@action(
    name="get_line_room_member_profile",
    description="Get a room member's display name + picture URL.",
    action_sets=["line_groups"],
    input_schema={
        "room_id": {"type": "string", "description": "Room ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_room_member_profile(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "get_room_member_profile",
        room_id=input_data["room_id"], user_id=input_data["user_id"],
    )


@action(
    name="leave_line_room",
    description="Leave a LINE room (multi-person chat).",
    action_sets=["line_groups"],
    input_schema={
        "room_id": {"type": "string", "description": "Room ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def leave_line_room(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "leave_room", room_id=input_data["room_id"])


# ═══════════════════════════════════════════════════════════════════════════════
# Rich menus
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="create_line_rich_menu",
    description="Create a rich menu definition. rich_menu is a RichMenu object: {size:{width,height}, selected:bool, name, chatBarText, areas:[{bounds,action},...]}. Image must be uploaded separately via upload_line_rich_menu_image.",
    action_sets=["line_rich_menus", "line"],
    input_schema={
        "rich_menu": {"type": "object", "description": "RichMenu object.", "example": {}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_line_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "create_rich_menu", rich_menu=input_data["rich_menu"])


@action(
    name="get_line_rich_menu",
    description="Get a rich menu definition by ID.",
    action_sets=["line_rich_menus"],
    input_schema={
        "rich_menu_id": {"type": "string", "description": "Rich menu ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_rich_menu", rich_menu_id=input_data["rich_menu_id"])


@action(
    name="list_line_rich_menus",
    description="List all rich menus the bot has created.",
    action_sets=["line_rich_menus", "line"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_line_rich_menus(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "list_rich_menus")


@action(
    name="delete_line_rich_menu",
    description="Delete a rich menu.",
    action_sets=["line_rich_menus"],
    input_schema={
        "rich_menu_id": {"type": "string", "description": "Rich menu ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_line_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "delete_rich_menu", rich_menu_id=input_data["rich_menu_id"])


@action(
    name="upload_line_rich_menu_image",
    description="Upload the PNG/JPEG image for a rich menu (image dimensions must match the menu's size).",
    action_sets=["line_rich_menus", "line"],
    input_schema={
        "rich_menu_id": {"type": "string", "description": "Rich menu ID.", "example": ""},
        "file_path": {"type": "string", "description": "Local PNG or JPEG path.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def upload_line_rich_menu_image(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "upload_rich_menu_image",
        rich_menu_id=input_data["rich_menu_id"],
        file_path=input_data["file_path"],
    )


@action(
    name="set_line_default_rich_menu",
    description="Make a rich menu the default for all users.",
    action_sets=["line_rich_menus", "line"],
    input_schema={
        "rich_menu_id": {"type": "string", "description": "Rich menu ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_line_default_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "set_default_rich_menu", rich_menu_id=input_data["rich_menu_id"])


@action(
    name="get_line_default_rich_menu",
    description="Get the current default rich menu ID.",
    action_sets=["line_rich_menus"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_default_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_default_rich_menu")


@action(
    name="cancel_line_default_rich_menu",
    description="Unset the default rich menu.",
    action_sets=["line_rich_menus"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def cancel_line_default_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "cancel_default_rich_menu")


@action(
    name="link_line_rich_menu_to_user",
    description="Show a specific rich menu to a single user.",
    action_sets=["line_rich_menus", "line"],
    input_schema={
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
        "rich_menu_id": {"type": "string", "description": "Rich menu ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def link_line_rich_menu_to_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "link_rich_menu_to_user",
        user_id=input_data["user_id"], rich_menu_id=input_data["rich_menu_id"],
    )


@action(
    name="unlink_line_rich_menu_from_user",
    description="Remove the per-user rich menu override (falls back to default).",
    action_sets=["line_rich_menus"],
    input_schema={
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unlink_line_rich_menu_from_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "unlink_rich_menu_from_user", user_id=input_data["user_id"])


@action(
    name="get_line_user_rich_menu",
    description="Get the rich menu ID currently linked to a user.",
    action_sets=["line_rich_menus"],
    input_schema={
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_user_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_user_rich_menu", user_id=input_data["user_id"])


@action(
    name="bulk_link_line_rich_menu",
    description="Link many users (max 500) to a rich menu in one call. Returns 202; runs async.",
    action_sets=["line_rich_menus"],
    input_schema={
        "rich_menu_id": {"type": "string", "description": "Rich menu ID.", "example": ""},
        "user_ids": {"type": "array", "description": "User IDs (max 500).", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def bulk_link_line_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "bulk_link_rich_menu",
        rich_menu_id=input_data["rich_menu_id"], user_ids=input_data["user_ids"],
    )


@action(
    name="bulk_unlink_line_rich_menu",
    description="Unlink rich menus from many users in one call.",
    action_sets=["line_rich_menus"],
    input_schema={
        "user_ids": {"type": "array", "description": "User IDs.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def bulk_unlink_line_rich_menu(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "bulk_unlink_rich_menu", user_ids=input_data["user_ids"])


# ═══════════════════════════════════════════════════════════════════════════════
# Narrowcast + Audiences
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="send_line_narrowcast",
    description="Send messages to a filtered subset of friends (demographics or audience groups). Returns a request_id; poll with get_line_narrowcast_progress.",
    action_sets=["line_audiences", "line"],
    input_schema={
        "messages": {"type": "array", "description": "LINE message objects.", "example": []},
        "recipient": {"type": "object", "description": "Audience recipient spec (optional).", "example": {}},
        "demographic": {"type": "object", "description": "Demographic filter (optional).", "example": {}},
        "limit": {"type": "object", "description": "Limit spec (optional).", "example": {}},
        "notification_disabled": {"type": "boolean", "description": "Silent.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_line_narrowcast(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    nd = input_data.get("notification_disabled")
    return run_client_sync(
        "line", "send_narrowcast",
        messages=input_data["messages"],
        recipient=input_data.get("recipient") or None,
        demographic=input_data.get("demographic") or None,
        limit=input_data.get("limit") or None,
        notification_disabled=nd if nd is not None else None,
    )


@action(
    name="get_line_narrowcast_progress",
    description="Poll a narrowcast request's delivery progress.",
    action_sets=["line_audiences"],
    input_schema={
        "request_id": {"type": "string", "description": "Request ID from send_line_narrowcast.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_narrowcast_progress(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_narrowcast_progress", request_id=input_data["request_id"])


@action(
    name="create_line_user_id_audience",
    description="Create an audience group from explicit user IDs. audiences: [{id:'<user_id>'}, ...].",
    action_sets=["line_audiences"],
    input_schema={
        "description": {"type": "string", "description": "Audience description.", "example": ""},
        "audiences": {"type": "array", "description": "List of {id: user_id} dicts.", "example": []},
        "is_ifa_audience": {"type": "boolean", "description": "True for advertising-ID audience.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_line_user_id_audience(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "create_user_id_audience",
        description=input_data["description"],
        audiences=input_data.get("audiences") or None,
        is_ifa_audience=bool(input_data.get("is_ifa_audience", False)),
    )


@action(
    name="get_line_audience",
    description="Get an audience group's metadata + status.",
    action_sets=["line_audiences"],
    input_schema={
        "audience_group_id": {"type": "integer", "description": "Audience group ID.", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_audience(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_audience", audience_group_id=input_data["audience_group_id"])


@action(
    name="list_line_audiences",
    description="List the bot's audience groups (with optional filters).",
    action_sets=["line_audiences"],
    input_schema={
        "page": {"type": "integer", "description": "Page number.", "example": 1},
        "size": {"type": "integer", "description": "Page size (max 40).", "example": 20},
        "description": {"type": "string", "description": "Filter by description substring.", "example": ""},
        "status": {"type": "string", "description": "Filter by status: IN_PROGRESS | READY | FAILED | EXPIRED.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_line_audiences(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "list_audiences",
        page=input_data.get("page", 1),
        size=input_data.get("size", 20),
        description=input_data.get("description") or None,
        status=input_data.get("status") or None,
    )


@action(
    name="update_line_audience_description",
    description="Change an audience group's description.",
    action_sets=["line_audiences"],
    input_schema={
        "audience_group_id": {"type": "integer", "description": "Audience group ID.", "example": 0},
        "description": {"type": "string", "description": "New description.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_line_audience_description(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "update_audience_description",
        audience_group_id=input_data["audience_group_id"],
        description=input_data["description"],
    )


@action(
    name="delete_line_audience",
    description="Delete an audience group.",
    action_sets=["line_audiences"],
    input_schema={
        "audience_group_id": {"type": "integer", "description": "Audience group ID.", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_line_audience(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "delete_audience", audience_group_id=input_data["audience_group_id"])


# ═══════════════════════════════════════════════════════════════════════════════
# Insights
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="get_line_followers_count",
    description="Number of followers on a given date (YYYYMMDD).",
    action_sets=["line_insights", "line"],
    input_schema={
        "date": {"type": "string", "description": "YYYYMMDD.", "example": "20260520"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_followers_count(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_number_of_followers", date=input_data["date"])


@action(
    name="get_line_friend_demographics",
    description="Demographic breakdown of friends (gender, age, area).",
    action_sets=["line_insights"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_friend_demographics(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_friend_demographics")


@action(
    name="get_line_message_delivery_stats",
    description="Number of pushes/multicasts/broadcasts sent on a date.",
    action_sets=["line_insights"],
    input_schema={
        "date": {"type": "string", "description": "YYYYMMDD.", "example": "20260520"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_message_delivery_stats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_message_delivery_stats", date=input_data["date"])


@action(
    name="get_line_message_event_stats",
    description="Per-narrowcast/broadcast click/impression/open stats.",
    action_sets=["line_insights"],
    input_schema={
        "request_id": {"type": "string", "description": "Request ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_message_event_stats(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_message_event_stats", request_id=input_data["request_id"])


# ═══════════════════════════════════════════════════════════════════════════════
# Webhook + channel token admin
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="set_line_webhook_endpoint",
    description="Set the HTTPS endpoint where LINE will POST incoming events.",
    action_sets=["line_channel"],
    input_schema={
        "endpoint": {"type": "string", "description": "HTTPS URL.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_line_webhook_endpoint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "set_webhook_endpoint", endpoint=input_data["endpoint"])


@action(
    name="get_line_webhook_endpoint",
    description="Get the current webhook endpoint URL.",
    action_sets=["line_channel"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_line_webhook_endpoint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "get_webhook_endpoint")


@action(
    name="test_line_webhook_endpoint",
    description="Test the webhook (LINE sends a synthetic event). Returns status code + latency.",
    action_sets=["line_channel"],
    input_schema={
        "endpoint": {"type": "string", "description": "Override URL (optional, defaults to configured one).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def test_line_webhook_endpoint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "test_webhook_endpoint", endpoint=input_data.get("endpoint") or None)


@action(
    name="issue_line_channel_access_token",
    description="Issue a short-lived channel access token (v2.1). Useful for credential rotation.",
    action_sets=["line_channel"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "channel_secret": {"type": "string", "description": "Channel secret.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def issue_line_channel_access_token(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync(
        "line", "issue_channel_access_token",
        channel_id=input_data["channel_id"], channel_secret=input_data["channel_secret"],
    )


@action(
    name="revoke_line_channel_access_token",
    description="Revoke a channel access token.",
    action_sets=["line_channel"],
    input_schema={
        "access_token": {"type": "string", "description": "Token to revoke.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def revoke_line_channel_access_token(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "revoke_channel_access_token", access_token=input_data["access_token"])


@action(
    name="verify_line_access_token",
    description="Verify an access token is valid and show its scope/expiry.",
    action_sets=["line_channel"],
    input_schema={
        "access_token": {"type": "string", "description": "Token to verify.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def verify_line_access_token(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    return run_client_sync("line", "verify_access_token", access_token=input_data["access_token"])


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Webhook signature verification helper
#     Library-side concern; would only be useful if CraftBot ran the
#     webhook server itself, which it doesn't (send-only).
# - LIFF endpoints (LINE Front-end Framework)
#     Frontend mini-app surface, not interactive bot work.
# - LINE Login / LINE Profile+
#     Separate API; distinct integration.
# - LINE Pay
#     Separate billing API, out of scope.
# - statisticsPerUnit aggregated insights
#     Niche; standard insights cover the common reporting case.
