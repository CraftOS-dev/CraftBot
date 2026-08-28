# LINE — Integration Reference

LINE Messaging API integration. Send-only — incoming messages arrive via webhook configured outside this integration.

## Essentials

- **No incoming-message listener.** This is SEND-only — the agent can push, multicast, broadcast, or reply (via reply token from a webhook event). Direct messages from users do NOT arrive through any agent poll. If a user expects the agent to react to their LINE messages, that requires the webhook to be configured on the LINE Developer console.
- **Identity format:** LINE IDs are prefix-coded — `U...` = user, `C...` = group, `R...` = room. No `@username` or search endpoint — the agent must already have the ID.
- **Reply tokens are single-use and short-lived.** Use `reply_line_message` only against a token from an incoming webhook event; do NOT cache or reuse. After the token expires (or is consumed), fall back to `send_line_message` (push) — which counts against monthly quota.
- **Session-level facts the integration knows:** `bot_user_id`, `bot_display_name`. Use `get_line_bot_info`.
- **Push quotas:** push/multicast/broadcast count against the monthly message quota. Check remaining quota via `get_line_quota` before bulk sends; surface a clear error if exhausted instead of failing each send.
- **Config knobs:** `notification_disabled` silences push alerts; `message_prefix` prepends a string to every outgoing text.
