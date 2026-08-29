"""Google Docs operations — schemas for google_docs_actions.py.

Faithful port: names, descriptions, schemas, arg mapping, and result
shaping match the actions one-to-one. Deletes are flagged
``destructive=True`` (wrong-account mistakes can't be undone through the
API) and stay ``parallelizable=False`` like the actions.

NOTE: no operation declares an ``account`` input — the host adapter
injects it on every generated action and the core resolves it centrally
(conformance-enforced).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ...contracts import Operation
from .._shared import STATUS_OUTPUT, client_op, shape_result

_DOC_ID = {
    "type": "string",
    "description": "The Google Doc's document ID.",
    "example": "1abcDEF...",
}
_DOC_ID_SHORT = {
    "type": "string",
    "description": "Document ID.",
    "example": "1abcDEF...",
}


def _get_google_doc_op() -> Operation:
    """``get_google_doc`` needs post-processing (the include_metadata
    flatten), so it is hand-written instead of using ``client_op``.

    Behavior matches the action: default returns the body
    flattened to plain text (the client's ``get_document_text`` uses the
    identical flattening); ``include_metadata=True`` returns the raw
    structured document JSON from ``get_document``.
    """

    input_schema = {
        "document_id": dict(_DOC_ID),
        "include_metadata": {
            "type": "boolean",
            "description": (
                "Return the full structured document JSON (default false = plain text)."
            ),
            "example": False,
        },
    }

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if input_data.get("include_metadata"):
                raw = await asyncio.to_thread(
                    client.get_document, document_id=input_data["document_id"]
                )
            else:
                raw = await asyncio.to_thread(
                    client.get_document_text, document_id=input_data["document_id"]
                )
            return shape_result(
                raw,
                unwrap_envelope=True,
                fail_message="Failed to fetch document.",
            )
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return Operation(
        name="get_google_doc",
        description=(
            "Fetch a Google Doc. Default returns {document_id, title, text} "
            "(body flattened to plain text); set include_metadata for the raw "
            "structured JSON (needed for index-based edits)."
        ),
        input_schema=input_schema,
        output_schema=dict(STATUS_OUTPUT),
        fn=fn,
        tags=("google_docs_files", "google_docs"),
    )


def build_operations() -> List[Operation]:
    return [
        # ── File-level: create / get / list / search / delete / copy / export
        client_op(
            "create_google_doc",
            "create_document",
            description=(
                "Create a new blank Google Doc with the given title. Returns "
                "the document ID and editable URL."
            ),
            tags=("google_docs_files", "google_docs"),
            unwrap_envelope=True,
            fail_message="Failed to create Google Doc.",
            input_schema={
                "title": {
                    "type": "string",
                    "description": "Title for the new document.",
                    "example": "Meeting Notes",
                },
            },
        ),
        _get_google_doc_op(),
        client_op(
            "get_google_doc_text",
            "get_document_text",
            description=(
                "Get a Google Doc as plain text. Returns title and the doc "
                "body flattened to a string."
            ),
            tags=("google_docs_files", "google_docs"),
            unwrap_envelope=True,
            fail_message="Failed to read document.",
            input_schema={"document_id": dict(_DOC_ID)},
        ),
        client_op(
            "list_google_docs",
            "list_documents",
            description=(
                "List Google Docs the user owns or has access to, most recent first."
            ),
            tags=("google_docs_files", "google_docs"),
            unwrap_envelope=True,
            fail_message="Failed to list docs.",
            input_schema={
                "max_results": {
                    "type": "integer",
                    "description": "Max number of docs to return.",
                    "example": 50,
                },
            },
            arg_map=lambda d: {"max_results": d.get("max_results", 50)},
        ),
        client_op(
            "search_google_docs",
            "search_documents",
            description="Search for Google Docs by title fragment.",
            tags=("google_docs_files", "google_docs"),
            unwrap_envelope=True,
            fail_message="Failed to search docs.",
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
            arg_map=lambda d: {
                "query": d["query"],
                "max_results": d.get("max_results", 50),
            },
        ),
        client_op(
            "delete_google_doc",
            "delete_document",
            description="Move a Google Doc to the Drive trash.",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_files", "google_docs"),
            unwrap_envelope=True,
            success_message="Document deleted.",
            fail_message="Failed to delete document.",
            input_schema={"document_id": dict(_DOC_ID)},
        ),
        client_op(
            "copy_google_doc",
            "copy_document",
            description="Copy an existing Google Doc to a new file with a new title.",
            parallelizable=False,
            tags=("google_docs_files",),
            unwrap_envelope=True,
            fail_message="Failed to copy document.",
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
        ),
        client_op(
            "export_google_doc",
            "export_document",
            description=(
                "Export a Google Doc to PDF, DOCX, ODT, plain text, or HTML "
                "and save to a local file path."
            ),
            tags=("google_docs_files",),
            unwrap_envelope=True,
            fail_message="Failed to export document.",
            input_schema={
                "document_id": {
                    "type": "string",
                    "description": "Source document ID.",
                    "example": "1abcDEF...",
                },
                "mime_type": {
                    "type": "string",
                    "description": (
                        "Export MIME type. application/pdf | "
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document | "
                        "application/vnd.oasis.opendocument.text | "
                        "text/plain | text/html."
                    ),
                    "example": "application/pdf",
                },
                "dest_path": {
                    "type": "string",
                    "description": "Local file path to write to.",
                    "example": "/tmp/doc.pdf",
                },
            },
        ),
        # ── Content: insert / delete text, append, replace ────────────────
        client_op(
            "append_to_google_doc",
            "append_text",
            description="Append text to the end of a Google Doc.",
            parallelizable=False,
            tags=("google_docs_content", "google_docs"),
            unwrap_envelope=True,
            success_message="Text appended.",
            fail_message="Failed to append text.",
            input_schema={
                "document_id": dict(_DOC_ID),
                "text": {
                    "type": "string",
                    "description": "Text to append.",
                    "example": "\\n\\nFollow-up: ...",
                },
            },
        ),
        client_op(
            "insert_text_into_google_doc",
            "insert_text",
            description=(
                "Insert text at a specific UTF-16 index in the document. "
                "Index 1 is the start of the body."
            ),
            parallelizable=False,
            tags=("google_docs_content", "google_docs"),
            unwrap_envelope=True,
            success_message="Text inserted.",
            fail_message="Failed to insert text.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
        ),
        client_op(
            "delete_google_doc_range",
            "delete_content_range",
            description="Delete content in a range (between startIndex and endIndex).",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_content", "google_docs"),
            unwrap_envelope=True,
            success_message="Range deleted.",
            fail_message="Failed to delete range.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
        ),
        client_op(
            "replace_google_doc_text",
            "replace_text",
            description=(
                "Find-and-replace across the entire Google Doc body. Returns "
                "the number of occurrences changed."
            ),
            parallelizable=False,
            tags=("google_docs_content", "google_docs"),
            unwrap_envelope=True,
            fail_message="Failed to replace text.",
            input_schema={
                "document_id": dict(_DOC_ID),
                "find": {
                    "type": "string",
                    "description": "Text to find.",
                    "example": "TODO",
                },
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
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "find": d["find"],
                "replace": d["replace"],
                "match_case": d.get("match_case", False),
            },
        ),
        # ── Styling: text + paragraph ─────────────────────────────────────
        client_op(
            "style_google_doc_text",
            "update_text_style",
            description=(
                "Apply text-level styling (bold, italic, font size, color, "
                "link) to a range. Only supplied fields change; others stay "
                "untouched."
            ),
            parallelizable=False,
            tags=("google_docs_styling", "google_docs"),
            unwrap_envelope=True,
            success_message="Text styled.",
            fail_message="Failed to style text.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
                "bold": {
                    "type": "boolean",
                    "description": "Toggle bold.",
                    "example": True,
                },
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
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "start_index": d["start_index"],
                "end_index": d["end_index"],
                "bold": d.get("bold"),
                "italic": d.get("italic"),
                "underline": d.get("underline"),
                "strikethrough": d.get("strikethrough"),
                "font_size_pt": d.get("font_size_pt"),
                "font_family": d.get("font_family") or None,
                "foreground_color_hex": d.get("foreground_color_hex") or None,
                "background_color_hex": d.get("background_color_hex") or None,
                "link_url": d.get("link_url") or None,
            },
        ),
        client_op(
            "style_google_doc_paragraph",
            "update_paragraph_style",
            description=(
                "Apply paragraph-level styling (heading, alignment, line "
                "spacing) to a range."
            ),
            parallelizable=False,
            tags=("google_docs_styling", "google_docs"),
            unwrap_envelope=True,
            success_message="Paragraph styled.",
            fail_message="Failed to style paragraph.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "start_index": d["start_index"],
                "end_index": d["end_index"],
                "named_style_type": d.get("named_style_type") or None,
                "alignment": d.get("alignment") or None,
                "line_spacing": d.get("line_spacing"),
                "keep_with_next": d.get("keep_with_next"),
            },
        ),
        # ── Lists ─────────────────────────────────────────────────────────
        client_op(
            "create_google_doc_bullets",
            "create_paragraph_bullets",
            description="Turn paragraphs in a range into a bulleted or numbered list.",
            parallelizable=False,
            tags=("google_docs_lists",),
            unwrap_envelope=True,
            success_message="Bullets created.",
            fail_message="Failed to create bullets.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
                    "description": (
                        "BULLET_DISC_CIRCLE_SQUARE | NUMBERED_DECIMAL_NESTED | "
                        "BULLET_CHECKBOX | NUMBERED_DECIMAL_ALPHA_ROMAN | "
                        "BULLET_ARROW_DIAMOND_DISC."
                    ),
                    "example": "BULLET_DISC_CIRCLE_SQUARE",
                },
            },
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "start_index": d["start_index"],
                "end_index": d["end_index"],
                "bullet_preset": d.get("bullet_preset", "BULLET_DISC_CIRCLE_SQUARE"),
            },
        ),
        client_op(
            "delete_google_doc_bullets",
            "delete_paragraph_bullets",
            description="Remove bullet/numbered list formatting from a range.",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_lists",),
            unwrap_envelope=True,
            success_message="Bullets removed.",
            fail_message="Failed to remove bullets.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
        ),
        # ── Tables ────────────────────────────────────────────────────────
        client_op(
            "insert_google_doc_table",
            "insert_table",
            description="Insert a new empty table at a specific document index.",
            parallelizable=False,
            tags=("google_docs_tables", "google_docs"),
            unwrap_envelope=True,
            success_message="Table inserted.",
            fail_message="Failed to insert table.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "rows": {
                    "type": "integer",
                    "description": "Number of rows.",
                    "example": 3,
                },
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
        ),
        client_op(
            "insert_google_doc_table_row",
            "insert_table_row",
            description="Insert a row above or below a table cell.",
            parallelizable=False,
            tags=("google_docs_tables",),
            unwrap_envelope=True,
            fail_message="Failed to insert row.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "table_start_index": d["table_start_index"],
                "row_index": d["row_index"],
                "column_index": d["column_index"],
                "insert_below": d.get("insert_below", True),
            },
        ),
        client_op(
            "insert_google_doc_table_column",
            "insert_table_column",
            description="Insert a column left or right of a table cell.",
            parallelizable=False,
            tags=("google_docs_tables",),
            unwrap_envelope=True,
            fail_message="Failed to insert column.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "table_start_index": d["table_start_index"],
                "row_index": d["row_index"],
                "column_index": d["column_index"],
                "insert_right": d.get("insert_right", True),
            },
        ),
        client_op(
            "delete_google_doc_table_row",
            "delete_table_row",
            description="Delete a row at the specified cell location.",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_tables",),
            unwrap_envelope=True,
            fail_message="Failed to delete row.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "table_start_index": {
                    "type": "integer",
                    "description": "Table start index.",
                    "example": 5,
                },
                "row_index": {
                    "type": "integer",
                    "description": "Row to delete.",
                    "example": 1,
                },
                "column_index": {
                    "type": "integer",
                    "description": "Any column index in the row.",
                    "example": 0,
                },
            },
        ),
        client_op(
            "delete_google_doc_table_column",
            "delete_table_column",
            description="Delete a column at the specified cell location.",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_tables",),
            unwrap_envelope=True,
            fail_message="Failed to delete column.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
        ),
        client_op(
            "merge_google_doc_table_cells",
            "merge_table_cells",
            description="Merge a rectangular range of table cells into one.",
            parallelizable=False,
            tags=("google_docs_tables",),
            unwrap_envelope=True,
            fail_message="Failed to merge cells.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
                    "description": "Rows to span.",
                    "example": 2,
                },
                "column_span": {
                    "type": "integer",
                    "description": "Columns to span.",
                    "example": 2,
                },
            },
        ),
        client_op(
            "unmerge_google_doc_table_cells",
            "unmerge_table_cells",
            description="Reverse a cell merge in a table range.",
            parallelizable=False,
            tags=("google_docs_tables",),
            unwrap_envelope=True,
            fail_message="Failed to unmerge cells.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
        ),
        # ── Images ────────────────────────────────────────────────────────
        client_op(
            "insert_google_doc_image",
            "insert_inline_image",
            description=(
                "Insert an inline image (referenced by public URI) at a document index."
            ),
            parallelizable=False,
            tags=("google_docs_images", "google_docs"),
            unwrap_envelope=True,
            success_message="Image inserted.",
            fail_message="Failed to insert image.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "image_uri": {
                    "type": "string",
                    "description": "Publicly accessible image URL.",
                    "example": "https://example.com/logo.png",
                },
                "index": {
                    "type": "integer",
                    "description": "Insertion index.",
                    "example": 1,
                },
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
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "image_uri": d["image_uri"],
                "index": d["index"],
                "width_pt": d.get("width_pt"),
                "height_pt": d.get("height_pt"),
            },
        ),
        client_op(
            "replace_google_doc_image",
            "replace_image",
            description=(
                "Replace an existing inline image with a new URI (keeps "
                "position and size)."
            ),
            parallelizable=False,
            tags=("google_docs_images",),
            unwrap_envelope=True,
            success_message="Image replaced.",
            fail_message="Failed to replace image.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
        ),
        # ── Structure: page/section breaks, headers/footers, named ranges ─
        client_op(
            "insert_google_doc_page_break",
            "insert_page_break",
            description="Insert a page break at a document index.",
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Page break inserted.",
            fail_message="Failed to insert page break.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "index": {
                    "type": "integer",
                    "description": "Insertion index.",
                    "example": 1,
                },
            },
        ),
        client_op(
            "insert_google_doc_section_break",
            "insert_section_break",
            description=(
                "Insert a section break (NEXT_PAGE or CONTINUOUS) at a document index."
            ),
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Section break inserted.",
            fail_message="Failed to insert section break.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "index": {
                    "type": "integer",
                    "description": "Insertion index.",
                    "example": 1,
                },
                "section_type": {
                    "type": "string",
                    "description": "NEXT_PAGE | CONTINUOUS.",
                    "example": "NEXT_PAGE",
                },
            },
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "index": d["index"],
                "section_type": d.get("section_type", "NEXT_PAGE"),
            },
        ),
        client_op(
            "create_google_doc_header",
            "create_header",
            description=(
                "Create a document header. Returns the header ID for further edits."
            ),
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Header created.",
            fail_message="Failed to create header.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "header_type": {
                    "type": "string",
                    "description": "DEFAULT | FIRST_PAGE_HEADER.",
                    "example": "DEFAULT",
                },
            },
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "header_type": d.get("header_type", "DEFAULT"),
            },
        ),
        client_op(
            "create_google_doc_footer",
            "create_footer",
            description=(
                "Create a document footer. Returns the footer ID for further edits."
            ),
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Footer created.",
            fail_message="Failed to create footer.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "footer_type": {
                    "type": "string",
                    "description": "DEFAULT | FIRST_PAGE_FOOTER.",
                    "example": "DEFAULT",
                },
            },
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "footer_type": d.get("footer_type", "DEFAULT"),
            },
        ),
        client_op(
            "delete_google_doc_header",
            "delete_header",
            description="Delete a header by its ID.",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Header deleted.",
            fail_message="Failed to delete header.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "header_id": {
                    "type": "string",
                    "description": "Header ID.",
                    "example": "kix.xxxx",
                },
            },
        ),
        client_op(
            "delete_google_doc_footer",
            "delete_footer",
            description="Delete a footer by its ID.",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Footer deleted.",
            fail_message="Failed to delete footer.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
                "footer_id": {
                    "type": "string",
                    "description": "Footer ID.",
                    "example": "kix.xxxx",
                },
            },
        ),
        client_op(
            "create_google_doc_named_range",
            "create_named_range",
            description=(
                "Create a named range over a document range so it can be "
                "referenced later."
            ),
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Named range created.",
            fail_message="Failed to create named range.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
        ),
        client_op(
            "delete_google_doc_named_range",
            "delete_named_range",
            description="Delete a named range by name or by ID.",
            destructive=True,
            parallelizable=False,
            tags=("google_docs_structure",),
            unwrap_envelope=True,
            success_message="Named range deleted.",
            fail_message="Failed to delete named range.",
            input_schema={
                "document_id": dict(_DOC_ID_SHORT),
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
            arg_map=lambda d: {
                "document_id": d["document_id"],
                "name": d.get("name") or None,
                "named_range_id": d.get("named_range_id") or None,
            },
        ),
    ]
