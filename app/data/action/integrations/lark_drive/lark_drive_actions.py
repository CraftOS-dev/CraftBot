from agent_core import action


@action(
    name="list_lark_drive_files",
    description="List files and folders in Lark Drive. Pass an empty folder_token to list the root.",
    action_sets=["lark_drive"],
    input_schema={
        "folder_token": {
            "type": "string",
            "description": "Folder token to list inside. Empty string lists the root.",
            "example": "",
        },
        "page_size": {
            "type": "integer",
            "description": "Max items to return (capped at 200).",
            "example": 50,
        },
        "page_token": {
            "type": "string",
            "description": "Pagination cursor from a previous response's next_page_token.",
            "example": "",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def list_lark_drive_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_drive",
        "list_files",
        folder_token=input_data.get("folder_token", ""),
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_drive_file_metadata",
    description="Fetch metadata for one or more Lark Drive file tokens.",
    action_sets=["lark_drive"],
    input_schema={
        "file_tokens": {
            "type": "array",
            "description": "List of file tokens to look up.",
            "example": ["boxcnabcdef0123"],
        },
        "doc_type": {
            "type": "string",
            "description": "Document type — 'file' (default), 'doc', 'docx', 'sheet', 'bitable', 'mindnote', 'slides'.",
            "example": "file",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def get_lark_drive_file_metadata(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_drive",
        "get_file_metadata",
        file_tokens=input_data["file_tokens"],
        doc_type=input_data.get("doc_type", "file"),
    )


@action(
    name="create_lark_drive_folder",
    description="Create a new folder in Lark Drive. Empty parent_folder_token creates at the root.",
    action_sets=["lark_drive"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Folder name.",
            "example": "Reports 2026",
        },
        "parent_folder_token": {
            "type": "string",
            "description": "Parent folder token. Empty string for root.",
            "example": "",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def create_lark_drive_folder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_drive",
        "create_folder",
        name=input_data["name"],
        parent_folder_token=input_data.get("parent_folder_token", ""),
    )


@action(
    name="upload_lark_drive_file",
    description="Upload a local file to a Lark Drive folder. Max 20MB — larger files require chunked upload (not yet supported).",
    action_sets=["lark_drive"],
    input_schema={
        "file_path": {
            "type": "string",
            "description": "Absolute path to the local file to upload.",
            "example": "/home/user/report.pdf",
        },
        "parent_folder_token": {
            "type": "string",
            "description": "Destination folder token in Lark Drive.",
            "example": "fldcnabcdef0123",
        },
        "file_name": {
            "type": "string",
            "description": "Name to give the file in Drive. Defaults to basename of file_path.",
            "example": "report.pdf",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def upload_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_drive",
        "upload_file",
        file_path=input_data["file_path"],
        parent_folder_token=input_data["parent_folder_token"],
        file_name=input_data.get("file_name", ""),
    )


@action(
    name="download_lark_drive_file",
    description="Download a file from Lark Drive to a local path.",
    action_sets=["lark_drive"],
    input_schema={
        "file_token": {
            "type": "string",
            "description": "Lark Drive file token.",
            "example": "boxcnabcdef0123",
        },
        "dest_path": {
            "type": "string",
            "description": "Absolute local path to write the file to.",
            "example": "/home/user/Downloads/report.pdf",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def download_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_drive",
        "download_file",
        file_token=input_data["file_token"],
        dest_path=input_data["dest_path"],
    )


@action(
    name="delete_lark_drive_file",
    description="Delete a file or folder from Lark Drive by token.",
    action_sets=["lark_drive"],
    input_schema={
        "file_token": {
            "type": "string",
            "description": "Lark Drive file token to delete.",
            "example": "boxcnabcdef0123",
        },
        "file_type": {
            "type": "string",
            "description": "Type — 'file' (default), 'folder', 'doc', 'docx', 'sheet', 'bitable', 'mindnote', 'shortcut', 'slides'.",
            "example": "file",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def delete_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_drive",
        "delete_file",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "file"),
    )


@action(
    name="search_lark_drive_files",
    description="Full-text search across files in Lark Drive that the bot has access to.",
    action_sets=["lark_drive"],
    input_schema={
        "search_key": {
            "type": "string",
            "description": "Search query string.",
            "example": "Q1 report",
        },
        "count": {
            "type": "integer",
            "description": "Max results to return (capped at 50).",
            "example": 20,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {"type": "object"},
    },
)
async def search_lark_drive_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "lark_drive",
        "search_files",
        search_key=input_data["search_key"],
        count=input_data.get("count", 20),
    )
