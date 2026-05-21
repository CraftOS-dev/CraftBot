from agent_core import action


@action(
    name="create_google_doc",
    description="Create a new blank Google Doc with the given title. Returns the document ID and editable URL.",
    action_sets=["google_docs"],
    input_schema={
        "title": {
            "type": "string",
            "description": "Title for the new document.",
            "example": "Meeting Notes",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def create_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "create_document",
        unwrap_envelope=True,
        fail_message="Failed to create Google Doc.",
        title=input_data["title"],
    )


@action(
    name="get_google_doc",
    description="Fetch the full structured content of a Google Doc.",
    action_sets=["google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "The Google Doc's document ID.",
            "example": "1abcDEF...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "get_document",
        unwrap_envelope=True,
        fail_message="Failed to fetch document.",
        document_id=input_data["document_id"],
    )


@action(
    name="get_google_doc_text",
    description="Get a Google Doc as plain text. Returns title and the doc body flattened to a string.",
    action_sets=["google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "The Google Doc's document ID.",
            "example": "1abcDEF...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_doc_text(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "get_document_text",
        unwrap_envelope=True,
        fail_message="Failed to read document.",
        document_id=input_data["document_id"],
    )


@action(
    name="append_to_google_doc",
    description="Append text to the end of a Google Doc.",
    action_sets=["google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "The Google Doc's document ID.",
            "example": "1abcDEF...",
        },
        "text": {
            "type": "string",
            "description": "Text to append.",
            "example": "\\n\\nFollow-up: ...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def append_to_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "append_text",
        unwrap_envelope=True,
        success_message="Text appended.",
        fail_message="Failed to append text.",
        document_id=input_data["document_id"],
        text=input_data["text"],
    )


@action(
    name="replace_google_doc_text",
    description="Find-and-replace across the entire Google Doc body. Returns the number of occurrences changed.",
    action_sets=["google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "The Google Doc's document ID.",
            "example": "1abcDEF...",
        },
        "find": {"type": "string", "description": "Text to find.", "example": "TODO"},
        "replace": {
            "type": "string",
            "description": "Replacement text.",
            "example": "DONE",
        },
        "match_case": {
            "type": "boolean",
            "description": "Whether the search is case-sensitive.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def replace_google_doc_text(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "replace_text",
        unwrap_envelope=True,
        fail_message="Failed to replace text.",
        document_id=input_data["document_id"],
        find=input_data["find"],
        replace=input_data["replace"],
        match_case=input_data.get("match_case", False),
    )


@action(
    name="list_google_docs",
    description="List Google Docs the user owns or has access to, most recent first.",
    action_sets=["google_docs"],
    input_schema={
        "max_results": {
            "type": "integer",
            "description": "Max number of docs to return.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_google_docs(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "list_documents",
        unwrap_envelope=True,
        fail_message="Failed to list docs.",
        max_results=input_data.get("max_results", 50),
    )


@action(
    name="search_google_docs",
    description="Search for Google Docs by title fragment.",
    action_sets=["google_docs"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Title fragment to search for.",
            "example": "Meeting",
        },
        "max_results": {
            "type": "integer",
            "description": "Max number of docs to return.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_google_docs(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "search_documents",
        unwrap_envelope=True,
        fail_message="Failed to search docs.",
        query=input_data["query"],
        max_results=input_data.get("max_results", 50),
    )


@action(
    name="delete_google_doc",
    description="Move a Google Doc to the Drive trash.",
    action_sets=["google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "The Google Doc's document ID.",
            "example": "1abcDEF...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def delete_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_document",
        unwrap_envelope=True,
        success_message="Document deleted.",
        fail_message="Failed to delete document.",
        document_id=input_data["document_id"],
    )
