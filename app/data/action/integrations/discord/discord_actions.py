from agent_core import action


# ═══════════════════════════════════════════════════════════════════════════════
# Messages — send / edit / delete / reply / bulk-delete / pins / reactions
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="send_discord_message",
    irreversible=True,
    description="Send a message to a Discord channel.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "Discord channel ID.",
            "example": "123456789012345678",
        },
        "content": {
            "type": "string",
            "description": "Message content.",
            "example": "Hello!",
        },
        "reply_to": {
            "type": "string",
            "description": "Message ID to reply to (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_discord_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "bot_send_message",
        channel_id=input_data["channel_id"],
        content=input_data["content"],
        reply_to=input_data.get("reply_to") or None,
    )


@action(
    name="edit_discord_message",
    description="Edit a previously-sent Discord message (bot can only edit its own messages).",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "content": {
            "type": "string",
            "description": "New message content.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def edit_discord_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "edit_message",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
        content=input_data["content"],
    )


@action(
    name="delete_discord_message",
    description="Delete a Discord message.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "delete_message",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
    )


@action(
    name="bulk_delete_discord_messages",
    description="Delete 2-100 messages at once. All must be less than 14 days old.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_ids": {
            "type": "array",
            "description": "Array of message IDs (2-100).",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def bulk_delete_discord_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "bulk_delete_messages",
        channel_id=input_data["channel_id"],
        message_ids=input_data["message_ids"],
    )


@action(
    name="crosspost_discord_message",
    description="Publish a message from an announcement channel to following servers.",
    action_sets=["discord_messages"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "Announcement channel ID.",
            "example": "",
        },
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def crosspost_discord_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "crosspost_message",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
    )


@action(
    name="get_discord_messages",
    description="Get messages from a Discord channel.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "Discord channel ID.",
            "example": "123456789012345678",
        },
        "limit": {
            "type": "integer",
            "description": "Max messages to return (1-100).",
            "example": 50,
        },
        "before": {
            "type": "string",
            "description": "Message ID to get messages before (optional).",
            "example": "",
        },
        "after": {
            "type": "string",
            "description": "Message ID to get messages after (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "get_messages",
        channel_id=input_data["channel_id"],
        limit=input_data.get("limit", 50),
        before=input_data.get("before") or None,
        after=input_data.get("after") or None,
    )


@action(
    name="pin_discord_message",
    description="Pin a message in a Discord channel.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def pin_discord_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "pin_message",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
    )


@action(
    name="unpin_discord_message",
    description="Unpin a message from a Discord channel.",
    action_sets=["discord_messages"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unpin_discord_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "unpin_message",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
    )


@action(
    name="list_discord_pinned_messages",
    description="List pinned messages in a Discord channel. Lean messages by default; include_metadata=true returns raw message objects.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "include_metadata": {
            "type": "boolean",
            "description": "Return full raw message objects (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {messages: [{id, content, author: {id, username, bot}, timestamp, attachments?}], count}.",
        },
    },
)
def list_discord_pinned_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "discord", "list_pinned_messages", channel_id=input_data["channel_id"]
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict):
        return res
    lean = []
    for m in result.get("messages", []):
        if not isinstance(m, dict):
            continue
        a = m.get("author") or {}
        item = {
            "id": m.get("id"),
            "content": m.get("content"),
            "author": {
                "id": a.get("id"),
                "username": a.get("username"),
                "bot": a.get("bot", False),
            },
            "timestamp": m.get("timestamp"),
        }
        atts = [
            {
                "id": att.get("id"),
                "filename": att.get("filename"),
                "url": att.get("url"),
            }
            for att in m.get("attachments") or []
            if isinstance(att, dict)
        ]
        if atts:
            item["attachments"] = atts
        lean.append(item)
    return {
        **res,
        "result": {"messages": lean, "count": result.get("count", len(lean))},
    }


@action(
    name="add_discord_reaction",
    description="Add a reaction emoji to a message.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "Channel ID.",
            "example": "123",
        },
        "message_id": {
            "type": "string",
            "description": "Message ID.",
            "example": "456",
        },
        "emoji": {
            "type": "string",
            "description": "Unicode emoji or 'name:id' for custom.",
            "example": "👍",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_discord_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "add_reaction",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
        emoji=input_data["emoji"],
    )


@action(
    name="remove_discord_own_reaction",
    description="Remove the bot's own reaction from a message.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "emoji": {"type": "string", "description": "Emoji.", "example": "👍"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def remove_discord_own_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "remove_own_reaction",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
        emoji=input_data["emoji"],
    )


@action(
    name="remove_discord_user_reaction",
    description="Remove a specific user's reaction from a message (mod action).",
    action_sets=["discord_messages"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "emoji": {"type": "string", "description": "Emoji.", "example": ""},
        "user_id": {
            "type": "string",
            "description": "User ID whose reaction to remove.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def remove_discord_user_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "remove_user_reaction",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
        emoji=input_data["emoji"],
        user_id=input_data["user_id"],
    )


@action(
    name="list_discord_reaction_users",
    description="List users who reacted with a specific emoji.",
    action_sets=["discord_messages"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "emoji": {"type": "string", "description": "Emoji.", "example": ""},
        "limit": {"type": "integer", "description": "Max users.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_reaction_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "list_reaction_users",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
        emoji=input_data["emoji"],
        limit=input_data.get("limit", 100),
    )


@action(
    name="clear_discord_reactions",
    description="Clear all reactions on a message, or just one emoji's reactions.",
    action_sets=["discord_messages"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "emoji": {
            "type": "string",
            "description": "Specific emoji (optional — omit to clear ALL reactions).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def clear_discord_reactions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "clear_reactions",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
        emoji=input_data.get("emoji") or None,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Threads
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="create_discord_thread_from_message",
    description="Create a thread anchored to an existing message.",
    action_sets=["discord_threads", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "message_id": {
            "type": "string",
            "description": "Message to thread from.",
            "example": "",
        },
        "name": {
            "type": "string",
            "description": "Thread name (1-100 chars).",
            "example": "Discussion",
        },
        "auto_archive_duration": {
            "type": "integer",
            "description": "Minutes: 60, 1440, 4320, 10080.",
            "example": 1440,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_thread_from_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "create_thread_from_message",
        channel_id=input_data["channel_id"],
        message_id=input_data["message_id"],
        name=input_data["name"],
        auto_archive_duration=input_data.get("auto_archive_duration", 1440),
    )


@action(
    name="create_discord_thread",
    description="Create a thread (no starter message). thread_type: 10=announcement, 11=public, 12=private.",
    action_sets=["discord_threads", "discord"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "Parent channel ID.",
            "example": "",
        },
        "name": {"type": "string", "description": "Thread name.", "example": ""},
        "thread_type": {"type": "integer", "description": "10/11/12.", "example": 11},
        "auto_archive_duration": {
            "type": "integer",
            "description": "Minutes.",
            "example": 1440,
        },
        "invitable": {
            "type": "boolean",
            "description": "Allow non-mods to add others (private threads).",
            "example": True,
        },
        "rate_limit_per_user": {
            "type": "integer",
            "description": "Slowmode seconds (optional).",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    rl = input_data.get("rate_limit_per_user")
    return run_client_sync(
        "discord",
        "create_thread",
        channel_id=input_data["channel_id"],
        name=input_data["name"],
        thread_type=input_data.get("thread_type", 11),
        auto_archive_duration=input_data.get("auto_archive_duration", 1440),
        invitable=bool(input_data.get("invitable", True)),
        rate_limit_per_user=rl if rl is not None else None,
    )


@action(
    name="join_discord_thread",
    description="Join a Discord thread as the bot.",
    action_sets=["discord_threads", "discord"],
    input_schema={
        "thread_id": {
            "type": "string",
            "description": "Thread (channel) ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def join_discord_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "join_thread", thread_id=input_data["thread_id"])


@action(
    name="leave_discord_thread",
    description="Leave a Discord thread.",
    action_sets=["discord_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def leave_discord_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "leave_thread", thread_id=input_data["thread_id"])


@action(
    name="add_discord_thread_member",
    description="Add a user to a thread.",
    action_sets=["discord_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_discord_thread_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "add_thread_member",
        thread_id=input_data["thread_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="remove_discord_thread_member",
    description="Remove a user from a thread.",
    action_sets=["discord_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def remove_discord_thread_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "remove_thread_member",
        thread_id=input_data["thread_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="list_discord_thread_members",
    description="List members of a thread.",
    action_sets=["discord_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_thread_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "list_thread_members", thread_id=input_data["thread_id"]
    )


@action(
    name="list_discord_active_threads",
    description="List active (non-archived) threads in a guild the bot can access.",
    action_sets=["discord_threads", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_active_threads(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "list_active_threads", guild_id=input_data["guild_id"]
    )


@action(
    name="archive_discord_thread",
    description="Archive a thread (closes for new messages).",
    action_sets=["discord_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def archive_discord_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "archive_thread", thread_id=input_data["thread_id"]
    )


@action(
    name="unarchive_discord_thread",
    description="Unarchive a previously-archived thread.",
    action_sets=["discord_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unarchive_discord_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "unarchive_thread", thread_id=input_data["thread_id"]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Channels — list / info / CRUD / permissions / invites
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="get_discord_channels",
    description="Get all channels in a Discord guild. Lean channel list by default; include_metadata=true returns raw channel objects plus type-grouped subsets.",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "guild_id": {
            "type": "string",
            "description": "Discord guild (server) ID.",
            "example": "123456789012345678",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return full raw channel objects (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {all_channels: [{id, name, type, parent_id, position?, topic?}]}.",
        },
    },
)
def get_discord_channels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "discord", "get_guild_channels", guild_id=input_data["guild_id"]
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict):
        return res
    lean = []
    for c in result.get("all_channels", []):
        if not isinstance(c, dict):
            continue
        ch = {
            "id": c.get("id"),
            "name": c.get("name"),
            "type": c.get("type"),
            "parent_id": c.get("parent_id"),
        }
        if c.get("position") is not None:
            ch["position"] = c.get("position")
        if c.get("topic"):
            ch["topic"] = c.get("topic")
        lean.append(ch)
    return {**res, "result": {"all_channels": lean}}


@action(
    name="get_discord_channel",
    description="Get info about a single Discord channel.",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "get_channel", channel_id=input_data["channel_id"]
    )


@action(
    name="create_discord_channel",
    description="Create a channel in a guild. channel_type: 0=text, 2=voice, 4=category, 5=announcement, 13=stage, 15=forum.",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "Channel name.",
            "example": "general",
        },
        "channel_type": {
            "type": "integer",
            "description": "0/2/4/5/13/15.",
            "example": 0,
        },
        "topic": {
            "type": "string",
            "description": "Topic (text channels only).",
            "example": "",
        },
        "parent_id": {
            "type": "string",
            "description": "Category ID (optional).",
            "example": "",
        },
        "nsfw": {"type": "boolean", "description": "NSFW flag.", "example": False},
        "rate_limit_per_user": {
            "type": "integer",
            "description": "Slowmode seconds.",
            "example": 0,
        },
        "position": {
            "type": "integer",
            "description": "Channel position.",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "create_guild_channel",
        guild_id=input_data["guild_id"],
        name=input_data["name"],
        channel_type=input_data.get("channel_type", 0),
        topic=input_data.get("topic") or None,
        parent_id=input_data.get("parent_id") or None,
        nsfw=bool(input_data.get("nsfw", False)),
        rate_limit_per_user=input_data.get("rate_limit_per_user")
        if "rate_limit_per_user" in input_data
        else None,
        position=input_data.get("position") if "position" in input_data else None,
    )


@action(
    name="modify_discord_channel",
    description="Edit channel name/topic/slowmode/category/NSFW.",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "topic": {
            "type": "string",
            "description": "New topic (optional).",
            "example": "",
        },
        "nsfw": {
            "type": "boolean",
            "description": "NSFW flag (optional).",
            "example": False,
        },
        "rate_limit_per_user": {
            "type": "integer",
            "description": "Slowmode seconds (optional).",
            "example": 0,
        },
        "parent_id": {
            "type": "string",
            "description": "New category ID (optional).",
            "example": "",
        },
        "position": {
            "type": "integer",
            "description": "New position (optional).",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def modify_discord_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "modify_channel",
        channel_id=input_data["channel_id"],
        name=input_data.get("name") or None,
        topic=input_data["topic"] if "topic" in input_data else None,
        nsfw=input_data["nsfw"] if "nsfw" in input_data else None,
        rate_limit_per_user=input_data["rate_limit_per_user"]
        if "rate_limit_per_user" in input_data
        else None,
        parent_id=input_data.get("parent_id") or None,
        position=input_data["position"] if "position" in input_data else None,
    )


@action(
    name="delete_discord_channel",
    description="Delete a Discord channel.",
    action_sets=["discord_channels"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "delete_channel", channel_id=input_data["channel_id"]
    )


@action(
    name="set_discord_channel_permissions",
    description="Set permission overwrites for a role/member on a channel. allow/deny are decimal-string bitfields. type: 0=role, 1=member.",
    action_sets=["discord_channels"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "overwrite_id": {
            "type": "string",
            "description": "Role ID or member ID.",
            "example": "",
        },
        "allow": {
            "type": "string",
            "description": "Allow bitfield as decimal string.",
            "example": "0",
        },
        "deny": {
            "type": "string",
            "description": "Deny bitfield as decimal string.",
            "example": "0",
        },
        "type": {"type": "integer", "description": "0=role, 1=member.", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_discord_channel_permissions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "edit_channel_permissions",
        channel_id=input_data["channel_id"],
        overwrite_id=input_data["overwrite_id"],
        allow=input_data.get("allow", "0"),
        deny=input_data.get("deny", "0"),
        type=input_data.get("type", 0),
    )


@action(
    name="delete_discord_channel_permission",
    description="Remove a permission overwrite from a channel.",
    action_sets=["discord_channels"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "overwrite_id": {
            "type": "string",
            "description": "Role/member ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_channel_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "delete_channel_permission",
        channel_id=input_data["channel_id"],
        overwrite_id=input_data["overwrite_id"],
    )


@action(
    name="list_discord_channel_invites",
    description="List invite codes for a channel.",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_channel_invites(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "list_channel_invites", channel_id=input_data["channel_id"]
    )


@action(
    name="create_discord_invite",
    description="Create an invite for a channel.",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "max_age": {
            "type": "integer",
            "description": "Seconds until expiry (0=never).",
            "example": 86400,
        },
        "max_uses": {"type": "integer", "description": "0=unlimited.", "example": 0},
        "temporary": {
            "type": "boolean",
            "description": "Members are kicked after disconnect.",
            "example": False,
        },
        "unique": {
            "type": "boolean",
            "description": "Don't reuse existing invite.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_invite(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "create_channel_invite",
        channel_id=input_data["channel_id"],
        max_age=input_data.get("max_age", 86400),
        max_uses=input_data.get("max_uses", 0),
        temporary=bool(input_data.get("temporary", False)),
        unique=bool(input_data.get("unique", False)),
    )


@action(
    name="delete_discord_invite",
    description="Delete (revoke) a Discord invite code.",
    action_sets=["discord_channels"],
    input_schema={
        "invite_code": {"type": "string", "description": "Invite code.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_invite(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "delete_invite", invite_code=input_data["invite_code"]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Webhooks (channel-scoped)
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="list_discord_webhooks",
    description="List webhooks in a channel. Lean by default; include_metadata=true returns full raw objects. The webhook token is never returned.",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "include_metadata": {
            "type": "boolean",
            "description": "Return full raw webhook objects, minus token (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {webhooks: [{id, name, type, channel_id, guild_id, application_id}], count}. Token is always omitted.",
        },
    },
)
def list_discord_webhooks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "discord", "list_channel_webhooks", channel_id=input_data["channel_id"]
    )
    if res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict):
        return res
    include = bool(input_data.get("include_metadata"))
    shaped = []
    for w in result.get("webhooks", []):
        if not isinstance(w, dict):
            continue
        if include:
            wh = {k: v for k, v in w.items() if k != "token"}
            u = wh.get("user")
            if isinstance(u, dict):
                wh["user"] = {"id": u.get("id"), "username": u.get("username")}
        else:
            wh = {
                "id": w.get("id"),
                "name": w.get("name"),
                "type": w.get("type"),
                "channel_id": w.get("channel_id"),
                "guild_id": w.get("guild_id"),
                "application_id": w.get("application_id"),
            }
        shaped.append(wh)
    return {
        **res,
        "result": {"webhooks": shaped, "count": result.get("count", len(shaped))},
    }


@action(
    name="create_discord_webhook",
    description="Create a webhook on a channel. Returns id + token (the token gives webhook-only posting auth).",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "Webhook name.",
            "example": "Notifier",
        },
        "avatar": {
            "type": "string",
            "description": "Data-URI avatar (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_webhook(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "create_webhook",
        channel_id=input_data["channel_id"],
        name=input_data["name"],
        avatar=input_data.get("avatar") or None,
    )


@action(
    name="get_discord_webhook",
    description="Get a webhook by ID. Lean by default; include_metadata=true returns the full raw object. The webhook token is never returned.",
    action_sets=["discord_channels"],
    input_schema={
        "webhook_id": {"type": "string", "description": "Webhook ID.", "example": ""},
        "include_metadata": {
            "type": "boolean",
            "description": "Return the full raw webhook object, minus token (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {id, name, type, channel_id, guild_id, application_id}. Token is always omitted.",
        },
    },
)
def get_discord_webhook(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync("discord", "get_webhook", webhook_id=input_data["webhook_id"])
    if res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict):
        return res
    if input_data.get("include_metadata"):
        wh = {k: v for k, v in result.items() if k != "token"}
        u = wh.get("user")
        if isinstance(u, dict):
            wh["user"] = {"id": u.get("id"), "username": u.get("username")}
    else:
        wh = {
            "id": result.get("id"),
            "name": result.get("name"),
            "type": result.get("type"),
            "channel_id": result.get("channel_id"),
            "guild_id": result.get("guild_id"),
            "application_id": result.get("application_id"),
        }
    return {**res, "result": wh}


@action(
    name="modify_discord_webhook",
    description="Edit a webhook's name/avatar/channel.",
    action_sets=["discord_channels"],
    input_schema={
        "webhook_id": {"type": "string", "description": "Webhook ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "avatar": {
            "type": "string",
            "description": "New avatar data-URI (optional).",
            "example": "",
        },
        "channel_id": {
            "type": "string",
            "description": "Move to channel (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def modify_discord_webhook(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "modify_webhook",
        webhook_id=input_data["webhook_id"],
        name=input_data["name"] if "name" in input_data else None,
        avatar=input_data["avatar"] if "avatar" in input_data else None,
        channel_id=input_data["channel_id"] if "channel_id" in input_data else None,
    )


@action(
    name="delete_discord_webhook",
    description="Delete a Discord webhook.",
    action_sets=["discord_channels"],
    input_schema={
        "webhook_id": {"type": "string", "description": "Webhook ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_webhook(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "delete_webhook", webhook_id=input_data["webhook_id"]
    )


@action(
    name="execute_discord_webhook",
    description="Post a message via a webhook (auth via webhook_token, not bot token).",
    action_sets=["discord_channels", "discord"],
    input_schema={
        "webhook_id": {"type": "string", "description": "Webhook ID.", "example": ""},
        "webhook_token": {
            "type": "string",
            "description": "Webhook token (from creation).",
            "example": "",
        },
        "content": {"type": "string", "description": "Message content.", "example": ""},
        "username": {
            "type": "string",
            "description": "Override sender username (optional).",
            "example": "",
        },
        "avatar_url": {
            "type": "string",
            "description": "Override sender avatar (optional).",
            "example": "",
        },
        "embeds": {
            "type": "array",
            "description": "Embed objects (optional).",
            "example": [],
        },
        "wait": {
            "type": "boolean",
            "description": "Wait for server confirmation (returns message).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def execute_discord_webhook(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "execute_webhook",
        webhook_id=input_data["webhook_id"],
        webhook_token=input_data["webhook_token"],
        content=input_data.get("content") or None,
        username=input_data.get("username") or None,
        avatar_url=input_data.get("avatar_url") or None,
        embeds=input_data.get("embeds") or None,
        wait=bool(input_data.get("wait", False)),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Members — list / get / search / modify (nick/roles/timeout/voice) / kick / ban
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="list_discord_guild_members",
    description="List members of a guild. Lean members by default; include_metadata=true returns raw member objects.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {
            "type": "string",
            "description": "Guild ID.",
            "example": "123456789012345678",
        },
        "limit": {"type": "integer", "description": "Limit.", "example": 100},
        "include_metadata": {
            "type": "boolean",
            "description": "Return full raw member objects (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {members: [{user: {id, username, global_name?}, nick?, roles, joined_at}]}.",
        },
    },
)
def list_discord_guild_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "discord",
        "list_guild_members",
        guild_id=input_data["guild_id"],
        limit=input_data.get("limit", 100),
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict):
        return res
    lean = []
    for m in result.get("members", []):
        if not isinstance(m, dict):
            continue
        u = m.get("user") or {}
        user = {"id": u.get("id"), "username": u.get("username")}
        if u.get("global_name"):
            user["global_name"] = u.get("global_name")
        member = {
            "user": user,
            "roles": m.get("roles", []),
            "joined_at": m.get("joined_at"),
        }
        if m.get("nick"):
            member["nick"] = m.get("nick")
        lean.append(member)
    return {**res, "result": {"members": lean}}


@action(
    name="get_discord_guild_member",
    description="Get a single guild member (incl. roles, joined_at, nick).",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_guild_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "get_guild_member",
        guild_id=input_data["guild_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="search_discord_guild_members",
    description="Search for members by username/nickname prefix.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "query": {"type": "string", "description": "Name prefix.", "example": "alice"},
        "limit": {
            "type": "integer",
            "description": "Max results (max 1000).",
            "example": 10,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_discord_guild_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "search_guild_members",
        guild_id=input_data["guild_id"],
        query=input_data["query"],
        limit=input_data.get("limit", 10),
    )


@action(
    name="modify_discord_guild_member",
    description="Modify a guild member: nick / roles (full replace) / mute/deaf / move voice channel / timeout. communication_disabled_until is an ISO 8601 timestamp (max 28 days in future) — null/omit to clear.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
        "nick": {
            "type": "string",
            "description": "New nickname (optional, '' to clear).",
            "example": "",
        },
        "roles": {
            "type": "array",
            "description": "Full list of role IDs (replaces existing).",
            "example": [],
        },
        "mute": {"type": "boolean", "description": "Voice mute.", "example": False},
        "deaf": {"type": "boolean", "description": "Voice deafen.", "example": False},
        "channel_id": {
            "type": "string",
            "description": "Move to this voice channel.",
            "example": "",
        },
        "communication_disabled_until": {
            "type": "string",
            "description": "Timeout end (ISO 8601).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def modify_discord_guild_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "modify_guild_member",
        guild_id=input_data["guild_id"],
        user_id=input_data["user_id"],
        nick=input_data["nick"] if "nick" in input_data else None,
        roles=input_data["roles"] if "roles" in input_data else None,
        mute=input_data["mute"] if "mute" in input_data else None,
        deaf=input_data["deaf"] if "deaf" in input_data else None,
        channel_id=input_data["channel_id"] if "channel_id" in input_data else None,
        communication_disabled_until=input_data["communication_disabled_until"]
        if "communication_disabled_until" in input_data
        else None,
    )


@action(
    name="set_discord_bot_nickname",
    description="Set the bot's nickname in a guild.",
    action_sets=["discord_members"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "nick": {
            "type": "string",
            "description": "New nickname (empty to clear).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_discord_bot_nickname(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "modify_current_member_nick",
        guild_id=input_data["guild_id"],
        nick=input_data.get("nick") or None,
    )


@action(
    name="add_discord_member_role",
    description="Assign a role to a guild member.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
        "role_id": {"type": "string", "description": "Role ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_discord_member_role(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "add_guild_member_role",
        guild_id=input_data["guild_id"],
        user_id=input_data["user_id"],
        role_id=input_data["role_id"],
    )


@action(
    name="remove_discord_member_role",
    description="Remove a role from a guild member.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
        "role_id": {"type": "string", "description": "Role ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def remove_discord_member_role(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "remove_guild_member_role",
        guild_id=input_data["guild_id"],
        user_id=input_data["user_id"],
        role_id=input_data["role_id"],
    )


@action(
    name="kick_discord_member",
    description="Kick a user from a guild (they can rejoin via invite).",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def kick_discord_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "kick_guild_member",
        guild_id=input_data["guild_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="ban_discord_member",
    description="Ban a user from a guild. delete_message_seconds (0..604800) wipes their recent messages.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
        "delete_message_seconds": {
            "type": "integer",
            "description": "0..604800 (7d).",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def ban_discord_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "ban_guild_member",
        guild_id=input_data["guild_id"],
        user_id=input_data["user_id"],
        delete_message_seconds=input_data.get("delete_message_seconds", 0),
    )


@action(
    name="unban_discord_member",
    description="Lift a ban on a user.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unban_discord_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "unban_guild_member",
        guild_id=input_data["guild_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="list_discord_bans",
    description="List bans in a guild.",
    action_sets=["discord_members"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "limit": {"type": "integer", "description": "Max results.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_bans(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "list_guild_bans",
        guild_id=input_data["guild_id"],
        limit=input_data.get("limit", 100),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Guild — list/info + roles + emojis/stickers + scheduled events + audit log + invites
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="list_discord_guilds",
    description="List Discord guilds (servers) the bot is in.",
    action_sets=["discord_guild", "discord"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max guilds to return.",
            "example": 100,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_guilds(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "get_bot_guilds", limit=input_data.get("limit", 100)
    )


@action(
    name="get_discord_guild",
    description="Get info about a Discord guild. Lean summary by default; include_metadata=true returns the raw guild object (roles, emojis, stickers, features).",
    action_sets=["discord_guild", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "include_metadata": {
            "type": "boolean",
            "description": "Return the full raw guild object (default false = lean).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {id, name, description, owner_id, member_count?, approximate_member_count?, premium_tier?, preferred_locale?}.",
        },
    },
)
def get_discord_guild(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync("discord", "get_guild", guild_id=input_data["guild_id"])
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    g = res.get("result")
    if not isinstance(g, dict):
        return res
    lean = {
        "id": g.get("id"),
        "name": g.get("name"),
        "description": g.get("description"),
        "owner_id": g.get("owner_id"),
    }
    for k in (
        "member_count",
        "approximate_member_count",
        "premium_tier",
        "preferred_locale",
    ):
        if g.get(k) is not None:
            lean[k] = g.get(k)
    return {**res, "result": lean}


@action(
    name="list_discord_guild_roles",
    description="List roles in a guild.",
    action_sets=["discord_guild", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_guild_roles(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "get_guild_roles", guild_id=input_data["guild_id"]
    )


@action(
    name="create_discord_role",
    description="Create a new role in a guild. permissions is a decimal-string bitfield. color is an integer (0xRRGGBB).",
    action_sets=["discord_guild", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "name": {"type": "string", "description": "Role name.", "example": ""},
        "permissions": {
            "type": "string",
            "description": "Permissions bitfield (optional).",
            "example": "0",
        },
        "color": {
            "type": "integer",
            "description": "Color int (optional).",
            "example": 0,
        },
        "hoist": {
            "type": "boolean",
            "description": "Display separately in member list.",
            "example": False,
        },
        "mentionable": {
            "type": "boolean",
            "description": "Can be @-mentioned.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_role(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "create_guild_role",
        guild_id=input_data["guild_id"],
        name=input_data["name"],
        permissions=input_data.get("permissions") or None,
        color=input_data["color"] if "color" in input_data else None,
        hoist=bool(input_data.get("hoist", False)),
        mentionable=bool(input_data.get("mentionable", False)),
    )


@action(
    name="modify_discord_role",
    description="Edit a role's name/permissions/color/hoist/mentionable.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "role_id": {"type": "string", "description": "Role ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "permissions": {
            "type": "string",
            "description": "New permissions (optional).",
            "example": "",
        },
        "color": {
            "type": "integer",
            "description": "New color (optional).",
            "example": 0,
        },
        "hoist": {
            "type": "boolean",
            "description": "Hoist (optional).",
            "example": False,
        },
        "mentionable": {
            "type": "boolean",
            "description": "Mentionable (optional).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def modify_discord_role(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "modify_guild_role",
        guild_id=input_data["guild_id"],
        role_id=input_data["role_id"],
        name=input_data.get("name") or None,
        permissions=input_data.get("permissions") or None,
        color=input_data["color"] if "color" in input_data else None,
        hoist=input_data["hoist"] if "hoist" in input_data else None,
        mentionable=input_data["mentionable"] if "mentionable" in input_data else None,
    )


@action(
    name="delete_discord_role",
    description="Delete a role from a guild.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "role_id": {"type": "string", "description": "Role ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_role(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "delete_guild_role",
        guild_id=input_data["guild_id"],
        role_id=input_data["role_id"],
    )


@action(
    name="list_discord_emojis",
    description="List custom emojis in a guild.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_emojis(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "list_guild_emojis", guild_id=input_data["guild_id"]
    )


@action(
    name="create_discord_emoji",
    description="Create a custom emoji. image is a data-URI: 'data:image/png;base64,<base64>'.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "Emoji name (alphanumeric+underscore).",
            "example": "",
        },
        "image": {"type": "string", "description": "Data-URI string.", "example": ""},
        "roles": {
            "type": "array",
            "description": "Role IDs restricted to use (optional).",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_emoji(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "create_guild_emoji",
        guild_id=input_data["guild_id"],
        name=input_data["name"],
        image=input_data["image"],
        roles=input_data.get("roles") or None,
    )


@action(
    name="delete_discord_emoji",
    description="Delete a custom emoji.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "emoji_id": {"type": "string", "description": "Emoji ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_emoji(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "delete_guild_emoji",
        guild_id=input_data["guild_id"],
        emoji_id=input_data["emoji_id"],
    )


@action(
    name="list_discord_stickers",
    description="List custom stickers in a guild.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_stickers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "list_guild_stickers", guild_id=input_data["guild_id"]
    )


@action(
    name="list_discord_scheduled_events",
    description="List scheduled events in a guild.",
    action_sets=["discord_guild", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "with_user_count": {
            "type": "boolean",
            "description": "Include RSVP counts.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_scheduled_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "list_scheduled_events",
        guild_id=input_data["guild_id"],
        with_user_count=bool(input_data.get("with_user_count", False)),
    )


@action(
    name="create_discord_scheduled_event",
    description="Create a scheduled event. entity_type: 1=stage, 2=voice, 3=external. For external, provide entity_metadata={'location':'...'} and scheduled_end_time.",
    action_sets=["discord_guild", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "name": {"type": "string", "description": "Event name.", "example": ""},
        "scheduled_start_time": {
            "type": "string",
            "description": "ISO 8601 start time.",
            "example": "",
        },
        "entity_type": {
            "type": "integer",
            "description": "1=stage, 2=voice, 3=external.",
            "example": 3,
        },
        "scheduled_end_time": {
            "type": "string",
            "description": "ISO 8601 end (required for external).",
            "example": "",
        },
        "channel_id": {
            "type": "string",
            "description": "Voice/stage channel ID (required for 1/2).",
            "example": "",
        },
        "entity_metadata": {
            "type": "object",
            "description": "{'location': '...'} for external events.",
            "example": {},
        },
        "description": {
            "type": "string",
            "description": "Event description (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_discord_scheduled_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "create_scheduled_event",
        guild_id=input_data["guild_id"],
        name=input_data["name"],
        scheduled_start_time=input_data["scheduled_start_time"],
        entity_type=input_data["entity_type"],
        scheduled_end_time=input_data.get("scheduled_end_time") or None,
        channel_id=input_data.get("channel_id") or None,
        entity_metadata=input_data.get("entity_metadata") or None,
        description=input_data.get("description") or None,
    )


@action(
    name="delete_discord_scheduled_event",
    description="Delete a scheduled event.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "event_id": {"type": "string", "description": "Event ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_discord_scheduled_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "delete_scheduled_event",
        guild_id=input_data["guild_id"],
        event_id=input_data["event_id"],
    )


@action(
    name="get_discord_audit_log",
    description="Get the guild audit log (mod actions). action_type filters: 1=guild_update, 10=channel_create, 11=channel_update, 12=channel_delete, 20=member_kick, 22=member_ban_add, 23=member_ban_remove, 25=member_update, 30=role_create, 72=message_delete (see Discord docs).",
    action_sets=["discord_guild", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "user_id": {
            "type": "string",
            "description": "Filter by user who triggered (optional).",
            "example": "",
        },
        "action_type": {
            "type": "integer",
            "description": "Filter by action type code (optional).",
            "example": 0,
        },
        "before": {
            "type": "string",
            "description": "Pagination: entry ID.",
            "example": "",
        },
        "limit": {"type": "integer", "description": "1-100.", "example": 50},
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw audit log incl. users[]/webhooks[] side tables (default false = lean entries).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {audit_log_entries: [{id, action_type, user_id, target_id, reason?, changes?: [{key, old?, new?}]}]}.",
        },
    },
)
def get_discord_audit_log(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    at = input_data.get("action_type")
    res = run_client_sync(
        "discord",
        "get_audit_log",
        guild_id=input_data["guild_id"],
        user_id=input_data.get("user_id") or None,
        action_type=at if at else None,
        before=input_data.get("before") or None,
        limit=input_data.get("limit", 50),
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict):
        return res
    lean = []
    for e in result.get("audit_log_entries", []):
        if not isinstance(e, dict):
            continue
        entry = {
            "id": e.get("id"),
            "action_type": e.get("action_type"),
            "user_id": e.get("user_id"),
            "target_id": e.get("target_id"),
        }
        if e.get("reason"):
            entry["reason"] = e.get("reason")
        changes = []
        for ch in e.get("changes") or []:
            if not isinstance(ch, dict):
                continue
            c = {"key": ch.get("key")}
            if "old_value" in ch:
                c["old"] = ch.get("old_value")
            if "new_value" in ch:
                c["new"] = ch.get("new_value")
            changes.append(c)
        if changes:
            entry["changes"] = changes
        lean.append(entry)
    return {**res, "result": {"audit_log_entries": lean}}


@action(
    name="list_discord_guild_invites",
    description="List all invites for a guild.",
    action_sets=["discord_guild"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_guild_invites(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "list_guild_invites", guild_id=input_data["guild_id"]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Users — bot user, user lookup, DMs
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="get_discord_user",
    description="Get info about any Discord user by ID.",
    action_sets=["discord_members", "discord"],
    input_schema={
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "get_user", user_id=input_data["user_id"])


@action(
    name="get_discord_bot_user",
    description="Get info about the authenticated Discord bot.",
    action_sets=["discord_guild", "discord"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_bot_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "get_bot_user")


@action(
    name="send_discord_dm",
    irreversible=True,
    description="Send a direct message to a Discord user.",
    action_sets=["discord_messages", "discord"],
    input_schema={
        "recipient_id": {
            "type": "string",
            "description": "Discord user ID to DM.",
            "example": "123456789012345678",
        },
        "content": {
            "type": "string",
            "description": "Message content.",
            "example": "Hey there!",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_discord_dm(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "send_dm",
        recipient_id=input_data["recipient_id"],
        content=input_data["content"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# User-account actions (self-bot / personal automation)
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="get_discord_user_account",
    description="Get info about the authenticated user account (selfbot/user token).",
    action_sets=["discord_user"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_user_account(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "user_get_current_user")


@action(
    name="send_discord_user_message",
    irreversible=True,
    description="Send user message (self-bot).",
    action_sets=["discord_user"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "Channel ID.",
            "example": "123",
        },
        "content": {"type": "string", "description": "Content.", "example": "Hi"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_discord_user_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "user_send_message",
        channel_id=input_data["channel_id"],
        content=input_data["content"],
    )


@action(
    name="get_discord_user_guilds",
    description="Get user guilds.",
    action_sets=["discord_user"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_user_guilds(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "user_get_guilds")


@action(
    name="get_discord_user_dm_channels",
    description="Get user DMs.",
    action_sets=["discord_user"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_user_dm_channels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "user_get_dm_channels")


@action(
    name="send_discord_user_dm",
    irreversible=True,
    description="Send user DM.",
    action_sets=["discord_user"],
    input_schema={
        "recipient_id": {
            "type": "string",
            "description": "Recipient ID.",
            "example": "123",
        },
        "content": {"type": "string", "description": "Content.", "example": "Hi"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_discord_user_dm(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "user_send_dm",
        recipient_id=input_data["recipient_id"],
        content=input_data["content"],
    )


@action(
    name="get_discord_user_relationships",
    description="Get the user account's friends/blocked/pending invitations (selfbot only).",
    action_sets=["discord_user"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_user_relationships(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "user_get_relationships")


@action(
    name="search_discord_guild_messages_as_user",
    description="Search messages in a guild (selfbot — uses user token's search permission). Lean flattened hits by default; include_metadata=true returns Discord's raw arrays-of-arrays.",
    action_sets=["discord_user"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": ""},
        "query": {"type": "string", "description": "Search content.", "example": ""},
        "limit": {"type": "integer", "description": "Max results.", "example": 25},
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw search result groups (default false = lean flattened hits).",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: {total_results, messages: [{id, channel_id, author: {id, username}, content, timestamp}]}.",
        },
    },
)
def search_discord_guild_messages_as_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "discord",
        "user_search_guild_messages",
        guild_id=input_data["guild_id"],
        query=input_data["query"],
        limit=input_data.get("limit", 25),
    )
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    result = res.get("result")
    if not isinstance(result, dict):
        return res
    hits = []
    for group in result.get("messages", []) or []:
        items = group if isinstance(group, list) else [group]
        items = [m for m in items if isinstance(m, dict)]
        marked = [m for m in items if m.get("hit")]
        for m in marked or items:
            a = m.get("author") or {}
            hits.append(
                {
                    "id": m.get("id"),
                    "channel_id": m.get("channel_id"),
                    "author": {"id": a.get("id"), "username": a.get("username")},
                    "content": m.get("content"),
                    "timestamp": m.get("timestamp"),
                }
            )
    return {
        **res,
        "result": {"total_results": result.get("total_results"), "messages": hits},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Voice (async — lazy-loads discord.py voice helpers)
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="join_discord_voice_channel",
    description="Join voice channel.",
    action_sets=["discord_voice", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": "123"},
        "channel_id": {
            "type": "string",
            "description": "Channel ID.",
            "example": "456",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def join_discord_voice_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "discord",
        "join_voice",
        guild_id=input_data["guild_id"],
        channel_id=input_data["channel_id"],
    )


@action(
    name="leave_discord_voice_channel",
    description="Leave voice channel.",
    action_sets=["discord_voice", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": "123"}
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def leave_discord_voice_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("discord", "leave_voice", guild_id=input_data["guild_id"])


@action(
    name="speak_discord_voice_tts",
    description="Speak TTS in voice.",
    action_sets=["discord_voice", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": "123"},
        "text": {"type": "string", "description": "Text.", "example": "Hello"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def speak_discord_voice_tts(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "discord",
        "speak_tts",
        guild_id=input_data["guild_id"],
        text=input_data["text"],
    )


@action(
    name="get_discord_voice_status",
    description="Get voice status.",
    action_sets=["discord_voice", "discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": "123"}
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_voice_status(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "get_voice_status", guild_id=input_data["guild_id"]
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Application commands (slash commands) / interactions / components
#     Requires a paired Events API / Gateway interaction handler to receive
#     button clicks and command invocations. Not actionable from a one-shot
#     agent loop without persistent event subscription plumbing.
# - Gateway events (MESSAGE_REACTION_ADD, TYPING_START, PRESENCE_UPDATE, etc.)
#     Handled by the listener internally.
# - Voice receive / recording / per-user voice state queries
#     Heavy WebSocket-bound work; the voice manager exposes only the
#     play/stop surface that fits a request-response model.
# - Stage instances (live stage management)
#     Niche; create_discord_scheduled_event covers the "schedule a stage" path.
# - OAuth2 application authorization endpoints, application/team admin
#     Developer-portal admin, not personal-agent work.
# - Polls (create/end), Soundboard
#     Newer features in flux; add when stable.
# - Guild widget / vanity URL / preview / discovery
#     Public-facing server-discovery configuration; niche.
# - Auto-moderation rules
#     Server-admin-level configuration; out of scope for a generalist agent.
