# Lark Drive — Integration Reference

Files and folders in Lark Drive via the same Custom App as `lark` and `lark_calendar`. Backs Lark Docs, Sheets, and Bitable internally.

## Essentials

- **No event listening.** `supports_listening = False`. File-change events are not pushed — request-response only.
- **`folder_token` empty string = the user's Drive root.** No "/" path — pass `""` to list root.
- **All identifiers are opaque tokens, not paths.** `file_token` and `folder_token` are Lark-generated strings; there are no human-readable paths. Always `list_lark_drive_files` or `search_lark_drive_files` to resolve names → tokens before any operation.
- **`delete_lark_drive_file` requires the correct `file_type`.** Values: `file`, `folder`, `doc`, `docx`, `sheet`, `bitable`, `mindnote`, `shortcut`, `slides`. Mismatched type silently fails — get the type from `get_lark_drive_file_metadata` first if unsure.
- **Pagination:** pass returned `next_page_token` back until `has_more` is false. The router shouldn't assume the first page is the full list.
- **Upload cap is 20MB.** Larger files would need chunked upload, which the integration does NOT yet implement. Tell the user up-front rather than retrying after a failure.
- **Same Custom App as `lark` / `lark_calendar`** — App ID + Secret are pasted into each service separately (independent connect/disconnect tiles).
