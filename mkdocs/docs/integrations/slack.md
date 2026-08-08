# Slack

The Slack integration connects the agent to a Slack workspace with a bot token. The agent can post and edit messages, manage channels and members, work with files, users, usergroups, bookmarks, and reminders, and search history. A polling listener turns new messages in channels the bot has joined into events the agent reacts to.

## Requirements

| Requirement | Details |
|---|---|
| Slack workspace | The agent acts as a bot user in this workspace |
| Bot token or app invite | Connect the shared CraftOS app by OAuth, or paste your own bot token (`xoxb-...`) |
| OAuth scopes | `chat:write`, `channels:read`, `channels:history`, `users:read`, `search:read`, `files:write` at minimum |
| User token (optional) | A `xoxp-...` token is required for search, presence, and reminder actions |
| Network access | CraftBot calls Slack's Web API over HTTPS |

## Setup

You can connect in two ways.

**Invite the shared app (fastest).**

1. Run `/slack invite`. CraftBot opens the OAuth flow for the shared CraftOS app.
2. Approve the install for your workspace. Slack redirects to `https://localhost:8765`, which serves a self-signed certificate, so click through the browser warning.
3. CraftBot stores the workspace-scoped bot token it receives from the install.

**Use your own bot token.**

1. Open [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App → From scratch**, then pick your workspace.
2. Under **OAuth & Permissions**, add the bot scopes `chat:write`, `channels:read`, `channels:history`, `users:read`, `search:read`, and `files:write`.
3. Click **Install to Workspace** at the top, then copy the **Bot User OAuth Token** (`xoxb-...`).
4. In CraftBot, open **Settings → Integrations → Slack**, paste the token, and connect. From chat, `/slack login <bot_token> [workspace_name]` does the same thing.
5. Verify with `/slack status`. It lists each connected workspace and its ID.

`/slack logout [workspace_id]` removes a workspace credential and stops its listener.

## How it connects

**Authentication.** Every API call sends the bot token as a bearer token to Slack's Web API. At login CraftBot calls `auth.test` to validate the token and resolve the workspace, then stores the token and workspace name in the credential store as `slack.json`. See [Credentials](credentials.md).

**Polling listener.** While connected, CraftBot polls every 3 seconds. It lists the conversations the bot belongs to (public channels, private channels, group DMs, and direct messages) and reads new messages since the last poll. On start it runs a catchup pass to record current timestamps so it does not replay old history. If a channel keeps returning `channel_not_found`, the listener drops it silently, so the bot only receives events from channels it has actually joined.

**Multi-account.** Each workspace is a separate credential keyed by workspace ID. Connect several with repeated `/slack login` calls, name each with the optional `workspace_name` argument, and `/slack status` lists them all. Remove one with `/slack logout <workspace_id>`.

## What the agent can do

The 60 Slack actions are grouped into action sets the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Messages

| Action | Purpose |
|---|---|
| `send_slack_message` | Send a message to a channel or DM; pass `thread_ts` to reply in a thread |
| `update_slack_message` | Edit a previously sent message |
| `delete_slack_message` | Delete a message |
| `send_slack_ephemeral` | Send an ephemeral message visible only to one user in a channel |
| `schedule_slack_message` | Schedule a message to be sent at a future Unix timestamp |
| `delete_scheduled_slack_message` | Cancel a previously scheduled message |
| `list_scheduled_slack_messages` | List the bot's pending scheduled messages |
| `get_slack_message_permalink` | Get a shareable permalink URL for a message |
| `get_slack_thread_replies` | Get all messages in a thread (the parent plus every reply) |

### Reactions

| Action | Purpose |
|---|---|
| `add_slack_reaction` | Add an emoji reaction to a message |
| `remove_slack_reaction` | Remove an emoji reaction from a message |
| `get_slack_reactions` | Get all reactions on a message |
| `list_slack_user_reactions` | List messages a user has reacted to |

### Pins

| Action | Purpose |
|---|---|
| `pin_slack_message` | Pin a message to a channel |
| `unpin_slack_message` | Unpin a message from a channel |
| `list_slack_pins` | List pinned items in a channel |

### Channels

| Action | Purpose |
|---|---|
| `list_slack_channels` | List channels in the workspace |
| `get_slack_channel_info` | Get info about a channel |
| `get_slack_channel_history` | Get message history from a channel |
| `list_slack_channel_members` | List members of a channel |
| `create_slack_channel` | Create a new channel |
| `invite_to_slack_channel` | Invite users to a channel |
| `archive_slack_channel` | Archive a channel |
| `unarchive_slack_channel` | Unarchive a previously archived channel |
| `rename_slack_channel` | Rename a channel |
| `set_slack_channel_topic` | Set a channel's topic |
| `set_slack_channel_purpose` | Set a channel's purpose or description |
| `join_slack_channel` | Have the bot join a channel |
| `leave_slack_channel` | Have the bot leave a channel |
| `kick_user_from_slack_channel` | Remove a user from a channel |
| `close_slack_conversation` | Close a DM, group DM, or private channel |

### Direct messages

| Action | Purpose |
|---|---|
| `open_slack_dm` | Open a DM with one or more users and return its channel ID |

### Files

| Action | Purpose |
|---|---|
| `upload_slack_file` | Upload a local file, optionally sharing it into a channel with an initial comment |
| `list_slack_files` | List files in the workspace, optionally filtered by channel, user, or type |
| `get_slack_file_info` | Get metadata for a file (name, size, URL, channels shared into) |
| `delete_slack_file` | Delete a file (irreversible) |

### Users

| Action | Purpose |
|---|---|
| `list_slack_users` | List users in the workspace |
| `get_slack_user_info` | Get info about a user |
| `lookup_slack_user_by_email` | Resolve a user by their email address |
| `get_slack_user_presence` | Check whether a user is online (active) or away |
| `set_slack_user_presence` | Set the authenticated user's presence (requires a `xoxp-` user token) |

### Usergroups

| Action | Purpose |
|---|---|
| `list_slack_usergroups` | List usergroups (`@team` mentions) in the workspace |
| `create_slack_usergroup` | Create a new usergroup |
| `update_slack_usergroup` | Update a usergroup's name, handle, description, or channels |
| `list_slack_usergroup_users` | List the users in a usergroup |
| `set_slack_usergroup_users` | Replace the members of a usergroup |
| `enable_slack_usergroup` | Enable a previously disabled usergroup |
| `disable_slack_usergroup` | Disable a usergroup, keeping it but hiding it from autocomplete |

### Workspace

| Action | Purpose |
|---|---|
| `get_slack_auth_info` | Get info about the authenticated bot or user (team, user, bot ID) |
| `get_slack_team_info` | Get info about the workspace (name, domain, icon) |

### Search

| Action | Purpose |
|---|---|
| `search_slack_messages` | Search for messages across the workspace (requires a user token with `search:read`) |

### Bookmarks

| Action | Purpose |
|---|---|
| `list_slack_bookmarks` | List bookmarks pinned to a channel |
| `add_slack_bookmark` | Add a bookmark to a channel |
| `edit_slack_bookmark` | Edit an existing channel bookmark |
| `remove_slack_bookmark` | Delete a channel bookmark |

### Reminders

| Action | Purpose |
|---|---|
| `add_slack_reminder` | Add a reminder at a timestamp or natural-language time (requires a user token) |
| `list_slack_reminders` | List the authenticated user's reminders |
| `get_slack_reminder` | Get info about a single reminder |
| `complete_slack_reminder` | Mark a reminder as complete |
| `delete_slack_reminder` | Delete a reminder |

## Example requests

```
Post "Deploy is live" to the #releases channel.
```

```
Summarize the last 50 messages in #support and DM me the result.
```

```
Create a private channel called incident-2026-07-18 and invite the on-call group.
```

```
Search Slack for messages mentioning "invoice bug" from the last week.
```

```
Upload report.pdf to #finance with the comment "Q2 numbers attached".
```

```
React with :eyes: to the latest message in #design and pin it.
```

## Configuration

Slack has no listener filters. The bot receives messages only from channels it has joined, so you control its reach by adding it to or removing it from channels. Credentials are stored per workspace in `slack.json`, and multiple workspaces coexist. Search, presence, and reminder actions need a user token (`xoxp-...`); connect one with `/slack login <xoxp_token>` if you use those actions.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `not_authed` or `invalid_auth` | The bot token is wrong, revoked, or reinstalled | Reinstall the app and run `/slack login <new_token>` |
| `channel_not_found` or `not_in_channel` | The bot is not a member of that channel | Invite the bot to the channel; retrying the same call does not help |
| Agent stops seeing messages from one channel | The listener dropped a channel that kept erroring | Confirm the bot is still a member of that channel |
| `missing_scope` on an action | The token lacks the scope that action needs | Add the scope under **OAuth & Permissions**, reinstall, and log in again |
| Search, presence, or reminders fail | Those actions require a user token, not a bot token | Connect a `xoxp-...` user token with the matching scope |
| OAuth redirect warning in the browser | Slack requires HTTPS and CraftBot serves a self-signed cert on `https://localhost:8765` | Click through the browser warning to finish the install |

## Next

- [Discord](discord.md): another chat platform with a message-based listener
- [Credentials](credentials.md): where tokens are stored and how `/cred status` reports them
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
