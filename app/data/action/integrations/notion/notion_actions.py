from agent_core import action


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


@action(
    name="get_notion_page",
    description="Get a Notion page by ID.",
    action_sets=["notion"],
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
    action_sets=["notion"],
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
    name="query_notion_database",
    description="Query a Notion database with optional filters and sorts.",
    action_sets=["notion"],
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
    name="update_notion_page",
    description="Update a Notion page's properties.",
    action_sets=["notion"],
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
    name="get_notion_database_schema",
    description="Get a Notion database schema by ID.",
    action_sets=["notion"],
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
    name="get_notion_page_content",
    description="Get the content blocks of a Notion page.",
    action_sets=["notion"],
    input_schema={
        "page_id": {"type": "string", "description": "Page ID.", "example": "abc123"},
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
    description="Append content blocks to a Notion page.",
    action_sets=["notion"],
    input_schema={
        "page_id": {"type": "string", "description": "Page ID.", "example": "abc123"},
        "children": {
            "type": "array",
            "description": "List of block objects.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def append_notion_page_content(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "notion",
        "append_block_children",
        block_id=input_data["page_id"],
        children=input_data["children"],
    )
