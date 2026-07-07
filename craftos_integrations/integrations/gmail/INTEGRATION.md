# Gmail — Integration Reference

Send and read mail from the user's connected Google account. Part of the Google Workspace bundle (shares OAuth credentials with `google_calendar`, `google_drive`, `google_docs`).

## Essentials

- **The integration knows the user's own email address** (`cred.email`). NEVER ask the user for it. Read the connected credential or call `check_integration_status("google")` if you need it.
- **Multiple Gmail accounts may be connected**, each with an optional nickname ("work", "personal"). Every action takes an optional `account` param (email, unique email substring, or nickname). **If the user's message qualifies which account at all** ("my work Gmail", "the school one"), extract that word and pass it — don't silently default to primary. Only omit `account` when the user gave no qualifier. An unresolvable/ambiguous `account` returns an error listing the connected accounts; relay that to the user instead of guessing.
- **`From` is always the account the call resolved to.** You cannot spoof a different sender within one account.
- **Self-emails are auto-filtered on incoming events** — the agent's own outgoing mail doesn't loop back as new mail.
- **Identity format:** plain email-address strings (e.g. `alice@example.com`). Multiple recipients: depends on action; read the schema.
- **Message IDs are Gmail-opaque strings.** Don't construct them; always pull from `list_gmail` / search results.
- **`process_incoming=False` config:** if set, incoming mail is silently dropped (the agent never sees new emails). Sending and reading still work. If a user expected push-style notifications and isn't getting any, check this flag first.
- **`historyId` 404 is self-healing.** The internal polling sometimes returns 404 when the historyId expires — the client transparently re-fetches. Don't surface or retry.
