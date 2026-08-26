# Telegram Bot — Integration Reference

Bot-token integration (the `@BotFather` flow). Sends and reads via a Telegram bot account. Distinct from `telegram_user`, which is an MTProto user-session integration.

## Essentials

- **No "self" alias.** Bots don't have a personal inbox. Send-to-self has no shortcut here — the agent must target a chat by `chat_id`. If the user says "message me on Telegram", they probably mean `telegram_user`, not this one.
- **Identity formats:** `chat_id` is numeric (e.g. `123456789`, negative for groups/supergroups/channels) OR `@username` (Telegram resolves server-side). Don't pass display names.
- **The bot must already be in the chat.** A bot cannot DM a user that hasn't first sent `/start` to it. Common error: `chat not found` when the target user hasn't initiated. Surface that to the user — retrying won't fix it.
- **Session-level facts the integration knows:** `bot_username` (resolved at login). Use `get_telegram_bot_info` rather than asking the user.
- **`self_messages_only` config flag:** when True, the listener drops everything except 1:1 private DMs (filters out groups/supergroups). Affects what the agent *sees* on incoming events; doesn't change sending.
