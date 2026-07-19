# Google Drive

The Google Drive integration lets the agent manage your files and folders: list, search, upload, download, move, share, comment, and track versions. You connect once through Google's consent screen, and everything after that runs through the Drive API. There is no listener: Drive never pushes file-change events to the agent, so every action is a request the agent makes on your behalf.

## Requirements

| Requirement | Details |
|---|---|
| Google account | Any Gmail or Google Workspace account |
| A browser | For the one-time OAuth consent |
| CraftBot running | Connect from **Settings → Integrations** in the browser interface |
| OAuth app | None needed. Release builds embed a CraftOS Google client (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` override it for self-hosted setups) |

## Setup

1. Open **Settings → Integrations** and click **Connect** on the Google Drive card. You can also run `/google_drive login` in chat.
2. Your browser opens Google's consent screen. CraftBot requests the `drive` scope (read, write, share, and delete files and folders), plus `userinfo.email` and `userinfo.profile` to record which account is connected.
3. Approve access. Google redirects back to `http://localhost:8765`, where CraftBot exchanges the code for tokens.
4. CraftBot confirms with "Google Drive connected as *your address*". The credential is saved locally as `gdrive.json`.
5. Verify any time with `/google_drive status` or `/cred status`.

The consent screen may warn about an unverified app. Drive uses the broad `drive` scope so the agent can see files you already own, not only files it created itself. This wider scope is what triggers the warning.

Connecting Google Drive grants the Drive scope to this credential only. Gmail, Google Calendar, Google Docs, and YouTube each have their own card, their own consent screen, and their own credential file. Connecting one Google service does not connect the others.

## How it connects

**Authentication.** OAuth 2.0 authorization code flow with PKCE, using the shared CraftOS Google client. Consent is requested with offline access, so CraftBot receives a refresh token along with the access token.

**Token refresh.** Access tokens expire after about an hour. Before each API call CraftBot checks the stored expiry and refreshes the token automatically with the refresh token, writing the new token back to `gdrive.json`. You only reconnect if Google revokes the refresh token, for example after a password change.

**No listener.** Drive does not poll or receive push notifications. The agent reads and changes files only when a task calls for it.

## What the agent can do

All 39 Google Drive actions, grouped by domain. Each purpose comes from the action's registered description.

### Files

| Action | Purpose |
|---|---|
| `list_drive_files` | List files in a specific Google Drive folder |
| `search_drive_files` | Free-form search across all of Drive using Drive's q-query syntax |
| `get_drive_file` | Get metadata for a single Drive file or folder |
| `upload_drive_file` | Upload a local file to Google Drive. MIME type is auto-detected if omitted |
| `update_drive_file_content` | Replace an existing Drive file's binary content with a local file. Does not change metadata |
| `download_drive_file` | Download a regular, non-Google-native Drive file to a local path |
| `export_drive_file` | Export a Google-native file (Doc, Sheet, Slide, Drawing) to a local path in another format. Limit 10 MB |
| `copy_drive_file` | Duplicate a Drive file. Optionally rename and place in a different folder |
| `move_drive_file` | Move a file to a different Google Drive folder |
| `update_drive_file_metadata` | Rename, re-describe, star, or trash a Drive file. Use `trashed=true` to send to trash without permanent delete |
| `delete_drive_file` | Permanently delete a Drive file. Irreversible. To send to trash instead, use `update_drive_file_metadata` with `trashed=true` |

### Trash and account

| Action | Purpose |
|---|---|
| `empty_drive_trash` | Permanently delete everything in the user's Drive trash. Irreversible |
| `get_drive_about` | Get Drive account info: user, storage quota, max upload size. Set `include_metadata` for the supported export and import format maps |

### Folders

| Action | Purpose |
|---|---|
| `create_drive_folder` | Create a new folder in Google Drive |
| `find_drive_folder_by_name` | Find a folder by name |
| `resolve_drive_folder_path` | Resolve a folder path to a folder ID |

### Permissions

| Action | Purpose |
|---|---|
| `list_drive_permissions` | List who has access to a Drive file or folder, with their role |
| `get_drive_permission` | Get one specific permission by ID |
| `add_drive_permission` | Share a Drive file or folder. `perm_type`: user, group, domain, anyone. `role`: reader, commenter, writer, owner |
| `update_drive_permission` | Change a permission's role |
| `remove_drive_permission` | Revoke access by deleting a permission |

### Comments and replies

| Action | Purpose |
|---|---|
| `list_drive_comments` | List comments on a Drive file |
| `get_drive_comment` | Get a single comment with its replies |
| `create_drive_comment` | Post a top-level comment on a Drive file. `anchor` is an optional region anchor |
| `update_drive_comment` | Edit a comment's content or mark it resolved |
| `delete_drive_comment` | Delete a comment |
| `list_drive_comment_replies` | List replies on a comment |
| `create_drive_comment_reply` | Reply to a comment |
| `update_drive_comment_reply` | Edit a reply |
| `delete_drive_comment_reply` | Delete a reply |

### Revisions

| Action | Purpose |
|---|---|
| `list_drive_revisions` | List revisions (version history) of a Drive file |
| `get_drive_revision` | Get details of a specific revision |
| `update_drive_revision` | Mark a revision keep-forever (pin) or set publish state for Google-native files |
| `delete_drive_revision` | Delete a revision |

### Shared drives

| Action | Purpose |
|---|---|
| `list_shared_drives` | List shared drives the user has access to |
| `get_shared_drive` | Get metadata for a shared drive |
| `create_shared_drive` | Create a new shared drive. The user must have permission to create shared drives in their org |
| `update_shared_drive` | Rename or hide/unhide a shared drive |
| `delete_shared_drive` | Delete a shared drive. The drive must be empty |

## Example requests

- "Find every PDF in my Drive with 'invoice' in the name and download them to my workspace."
- "Create a folder called Q3 and move all the files from my Reports folder into it."
- "Share my Budget spreadsheet with alice@example.com as a commenter."
- "Upload report.docx from my workspace to Drive and tell me the share link."
- "List everyone who has access to my Proposal folder and revoke access for anyone outside my team."
- "Post a comment on my Design doc asking the reviewers to sign off by Friday."

## Configuration

- **Own OAuth app.** Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` as environment variables to use your own Google Cloud OAuth client instead of the embedded one. See [Credentials](credentials.md).
- **Credential file.** The token lives in `gdrive.json` in the local credential store. `/google_drive logout` removes it. The Google Workspace meta-integration writes this file too when you connect everything at once, so the two stay interchangeable.
- **Sharing roles.** `add_drive_permission` takes an email address and a case-sensitive role (`reader`, `commenter`, `writer`, `owner`). Google's permission sync can lag a few seconds, so a recipient may not see access instantly.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Consent completes but CraftBot never confirms | Port `8765` is blocked or in use, so the redirect never arrived | Free the port and run `/google_drive login` again |
| Actions fail with "No google_drive credentials" | Not connected, or logged out | Connect from **Settings → Integrations** or run `/google_drive login` |
| Consent screen warns about an unverified app | Drive uses the broad `drive` scope by design | Continue past the warning to grant access, or verify your own OAuth app if self-hosting |
| A folder listing includes deleted files | The search query omitted the `trashed = false` predicate | Ask the agent to filter to non-trashed files, or search with `'{folder_id}' in parents and trashed = false` |
| Sharing fails or the recipient sees nothing | Sharing needs an email address, not a name, and Google's sync lags a few seconds | Provide the exact email address and allow a short delay before checking |
| Every request fails with 401 after working fine | Google revoked the refresh token (password change, security review) | `/google_drive logout`, then reconnect |

## Next

- [Google Docs](google-docs.md): create and edit the documents stored in your Drive
- [Gmail](gmail.md): the mail side of the same Google connection flow
- [Credentials](credentials.md): where the token lives and how refresh works
