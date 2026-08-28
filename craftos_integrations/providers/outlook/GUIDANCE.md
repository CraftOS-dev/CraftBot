# Outlook

Microsoft 365 / Outlook.com mail via Microsoft Graph — read, search, send,
reply/forward, drafts, attachments, folders, inbox rules, categories,
mailbox settings.

## Multi-account
- Every Outlook action accepts an optional `account` (email, nickname, or
  a unique fragment like "work"). Omit it to use the primary account.
- When the user names an account in any form ("my work mailbox", "the
  contoso address"), pass it as `account` — never silently default to
  primary.
- Message, folder, attachment, rule, and category ids are
  **account-scoped**: an id returned by `search_outlook_emails` with
  `account="work"` must be used with `account="work"` on every follow-up
  action (get/reply/move/delete/etc.).
- For destructive actions (send, delete, folder delete) with multiple
  accounts connected and no account named: ask the user which account
  before acting.

## Essentials
- **The integration knows the user's own email address** — read it from
  the connected account; never ask the user for it.
- **`From` is always the connected account.** It cannot be spoofed on
  send.
- **Message IDs are Microsoft Graph opaque IDs** (`AAMk...`). Pull them
  from list/search results; never construct them. Conversation IDs group
  related messages — useful for finding threads.
- **`delete_outlook_email` is permanent.** Prefer `move_outlook_email` to
  `deleteditems` for a soft delete.
- **Well-known folder names** work anywhere a folder id is accepted:
  `inbox`, `drafts`, `sentitems`, `deleteditems`, `archive`, `junkemail`
  (and `msgfolderroot` as the top-level parent).
- **`add_outlook_attachment` only works on drafts** and only for files
  under 3 MB.
- **Token refresh is automatic** (60-second buffer before the ~2-hour
  TTL). A 401 means the access token expired and the client is
  refreshing — wait and retry; only direct the user to reconnect if 401s
  persist across retries.
