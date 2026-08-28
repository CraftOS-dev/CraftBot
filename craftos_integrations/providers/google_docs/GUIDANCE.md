# Google Docs

Documents — create, read, edit, style, tables, images, export.

## Multi-account
- Every Google Docs action accepts an optional `account` (email, nickname,
  or a unique fragment like "work"). Omit it to use the primary account.
- When the user names an account in any form ("my school account", "the
  work Drive"), pass it as `account` — never silently default to primary.
- Document ids are **account-scoped**: an id returned by
  `list_google_docs` or `search_google_docs` with `account="work"` must be
  used with `account="work"` on every follow-up action
  (get/append/style/delete/export/etc.).
- For destructive actions (deletes, range deletes) with multiple accounts
  connected and no account named: ask the user which account before
  acting.

## Behavior
- Document IDs are long opaque strings (embedded in URLs as
  `/document/d/{id}/edit`). Never construct them — discover via
  `search_google_docs` (title fragment) or `list_google_docs`.
- `append_to_google_doc` is not idempotent: it reads the doc's current
  end-index, then inserts. If an append errored but may have landed
  server-side, verify with `get_google_doc_text` before retrying.
- `get_google_doc_text` (and the default `get_google_doc`) flatten body
  text only — tables, images, and embedded objects are dropped. For
  structured reads (needed for index-based edits) use `get_google_doc`
  with `include_metadata=true` and walk the returned content tree.
- `replace_google_doc_text` is `replaceAllText` — every occurrence in the
  body is swapped at once, with no preview. Confirm scope with the user
  before broad replacements.
- The connected account's email comes from the credential — never ask the
  user for it.
- Uses the broad Drive scope so list/search can see docs the user already
  owns (not just integration-created files); the OAuth consent screen may
  show an "unverified app" warning.
- No event listening — Docs is purely request-response.
