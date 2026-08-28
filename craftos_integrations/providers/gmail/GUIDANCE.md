# Gmail

Email — read, search, send, drafts, labels, threads.

## Multi-account
- Every Gmail action accepts an optional `account` (email, nickname, or a
  unique fragment like "work"). Omit it to use the primary account.
- When the user names an account in any form ("my school email", "the work
  inbox"), pass it as `account` — never silently default to primary.
- Message/thread/draft ids are **account-scoped**: an id returned by
  `search_gmail` with `account="work"` must be used with `account="work"`
  on every follow-up action (get/trash/reply/etc.).
- For destructive actions (delete, batch operations) with multiple
  accounts connected and no account named: ask the user which account
  before acting.

## Behavior
- "Any updates / what's new" questions: if the unread check comes back
  empty, don't answer a flat "no updates" — say there's nothing unread and
  either offer or show the most recent messages (`unread_only=false`).
- `send_gmail` with no `to` sends to the connected account's own address.
- Prefer `trash_gmail` (reversible) over `delete_gmail` (permanent).
- Use Gmail search syntax in `search_gmail` (`from:`, `subject:`,
  `newer_than:7d`, `has:attachment`, ...).
