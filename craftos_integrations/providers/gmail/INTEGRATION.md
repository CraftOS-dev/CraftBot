# Gmail — Integration Reference

Send and read mail from the user's connected Google account. Part of the Google Workspace bundle (shares OAuth credentials with `google_calendar`, `google_drive`, `google_docs`).

## Essentials

- **The integration knows the user's own email address** (`cred.email`). NEVER ask the user for it. Read the connected credential or call `check_integration_status("google")` if you need it.
- **`From` is always the connected account.** You cannot spoof sender on send.
- **Self-emails are auto-filtered on incoming events** — the agent's own outgoing mail doesn't loop back as new mail.
- **Identity format:** plain email-address strings (e.g. `alice@example.com`). Multiple recipients: depends on action; read the schema.
- **Message IDs are Gmail-opaque strings.** Don't construct them; always pull from `list_gmail` / search results.
- **`process_incoming=False` config:** if set, incoming mail is silently dropped (the agent never sees new emails). Sending and reading still work. If a user expected push-style notifications and isn't getting any, check this flag first.
- **`historyId` 404 is self-healing.** The internal polling sometimes returns 404 when the historyId expires — the client transparently re-fetches. Don't surface or retry.
