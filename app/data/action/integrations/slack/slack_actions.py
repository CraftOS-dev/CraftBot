from agent_core import action


# ------------------------------------------------------------------
# Messages — post / update / delete / ephemeral / schedule / permalink / threads
# ------------------------------------------------------------------


@action(
    name="send_slack_message",
    description="Send a message to a Slack channel or DM. Pass thread_ts to reply in a thread.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID or name.",
            "example": "C01234567",
        },
        "text": {
            "type": "string",
            "description": "Message text.",
            "example": "Hello team!",
        },
        "thread_ts": {
            "type": "string",
            "description": "Optional thread timestamp for replies.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_slack_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "slack",
        "send_message",
        recipient=input_data["channel"],
        text=input_data["text"],
        thread_ts=input_data.get("thread_ts"),
    )


@action(
    name="update_slack_message",
    description="Edit a previously-sent Slack message. ts is the timestamp returned when posting.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "ts": {
            "type": "string",
            "description": "Timestamp of the message to edit.",
            "example": "1234567890.123456",
        },
        "text": {
            "type": "string",
            "description": "New text (optional).",
            "example": "",
        },
        "blocks": {
            "type": "array",
            "description": "New Block Kit blocks (optional).",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_slack_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "update_message",
        channel=input_data["channel"],
        ts=input_data["ts"],
        text=input_data["text"] if "text" in input_data else None,
        blocks=input_data["blocks"] if "blocks" in input_data else None,
    )


@action(
    name="delete_slack_message",
    description="Delete a Slack message.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "ts": {"type": "string", "description": "Message timestamp.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_slack_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "delete_message",
        channel=input_data["channel"],
        ts=input_data["ts"],
    )


@action(
    name="send_slack_ephemeral",
    description="Send an ephemeral message visible only to one user in a channel.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "user": {
            "type": "string",
            "description": "User ID who will see the message.",
            "example": "U12345",
        },
        "text": {"type": "string", "description": "Message text.", "example": ""},
        "blocks": {
            "type": "array",
            "description": "Block Kit blocks (optional).",
            "example": [],
        },
        "thread_ts": {
            "type": "string",
            "description": "Reply in a thread (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_slack_ephemeral(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "post_ephemeral",
        channel=input_data["channel"],
        user=input_data["user"],
        text=input_data["text"],
        blocks=input_data["blocks"] if "blocks" in input_data else None,
        thread_ts=input_data.get("thread_ts") or None,
    )


@action(
    name="schedule_slack_message",
    description="Schedule a Slack message to be sent at a future time. post_at is a Unix timestamp.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "post_at": {
            "type": "integer",
            "description": "Unix timestamp when to send.",
            "example": 0,
        },
        "text": {"type": "string", "description": "Message text.", "example": ""},
        "blocks": {
            "type": "array",
            "description": "Block Kit blocks (optional).",
            "example": [],
        },
        "thread_ts": {
            "type": "string",
            "description": "Optional thread reply.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def schedule_slack_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "schedule_message",
        channel=input_data["channel"],
        post_at=input_data["post_at"],
        text=input_data["text"],
        blocks=input_data["blocks"] if "blocks" in input_data else None,
        thread_ts=input_data.get("thread_ts") or None,
    )


@action(
    name="delete_scheduled_slack_message",
    description="Cancel a previously-scheduled Slack message.",
    action_sets=["slack_messages"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "scheduled_message_id": {
            "type": "string",
            "description": "Scheduled message ID (from schedule_slack_message response).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_scheduled_slack_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "delete_scheduled_message",
        channel=input_data["channel"],
        scheduled_message_id=input_data["scheduled_message_id"],
    )


@action(
    name="list_scheduled_slack_messages",
    description="List the bot's pending scheduled messages.",
    action_sets=["slack_messages"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Filter to one channel (optional).",
            "example": "",
        },
        "limit": {"type": "integer", "description": "Max results.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_scheduled_slack_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "list_scheduled_messages",
        channel=input_data.get("channel") or None,
        limit=input_data.get("limit", 100),
    )


@action(
    name="get_slack_message_permalink",
    description="Get a shareable permalink URL for a Slack message.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "message_ts": {
            "type": "string",
            "description": "Message timestamp.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_message_permalink(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "get_permalink",
        channel=input_data["channel"],
        message_ts=input_data["message_ts"],
    )


@action(
    name="get_slack_thread_replies",
    description="Get all messages in a Slack thread (the parent + all replies).",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "ts": {
            "type": "string",
            "description": "Parent message timestamp (thread_ts).",
            "example": "",
        },
        "limit": {"type": "integer", "description": "Max messages.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_thread_replies(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "get_thread_replies",
        channel=input_data["channel"],
        ts=input_data["ts"],
        limit=input_data.get("limit", 100),
    )


# ----- Reactions -----


@action(
    name="add_slack_reaction",
    description="Add an emoji reaction to a Slack message. name is the emoji code without colons (e.g. 'thumbsup', 'eyes').",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "timestamp": {
            "type": "string",
            "description": "Message timestamp.",
            "example": "",
        },
        "name": {
            "type": "string",
            "description": "Emoji name without colons.",
            "example": "thumbsup",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_slack_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "add_reaction",
        channel=input_data["channel"],
        timestamp=input_data["timestamp"],
        name=input_data["name"],
    )


@action(
    name="remove_slack_reaction",
    description="Remove an emoji reaction from a Slack message.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "timestamp": {
            "type": "string",
            "description": "Message timestamp.",
            "example": "",
        },
        "name": {
            "type": "string",
            "description": "Emoji name without colons.",
            "example": "thumbsup",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def remove_slack_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "remove_reaction",
        channel=input_data["channel"],
        timestamp=input_data["timestamp"],
        name=input_data["name"],
    )


@action(
    name="get_slack_reactions",
    description="Get all reactions on a Slack message.",
    action_sets=["slack_messages"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "timestamp": {
            "type": "string",
            "description": "Message timestamp.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_reactions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "get_reactions",
        channel=input_data["channel"],
        timestamp=input_data["timestamp"],
    )


@action(
    name="list_slack_user_reactions",
    description="List messages a user has reacted to.",
    action_sets=["slack_messages"],
    input_schema={
        "user": {
            "type": "string",
            "description": "User ID (optional, defaults to auth'd user).",
            "example": "",
        },
        "count": {"type": "integer", "description": "Max results.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_user_reactions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "list_user_reactions",
        user=input_data.get("user") or None,
        count=input_data.get("count", 100),
    )


# ----- Pins -----


@action(
    name="pin_slack_message",
    description="Pin a message to a Slack channel.",
    action_sets=["slack_messages", "slack"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "timestamp": {
            "type": "string",
            "description": "Message timestamp.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def pin_slack_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "pin_message",
        channel=input_data["channel"],
        timestamp=input_data["timestamp"],
    )


@action(
    name="unpin_slack_message",
    description="Unpin a message from a Slack channel.",
    action_sets=["slack_messages"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "timestamp": {
            "type": "string",
            "description": "Message timestamp.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unpin_slack_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "unpin_message",
        channel=input_data["channel"],
        timestamp=input_data["timestamp"],
    )


@action(
    name="list_slack_pins",
    description="List pinned items in a Slack channel.",
    action_sets=["slack_messages"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_pins(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "list_pins", channel=input_data["channel"])


# ------------------------------------------------------------------
# Conversations — list/info/create/invite/open/archive/rename/topic/members
# ------------------------------------------------------------------


@action(
    name="list_slack_channels",
    description="List channels in the Slack workspace.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max channels to return.",
            "example": 100,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "channels": {"type": "array"},
    },
)
def list_slack_channels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "list_channels", limit=input_data.get("limit", 100))


@action(
    name="get_slack_channel_info",
    description="Get info about a Slack channel.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C1234567",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_channel_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "get_channel_info", channel=input_data["channel"])


@action(
    name="get_slack_channel_history",
    description="Get message history from a Slack channel.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C01234567",
        },
        "limit": {"type": "integer", "description": "Max messages.", "example": 50},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "messages": {"type": "array"},
    },
)
def get_slack_channel_history(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "get_channel_history",
        channel=input_data["channel"],
        limit=input_data.get("limit", 50),
    )


@action(
    name="list_slack_channel_members",
    description="List members of a Slack channel.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "limit": {"type": "integer", "description": "Max members.", "example": 100},
        "cursor": {
            "type": "string",
            "description": "Pagination cursor.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_channel_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "list_channel_members",
        channel=input_data["channel"],
        limit=input_data.get("limit", 100),
        cursor=input_data.get("cursor") or None,
    )


@action(
    name="create_slack_channel",
    description="Create a new Slack channel.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Channel name.",
            "example": "project-alpha",
        },
        "is_private": {
            "type": "boolean",
            "description": "Is private?",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "create_channel",
        name=input_data["name"],
        is_private=input_data.get("is_private", False),
    )


@action(
    name="invite_to_slack_channel",
    description="Invite users to a Slack channel.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Channel ID.",
            "example": "C1234567",
        },
        "users": {
            "type": "array",
            "description": "List of user IDs.",
            "example": ["U123"],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def invite_to_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "invite_to_channel",
        channel=input_data["channel"],
        users=input_data["users"],
    )


@action(
    name="open_slack_dm",
    description="Open a DM with Slack users.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "users": {
            "type": "array",
            "description": "List of user IDs.",
            "example": ["U123"],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def open_slack_dm(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "open_dm", users=input_data["users"])


@action(
    name="archive_slack_channel",
    description="Archive a Slack channel.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def archive_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "archive_channel", channel=input_data["channel"])


@action(
    name="unarchive_slack_channel",
    description="Unarchive a previously-archived Slack channel.",
    action_sets=["slack_conversations"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unarchive_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "unarchive_channel", channel=input_data["channel"])


@action(
    name="rename_slack_channel",
    description="Rename a Slack channel.",
    action_sets=["slack_conversations"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "name": {"type": "string", "description": "New channel name.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def rename_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "rename_channel",
        channel=input_data["channel"],
        name=input_data["name"],
    )


@action(
    name="set_slack_channel_topic",
    description="Set a Slack channel's topic.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "topic": {"type": "string", "description": "New topic.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_slack_channel_topic(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "set_channel_topic",
        channel=input_data["channel"],
        topic=input_data["topic"],
    )


@action(
    name="set_slack_channel_purpose",
    description="Set a Slack channel's purpose / description.",
    action_sets=["slack_conversations"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "purpose": {"type": "string", "description": "New purpose.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_slack_channel_purpose(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "set_channel_purpose",
        channel=input_data["channel"],
        purpose=input_data["purpose"],
    )


@action(
    name="join_slack_channel",
    description="Have the bot join a Slack channel.",
    action_sets=["slack_conversations", "slack"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def join_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "join_channel", channel=input_data["channel"])


@action(
    name="leave_slack_channel",
    description="Have the bot leave a Slack channel.",
    action_sets=["slack_conversations"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def leave_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "leave_channel", channel=input_data["channel"])


@action(
    name="kick_user_from_slack_channel",
    description="Remove a user from a Slack channel.",
    action_sets=["slack_conversations"],
    input_schema={
        "channel": {"type": "string", "description": "Channel ID.", "example": ""},
        "user": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def kick_user_from_slack_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "kick_user",
        channel=input_data["channel"],
        user=input_data["user"],
    )


@action(
    name="close_slack_conversation",
    description="Close a DM, MPDM, or private channel.",
    action_sets=["slack_conversations"],
    input_schema={
        "channel": {"type": "string", "description": "Conversation ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def close_slack_conversation(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "close_conversation", channel=input_data["channel"])


# ------------------------------------------------------------------
# Files
# ------------------------------------------------------------------


@action(
    name="upload_slack_file",
    description="Upload a local file to Slack using the modern 3-step files.getUploadURLExternal flow. Optionally share into a channel + post initial comment.",
    action_sets=["slack_files", "slack"],
    input_schema={
        "file_path": {
            "type": "string",
            "description": "Absolute path to local file.",
            "example": "C:/Users/me/report.pdf",
        },
        "channel_id": {
            "type": "string",
            "description": "Channel ID to share into (optional).",
            "example": "C01234567",
        },
        "initial_comment": {
            "type": "string",
            "description": "Message text with the file (optional).",
            "example": "",
        },
        "title": {
            "type": "string",
            "description": "File title (optional).",
            "example": "",
        },
        "thread_ts": {
            "type": "string",
            "description": "Reply in a thread (optional).",
            "example": "",
        },
        "filename": {
            "type": "string",
            "description": "Override filename (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def upload_slack_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "upload_file_v2",
        file_path=input_data["file_path"],
        channel_id=input_data.get("channel_id") or None,
        initial_comment=input_data.get("initial_comment") or None,
        title=input_data.get("title") or None,
        thread_ts=input_data.get("thread_ts") or None,
        filename=input_data.get("filename") or None,
    )


@action(
    name="list_slack_files",
    description="List files in the workspace (optionally filter by channel, user, or types like 'images,zips').",
    action_sets=["slack_files", "slack"],
    input_schema={
        "channel": {
            "type": "string",
            "description": "Filter to channel (optional).",
            "example": "",
        },
        "user": {
            "type": "string",
            "description": "Filter to user (optional).",
            "example": "",
        },
        "types": {
            "type": "string",
            "description": "Comma-separated types: all, spaces, snippets, images, gdocs, zips, pdfs (optional).",
            "example": "",
        },
        "count": {"type": "integer", "description": "Max results.", "example": 100},
        "page": {"type": "integer", "description": "Page number.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "list_files",
        channel=input_data.get("channel") or None,
        user=input_data.get("user") or None,
        types=input_data.get("types") or None,
        count=input_data.get("count", 100),
        page=input_data.get("page", 1),
    )


@action(
    name="get_slack_file_info",
    description="Get metadata for a Slack file (name, size, URL, channels shared into).",
    action_sets=["slack_files", "slack"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": "F0123ABC"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_file_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "get_file_info", file_id=input_data["file_id"])


@action(
    name="delete_slack_file",
    description="Delete a Slack file. Irreversible.",
    action_sets=["slack_files"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_slack_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "delete_file", file_id=input_data["file_id"])


# ------------------------------------------------------------------
# Users + usergroups + presence
# ------------------------------------------------------------------


@action(
    name="list_slack_users",
    description="List users in the Slack workspace.",
    action_sets=["slack_users", "slack"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max users to return.",
            "example": 100,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "users": {"type": "array"},
    },
)
def list_slack_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "list_users", limit=input_data.get("limit", 100))


@action(
    name="get_slack_user_info",
    description="Get info about a Slack user.",
    action_sets=["slack_users", "slack"],
    input_schema={
        "slack_user_id": {
            "type": "string",
            "description": "User ID.",
            "example": "U1234567",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_user_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "get_user_info", user_id=input_data["slack_user_id"]
    )


@action(
    name="lookup_slack_user_by_email",
    description="Resolve a Slack user by their email address.",
    action_sets=["slack_users", "slack"],
    input_schema={
        "email": {
            "type": "string",
            "description": "Email address.",
            "example": "alice@example.com",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def lookup_slack_user_by_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "lookup_user_by_email", email=input_data["email"])


@action(
    name="get_slack_user_presence",
    description="Check whether a Slack user is online (active) or offline (away).",
    action_sets=["slack_users"],
    input_schema={
        "user": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_user_presence(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "get_user_presence", user=input_data["user"])


@action(
    name="set_slack_user_presence",
    description="Set the authenticated user's presence (requires user token xoxp-, not bot token).",
    action_sets=["slack_users"],
    input_schema={
        "presence": {
            "type": "string",
            "description": "auto or away.",
            "example": "auto",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_slack_user_presence(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "set_user_presence", presence=input_data["presence"]
    )


@action(
    name="list_slack_usergroups",
    description="List Slack usergroups (@team mentions) in the workspace.",
    action_sets=["slack_users", "slack"],
    input_schema={
        "include_disabled": {
            "type": "boolean",
            "description": "Include disabled groups.",
            "example": False,
        },
        "include_count": {
            "type": "boolean",
            "description": "Include member counts.",
            "example": False,
        },
        "include_users": {
            "type": "boolean",
            "description": "Include user list per group.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_usergroups(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "list_usergroups",
        include_disabled=bool(input_data.get("include_disabled", False)),
        include_count=bool(input_data.get("include_count", False)),
        include_users=bool(input_data.get("include_users", False)),
    )


@action(
    name="create_slack_usergroup",
    description="Create a new Slack usergroup.",
    action_sets=["slack_users"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Group name (e.g. 'Marketing').",
            "example": "",
        },
        "handle": {
            "type": "string",
            "description": "Handle without @ (optional).",
            "example": "",
        },
        "description": {
            "type": "string",
            "description": "Description (optional).",
            "example": "",
        },
        "channels": {
            "type": "array",
            "description": "Default channels (optional).",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_slack_usergroup(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "create_usergroup",
        name=input_data["name"],
        handle=input_data.get("handle") or None,
        description=input_data.get("description") or None,
        channels=input_data.get("channels") or None,
    )


@action(
    name="update_slack_usergroup",
    description="Update a Slack usergroup's name/handle/description/channels.",
    action_sets=["slack_users"],
    input_schema={
        "usergroup": {"type": "string", "description": "Usergroup ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "handle": {
            "type": "string",
            "description": "New handle (optional).",
            "example": "",
        },
        "description": {
            "type": "string",
            "description": "New description (optional).",
            "example": "",
        },
        "channels": {
            "type": "array",
            "description": "New default channels (optional).",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_slack_usergroup(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "update_usergroup",
        usergroup=input_data["usergroup"],
        name=input_data["name"] if "name" in input_data else None,
        handle=input_data["handle"] if "handle" in input_data else None,
        description=input_data["description"] if "description" in input_data else None,
        channels=input_data["channels"] if "channels" in input_data else None,
    )


@action(
    name="list_slack_usergroup_users",
    description="List the users in a Slack usergroup.",
    action_sets=["slack_users"],
    input_schema={
        "usergroup": {"type": "string", "description": "Usergroup ID.", "example": ""},
        "include_disabled": {
            "type": "boolean",
            "description": "Include disabled users.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_usergroup_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "list_usergroup_users",
        usergroup=input_data["usergroup"],
        include_disabled=bool(input_data.get("include_disabled", False)),
    )


@action(
    name="set_slack_usergroup_users",
    description="REPLACE the members of a Slack usergroup.",
    action_sets=["slack_users"],
    input_schema={
        "usergroup": {"type": "string", "description": "Usergroup ID.", "example": ""},
        "users": {
            "type": "array",
            "description": "List of user IDs to set as members.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_slack_usergroup_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "update_usergroup_users",
        usergroup=input_data["usergroup"],
        users=input_data["users"],
    )


@action(
    name="enable_slack_usergroup",
    description="Enable a previously-disabled Slack usergroup.",
    action_sets=["slack_users"],
    input_schema={
        "usergroup": {"type": "string", "description": "Usergroup ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def enable_slack_usergroup(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "enable_usergroup", usergroup=input_data["usergroup"]
    )


@action(
    name="disable_slack_usergroup",
    description="Disable a Slack usergroup (keeps it but hides from autocomplete).",
    action_sets=["slack_users"],
    input_schema={
        "usergroup": {"type": "string", "description": "Usergroup ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def disable_slack_usergroup(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "disable_usergroup", usergroup=input_data["usergroup"]
    )


# ------------------------------------------------------------------
# Workspace: auth / team / search / bookmarks / reminders
# ------------------------------------------------------------------


@action(
    name="get_slack_auth_info",
    description="Get info about the authenticated Slack bot/user (team, user, bot_id).",
    action_sets=["slack_workspace", "slack"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_auth_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "auth_test")


@action(
    name="get_slack_team_info",
    description="Get info about the Slack workspace (team name, domain, icon).",
    action_sets=["slack_workspace", "slack"],
    input_schema={
        "team": {
            "type": "string",
            "description": "Team ID (optional, defaults to current).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_team_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "get_team_info", team=input_data.get("team") or None
    )


@action(
    name="search_slack_messages",
    description="Search for messages in the Slack workspace (requires user token / search:read).",
    action_sets=["slack_workspace", "slack"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Search query.",
            "example": "project update",
        },
        "count": {"type": "integer", "description": "Max results.", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_slack_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "search_messages",
        query=input_data["query"],
        count=input_data.get("count", 20),
    )


@action(
    name="list_slack_bookmarks",
    description="List bookmarks pinned to a Slack channel.",
    action_sets=["slack_workspace", "slack"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_bookmarks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "list_bookmarks", channel_id=input_data["channel_id"]
    )


@action(
    name="add_slack_bookmark",
    description="Add a bookmark to a Slack channel.",
    action_sets=["slack_workspace", "slack"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "title": {
            "type": "string",
            "description": "Bookmark title.",
            "example": "Project doc",
        },
        "type": {
            "type": "string",
            "description": "Bookmark type (link).",
            "example": "link",
        },
        "link": {
            "type": "string",
            "description": "URL (for type=link).",
            "example": "",
        },
        "emoji": {
            "type": "string",
            "description": "Emoji shortcode (optional).",
            "example": ":bookmark:",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_slack_bookmark(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "add_bookmark",
        channel_id=input_data["channel_id"],
        title=input_data["title"],
        type=input_data.get("type", "link"),
        link=input_data.get("link") or None,
        emoji=input_data.get("emoji") or None,
    )


@action(
    name="edit_slack_bookmark",
    description="Edit an existing channel bookmark.",
    action_sets=["slack_workspace"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "bookmark_id": {"type": "string", "description": "Bookmark ID.", "example": ""},
        "title": {
            "type": "string",
            "description": "New title (optional).",
            "example": "",
        },
        "link": {"type": "string", "description": "New URL (optional).", "example": ""},
        "emoji": {
            "type": "string",
            "description": "New emoji (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def edit_slack_bookmark(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "edit_bookmark",
        channel_id=input_data["channel_id"],
        bookmark_id=input_data["bookmark_id"],
        title=input_data["title"] if "title" in input_data else None,
        link=input_data["link"] if "link" in input_data else None,
        emoji=input_data["emoji"] if "emoji" in input_data else None,
    )


@action(
    name="remove_slack_bookmark",
    description="Delete a channel bookmark.",
    action_sets=["slack_workspace"],
    input_schema={
        "channel_id": {"type": "string", "description": "Channel ID.", "example": ""},
        "bookmark_id": {"type": "string", "description": "Bookmark ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def remove_slack_bookmark(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "remove_bookmark",
        channel_id=input_data["channel_id"],
        bookmark_id=input_data["bookmark_id"],
    )


@action(
    name="add_slack_reminder",
    description="Add a Slack reminder. time can be a Unix timestamp or natural-language ('in 15 minutes'). Requires user token (xoxp-) — bot tokens can't create reminders.",
    action_sets=["slack_workspace", "slack"],
    input_schema={
        "text": {
            "type": "string",
            "description": "Reminder text.",
            "example": "Send the weekly report",
        },
        "time": {
            "type": "string",
            "description": "Unix timestamp OR natural-language ('in 15 minutes').",
            "example": "in 15 minutes",
        },
        "user": {
            "type": "string",
            "description": "User ID (optional, defaults to self).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_slack_reminder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack",
        "add_reminder",
        text=input_data["text"],
        time=input_data["time"],
        user=input_data.get("user") or None,
    )


@action(
    name="list_slack_reminders",
    description="List the authenticated user's Slack reminders.",
    action_sets=["slack_workspace"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_slack_reminders(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "list_reminders")


@action(
    name="get_slack_reminder",
    description="Get info about a single Slack reminder.",
    action_sets=["slack_workspace"],
    input_schema={
        "reminder": {"type": "string", "description": "Reminder ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_slack_reminder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "get_reminder_info", reminder=input_data["reminder"]
    )


@action(
    name="complete_slack_reminder",
    description="Mark a Slack reminder as complete.",
    action_sets=["slack_workspace"],
    input_schema={
        "reminder": {"type": "string", "description": "Reminder ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def complete_slack_reminder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "slack", "complete_reminder", reminder=input_data["reminder"]
    )


@action(
    name="delete_slack_reminder",
    description="Delete a Slack reminder.",
    action_sets=["slack_workspace"],
    input_schema={
        "reminder": {"type": "string", "description": "Reminder ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_slack_reminder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("slack", "delete_reminder", reminder=input_data["reminder"])


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Events API subscriptions, RTM (deprecated), Socket Mode setup
#     Server-side event-receiving plumbing. The listener handles it internally.
# - views.* (modal/home/app views) and interactions.* (block button responses)
#     Interactive UI surface that requires a paired Events API endpoint to
#     handle callbacks. Not actionable from a one-shot agent loop.
# - canvases / lists (canvases.create/edit/listcategories, slackLists)
#     New Block Kit-adjacent surfaces; not stable enough across plans.
# - admin.* and scim
#     Enterprise Grid admin. Requires enterprise tokens.
# - apps.connections.open (Socket Mode tokens)
#     Realtime infrastructure.
# - dnd.* (Do-not-disturb)
#     User-token-only, rarely needed by an assistant.
# - migration.exchange / stars / dialog.* (deprecated)
#     Legacy surfaces.
# - chat.unfurl / link_shared
#     Event-driven; requires Events API loop.
