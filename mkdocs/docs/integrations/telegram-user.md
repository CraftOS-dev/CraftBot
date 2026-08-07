# Telegram (User)

The Telegram user integration connects the agent to your own personal Telegram account over Telegram's MTProto API. The agent acts as you: it can message anyone you can reach, send files, read your recent chats and messages, and search your contacts. A realtime listener turns incoming messages into events the agent reacts to.

For a separate bot account created with @BotFather, see [Telegram (Bot)](telegram-bot.md).

## Bot account or user account

| | Telegram (Bot) | Telegram (User) |
|---|---|---|
| Identity | A separate bot account | Your own Telegram account |
| Reach | Only users who have sent `/start`, plus groups and channels it was added to | Anyone and any chat you can reach yourself |
| Best for | Public channels, groups, broadcasts, moderation | Personal messaging, DMs, private groups, "message me on Telegram" |
| Setup | A bot token from @BotFather | An `api_id` and `api_hash` plus a phone login |

Pick the bot when you want a distinct account with admin and moderation powers in groups. Pick the user account when you want the agent to send and read as you.

## Requirements

| Requirement | Details |
|---|---|
| Telegram account | The agent acts as this account for every call |
| `api_id` and `api_hash` | Created at [my.telegram.org](https://my.telegram.org), set as `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` |
| Phone and login code | Telegram sends a one-time code during connect; a 2FA password is needed if you have one set |
| `telethon` package | The MTProto client library, installed in the CraftBot environment |
| `qrcode` package (optional) | Only for QR login with `/telegram_user login-qr` |

## Setup

1. Open [my.telegram.org](https://my.telegram.org) and log in with your Telegram phone number.
2. Click **API development tools**, fill in any app name and short name, and submit.
3. Copy the `api_id` (a number) and `api_hash` (a long hex string).
4. Set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in CraftBot config.
5. In CraftBot, open **Settings → Integrations → Telegram (User)** and connect. You are prompted for your phone number, then the login code Telegram sends you.
6. From chat, the login is two steps. Send `/telegram_user login <phone_number>` to request a code, then `/telegram_user login <phone_number> <code>` to verify. Add your 2FA password as a third argument if you have one: `/telegram_user login <phone_number> <code> <2fa_password>`.
7. Verify with `/telegram_user status`. It shows the connected phone number.

`/telegram_user login-qr` logs in by scanning a QR code instead of entering a phone code. `/telegram_user logout` removes the credential and stops the listener.

## How it connects

**Authentication.** Connecting creates an MTProto session string that is stored with your `api_id`, `api_hash`, and phone number in the credential store as `telegram_user.json`. Later calls reuse the session string, so you do not re-enter a code on every run. See [Credentials](credentials.md).

**Realtime listener.** While connected, CraftBot keeps a live Telethon connection open and subscribes to new-message events. On startup it catches up on anything missed while offline, then dispatches each new text message. Only messages that carry text are forwarded.

**Self-send shortcut.** Setting the recipient to `user`, `me`, `self`, or `owner` routes to your own Saved Messages, Telegram's personal note-to-self chat. You never need to supply your own Telegram ID.

**Echo filtering.** Every message the agent sends is prefixed with the agent's name in brackets so the agent can recognize and skip its own messages when they appear in Saved Messages. Do not add the prefix yourself.

**Identity formats.** Use a numeric user or chat ID (negative for groups and channels) or an `@username`. Display names are not resolvable, so search by name with `search_telegram_user_contacts` when you only have a name.

## What the agent can do

The 6 Telegram user actions form the `telegram_user` action set, which the agent loads when a task needs it. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

| Action | Purpose |
|---|---|
| `get_telegram_chats` | Get your recent chats via the Telegram user account |
| `read_telegram_messages` | Read messages from a chat via the Telegram user account |
| `send_telegram_user_message` | Send a text message as you (use `@username` or `self` for Saved Messages) |
| `send_telegram_user_file` | Send a file as you |
| `search_telegram_user_contacts` | Search your contacts by name or username |
| `get_telegram_user_account_info` | Get your own account info (name, username, phone, user ID) |

## Example requests

```
Message @alex on Telegram that the reservation is confirmed for 7pm.
```

```
Send myself a note on Telegram summarizing today's tasks.
```

```
Read the last 20 messages from my chat with the design team and summarize them.
```

```
Find my contact named Priya and send her the file invoice.pdf from the workspace.
```

```
List my recent Telegram chats and tell me which ones have unread messages.
```

## Configuration

The setting lives in **Settings → Integrations → Telegram (User)** and is stored in `telegram_user_config.json` next to the credential. The listener re-reads it on every incoming message.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Self-messages only (`self_messages_only`) | checkbox | off | When on, only messages in your own Saved Messages chat reach the agent. DMs from contacts and group or channel messages are dropped. Useful for using Telegram purely as a personal command channel |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "telethon is not installed" | The MTProto client library is missing | Install `telethon` in the CraftBot environment |
| "Not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH" | The API credentials are unset | Create them at [my.telegram.org](https://my.telegram.org) and set both values |
| "Invalid verification code" or "Code expired" | Wrong or stale login code | Request a fresh code with `/telegram_user login <phone>` and enter it promptly |
| "2FA enabled" during login | The account has a two-step password set | Repeat the second step with the password as a third argument |
| Session expired or revoked (`AuthKeyUnregisteredError`) | The session was invalidated from another device | Reconnect with `/telegram_user login`. Do not retry the failing call |
| "Rate limited. Please wait N seconds" (`FloodWaitError`) | Telegram is throttling the account | Wait the stated number of seconds before sending again |
| "Could not find chat" when sending | A numeric ID or display name was used that Telegram cannot resolve | Use an `@username`, or search first with `search_telegram_user_contacts` |

## Security note

A user-account connection lets the agent send messages as you to any of your contacts. Review automations that send Telegram messages before enabling them to run unattended.

## Next

- [Telegram (Bot)](telegram-bot.md): connect a bot account for public channels, groups, and moderation
- [Credentials](credentials.md): where the session is stored and how `/cred status` reports it
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
