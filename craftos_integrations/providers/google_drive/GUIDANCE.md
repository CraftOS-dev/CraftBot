# Google Drive

Files — list, search, upload, download, export, share, comments,
revisions, shared drives.

## Multi-account
- Every Drive action accepts an optional `account` (email, nickname, or a
  unique fragment like "work"). Omit it to use the primary account.
- When the user names an account in any form ("my school Drive", "the
  work account"), pass it as `account` — never silently default to
  primary.
- File/folder/permission/comment/revision ids are **account-scoped**: an
  id returned by `search_drive_files` with `account="work"` must be used
  with `account="work"` on every follow-up action (get/move/share/etc.).
- Permission grants come FROM the selected account:
  `add_drive_permission` shares the file as that account, and the grantee
  receives access (and any notification email) from that account's
  address.
- For destructive actions (delete, empty trash, permission changes) with
  multiple accounts connected and no account named: ask the user which
  account before acting.

## Behavior
- No event listening — Drive is purely request-response.
- File and folder IDs are opaque strings; never construct them. Discover
  them with `search_drive_files` (Drive q-query syntax),
  `find_drive_folder_by_name`, or `list_drive_files`.
- `"root"` is the special folder ID for the account's My Drive root.
- Include `trashed = false` in q-queries — omitting it returns deleted
  files too.
- Folders are files with `mimeType = "application/vnd.google-apps.folder"`;
  filter by mimeType to separate them in search results.
- Sharing requires an email address, not a name or handle. Roles are
  case-sensitive: `reader`, `commenter`, `writer`, `owner`. Google's
  permission sync can lag a few seconds — don't assume the recipient sees
  it instantly.
- Move = re-parent: `move_drive_file` swaps the file's `parents`; there
  is no path rename.
- Prefer `update_drive_file_metadata` with `trashed=true` (reversible)
  over `delete_drive_file` (permanent).
- For Google-native files (Docs/Sheets/Slides) use `export_drive_file`;
  `download_drive_file` only works for regular binary files.
- The connected account's email is known from the credential — never ask
  the user for it.
