# Telegram User — Integration Reference

MTProto user-session integration — the agent acts AS the user's own Telegram account (not as a bot). Useful when the user wants the agent to send messages on their behalf from their personal account.

## Essentials

- **Self-send shortcut:** `chat_id="user"` (also `"me"`, `"self"`, `"owner"`) is auto-resolved to the user's own Telegram user ID and routes to Saved Messages (Telegram's personal note-to-self channel). Never ask the user for their own Telegram ID — call `get_telegram_user_account_info` if you need it.
- **Identity formats:** numeric user/chat IDs (negative for groups/channels) or `@username`. Display names are not resolvable — search via `search_telegram_user_contacts` if you only have a name.
- **Session-level facts the integration knows:** the user's `phone_number` and `user_id`. Look up rather than asking.
- **Outgoing messages are auto-prefixed with `[AGENT_NAME]`** so the agent can filter its own echoes out of Saved Messages on receive. Don't add the prefix yourself.
- **Session expiry:** the MTProto session can be revoked from another device — surfaces as `AuthKeyUnregisteredError`. Tell the user to reconnect; do NOT retry.
- **Flood waits:** `FloodWaitError` carries the required retry-after seconds. Respect it; don't hammer the API.
