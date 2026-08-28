# Notion — Integration Reference

REST integration via an internal integration token (or OAuth). Query and edit pages and databases. Query-only — does not listen for changes.

## Essentials

- **No event listening.** `supports_listening = False`. Notion will never push incoming messages to the router — it's request-response only. Don't promise the user "you'll be notified when X changes."
- **IDs are 36-char UUIDs with hyphens, not human-readable names.** Always `search_notion` first to resolve a name like "Roadmap" to its page or database ID.
- **`create_notion_page` requires `parent_type` AND matching `parent_id`.** `parent_type` is either `"page_id"` or `"database_id"`. Mismatched type → server-side failure. The parent must already exist.
- **Page content is Notion block JSON, not markdown.** `append_notion_page_content` expects rich Notion block objects (paragraph, heading_1, bulleted_list_item, etc.) — passing markdown silently fails. If the user gives markdown, the router must convert.
- **Database properties are typed nested objects, not flat strings.** Before `update_notion_page` on a database row, call `get_notion_database_schema` to learn each property's type (title vs rich_text vs select vs date), then build the correctly-shaped object.
- **An integration only sees pages it's been explicitly shared with.** "Notion can't find the page" usually means the user hasn't invited the integration to that page — direct them to the page's "..." → "Add connections" menu, not a retry.
