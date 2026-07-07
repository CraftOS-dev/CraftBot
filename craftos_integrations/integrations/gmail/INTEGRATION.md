# Gmail — Integration Reference

Send and read mail from the user's connected Google account. Part of the Google Workspace bundle (shares OAuth credentials with `google_calendar`, `google_drive`, `google_docs`).

## Essentials

- **There is no signature feature — none, ever, in any form — and this does NOT change no matter how many times the user asks or how insistently.** `send_gmail` has no signature/`sendAs` parameter. There is no way anywhere in this codebase to read the user's real Gmail signature (the `sendAs` API is intentionally not wired up). If the user pushes back after being told this once, the honest answer is still the same one — it does not become true because they insisted. **Do NOT escalate to inventing a new mechanism on each retry** — real fabrications already seen and BANNED: "signature was automatically included by Gmail", "Gmail adds a signature automatically when the body has content", "I fetched your real signature and manually added it". None of these are real. If asked again, repeat the plain truth: no signature capability exists, full stop. If the user wants their actual saved Gmail signature applied, that requires a new feature to be built (reading `sendAs.signature` via the Gmail API) — tell them that's not implemented, don't attempt a workaround that fakes it.
- **The integration knows the user's own email address** (`cred.email`). NEVER ask the user for it. Read the connected credential or call `check_integration_status("google")` if you need it.
- **`From` is always the connected account.** You cannot spoof sender on send.
- **Self-emails are auto-filtered on incoming events** — the agent's own outgoing mail doesn't loop back as new mail.
- **Identity format:** plain email-address strings (e.g. `alice@example.com`). Multiple recipients: depends on action; read the schema.
- **Message IDs are Gmail-opaque strings.** Don't construct them; always pull from `list_gmail` / search results.
- **`process_incoming=False` config:** if set, incoming mail is silently dropped (the agent never sees new emails). Sending and reading still work. If a user expected push-style notifications and isn't getting any, check this flag first.
- **`historyId` 404 is self-healing.** The internal polling sometimes returns 404 when the historyId expires — the client transparently re-fetches. Don't surface or retry.
- **`process_incoming` (the "Auto-process incoming emails" toggle) has no dedicated action.** Read/edit it directly at `.credentials/gmail_config.json` (key `process_incoming`, bool) — see "Per-integration runtime config" in `## Integrations` in AGENT.md for the safe read-merge-write-verify procedure before claiming you changed it.
