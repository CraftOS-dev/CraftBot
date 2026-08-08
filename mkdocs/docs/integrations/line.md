# LINE

The LINE integration connects the agent to a LINE Messaging API channel with a channel access token and channel secret. The agent can push, reply, multicast, and broadcast messages, send rich content, manage rich menus and audiences, read insights, and configure the webhook endpoint. It is send-only: inbound messages arrive through a webhook you configure on the LINE Developers console, not through a listener.

## Requirements

| Requirement | Details |
|---|---|
| LINE Business account | Create a provider and channel at [developers.line.biz](https://developers.line.biz) |
| Messaging API channel | The bot sends and replies as this channel |
| Channel access token | A long-lived token issued from the channel's Messaging API tab |
| Channel secret | Used to verify webhook signatures; stored at connect time |
| Webhook (for inbound) | Configured on the LINE console for the agent to react to user messages |
| Network access | CraftBot calls the LINE Messaging API over HTTPS |

## Setup

1. Open [developers.line.biz](https://developers.line.biz), create a provider, and add a **Messaging API** channel.
2. On the channel's **Messaging API** tab, issue a **Channel access token** and copy it.
3. On the **Basic settings** tab, copy the **Channel secret**.
4. In CraftBot, open **Settings → Integrations → LINE**, paste the channel access token and channel secret, and connect. From chat, `/line login <channel_access_token> [channel_secret]` does the same thing.
5. Verify with `/line status`. It shows the connected bot.

`/line logout` removes the credential.

## How it connects

**Authentication.** Every call sends the channel access token as a bearer token to the LINE Messaging API. CraftBot stores the token and the channel secret in the credential store as `line.json`. The channel secret is kept for verifying webhook signatures. See [Credentials](credentials.md).

**Send-only, no listener.** LINE delivers inbound messages by webhook only, so there is no poll and no listener interval. Direct messages from users do not reach the agent unless you configure a webhook on the LINE console and point it at your CraftBot instance. The agent can still push, multicast, and broadcast at any time.

**Reply tokens.** A reply token comes from an incoming webhook event and is single-use with a one-minute window. The agent uses `reply_line_message` against a fresh token. After the token expires or is used, the agent falls back to `send_line_message` (a push), which counts against the monthly quota.

**Single channel.** One channel is connected per credential. The agent looks up its own bot identity rather than asking you. Recipient IDs are prefix-coded: `U` for a user, `C` for a group, and `R` for a room.

## What the agent can do

The 59 LINE actions are grouped into action sets the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Messaging

| Action | Purpose |
|---|---|
| `send_line_message` | Push a text message to a user, group, or room |
| `reply_line_message` | Reply to a message using a reply token (one-minute window) |
| `multicast_line_message` | Send the same text to up to 500 user IDs |
| `broadcast_line_message` | Broadcast a text to all friends |
| `push_line_messages` | Push up to 5 LINE message objects to one recipient for full control over shape |
| `reply_line_messages` | Reply with up to 5 LINE message objects |
| `multicast_line_messages` | Multicast up to 5 LINE message objects to many users |
| `broadcast_line_messages` | Broadcast up to 5 LINE message objects to all friends |

### Rich content

| Action | Purpose |
|---|---|
| `send_line_image` | Push an image from a public HTTPS URL |
| `send_line_video` | Push a video with a preview image |
| `send_line_audio` | Push an audio file with a required duration |
| `send_line_location` | Push a location pin |
| `send_line_sticker` | Push a LINE sticker by package and sticker ID |
| `send_line_flex` | Push a Flex Message, LINE's rich interactive card format |
| `send_line_template` | Push a template message (buttons, confirm, carousel, image carousel) |
| `send_line_imagemap` | Push a clickable image with tappable regions |
| `download_line_message_content` | Download the binary content of a user-sent image, video, audio, or file message |

### Profile and bot

| Action | Purpose |
|---|---|
| `get_line_profile` | Fetch a user's display name and picture URL |
| `get_line_bot_info` | Get the connected bot's own profile |
| `get_line_quota` | Get the bot's monthly push-message quota |

### Groups and rooms

| Action | Purpose |
|---|---|
| `get_line_group_summary` | Get a group's name and picture URL |
| `get_line_group_member_count` | Get a group's member count |
| `list_line_group_members` | List the user IDs of group members |
| `get_line_group_member_profile` | Get a group member's display name and picture URL |
| `leave_line_group` | Leave a group |
| `get_line_room_member_count` | Get a room's member count |
| `list_line_room_members` | List the user IDs in a room |
| `get_line_room_member_profile` | Get a room member's display name and picture URL |
| `leave_line_room` | Leave a room |

### Rich menus

| Action | Purpose |
|---|---|
| `create_line_rich_menu` | Create a rich menu definition |
| `get_line_rich_menu` | Get a rich menu definition by ID |
| `list_line_rich_menus` | List all rich menus the bot has created |
| `delete_line_rich_menu` | Delete a rich menu |
| `upload_line_rich_menu_image` | Upload the image for a rich menu, matching its size |
| `set_line_default_rich_menu` | Make a rich menu the default for all users |
| `get_line_default_rich_menu` | Get the current default rich menu ID |
| `cancel_line_default_rich_menu` | Unset the default rich menu |
| `link_line_rich_menu_to_user` | Show a specific rich menu to a single user |
| `unlink_line_rich_menu_from_user` | Remove a user's rich menu override so they fall back to the default |
| `get_line_user_rich_menu` | Get the rich menu currently linked to a user |
| `bulk_link_line_rich_menu` | Link up to 500 users to a rich menu in one call |
| `bulk_unlink_line_rich_menu` | Unlink rich menus from many users in one call |

### Narrowcast and audiences

| Action | Purpose |
|---|---|
| `send_line_narrowcast` | Send messages to a filtered subset of friends by demographics or audience |
| `get_line_narrowcast_progress` | Poll a narrowcast request's delivery progress |
| `create_line_user_id_audience` | Create an audience group from explicit user IDs |
| `get_line_audience` | Get an audience group's metadata and status |
| `list_line_audiences` | List the bot's audience groups |
| `update_line_audience_description` | Change an audience group's description |
| `delete_line_audience` | Delete an audience group |

### Insights

| Action | Purpose |
|---|---|
| `get_line_followers_count` | Get the number of followers on a given date |
| `get_line_friend_demographics` | Get a demographic breakdown of friends by gender, age, and area |
| `get_line_message_delivery_stats` | Get the number of pushes, multicasts, and broadcasts sent on a date |
| `get_line_message_event_stats` | Get click, impression, and open stats for a broadcast or narrowcast |

### Webhook

| Action | Purpose |
|---|---|
| `set_line_webhook_endpoint` | Set the HTTPS endpoint where LINE posts incoming events |
| `get_line_webhook_endpoint` | Get the current webhook endpoint URL |
| `test_line_webhook_endpoint` | Test the webhook with a synthetic event and return status and latency |

### Tokens

| Action | Purpose |
|---|---|
| `issue_line_channel_access_token` | Issue a short-lived channel access token for rotation |
| `revoke_line_channel_access_token` | Revoke a channel access token |
| `verify_line_access_token` | Verify an access token and show its scope and expiry |

## Example requests

```
Push a LINE message to user U123... reminding them the store opens at 9.
```

```
Broadcast a New Year greeting to all my LINE friends.
```

```
Send a LINE Flex card with today's menu and a "Book now" button.
```

```
Check my remaining LINE push quota before I send a broadcast.
```

```
Set a default rich menu for all users from the image menu.png.
```

```
Show me the follower count and friend demographics for last month.
```

## Configuration

Open **Settings → Integrations → LINE**. Two knobs apply to outgoing messages.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Notifications disabled (`notification_disabled`) | checkbox | off | When on, push messages arrive without a push notification alert on the recipient's device |
| Message prefix (`message_prefix`) | text | empty | A string prepended to every outgoing text message |

To receive inbound messages, set the webhook on the LINE console (or with `set_line_webhook_endpoint`) and point it at your CraftBot instance.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 401 or "invalid token" | The channel access token is wrong, revoked, or expired | Issue a new token on the console and run `/line login <token> [channel_secret]` |
| Reply fails with an invalid reply token | The one-minute reply window closed, or the token was already used | Send with `send_line_message` (push) instead of replying |
| Sends fail after a busy period | The monthly push quota is exhausted | Check `get_line_quota`, then wait for the next cycle or raise your plan limit |
| Agent never reacts to user messages | No webhook is configured, so inbound events never arrive | Set the webhook on the LINE console or with `set_line_webhook_endpoint` |
| "Invalid recipient" on a send | The ID prefix is wrong for the target | Use `U` for a user, `C` for a group, and `R` for a room |
| Media message rejected | The content URL is not a public HTTPS URL | Host the image, video, or audio at a reachable HTTPS URL |

## Next

- [Slack](slack.md): another messaging platform with an action-based surface
- [Credentials](credentials.md): where the token is stored and how `/cred status` reports it
- [Triggers](../core/concepts/triggers.md): how inbound webhook events become tasks
