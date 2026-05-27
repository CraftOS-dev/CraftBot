# Discord — Integration Reference

Bot integration for messages, threads, reactions, voice, moderation. Talks to Discord's REST + Gateway via a bot token.

## Essentials

- **Send target format matters and varies by action:** `send_discord_message` uses `to: "channel:<id>"` for channels and `to: "user:<id>"` for DMs. Other actions (`add_discord_reaction`, `get_discord_messages`, `editMessage`) take `channelId` directly. Don't mix the two — passing a raw channel ID to `send_discord_message`'s `to` will fail silently or hit the wrong target.
- **Channel IDs are 18-digit snowflakes** (numeric strings, NOT names). Use `list_discord_guilds` then `get_discord_channels` to translate a channel name to its ID before sending.
- **DMs require a known DM channel ID,** not a user ID directly. Use `get_discord_user_dm_channels` to look one up, or `send_discord_dm`/`send_discord_user_dm` which handle the lookup internally.
- **Before asking the user for guildId/channelId**, call `list_discord_guilds` to see what servers the bot is in, then `get_discord_channels` to resolve channel names.
- **Session-level facts the integration knows:** `bot_id`, `bot_username`. Use introspection rather than asking the user.
- **`mention_only=True` config:** if set, the bot only processes incoming messages where it is @-mentioned. If incoming events aren't arriving, check this flag.
- **Permissions:** Discord enforces per-channel perms server-side. A `Missing Access` error means the bot isn't in the guild or lacks scopes — direct the user to the OAuth invite URL. Retrying won't help.
- **Routing replies:** Match the source. A message described as "in channel #&lt;id&gt;" came from a server channel — reply with `send_discord_message` using that `channel_id`. A message described as "via DM" came from a private DM — reply with `send_discord_dm` (or `send_discord_user_dm`) using the sender's user ID as `recipient_id`. Never DM a user who wrote in a server channel.