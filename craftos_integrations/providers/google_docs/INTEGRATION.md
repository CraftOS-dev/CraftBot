# Google Docs — Integration Reference

Create, read, edit, and search Google Docs on the user's Drive. Part of the Google Workspace bundle (shares OAuth shape with `gmail`, `google_calendar`, `google_drive`).

## Essentials

- **No event listening.** `supports_listening = False`. Docs will never push incoming changes — purely request-response.
- **Document IDs are 44+ char opaque strings** (embedded in URLs as `/document/d/{id}/edit`). Don't construct. Use `search_google_docs` (by title substring) or `list_google_docs` to discover.
- **`append_to_google_doc` is not idempotent.** It reads the current end-index, then inserts. If the append errored but actually succeeded server-side, retrying duplicates the text. Verify with `get_google_doc_text` before retrying.
- **`get_google_doc_text` flattens body text only.** Tables, images, and embedded objects are dropped. For structured reads use `get_google_doc` and walk the returned content tree.
- **`replace_google_doc_text` is `replaceAllText`** — every occurrence in the body is swapped at once, with no preview. Confirm scope with the user before broad replacements.
- **Session-level facts:** `cred.email` is the connected Google account. Never ask the user for it.
- **Scope warning:** the integration uses the broad `auth/drive` scope (not the narrower `drive.file`) so it can see docs the user owns even when not created by the integration. This is why the OAuth consent screen may warn the user about an "unverified app."
