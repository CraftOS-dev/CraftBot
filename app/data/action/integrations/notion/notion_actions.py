from agent_core import action


# ------------------------------------------------------------------
# Search (workspace-wide)
# ------------------------------------------------------------------


@action(
    name="search_notion",
    description="Search Notion workspace for pages and databases.",
    action_sets=["notion"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Search query.",
            "example": "meeting notes",
        },
        "filter_type": {
            "type": "string",
            "description": "Optional: 'page' or 'database'.",
            "example": "page",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_notion(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "search",
        query=input_data["query"],
        filter_type=input_data.get("filter_type"),
    )


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------


@action(
    name="get_notion_page",
    description="Get a Notion page by ID (returns metadata + properties, not block content).",
    action_sets=["notion_pages", "notion"],
    input_schema={
        "page_id": {
            "type": "string",
            "description": "Notion page ID.",
            "example": "abc123",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_notion_page(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("notion", "get_page", page_id=input_data["page_id"])


@action(
    name="create_notion_page",
    description="Create a new page in Notion.",
    action_sets=["notion_pages", "notion"],
    input_schema={
        "parent_id": {
            "type": "string",
            "description": "Parent page or database ID.",
            "example": "abc123",
        },
        "parent_type": {
            "type": "string",
            "description": "'page_id' or 'database_id'.",
            "example": "page_id",
        },
        "properties": {
            "type": "object",
            "description": "Page properties.",
            "example": {"title": [{"text": {"content": "New Page"}}]},
        },
        "children": {
            "type": "array",
            "description": "Optional content blocks.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_notion_page(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "create_page",
        parent_id=input_data["parent_id"],
        parent_type=input_data["parent_type"],
        properties=input_data["properties"],
        children=input_data.get("children"),
    )


@action(
    name="update_notion_page",
    description="Update a Notion page's properties (and/or archive state).",
    action_sets=["notion_pages", "notion"],
    input_schema={
        "page_id": {
            "type": "string",
            "description": "Page ID to update.",
            "example": "abc123",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {},
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_notion_page(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "update_page",
        page_id=input_data["page_id"],
        properties=input_data["properties"],
    )


@action(
    name="archive_notion_page",
    description="Archive a Notion page (send to trash). Reversible via restore_notion_page.",
    action_sets=["notion_pages", "notion"],
    input_schema={
        "page_id": {"type": "string", "description": "Page ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def archive_notion_page(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("notion", "archive_page", page_id=input_data["page_id"])


@action(
    name="restore_notion_page",
    description="Restore a previously-archived Notion page.",
    action_sets=["notion_pages"],
    input_schema={
        "page_id": {"type": "string", "description": "Page ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def restore_notion_page(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("notion", "restore_page", page_id=input_data["page_id"])


@action(
    name="get_notion_page_property",
    description="Get a single page property's value. For rollup/relation/people properties that paginate, this returns the full list.",
    action_sets=["notion_pages"],
    input_schema={
        "page_id": {"type": "string", "description": "Page ID.", "example": ""},
        "property_id": {
            "type": "string",
            "description": "Property ID (from page schema).",
            "example": "",
        },
        "page_size": {
            "type": "integer",
            "description": "Pagination size.",
            "example": 100,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_notion_page_property(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "get_page_property",
        page_id=input_data["page_id"],
        property_id=input_data["property_id"],
        page_size=input_data.get("page_size", 100),
    )


# ------------------------------------------------------------------
# Databases
# ------------------------------------------------------------------


@action(
    name="get_notion_database_schema",
    description="Get a Notion database schema by ID.",
    action_sets=["notion_databases", "notion"],
    input_schema={
        "database_id": {
            "type": "string",
            "description": "Database ID.",
            "example": "abc123",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "database": {"type": "object"},
    },
)
def get_notion_database_schema(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion", "get_database", database_id=input_data["database_id"]
    )


@action(
    name="query_notion_database",
    description="Query a Notion database with optional filters and sorts.",
    action_sets=["notion_databases", "notion"],
    input_schema={
        "database_id": {
            "type": "string",
            "description": "Database ID.",
            "example": "abc123",
        },
        "filter": {
            "type": "object",
            "description": "Optional Notion filter object.",
            "example": {},
        },
        "sorts": {
            "type": "array",
            "description": "Optional sort array.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def query_notion_database(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "query_database",
        database_id=input_data["database_id"],
        filter_obj=input_data.get("filter"),
        sorts=input_data.get("sorts"),
    )


@action(
    name="create_notion_database",
    description="Create a new database under a parent page. Schema goes in 'properties' (each value is a property type config like {'title': {}} / {'rich_text': {}} / {'select': {'options': [...]}}).",
    action_sets=["notion_databases", "notion"],
    input_schema={
        "parent_page_id": {
            "type": "string",
            "description": "Parent page ID.",
            "example": "",
        },
        "title": {
            "type": "array",
            "description": "Title rich_text array.",
            "example": [{"text": {"content": "Tasks"}}],
        },
        "description": {
            "type": "array",
            "description": "Description rich_text array (optional).",
            "example": [],
        },
        "properties": {
            "type": "object",
            "description": "Property schema (column definitions). Required.",
            "example": {"Name": {"title": {}}},
        },
        "is_inline": {
            "type": "boolean",
            "description": "Render inline.",
            "example": False,
        },
        "icon": {
            "type": "object",
            "description": "Icon (optional). e.g. {'type':'emoji','emoji':'📋'}.",
            "example": {},
        },
        "cover": {"type": "object", "description": "Cover (optional).", "example": {}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_notion_database(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "create_database",
        parent_page_id=input_data["parent_page_id"],
        title=input_data.get("title"),
        description=input_data.get("description"),
        properties=input_data.get("properties"),
        is_inline=bool(input_data.get("is_inline", False)),
        icon=input_data.get("icon") or None,
        cover=input_data.get("cover") or None,
    )


@action(
    name="update_notion_database",
    description="Update a Notion database (title, description, schema, inline state).",
    action_sets=["notion_databases", "notion"],
    input_schema={
        "database_id": {"type": "string", "description": "Database ID.", "example": ""},
        "title": {
            "type": "array",
            "description": "New title rich_text (optional).",
            "example": [],
        },
        "description": {
            "type": "array",
            "description": "New description rich_text (optional).",
            "example": [],
        },
        "properties": {
            "type": "object",
            "description": "Property updates (rename / change type / remove with null) (optional).",
            "example": {},
        },
        "is_inline": {
            "type": "boolean",
            "description": "Set inline (optional).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_notion_database(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "update_database",
        database_id=input_data["database_id"],
        title=input_data.get("title"),
        description=input_data.get("description"),
        properties=input_data.get("properties"),
        is_inline=input_data["is_inline"] if "is_inline" in input_data else None,
    )


@action(
    name="archive_notion_database",
    description="Archive a Notion database.",
    action_sets=["notion_databases"],
    input_schema={
        "database_id": {"type": "string", "description": "Database ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def archive_notion_database(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion", "archive_database", database_id=input_data["database_id"]
    )


@action(
    name="restore_notion_database",
    description="Restore an archived Notion database.",
    action_sets=["notion_databases"],
    input_schema={
        "database_id": {"type": "string", "description": "Database ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def restore_notion_database(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion", "restore_database", database_id=input_data["database_id"]
    )


# ------------------------------------------------------------------
# Blocks
# ------------------------------------------------------------------


@action(
    name="get_notion_page_content",
    description="Get the content blocks of a Notion page (or any block that has children).",
    action_sets=["notion_blocks", "notion"],
    input_schema={
        "page_id": {
            "type": "string",
            "description": "Page ID (or block ID for nested children).",
            "example": "abc123",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "content": {"type": "array"},
    },
)
def get_notion_page_content(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion", "get_block_children", block_id=input_data["page_id"]
    )


@action(
    name="append_notion_page_content",
    description="Append content blocks to a Notion page (or any block).",
    action_sets=["notion_blocks", "notion"],
    input_schema={
        "page_id": {
            "type": "string",
            "description": "Page ID (or block ID).",
            "example": "abc123",
        },
        "children": {
            "type": "array",
            "description": "List of block objects.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def append_notion_page_content(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "append_block_children",
        block_id=input_data["page_id"],
        children=input_data["children"],
    )


@action(
    name="get_notion_block",
    description="Get a single block (not its children) by block ID.",
    action_sets=["notion_blocks", "notion"],
    input_schema={
        "block_id": {"type": "string", "description": "Block ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_notion_block(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("notion", "get_block", block_id=input_data["block_id"])


@action(
    name="update_notion_block",
    description="Update a block's content. block_update has the per-block-type key as the top-level field, e.g. {'to_do': {'rich_text': [...], 'checked': true}} for a to-do, {'paragraph': {'rich_text': [...]}} for a paragraph. Pass {'in_trash': true} to soft-delete.",
    action_sets=["notion_blocks", "notion"],
    input_schema={
        "block_id": {"type": "string", "description": "Block ID.", "example": ""},
        "block_update": {
            "type": "object",
            "description": "Per-block-type update object.",
            "example": {"paragraph": {"rich_text": [{"text": {"content": "Updated"}}]}},
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_notion_block(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "update_block",
        block_id=input_data["block_id"],
        block_update=input_data["block_update"],
    )


@action(
    name="delete_notion_block",
    description="Delete (soft delete, send to trash) a Notion block.",
    action_sets=["notion_blocks", "notion"],
    input_schema={
        "block_id": {"type": "string", "description": "Block ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_notion_block(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("notion", "delete_block", block_id=input_data["block_id"])


# ------------------------------------------------------------------
# Comments
# ------------------------------------------------------------------


@action(
    name="list_notion_comments",
    description="List comments on a page or block.",
    action_sets=["notion_comments", "notion"],
    input_schema={
        "block_id": {
            "type": "string",
            "description": "Block or page ID.",
            "example": "",
        },
        "page_size": {"type": "integer", "description": "Max results.", "example": 100},
        "start_cursor": {
            "type": "string",
            "description": "Pagination cursor (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_notion_comments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "list_comments",
        block_id=input_data["block_id"],
        page_size=input_data.get("page_size", 100),
        start_cursor=input_data.get("start_cursor") or None,
    )


@action(
    name="create_notion_comment",
    description="Post a comment on a page/block, or reply in a discussion. Provide exactly one of parent_page_id, parent_block_id, or discussion_id.",
    action_sets=["notion_comments", "notion"],
    input_schema={
        "rich_text": {
            "type": "array",
            "description": "Comment content as rich_text array.",
            "example": [{"text": {"content": "Looks good!"}}],
        },
        "parent_page_id": {
            "type": "string",
            "description": "Page ID for a new top-level discussion (optional).",
            "example": "",
        },
        "parent_block_id": {
            "type": "string",
            "description": "Block ID for a new top-level discussion (optional).",
            "example": "",
        },
        "discussion_id": {
            "type": "string",
            "description": "Discussion ID to reply to (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_notion_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "create_comment",
        rich_text=input_data["rich_text"],
        parent_page_id=input_data.get("parent_page_id") or None,
        parent_block_id=input_data.get("parent_block_id") or None,
        discussion_id=input_data.get("discussion_id") or None,
    )


# ------------------------------------------------------------------
# Users
# ------------------------------------------------------------------


@action(
    name="list_notion_users",
    description="List workspace members visible to the integration.",
    action_sets=["notion_users", "notion"],
    input_schema={
        "page_size": {"type": "integer", "description": "Max results.", "example": 100},
        "start_cursor": {
            "type": "string",
            "description": "Pagination cursor (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_notion_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "list_users",
        page_size=input_data.get("page_size", 100),
        start_cursor=input_data.get("start_cursor") or None,
    )


@action(
    name="get_notion_user",
    description="Get a single Notion user by ID.",
    action_sets=["notion_users", "notion"],
    input_schema={
        "user_id": {"type": "string", "description": "User ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_notion_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("notion", "get_user", user_id=input_data["user_id"])


@action(
    name="get_notion_bot_info",
    description="Get info about the authenticated Notion bot (workspace_name, owner, capabilities).",
    action_sets=["notion_users", "notion"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_notion_bot_info(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync("notion", "get_bot_info")


# ------------------------------------------------------------------
# File uploads
# ------------------------------------------------------------------


@action(
    name="upload_notion_file",
    description="High-level: upload a local file in one call (single-part). Returns the file_upload object with id+status='uploaded'. Attach to a block via {'type':'file_upload','file_upload':{'id': <id>}}. Use multi-part flow for files >20 MB.",
    action_sets=["notion_files", "notion"],
    input_schema={
        "file_path": {
            "type": "string",
            "description": "Absolute path to local file.",
            "example": "C:/Users/me/report.pdf",
        },
        "content_type": {
            "type": "string",
            "description": "MIME type (autodetect if omitted).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def upload_notion_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "upload_local_file",
        file_path=input_data["file_path"],
        content_type=input_data.get("content_type") or None,
    )


@action(
    name="create_notion_file_upload",
    description="Step 1 of file upload: initialise a file_upload resource. Returns id + upload_url. Use mode=single_part for <20 MB, multi_part for larger, or external_url to import from a URL.",
    action_sets=["notion_files"],
    input_schema={
        "mode": {
            "type": "string",
            "description": "single_part | multi_part | external_url.",
            "example": "single_part",
        },
        "filename": {
            "type": "string",
            "description": "Required for multi_part.",
            "example": "",
        },
        "content_type": {
            "type": "string",
            "description": "MIME type (recommended).",
            "example": "",
        },
        "number_of_parts": {
            "type": "integer",
            "description": "Required for multi_part.",
            "example": 0,
        },
        "external_url": {
            "type": "string",
            "description": "Required for external_url mode.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_notion_file_upload(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    parts = input_data.get("number_of_parts")
    return run_client_sync(
        "notion",
        "create_file_upload",
        mode=input_data.get("mode", "single_part"),
        filename=input_data.get("filename") or None,
        content_type=input_data.get("content_type") or None,
        number_of_parts=parts if parts else None,
        external_url=input_data.get("external_url") or None,
    )


@action(
    name="send_notion_file_upload",
    description="Step 2: send file bytes to a pending file_upload. For multi_part uploads, repeat with each part_number.",
    action_sets=["notion_files"],
    input_schema={
        "file_upload_id": {
            "type": "string",
            "description": "ID from create_notion_file_upload.",
            "example": "",
        },
        "file_path": {
            "type": "string",
            "description": "Absolute path to local file (or one part for multi_part).",
            "example": "",
        },
        "part_number": {
            "type": "integer",
            "description": "1..1000, only for multi_part.",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_notion_file_upload(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    pn = input_data.get("part_number")
    return run_client_sync(
        "notion",
        "send_file_upload",
        file_upload_id=input_data["file_upload_id"],
        file_path=input_data["file_path"],
        part_number=pn if pn else None,
    )


@action(
    name="complete_notion_file_upload",
    description="Step 3 (multi_part only): finalize a multi-part upload after all parts sent.",
    action_sets=["notion_files"],
    input_schema={
        "file_upload_id": {
            "type": "string",
            "description": "File upload ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def complete_notion_file_upload(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "complete_file_upload",
        file_upload_id=input_data["file_upload_id"],
    )


@action(
    name="get_notion_file_upload",
    description="Get the current status of a file upload.",
    action_sets=["notion_files"],
    input_schema={
        "file_upload_id": {
            "type": "string",
            "description": "File upload ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_notion_file_upload(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "get_file_upload",
        file_upload_id=input_data["file_upload_id"],
    )


@action(
    name="list_notion_file_uploads",
    description="List file uploads created by this integration. Filter by status (pending|uploaded|expired|failed).",
    action_sets=["notion_files"],
    input_schema={
        "status": {
            "type": "string",
            "description": "Filter (optional).",
            "example": "",
        },
        "page_size": {"type": "integer", "description": "Max results.", "example": 100},
        "start_cursor": {
            "type": "string",
            "description": "Pagination cursor (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_notion_file_uploads(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "list_file_uploads",
        status=input_data.get("status") or None,
        page_size=input_data.get("page_size", 100),
        start_cursor=input_data.get("start_cursor") or None,
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Data sources (multi-source databases) sub-resource
#     Newer feature; the standard property-on-database surface covers the
#     common single-source case. Add when an agent task actually needs it.
# - OAuth invite / token refresh endpoints
#     Handled by the integration handler (/notion invite/login), not as
#     per-task actions.
# - Direct upload_url PUT (signed S3 URL approach)
#     The send_file_upload helper covers the realistic case; signed-URL
#     PUT is reserved for very large multi-part flows.
# - Workspace settings / sharing / page permissions
#     Notion does not expose these via REST; they're UI-only.
