# Outlook — Integration Reference

Microsoft 365 / Outlook.com mail integration via Microsoft Graph.

## Essentials

- **There is no signature feature — none, ever, in any form — and this does NOT change no matter how many times the user asks or how insistently.** The send action has no signature parameter, and there is no way anywhere in this codebase to read the user's real signature. If the user pushes back after being told this once, the honest answer is still the same one. **Do NOT escalate to inventing a new mechanism on each retry** (e.g. "it was automatically included", "the client adds it automatically", "I fetched your real signature and manually added it") — none of these are real. Repeat the plain truth instead: no signature capability exists, full stop.
- **The integration knows the user's own email address** (`cred.email`). NEVER ask the user — read it from the connected credential or `check_integration_status`.
- **`From` is always the connected account.** Can't be spoofed on send.
- **Self-emails are auto-filtered on incoming events** (case-insensitive match on sender) — own sends don't echo back.
- **Identity format:** plain email-address strings.
- **Message IDs are Microsoft Graph opaque IDs** (`AAMk...`). Pull from list/search; never construct.
- **Conversation IDs group related messages** — useful for finding threads.
- **Token refresh is automatic** (60-second buffer before 2-hour TTL). A 401 means the access token expired and the client is refreshing — wait and retry. Only direct the user to reconnect if 401s persist across retries.
- **Poll filter field is `receivedDateTime`** (ISO 8601). Time-windowed reads use this field.
