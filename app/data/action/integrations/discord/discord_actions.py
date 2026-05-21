from agent_core import action


# ═══════════════════════════════════════════════════════════════════════════════
# Bot actions (sync REST methods)
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="send_discord_message",
    description="Send a message to a Discord channel.",
    action_sets=["discord"],
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
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_discord_message(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "bot_send_message",
        channel_id=input_data["channel_id"],
        content=input_data["content"],
    )


@action(
    name="get_discord_messages",
    description="Get messages from a Discord channel.",
    action_sets=["discord"],
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
    )


@action(
    name="list_discord_guilds",
    description="List Discord guilds (servers) the bot is in.",
    action_sets=["discord"],
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
    name="get_discord_channels",
    description="Get all channels in a Discord guild.",
    action_sets=["discord"],
    input_schema={
        "guild_id": {
            "type": "string",
            "description": "Discord guild (server) ID.",
            "example": "123456789012345678",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_channels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord", "get_guild_channels", guild_id=input_data["guild_id"]
    )


@action(
    name="send_discord_dm",
    description="Send a direct message to a Discord user.",
    action_sets=["discord"],
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
)
def send_discord_dm(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "send_dm",
        recipient_id=input_data["recipient_id"],
        content=input_data["content"],
    )


@action(
    name="list_discord_guild_members",
    description="List guild members.",
    action_sets=["discord"],
    input_schema={
        "guild_id": {
            "type": "string",
            "description": "Guild ID.",
            "example": "123456789012345678",
        },
        "limit": {"type": "integer", "description": "Limit.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_discord_guild_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "list_guild_members",
        guild_id=input_data["guild_id"],
        limit=input_data.get("limit", 100),
    )


@action(
    name="add_discord_reaction",
    description="Add reaction.",
    action_sets=["discord"],
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
        "emoji": {"type": "string", "description": "Emoji.", "example": "👍"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
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


# ═══════════════════════════════════════════════════════════════════════════════
# User-account actions (self-bot / personal automation)
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="send_discord_user_message",
    description="Send user message (self-bot).",
    action_sets=["discord"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "Channel ID.",
            "example": "123",
        },
        "content": {"type": "string", "description": "Content.", "example": "Hi"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
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
    action_sets=["discord"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_user_guilds(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "user_get_guilds")


@action(
    name="get_discord_user_dm_channels",
    description="Get user DMs.",
    action_sets=["discord"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_discord_user_dm_channels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("discord", "user_get_dm_channels")


@action(
    name="send_discord_user_dm",
    description="Send user DM.",
    action_sets=["discord"],
    input_schema={
        "recipient_id": {
            "type": "string",
            "description": "Recipient ID.",
            "example": "123",
        },
        "content": {"type": "string", "description": "Content.", "example": "Hi"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_discord_user_dm(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "discord",
        "user_send_dm",
        recipient_id=input_data["recipient_id"],
        content=input_data["content"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Voice actions (async — lazy-loads discord.py voice helpers)
# ═══════════════════════════════════════════════════════════════════════════════


@action(
    name="join_discord_voice_channel",
    description="Join voice channel.",
    action_sets=["discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": "123"},
        "channel_id": {
            "type": "string",
            "description": "Channel ID.",
            "example": "456",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
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
    action_sets=["discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": "123"}
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def leave_discord_voice_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("discord", "leave_voice", guild_id=input_data["guild_id"])


@action(
    name="speak_discord_voice_tts",
    description="Speak TTS in voice.",
    action_sets=["discord"],
    input_schema={
        "guild_id": {"type": "string", "description": "Guild ID.", "example": "123"},
        "text": {"type": "string", "description": "Text.", "example": "Hello"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
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
    action_sets=["discord"],
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
