# Discord — Integration Reference

Bot integration for messages, threads, reactions, voice, moderation. Talks to Discord's REST + Gateway via a bot token.

## Essentials

- **`send_discord_message` takes `channel_id`: a bare numeric channel snowflake** (e.g. `1234567890123456789`). Never wrap it in a prefix like `"channel:<id>"` — no such format exists. All channel-taking actions (`send_discord_message`, `add_discord_reaction`, `get_discord_messages`, `edit_discord_message`) take the same bare `channel_id`.
- **A server (guild) ID is NOT a channel ID.** Both are near-identical ~19-digit snowflakes; sending to a guild ID fails with Unknown Channel. Always translate first: `list_discord_guilds` → `get_discord_channels(guild_id)` → pick a text channel's `id` → send. To post in ALL connected servers, do this once per guild — exactly one send per guild, then stop; the send result names the channel and server it landed in, so check it before sending again.
- **DMs require a known DM channel ID,** not a user ID directly. Use `get_discord_user_dm_channels` to look one up, or `send_discord_dm`/`send_discord_user_dm` which handle the lookup internally.
- **Session-level facts the integration knows:** `bot_id`, `bot_username`. Use introspection rather than asking the user.
- **`mention_only=True` config:** if set, the bot only processes incoming messages where it is @-mentioned. If incoming events aren't arriving, check this flag.
- **Permissions:** Discord enforces per-channel perms server-side. A `Missing Access` error means the bot isn't in the guild or lacks scopes — direct the user to the OAuth invite URL. Retrying won't help.
