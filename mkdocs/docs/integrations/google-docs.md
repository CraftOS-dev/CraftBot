# Google Docs

The Google Docs integration lets the agent create, read, edit, and search documents in your Google Drive. You connect once through Google's consent screen, and everything after that runs through the Docs and Drive APIs. There is no listener: Docs never pushes events to the agent, so every action is a request the agent makes on your behalf.

## Requirements

| Requirement | Details |
|---|---|
| Google account | Any Gmail or Google Workspace account |
| A browser | For the one-time OAuth consent |
| CraftBot running | Connect from **Settings → Integrations** in the browser interface |
| OAuth app | None needed. Release builds embed a CraftOS Google client (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` override it for self-hosted setups) |

## Setup

1. Open **Settings → Integrations** and click **Connect** on the Google Docs card. You can also run `/google_docs login` in chat.
2. Your browser opens Google's consent screen. CraftBot requests `documents` (read and write document content) and `drive` (find and manage the files those documents live in), plus `userinfo.email` and `userinfo.profile` to record which account is connected.
3. Approve access. Google redirects back to `http://localhost:8765`, where CraftBot exchanges the code for tokens.
4. CraftBot confirms with "Google Docs connected as *your address*". The credential is saved locally as `gdocs.json`.
5. Verify any time with `/google_docs status` or `/cred status`.

The consent screen may warn about an unverified app. Docs uses the broad `drive` scope so the agent can open documents you already own, not only documents it created itself. This wider scope is what triggers the warning.

Connecting Google Docs grants Docs and Drive scopes to this credential only. Gmail, Google Calendar, Google Drive, and YouTube each have their own card, their own consent screen, and their own credential file. Connecting one Google service does not connect the others.

## How it connects

**Authentication.** OAuth 2.0 authorization code flow with PKCE, using the shared CraftOS Google client. Consent is requested with offline access, so CraftBot receives a refresh token along with the access token.

**Token refresh.** Access tokens expire after about an hour. Before each API call CraftBot checks the stored expiry and refreshes the token automatically with the refresh token, writing the new token back to `gdocs.json`. You only reconnect if Google revokes the refresh token, for example after a password change.

**No listener.** Docs does not poll or receive push notifications. The agent reads and edits documents only when a task calls for it.

## What the agent can do

All 33 Google Docs actions, grouped by domain. Each purpose comes from the action's registered description.

### Documents

| Action | Purpose |
|---|---|
| `create_google_doc` | Create a new blank Google Doc with the given title. Returns the document ID and editable URL |
| `get_google_doc` | Fetch a Google Doc. Default returns `{document_id, title, text}`; set `include_metadata` for the raw structured JSON needed for index-based edits |
| `get_google_doc_text` | Get a Google Doc as plain text. Returns title and the doc body flattened to a string |
| `list_google_docs` | List Google Docs the user owns or has access to, most recent first |
| `search_google_docs` | Search for Google Docs by title fragment |
| `delete_google_doc` | Move a Google Doc to the Drive trash |
| `copy_google_doc` | Copy an existing Google Doc to a new file with a new title |
| `export_google_doc` | Export a Google Doc to PDF, DOCX, ODT, plain text, or HTML and save to a local file path |

### Text editing

| Action | Purpose |
|---|---|
| `append_to_google_doc` | Append text to the end of a Google Doc |
| `insert_text_into_google_doc` | Insert text at a specific UTF-16 index in the document. Index 1 is the start of the body |
| `delete_google_doc_range` | Delete content in a range between `startIndex` and `endIndex` |
| `replace_google_doc_text` | Find-and-replace across the entire Google Doc body. Returns the number of occurrences changed |

### Styling and lists

| Action | Purpose |
|---|---|
| `style_google_doc_text` | Apply text-level styling (bold, italic, font size, color, link) to a range. Only supplied fields change |
| `style_google_doc_paragraph` | Apply paragraph-level styling (heading, alignment, line spacing) to a range |
| `create_google_doc_bullets` | Turn paragraphs in a range into a bulleted or numbered list |
| `delete_google_doc_bullets` | Remove bullet or numbered list formatting from a range |

### Tables

| Action | Purpose |
|---|---|
| `insert_google_doc_table` | Insert a new empty table at a specific document index |
| `insert_google_doc_table_row` | Insert a row above or below a table cell |
| `insert_google_doc_table_column` | Insert a column left or right of a table cell |
| `delete_google_doc_table_row` | Delete a row at the specified cell location |
| `delete_google_doc_table_column` | Delete a column at the specified cell location |
| `merge_google_doc_table_cells` | Merge a rectangular range of table cells into one |
| `unmerge_google_doc_table_cells` | Reverse a cell merge in a table range |

### Images and breaks

| Action | Purpose |
|---|---|
| `insert_google_doc_image` | Insert an inline image, referenced by public URI, at a document index |
| `replace_google_doc_image` | Replace an existing inline image with a new URI, keeping position and size |
| `insert_google_doc_page_break` | Insert a page break at a document index |
| `insert_google_doc_section_break` | Insert a section break (`NEXT_PAGE` or `CONTINUOUS`) at a document index |

### Headers, footers, and named ranges

| Action | Purpose |
|---|---|
| `create_google_doc_header` | Create a document header. Returns the header ID for further edits |
| `create_google_doc_footer` | Create a document footer. Returns the footer ID for further edits |
| `delete_google_doc_header` | Delete a header by its ID |
| `delete_google_doc_footer` | Delete a footer by its ID |
| `create_google_doc_named_range` | Create a named range over a document range so it can be referenced later |
| `delete_google_doc_named_range` | Delete a named range by name or by ID |

## Example requests

- "Create a Google Doc called Q3 Report, add a title heading, and paste in the summary I just wrote."
- "Find my doc called Onboarding Checklist and replace every mention of 'Slack' with 'Teams'."
- "Turn the list of tasks in my Project Plan doc into a numbered list and make the section titles bold."
- "Insert a 3-by-4 table at the top of my Budget doc and merge the first row into one cell."
- "Export my Meeting Notes doc to PDF and save it in my workspace."
- "Copy my Proposal Template into a new doc called Acme Proposal so I can edit it without touching the original."

## Configuration

- **Own OAuth app.** Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` as environment variables to use your own Google Cloud OAuth client instead of the embedded one. See [Credentials](credentials.md).
- **Credential file.** The token lives in `gdocs.json` in the local credential store. `/google_docs logout` removes it. The Google Workspace meta-integration writes this file too when you connect everything at once, so the two stay interchangeable.
- **Scope note.** Docs requests both the `documents` and the full `drive` scope. The wider Drive scope is required so the agent can open documents you already own, and it is why the consent screen shows the unverified-app warning.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Consent completes but CraftBot never confirms | Port `8765` is blocked or in use, so the redirect never arrived | Free the port and run `/google_docs login` again |
| Actions fail with "No google_docs credentials" | Not connected, or logged out | Connect from **Settings → Integrations** or run `/google_docs login` |
| Consent screen warns about an unverified app | Docs uses the broad `drive` scope by design | Continue past the warning to grant access, or verify your own OAuth app if self-hosting |
| A second `append_to_google_doc` duplicates text | Append is not idempotent, and a retry after a silent success inserts twice | Read the doc with `get_google_doc_text` before retrying an append that appeared to fail |
| Every request fails with 401 after working fine | Google revoked the refresh token (password change, security review) | `/google_docs logout`, then reconnect |

## Next

- [Google Drive](google-drive.md): manage the files and folders your documents live in
- [Gmail](gmail.md): the mail side of the same Google connection flow
- [Credentials](credentials.md): where the token lives and how refresh works
