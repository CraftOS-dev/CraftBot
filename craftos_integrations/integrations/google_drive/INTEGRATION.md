# Google Drive — Integration Reference

List, search, move, share, and delete files and folders in the user's Drive. Part of the Google Workspace bundle (shares OAuth shape with `gmail`, `google_calendar`, `google_docs`).

## Essentials

- **No event listening.** `supports_listening = False`. Drive will never push file-change notifications — purely request-response.
- **File and folder IDs are opaque 44-char strings.** Don't construct. Use `search_drive` (free-form q-query), `find_drive_folder_by_name`, or `list_drive_files` to discover.
- **`"root"` is the special folder ID** for the user's Drive root. To list a folder's contents, query `'{folder_id}' in parents and trashed = false` — the `trashed = false` predicate is critical, omitting it returns deleted files.
- **Folders are files with `mimeType: "application/vnd.google-apps.folder"`.** Filtering by mimeType is the canonical way to separate them in search results.
- **Sharing requires an email address, not a name or handle.** `share_drive_file` takes `emailAddress` + a role enum (`reader`, `commenter`, `writer`, `owner` — case-sensitive). Google's permission sync can lag a few seconds — don't assume the recipient sees it instantly.
- **Move = re-parent.** `move_drive_file` adds new parent IDs and removes old ones in a single call. To move within Drive there's no "rename path"; the file just changes its `parents` array.
- **Multiple Google accounts may be connected**, each with an optional nickname ("work", "personal") — shared across Gmail/Calendar/Docs/Drive/YouTube, so a nickname set once applies to all of them. Every action takes an optional `account` param (email, unique email substring, or nickname). **If the user's message qualifies which account at all** ("my work Drive", "the school one"), extract that word and pass it — don't silently default to primary. Only omit `account` when the user gave no qualifier. An unresolvable/ambiguous `account` returns an error listing the connected accounts — relay that to the user instead of guessing.
- **Session-level facts:** `cred.email` is the *primary* connected account (unless `account` is passed). Never ask the user for it.
