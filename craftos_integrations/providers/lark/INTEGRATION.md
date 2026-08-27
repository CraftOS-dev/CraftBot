# Lark — Integration Reference

Lark (Feishu) bot integration. Messages, calendar, drive, chat search. Uses the `lark_oapi` SDK with a WebSocket event stream.

## Essentials

- **No "self" alias.** Lark doesn't model a user-to-self relationship for a bot account. Specify a recipient explicitly.
- **Recipient resolution is type-tagged.** `send_lark_message` takes a `receive_id_type` arg: one of `open_id` (default), `user_id`, `email`, `chat_id`, `union_id`. If sending by email, set `receive_id_type="email"` (don't try to embed the email in `open_id`). If you only have an email, use `get_lark_user_by_email` to discover the `open_id`.
- **Identity formats:** `open_id` starts with `ou_...`, `chat_id` starts with `oc_...`. Different prefixes mean different lookup paths — don't pass them interchangeably.
- **Message `content` is a JSON-encoded STRING**, not a JSON object. For a plain text message, the value is `{"text": "Hello"}` serialised to string (so the actual content arg is the string `'{"text": "Hello"}'`). The action's example shows the right shape — match it.
- **Critical: app must be approved by the tenant admin.** The WebSocket will connect fine even if the current app version is unapproved, but events will NOT arrive. If incoming messages aren't flowing, that's the first thing to check — direct the user to their Lark admin.
- **Token refresh is automatic** (2-hour TTL, refreshed within 60s of expiry). No manual intervention.
- **Session-level facts the integration knows:** `app_id`, `bot_id`. Use `get_lark_bot_info` rather than asking.
