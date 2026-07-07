# Outlook — Integration Reference

Microsoft 365 / Outlook.com mail integration via Microsoft Graph.

## Essentials

- **The integration knows the user's own email address** (`cred.email`). NEVER ask the user — read it from the connected credential or `check_integration_status`.
- **Multiple Outlook accounts may be connected**, each with an optional nickname ("work", "personal"). Every action takes an optional `account` param (email, unique email substring, or nickname). **If the user's message qualifies which account at all** ("my work Outlook", "the school one"), extract that word and pass it — don't silently default to primary. Only omit `account` when the user gave no qualifier. An unresolvable/ambiguous `account` returns an error listing the connected accounts; relay that instead of guessing.
- **`From` is always the account the call resolved to.** Can't be spoofed within one account.
- **Self-emails are auto-filtered on incoming events** (case-insensitive match on sender) — own sends don't echo back.
- **Identity format:** plain email-address strings.
- **Message IDs are Microsoft Graph opaque IDs** (`AAMk...`). Pull from list/search; never construct.
- **Conversation IDs group related messages** — useful for finding threads.
- **Token refresh is automatic** (60-second buffer before 2-hour TTL). A 401 means the access token expired and the client is refreshing — wait and retry. Only direct the user to reconnect if 401s persist across retries.
- **Poll filter field is `receivedDateTime`** (ISO 8601). Time-windowed reads use this field.
