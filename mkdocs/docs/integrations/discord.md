# Discord

The Discord integration connects the agent to a Discord bot with a bot token. The agent can send and manage messages, reactions, and threads, create and edit channels, manage guild members, roles, invites, emojis, scheduled events, and webhooks, read the audit log, join voice channels to speak, and act through an optional user account. A Gateway listener turns incoming messages into events the agent reacts to.

## Requirements

| Requirement | Details |
|---|---|
| Discord account | Used to create the application and bot |
| Bot token | Created in the Developer Portal on the Bot tab |
| Message Content Intent | The privileged intent that lets the bot read message text; enabled in the portal |
| Bot invited to a server | The bot must be added to each guild it operates in, through the OAuth invite URL |
| `OPENAI_API_KEY` (optional) | Only for voice speech-to-text and text-to-speech |
| Network access | CraftBot calls `discord.com` over HTTPS and connects to the Gateway over WebSocket |

## Setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Open the **Bot** tab, then click **Reset Token** (or **Copy**) to get the bot token.
3. On the same tab, enable **Message Content Intent** under Privileged Gateway Intents. Without it the bot receives events with empty message text.
4. Invite the bot to your server using the OAuth2 URL generator, granting the scopes and channel permissions it needs.
5. In CraftBot, open **Settings → Integrations → Discord**, paste the token into **Bot Token**, and connect. From chat, `/discord login <bot_token>` does the same thing.
6. Verify with `/discord status`. It shows the connected bot username and ID.

`/discord logout` removes the credential and stops the listener.

## How it connects

**Authentication.** REST calls send the bot token as a `Bot` authorization header to `discord.com/api`. At login CraftBot validates the token against the bot's own user profile and stores the token, bot ID, and username in the credential store as `discord.json`. See [Credentials](credentials.md).

**Gateway listener.** While connected, CraftBot opens a WebSocket to the Discord Gateway, identifies with the guild-messages, direct-messages, and message-content intents, and keeps the connection alive with heartbeats. It waits about two seconds after the ready handshake before dispatching, so messages sent before the bot came online do not replay. Messages from bots and from the bot itself are ignored, and only messages that carry text are forwarded. If the socket drops, the listener reconnects after five seconds.

**Message filtering.** Two config tiers decide what reaches the agent. If **mention_only** is on, a message must @-mention the bot. Allowlists then classify each sender: a **self** match is treated as if the bot owner sent it, a **third-party** match is treated as external chatter, and if any list is configured but the sender matches none, the message is dropped. With all four lists empty, every message is treated as third-party. See [Configuration](#configuration).

**Identity formats.** Channel, guild, user, and message IDs are numeric snowflakes, not names. Translate a channel name to its ID with `list_discord_guilds` and `get_discord_channels` before sending. To DM a user, `send_discord_dm` resolves the DM channel from the user ID for you.

**Replies.** When the agent responds to a Discord event, it posts a message back to the originating channel.

## What the agent can do

The 80 Discord actions are grouped into action sets (`discord_messages`, `discord_threads`, `discord_channels`, `discord_members`, `discord_guild`, `discord_voice`, `discord_user`) that the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Messages and reactions

| Action | Purpose |
|---|---|
| `send_discord_message` | Send a message to a Discord channel |
| `edit_discord_message` | Edit a message the bot sent (bots can only edit their own) |
| `delete_discord_message` | Delete a Discord message |
| `bulk_delete_discord_messages` | Delete 2 to 100 messages at once (all under 14 days old) |
| `crosspost_discord_message` | Publish an announcement-channel message to following servers |
| `get_discord_messages` | Get messages from a Discord channel |
| `pin_discord_message` | Pin a message in a channel |
| `unpin_discord_message` | Unpin a message from a channel |
| `list_discord_pinned_messages` | List pinned messages in a channel |
| `add_discord_reaction` | Add a reaction emoji to a message |
| `remove_discord_own_reaction` | Remove the bot's own reaction from a message |
| `remove_discord_user_reaction` | Remove a specific user's reaction (mod action) |
| `list_discord_reaction_users` | List users who reacted with a specific emoji |
| `clear_discord_reactions` | Clear all reactions on a message, or just one emoji's |

### Threads

| Action | Purpose |
|---|---|
| `create_discord_thread_from_message` | Create a thread anchored to an existing message |
| `create_discord_thread` | Create a thread with no starter message |
| `join_discord_thread` | Join a thread as the bot |
| `leave_discord_thread` | Leave a thread |
| `add_discord_thread_member` | Add a user to a thread |
| `remove_discord_thread_member` | Remove a user from a thread |
| `list_discord_thread_members` | List members of a thread |
| `list_discord_active_threads` | List active, non-archived threads in a guild |
| `archive_discord_thread` | Archive a thread, closing it to new messages |
| `unarchive_discord_thread` | Unarchive a previously archived thread |

### Channels and invites

| Action | Purpose |
|---|---|
| `get_discord_channels` | Get all channels in a guild |
| `get_discord_channel` | Get info about a single channel |
| `create_discord_channel` | Create a channel in a guild (text, voice, category, forum, and so on) |
| `modify_discord_channel` | Edit a channel's name, topic, slowmode, category, or NSFW flag |
| `delete_discord_channel` | Delete a channel |
| `set_discord_channel_permissions` | Set permission overwrites for a role or member on a channel |
| `delete_discord_channel_permission` | Remove a permission overwrite from a channel |
| `list_discord_channel_invites` | List invite codes for a channel |
| `create_discord_invite` | Create an invite for a channel |
| `delete_discord_invite` | Delete (revoke) an invite code |

### Webhooks

| Action | Purpose |
|---|---|
| `list_discord_webhooks` | List webhooks in a channel (the token is never returned) |
| `create_discord_webhook` | Create a webhook on a channel, returning its ID and token |
| `get_discord_webhook` | Get a webhook by ID |
| `modify_discord_webhook` | Edit a webhook's name, avatar, or channel |
| `delete_discord_webhook` | Delete a webhook |
| `execute_discord_webhook` | Post a message through a webhook using its token |

### Members and moderation

| Action | Purpose |
|---|---|
| `list_discord_guild_members` | List members of a guild |
| `get_discord_guild_member` | Get a single guild member with roles and join date |
| `search_discord_guild_members` | Search members by username or nickname prefix |
| `modify_discord_guild_member` | Set a member's nickname, roles, voice mute or deafen, voice channel, or timeout |
| `set_discord_bot_nickname` | Set the bot's own nickname in a guild |
| `add_discord_member_role` | Assign a role to a member |
| `remove_discord_member_role` | Remove a role from a member |
| `kick_discord_member` | Kick a user from a guild (they can rejoin via invite) |
| `ban_discord_member` | Ban a user, optionally wiping their recent messages |
| `unban_discord_member` | Lift a ban on a user |
| `list_discord_bans` | List bans in a guild |

### Guilds, roles, emojis, and events

| Action | Purpose |
|---|---|
| `list_discord_guilds` | List the guilds (servers) the bot is in |
| `get_discord_guild` | Get info about a guild |
| `list_discord_guild_roles` | List roles in a guild |
| `create_discord_role` | Create a role with permissions, color, and flags |
| `modify_discord_role` | Edit a role's name, permissions, color, hoist, or mentionable flag |
| `delete_discord_role` | Delete a role |
| `list_discord_emojis` | List custom emojis in a guild |
| `create_discord_emoji` | Create a custom emoji from a data URI |
| `delete_discord_emoji` | Delete a custom emoji |
| `list_discord_stickers` | List custom stickers in a guild |
| `list_discord_scheduled_events` | List scheduled events in a guild |
| `create_discord_scheduled_event` | Create a scheduled event (stage, voice, or external) |
| `delete_discord_scheduled_event` | Delete a scheduled event |
| `get_discord_audit_log` | Get the guild audit log of moderation actions |
| `list_discord_guild_invites` | List all invites for a guild |
| `get_discord_bot_user` | Get info about the authenticated bot |

### Users and DMs

| Action | Purpose |
|---|---|
| `get_discord_user` | Get info about any user by ID |
| `send_discord_dm` | Send a direct message to a user |

### Voice

| Action | Purpose |
|---|---|
| `join_discord_voice_channel` | Join a voice channel |
| `leave_discord_voice_channel` | Leave a voice channel |
| `speak_discord_voice_tts` | Speak text as text-to-speech in the joined voice channel |
| `get_discord_voice_status` | Get the current voice connection status |

### User account (self-bot)

These actions use a Discord user token stored on the credential rather than the bot token. They are optional and only work when a `user_token` is present in `discord.json`.

| Action | Purpose |
|---|---|
| `get_discord_user_account` | Get info about the authenticated user account |
| `send_discord_user_message` | Send a message as the user account |
| `get_discord_user_guilds` | List the user account's guilds |
| `get_discord_user_dm_channels` | List the user account's DM channels |
| `send_discord_user_dm` | Send a DM as the user account |
| `get_discord_user_relationships` | Get the user account's friends, blocks, and pending invites |
| `search_discord_guild_messages_as_user` | Search messages in a guild with the user account's search |

## Example requests

```
Post "release is live" in the #announcements channel of my server.
```

```
Read the last 50 messages in #support and summarize the open questions.
```

```
Create a thread on the pinned roadmap message called "Q3 planning" and invite the design lead.
```

```
Give the Contributor role to everyone who reacted with the rocket emoji on message 987654321.
```

```
Timeout the user who is spamming #general for 10 minutes and log why in the audit trail.
```

```
Only react to Discord messages that @-mention the bot, and treat messages from the Admin role as if I sent them.
```

## Configuration

These settings live in **Settings → Integrations → Discord** and are stored in `discord_config.json` next to the credential. The listener re-reads them on every incoming message, so changes apply without reconnecting. Role names are matched against the message's guild and cached for ten minutes.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Only when @-mentioned (`mention_only`) | checkbox | off | When on, only messages that @-mention the bot are forwarded |
| Third-party users (`third_party_usernames`) | list | empty | Usernames or display names whose messages reach the agent as external chatter |
| Third-party roles (`third_party_role_names`) | list | empty | Guild role names whose members' messages reach the agent as external chatter (ignored in DMs) |
| Self users (`self_usernames`) | list | empty | Usernames whose messages are treated as if the bot owner sent them; self matches win over third-party |
| Self roles (`self_role_names`) | list | empty | Role names whose members are treated as the owner (ignored in DMs) |

With all four lists empty, the filter is fully open and every message is treated as third-party.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Invalid bot token" at login | Token is wrong or was reset | Reset the token in the Developer Portal Bot tab and run `/discord login <token>` |
| Bot sends messages but incoming events have no text | Message Content Intent is off | Enable Message Content Intent in the portal, then reconnect |
| "Missing Access" on a channel | The bot is not in the guild or lacks channel permissions | Invite the bot with the OAuth URL and grant read and write in the channel. Retrying does not help |
| No incoming events arrive at all | `mention_only` is on, or an allowlist excludes the senders | Check the config in **Settings → Integrations → Discord** |
| A message right after startup is ignored | The listener drops events until the ready handshake settles | Send again after the bot finishes connecting |
| Voice actions fail | Voice dependencies or `OPENAI_API_KEY` are missing | Install the voice extras and FFmpeg, and set `OPENAI_API_KEY` for speech |
| A `discord_user` action reports no user token | No `user_token` is stored on the credential | These self-bot actions are optional; connect with a bot token for normal use |

## Next

- [Telegram (Bot)](telegram-bot.md): another chat integration with a token login and a message listener
- [Credentials](credentials.md): where the bot token is stored and how `/cred status` reports it
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
