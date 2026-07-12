from agent_core import action


# ------------------------------------------------------------------
# File-level: create / get / list / search / delete / copy / export
# Sub-set: google_docs_files
# ------------------------------------------------------------------


@action(
    name="create_google_doc",
    description="Create a new blank Google Doc with the given title. Returns the document ID and editable URL.",
    action_sets=["google_docs_files", "google_docs"],
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
    description="Fetch a Google Doc. Default returns {document_id, title, text} (body flattened to plain text); set include_metadata for the raw structured JSON (needed for index-based edits).",
    action_sets=["google_docs_files", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "The Google Doc's document ID.",
            "example": "1abcDEF...",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return the full structured document JSON (default false = plain text).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "google_docs",
        "get_document",
        unwrap_envelope=True,
        fail_message="Failed to fetch document.",
        document_id=input_data["document_id"],
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        doc = res.get("result")
        if isinstance(doc, dict):
            # Same flattening as the google_docs client's get_document_text.
            text_parts = []
            for elem in doc.get("body", {}).get("content", []) or []:
                para = elem.get("paragraph")
                if not para:
                    continue
                for run in para.get("elements") or []:
                    tr = run.get("textRun")
                    if tr and tr.get("content"):
                        text_parts.append(tr["content"])
            res = {
                **res,
                "result": {
                    "document_id": doc.get("documentId")
                    or input_data["document_id"],
                    "title": doc.get("title", ""),
                    "text": "".join(text_parts),
                },
            }
    return res


@action(
    name="get_google_doc_text",
    description="Get a Google Doc as plain text. Returns title and the doc body flattened to a string.",
    action_sets=["google_docs_files", "google_docs"],
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
    name="list_google_docs",
    description="List Google Docs the user owns or has access to, most recent first.",
    action_sets=["google_docs_files", "google_docs"],
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
    action_sets=["google_docs_files", "google_docs"],
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
    action_sets=["google_docs_files", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "The Google Doc's document ID.",
            "example": "1abcDEF...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
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


@action(
    name="copy_google_doc",
    description="Copy an existing Google Doc to a new file with a new title.",
    action_sets=["google_docs_files"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Source document ID.",
            "example": "1abcDEF...",
        },
        "new_title": {
            "type": "string",
            "description": "Title for the copy.",
            "example": "Meeting Notes (copy)",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def copy_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "copy_document",
        unwrap_envelope=True,
        fail_message="Failed to copy document.",
        document_id=input_data["document_id"],
        new_title=input_data["new_title"],
    )


@action(
    name="export_google_doc",
    description="Export a Google Doc to PDF, DOCX, ODT, plain text, or HTML and save to a local file path.",
    action_sets=["google_docs_files"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Source document ID.",
            "example": "1abcDEF...",
        },
        "mime_type": {
            "type": "string",
            "description": "Export MIME type. application/pdf | application/vnd.openxmlformats-officedocument.wordprocessingml.document | application/vnd.oasis.opendocument.text | text/plain | text/html.",
            "example": "application/pdf",
        },
        "dest_path": {
            "type": "string",
            "description": "Local file path to write to.",
            "example": "/tmp/doc.pdf",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def export_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "export_document",
        unwrap_envelope=True,
        fail_message="Failed to export document.",
        document_id=input_data["document_id"],
        mime_type=input_data["mime_type"],
        dest_path=input_data["dest_path"],
    )


# ------------------------------------------------------------------
# Content: insert / delete text, append, replace
# Sub-set: google_docs_content
# ------------------------------------------------------------------


@action(
    name="append_to_google_doc",
    description="Append text to the end of a Google Doc.",
    action_sets=["google_docs_content", "google_docs"],
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
    parallelizable=False,
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
    name="insert_text_into_google_doc",
    description="Insert text at a specific UTF-16 index in the document. Index 1 is the start of the body.",
    action_sets=["google_docs_content", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "text": {
            "type": "string",
            "description": "Text to insert.",
            "example": "Introduction\\n",
        },
        "index": {
            "type": "integer",
            "description": "Position (UTF-16 index). Index 1 = start of body.",
            "example": 1,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def insert_text_into_google_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "insert_text",
        unwrap_envelope=True,
        success_message="Text inserted.",
        fail_message="Failed to insert text.",
        document_id=input_data["document_id"],
        text=input_data["text"],
        index=input_data["index"],
    )


@action(
    name="delete_google_doc_range",
    description="Delete content in a range (between startIndex and endIndex).",
    action_sets=["google_docs_content", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "start_index": {
            "type": "integer",
            "description": "Start UTF-16 index (inclusive).",
            "example": 10,
        },
        "end_index": {
            "type": "integer",
            "description": "End UTF-16 index (exclusive).",
            "example": 30,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_doc_range(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_content_range",
        unwrap_envelope=True,
        success_message="Range deleted.",
        fail_message="Failed to delete range.",
        document_id=input_data["document_id"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
    )


@action(
    name="replace_google_doc_text",
    description="Find-and-replace across the entire Google Doc body. Returns the number of occurrences changed.",
    action_sets=["google_docs_content", "google_docs"],
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
    parallelizable=False,
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


# ------------------------------------------------------------------
# Styling: text + paragraph
# Sub-set: google_docs_styling
# ------------------------------------------------------------------


@action(
    name="style_google_doc_text",
    description="Apply text-level styling (bold, italic, font size, color, link) to a range. Only supplied fields change; others stay untouched.",
    action_sets=["google_docs_styling", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "start_index": {
            "type": "integer",
            "description": "Start UTF-16 index.",
            "example": 10,
        },
        "end_index": {
            "type": "integer",
            "description": "End UTF-16 index (exclusive).",
            "example": 30,
        },
        "bold": {"type": "boolean", "description": "Toggle bold.", "example": True},
        "italic": {
            "type": "boolean",
            "description": "Toggle italic.",
            "example": False,
        },
        "underline": {
            "type": "boolean",
            "description": "Toggle underline.",
            "example": False,
        },
        "strikethrough": {
            "type": "boolean",
            "description": "Toggle strikethrough.",
            "example": False,
        },
        "font_size_pt": {
            "type": "number",
            "description": "Font size in points.",
            "example": 14,
        },
        "font_family": {
            "type": "string",
            "description": "Font family name.",
            "example": "Arial",
        },
        "foreground_color_hex": {
            "type": "string",
            "description": "Foreground color (#RRGGBB).",
            "example": "#FF0000",
        },
        "background_color_hex": {
            "type": "string",
            "description": "Background color (#RRGGBB).",
            "example": "#FFFF00",
        },
        "link_url": {
            "type": "string",
            "description": "Turn range into a hyperlink to this URL.",
            "example": "https://example.com",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def style_google_doc_text(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "update_text_style",
        unwrap_envelope=True,
        success_message="Text styled.",
        fail_message="Failed to style text.",
        document_id=input_data["document_id"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
        bold=input_data.get("bold"),
        italic=input_data.get("italic"),
        underline=input_data.get("underline"),
        strikethrough=input_data.get("strikethrough"),
        font_size_pt=input_data.get("font_size_pt"),
        font_family=input_data.get("font_family") or None,
        foreground_color_hex=input_data.get("foreground_color_hex") or None,
        background_color_hex=input_data.get("background_color_hex") or None,
        link_url=input_data.get("link_url") or None,
    )


@action(
    name="style_google_doc_paragraph",
    description="Apply paragraph-level styling (heading, alignment, line spacing) to a range.",
    action_sets=["google_docs_styling", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "start_index": {
            "type": "integer",
            "description": "Start UTF-16 index.",
            "example": 1,
        },
        "end_index": {
            "type": "integer",
            "description": "End UTF-16 index (exclusive).",
            "example": 20,
        },
        "named_style_type": {
            "type": "string",
            "description": "NORMAL_TEXT | TITLE | SUBTITLE | HEADING_1..HEADING_6.",
            "example": "HEADING_1",
        },
        "alignment": {
            "type": "string",
            "description": "START | CENTER | END | JUSTIFIED.",
            "example": "CENTER",
        },
        "line_spacing": {
            "type": "number",
            "description": "Percentage (100 = single).",
            "example": 150,
        },
        "keep_with_next": {
            "type": "boolean",
            "description": "Keep with following paragraph.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def style_google_doc_paragraph(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "update_paragraph_style",
        unwrap_envelope=True,
        success_message="Paragraph styled.",
        fail_message="Failed to style paragraph.",
        document_id=input_data["document_id"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
        named_style_type=input_data.get("named_style_type") or None,
        alignment=input_data.get("alignment") or None,
        line_spacing=input_data.get("line_spacing"),
        keep_with_next=input_data.get("keep_with_next"),
    )


# ------------------------------------------------------------------
# Lists
# Sub-set: google_docs_lists
# ------------------------------------------------------------------


@action(
    name="create_google_doc_bullets",
    description="Turn paragraphs in a range into a bulleted or numbered list.",
    action_sets=["google_docs_lists"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "start_index": {
            "type": "integer",
            "description": "Start UTF-16 index.",
            "example": 10,
        },
        "end_index": {
            "type": "integer",
            "description": "End UTF-16 index.",
            "example": 60,
        },
        "bullet_preset": {
            "type": "string",
            "description": "BULLET_DISC_CIRCLE_SQUARE | NUMBERED_DECIMAL_NESTED | BULLET_CHECKBOX | NUMBERED_DECIMAL_ALPHA_ROMAN | BULLET_ARROW_DIAMOND_DISC.",
            "example": "BULLET_DISC_CIRCLE_SQUARE",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_google_doc_bullets(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "create_paragraph_bullets",
        unwrap_envelope=True,
        success_message="Bullets created.",
        fail_message="Failed to create bullets.",
        document_id=input_data["document_id"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
        bullet_preset=input_data.get("bullet_preset", "BULLET_DISC_CIRCLE_SQUARE"),
    )


@action(
    name="delete_google_doc_bullets",
    description="Remove bullet/numbered list formatting from a range.",
    action_sets=["google_docs_lists"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "start_index": {
            "type": "integer",
            "description": "Start UTF-16 index.",
            "example": 10,
        },
        "end_index": {
            "type": "integer",
            "description": "End UTF-16 index.",
            "example": 60,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_doc_bullets(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_paragraph_bullets",
        unwrap_envelope=True,
        success_message="Bullets removed.",
        fail_message="Failed to remove bullets.",
        document_id=input_data["document_id"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
    )


# ------------------------------------------------------------------
# Tables
# Sub-set: google_docs_tables
# ------------------------------------------------------------------


@action(
    name="insert_google_doc_table",
    description="Insert a new empty table at a specific document index.",
    action_sets=["google_docs_tables", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "rows": {"type": "integer", "description": "Number of rows.", "example": 3},
        "columns": {
            "type": "integer",
            "description": "Number of columns.",
            "example": 3,
        },
        "index": {
            "type": "integer",
            "description": "Position to insert at.",
            "example": 1,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def insert_google_doc_table(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "insert_table",
        unwrap_envelope=True,
        success_message="Table inserted.",
        fail_message="Failed to insert table.",
        document_id=input_data["document_id"],
        rows=input_data["rows"],
        columns=input_data["columns"],
        index=input_data["index"],
    )


@action(
    name="insert_google_doc_table_row",
    description="Insert a row above or below a table cell.",
    action_sets=["google_docs_tables"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "table_start_index": {
            "type": "integer",
            "description": "The table's start index in the document.",
            "example": 5,
        },
        "row_index": {
            "type": "integer",
            "description": "Reference cell row (0-based).",
            "example": 0,
        },
        "column_index": {
            "type": "integer",
            "description": "Reference cell column (0-based).",
            "example": 0,
        },
        "insert_below": {
            "type": "boolean",
            "description": "True = below, False = above.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def insert_google_doc_table_row(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "insert_table_row",
        unwrap_envelope=True,
        fail_message="Failed to insert row.",
        document_id=input_data["document_id"],
        table_start_index=input_data["table_start_index"],
        row_index=input_data["row_index"],
        column_index=input_data["column_index"],
        insert_below=input_data.get("insert_below", True),
    )


@action(
    name="insert_google_doc_table_column",
    description="Insert a column left or right of a table cell.",
    action_sets=["google_docs_tables"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "table_start_index": {
            "type": "integer",
            "description": "Table start index.",
            "example": 5,
        },
        "row_index": {
            "type": "integer",
            "description": "Reference cell row.",
            "example": 0,
        },
        "column_index": {
            "type": "integer",
            "description": "Reference cell column.",
            "example": 0,
        },
        "insert_right": {
            "type": "boolean",
            "description": "True = right, False = left.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def insert_google_doc_table_column(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "insert_table_column",
        unwrap_envelope=True,
        fail_message="Failed to insert column.",
        document_id=input_data["document_id"],
        table_start_index=input_data["table_start_index"],
        row_index=input_data["row_index"],
        column_index=input_data["column_index"],
        insert_right=input_data.get("insert_right", True),
    )


@action(
    name="delete_google_doc_table_row",
    description="Delete a row at the specified cell location.",
    action_sets=["google_docs_tables"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "table_start_index": {
            "type": "integer",
            "description": "Table start index.",
            "example": 5,
        },
        "row_index": {"type": "integer", "description": "Row to delete.", "example": 1},
        "column_index": {
            "type": "integer",
            "description": "Any column index in the row.",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_doc_table_row(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_table_row",
        unwrap_envelope=True,
        fail_message="Failed to delete row.",
        document_id=input_data["document_id"],
        table_start_index=input_data["table_start_index"],
        row_index=input_data["row_index"],
        column_index=input_data["column_index"],
    )


@action(
    name="delete_google_doc_table_column",
    description="Delete a column at the specified cell location.",
    action_sets=["google_docs_tables"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "table_start_index": {
            "type": "integer",
            "description": "Table start index.",
            "example": 5,
        },
        "row_index": {
            "type": "integer",
            "description": "Any row index in the column.",
            "example": 0,
        },
        "column_index": {
            "type": "integer",
            "description": "Column to delete.",
            "example": 1,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_doc_table_column(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_table_column",
        unwrap_envelope=True,
        fail_message="Failed to delete column.",
        document_id=input_data["document_id"],
        table_start_index=input_data["table_start_index"],
        row_index=input_data["row_index"],
        column_index=input_data["column_index"],
    )


@action(
    name="merge_google_doc_table_cells",
    description="Merge a rectangular range of table cells into one.",
    action_sets=["google_docs_tables"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "table_start_index": {
            "type": "integer",
            "description": "Table start index.",
            "example": 5,
        },
        "row_index": {
            "type": "integer",
            "description": "Top-left cell row.",
            "example": 0,
        },
        "column_index": {
            "type": "integer",
            "description": "Top-left cell column.",
            "example": 0,
        },
        "row_span": {"type": "integer", "description": "Rows to span.", "example": 2},
        "column_span": {
            "type": "integer",
            "description": "Columns to span.",
            "example": 2,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def merge_google_doc_table_cells(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "merge_table_cells",
        unwrap_envelope=True,
        fail_message="Failed to merge cells.",
        document_id=input_data["document_id"],
        table_start_index=input_data["table_start_index"],
        row_index=input_data["row_index"],
        column_index=input_data["column_index"],
        row_span=input_data["row_span"],
        column_span=input_data["column_span"],
    )


@action(
    name="unmerge_google_doc_table_cells",
    description="Reverse a cell merge in a table range.",
    action_sets=["google_docs_tables"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "table_start_index": {
            "type": "integer",
            "description": "Table start index.",
            "example": 5,
        },
        "row_index": {
            "type": "integer",
            "description": "Top-left cell row.",
            "example": 0,
        },
        "column_index": {
            "type": "integer",
            "description": "Top-left cell column.",
            "example": 0,
        },
        "row_span": {
            "type": "integer",
            "description": "Rows in merged region.",
            "example": 2,
        },
        "column_span": {
            "type": "integer",
            "description": "Columns in merged region.",
            "example": 2,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def unmerge_google_doc_table_cells(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "unmerge_table_cells",
        unwrap_envelope=True,
        fail_message="Failed to unmerge cells.",
        document_id=input_data["document_id"],
        table_start_index=input_data["table_start_index"],
        row_index=input_data["row_index"],
        column_index=input_data["column_index"],
        row_span=input_data["row_span"],
        column_span=input_data["column_span"],
    )


# ------------------------------------------------------------------
# Images
# Sub-set: google_docs_images
# ------------------------------------------------------------------


@action(
    name="insert_google_doc_image",
    description="Insert an inline image (referenced by public URI) at a document index.",
    action_sets=["google_docs_images", "google_docs"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "image_uri": {
            "type": "string",
            "description": "Publicly accessible image URL.",
            "example": "https://example.com/logo.png",
        },
        "index": {"type": "integer", "description": "Insertion index.", "example": 1},
        "width_pt": {
            "type": "number",
            "description": "Optional width in points.",
            "example": 200,
        },
        "height_pt": {
            "type": "number",
            "description": "Optional height in points.",
            "example": 150,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def insert_google_doc_image(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "insert_inline_image",
        unwrap_envelope=True,
        success_message="Image inserted.",
        fail_message="Failed to insert image.",
        document_id=input_data["document_id"],
        image_uri=input_data["image_uri"],
        index=input_data["index"],
        width_pt=input_data.get("width_pt"),
        height_pt=input_data.get("height_pt"),
    )


@action(
    name="replace_google_doc_image",
    description="Replace an existing inline image with a new URI (keeps position and size).",
    action_sets=["google_docs_images"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "image_object_id": {
            "type": "string",
            "description": "Inline image object ID.",
            "example": "kix.xxxx",
        },
        "image_uri": {
            "type": "string",
            "description": "New image URI.",
            "example": "https://example.com/new.png",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def replace_google_doc_image(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "replace_image",
        unwrap_envelope=True,
        success_message="Image replaced.",
        fail_message="Failed to replace image.",
        document_id=input_data["document_id"],
        image_object_id=input_data["image_object_id"],
        image_uri=input_data["image_uri"],
    )


# ------------------------------------------------------------------
# Structure: page/section breaks, headers/footers, named ranges
# Sub-set: google_docs_structure
# ------------------------------------------------------------------


@action(
    name="insert_google_doc_page_break",
    description="Insert a page break at a document index.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "index": {"type": "integer", "description": "Insertion index.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def insert_google_doc_page_break(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "insert_page_break",
        unwrap_envelope=True,
        success_message="Page break inserted.",
        fail_message="Failed to insert page break.",
        document_id=input_data["document_id"],
        index=input_data["index"],
    )


@action(
    name="insert_google_doc_section_break",
    description="Insert a section break (NEXT_PAGE or CONTINUOUS) at a document index.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "index": {"type": "integer", "description": "Insertion index.", "example": 1},
        "section_type": {
            "type": "string",
            "description": "NEXT_PAGE | CONTINUOUS.",
            "example": "NEXT_PAGE",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def insert_google_doc_section_break(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "insert_section_break",
        unwrap_envelope=True,
        success_message="Section break inserted.",
        fail_message="Failed to insert section break.",
        document_id=input_data["document_id"],
        index=input_data["index"],
        section_type=input_data.get("section_type", "NEXT_PAGE"),
    )


@action(
    name="create_google_doc_header",
    description="Create a document header. Returns the header ID for further edits.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "header_type": {
            "type": "string",
            "description": "DEFAULT | FIRST_PAGE_HEADER.",
            "example": "DEFAULT",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_google_doc_header(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "create_header",
        unwrap_envelope=True,
        success_message="Header created.",
        fail_message="Failed to create header.",
        document_id=input_data["document_id"],
        header_type=input_data.get("header_type", "DEFAULT"),
    )


@action(
    name="create_google_doc_footer",
    description="Create a document footer. Returns the footer ID for further edits.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "footer_type": {
            "type": "string",
            "description": "DEFAULT | FIRST_PAGE_FOOTER.",
            "example": "DEFAULT",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_google_doc_footer(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "create_footer",
        unwrap_envelope=True,
        success_message="Footer created.",
        fail_message="Failed to create footer.",
        document_id=input_data["document_id"],
        footer_type=input_data.get("footer_type", "DEFAULT"),
    )


@action(
    name="delete_google_doc_header",
    description="Delete a header by its ID.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "header_id": {
            "type": "string",
            "description": "Header ID.",
            "example": "kix.xxxx",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_doc_header(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_header",
        unwrap_envelope=True,
        success_message="Header deleted.",
        fail_message="Failed to delete header.",
        document_id=input_data["document_id"],
        header_id=input_data["header_id"],
    )


@action(
    name="delete_google_doc_footer",
    description="Delete a footer by its ID.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "footer_id": {
            "type": "string",
            "description": "Footer ID.",
            "example": "kix.xxxx",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_doc_footer(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_footer",
        unwrap_envelope=True,
        success_message="Footer deleted.",
        fail_message="Failed to delete footer.",
        document_id=input_data["document_id"],
        footer_id=input_data["footer_id"],
    )


@action(
    name="create_google_doc_named_range",
    description="Create a named range over a document range so it can be referenced later.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "name": {
            "type": "string",
            "description": "Range name.",
            "example": "intro_section",
        },
        "start_index": {
            "type": "integer",
            "description": "Start UTF-16 index.",
            "example": 1,
        },
        "end_index": {
            "type": "integer",
            "description": "End UTF-16 index.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_google_doc_named_range(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "create_named_range",
        unwrap_envelope=True,
        success_message="Named range created.",
        fail_message="Failed to create named range.",
        document_id=input_data["document_id"],
        name=input_data["name"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
    )


@action(
    name="delete_google_doc_named_range",
    description="Delete a named range by name or by ID.",
    action_sets=["google_docs_structure"],
    input_schema={
        "document_id": {
            "type": "string",
            "description": "Document ID.",
            "example": "1abcDEF...",
        },
        "name": {
            "type": "string",
            "description": "Range name to delete (one of name or id required).",
            "example": "intro_section",
        },
        "named_range_id": {
            "type": "string",
            "description": "Named range ID (alternative to name).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_google_doc_named_range(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_docs",
        "delete_named_range",
        unwrap_envelope=True,
        success_message="Named range deleted.",
        fail_message="Failed to delete named range.",
        document_id=input_data["document_id"],
        name=input_data.get("name") or None,
        named_range_id=input_data.get("named_range_id") or None,
    )
