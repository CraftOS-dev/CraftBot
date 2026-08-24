# Notion

Notes and databases — search, pages, databases, blocks, comments, users,
file uploads.

## Multi-account
- One connected account = one Notion **workspace**. Each OAuth grant is
  issued per workspace (Notion shows a native workspace picker on the
  authorize page), and its token never expires.
- Every Notion action accepts an optional `account` (workspace name,
  nickname, or a unique fragment). Omit it to use the primary workspace.
- When the user names a workspace in any form ("the company Notion", "my
  personal workspace"), pass it as `account` — never silently default to
  primary.
- Page/database/block IDs are **workspace-scoped**: an id returned by
  `search_notion` under one account must be used with the same `account`
  on every follow-up action (get/update/archive/append/etc.).
- With multiple workspaces connected and no workspace named, ask the user
  which workspace before creating or archiving content.

## Essentials
- **No event listening.** Notion is request-response only — it will never
  push incoming events. Don't promise the user "you'll be notified when X
  changes."
- **IDs are 36-char UUIDs with hyphens, not human-readable names.** Always
  `search_notion` first to resolve a name like "Roadmap" to its page or
  database ID.
- **`create_notion_page` requires `parent_type` AND matching `parent_id`.**
  `parent_type` is either `"page_id"` or `"database_id"`. Mismatched type →
  server-side failure. The parent must already exist.
- **Page content is Notion block JSON, not markdown.**
  `append_notion_page_content` expects rich Notion block objects
  (paragraph, heading_1, bulleted_list_item, ...) — passing markdown
  silently fails. If the user gives markdown, convert it first.
- **Database properties are typed nested objects, not flat strings.**
  Before `update_notion_page` on a database row, call
  `get_notion_database_schema` to learn each property's type (title vs
  rich_text vs select vs date), then build the correctly-shaped object.
- **An integration only sees pages it's been explicitly shared with.**
  "Notion can't find the page" usually means the user hasn't invited the
  integration to that page — direct them to the page's "..." → "Add
  connections" menu, not a retry.

## Behavior
- Archive/trash is reversible: `restore_notion_page` /
  `restore_notion_database` undo the archive actions, and
  `delete_notion_block` soft-deletes to trash (restorable in the Notion
  UI).
