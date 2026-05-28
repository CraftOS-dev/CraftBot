# -*- coding: utf-8 -*-
"""Google Docs - granular Google integration.

Connect just Docs (without granting Gmail/Calendar/Drive/YouTube scopes)
by clicking Connect on the Google Docs card. Credential is saved to
``gdocs.json``.

Same per-service shape as ``gmail.py`` / ``google_calendar.py`` /
``google_drive.py``. Docs uses two API surfaces:
  - ``docs.googleapis.com/v1`` for document content (read/write structured)
  - ``drive.googleapis.com/v3`` for file-level ops (create/list/copy)
The Docs scope ``auth/documents`` covers the docs API; we additionally
request the full ``auth/drive`` scope so list/search can find docs the
user already owns (the narrower ``drive.file`` scope only sees files the
integration itself created, which is a frequent source of "I can see the
doc in Drive but the agent can't" complaints).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    register_client,
    register_handler,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger
from .._google_common import (
    DOCS_SCOPES,
    DRIVE_SCOPES,
    GoogleApiClientMixin,
    GoogleCredential,
    make_google_oauth,
    run_google_login,
    run_google_logout,
    run_google_status,
)

logger = get_logger(__name__)

DOCS_API_BASE = "https://docs.googleapis.com/v1"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

# Docs needs both the documents scope (read/write doc bodies) AND
# the full Drive scope so list/search hits docs the user already owns
# in their Drive - not just those created by this integration.
# Trade-off: this is a Google "restricted" scope; the OAuth consent
# screen shows an "unverified app" warning until the app is verified.
# Matches the scope shape used by google_drive.py.
DOCS_AND_DRIVE_SCOPES = f"{DOCS_SCOPES} {DRIVE_SCOPES}"


GDOCS = IntegrationSpec(
    name="google_docs",
    cred_class=GoogleCredential,
    cred_file="gdocs.json",
    platform_id="google_docs",
)


# -----------------------------------------------------------------
# Handler - auth flow only
# -----------------------------------------------------------------


@register_handler(GDOCS.name)
class GoogleDocsHandler(IntegrationHandler):
    spec = GDOCS
    display_name = "Google Docs"
    description = "Read, edit, and create documents"
    auth_type = "oauth"
    icon = "google_docs"
    fields: List = []

    oauth = make_google_oauth(DOCS_AND_DRIVE_SCOPES)

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_login(self.spec, self.oauth, "Google Docs")

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_logout(self.spec, "Google Docs")

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "Google Docs")


# -----------------------------------------------------------------
# Client - Docs REST methods (no listener)
# -----------------------------------------------------------------


@register_client
class GoogleDocsClient(GoogleApiClientMixin, BasePlatformClient):
    spec = GDOCS
    PLATFORM_ID = GDOCS.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[GoogleCredential] = None

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return {"error": "Google Docs does not support send_message"}

    @property
    def supports_listening(self) -> bool:
        return False

    # ----- REST methods -----

    def create_document(self, title: str) -> Result:
        """Create a new blank Google Doc and return its metadata."""
        return http_request(
            "POST",
            f"{DOCS_API_BASE}/documents",
            headers=self._headers(),
            json={"title": title},
            transform=lambda d: {
                "document_id": d.get("documentId"),
                "title": d.get("title"),
                "url": f"https://docs.google.com/document/d/{d.get('documentId')}/edit",
            },
        )

    def get_document(self, document_id: str) -> Result:
        """Read a document's full structured content (body + headers/footers)."""
        return http_request(
            "GET",
            f"{DOCS_API_BASE}/documents/{document_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def get_document_text(self, document_id: str) -> Result:
        """Plain-text view of a document - flattens the body into a single string."""
        result = self.get_document(document_id)
        if "error" in result:
            return result
        doc = result["result"]
        text_parts: List[str] = []
        for elem in doc.get("body", {}).get("content", []) or []:
            para = elem.get("paragraph")
            if not para:
                continue
            for run in para.get("elements") or []:
                tr = run.get("textRun")
                if tr and tr.get("content"):
                    text_parts.append(tr["content"])
        return {
            "ok": True,
            "result": {
                "document_id": document_id,
                "title": doc.get("title", ""),
                "text": "".join(text_parts),
            },
        }

    def append_text(self, document_id: str, text: str) -> Result:
        """Append text to the end of a document via batchUpdate."""
        # Get the doc to find its current end-index for insertion.
        result = self.get_document(document_id)
        if "error" in result:
            return result
        body = result["result"].get("body", {})
        end_index = (
            body.get("content", [{}])[-1].get("endIndex", 1)
            if body.get("content")
            else 1
        )
        # Insert just before the trailing newline (endIndex - 1).
        return http_request(
            "POST",
            f"{DOCS_API_BASE}/documents/{document_id}:batchUpdate",
            headers=self._headers(),
            json={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": max(1, end_index - 1)},
                            "text": text,
                        }
                    },
                ],
            },
            expected=(200,),
            transform=lambda _d: {"appended": True, "document_id": document_id},
        )

    def replace_text(
        self, document_id: str, find: str, replace: str, match_case: bool = False
    ) -> Result:
        """Find-and-replace across the entire document body."""
        return http_request(
            "POST",
            f"{DOCS_API_BASE}/documents/{document_id}:batchUpdate",
            headers=self._headers(),
            json={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {"text": find, "matchCase": match_case},
                            "replaceText": replace,
                        }
                    },
                ],
            },
            expected=(200,),
            transform=lambda d: {
                "document_id": document_id,
                "occurrences_changed": (
                    (d.get("replies") or [{}])[0]
                    .get("replaceAllText", {})
                    .get("occurrencesChanged", 0)
                ),
            },
        )

    def list_documents(self, max_results: int = 50) -> Result:
        """List Google Docs files the user owns or has access to."""
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files",
            headers=self._auth_header(),
            params={
                "q": "mimeType='application/vnd.google-apps.document' and trashed=false",
                "pageSize": max_results,
                "fields": "files(id,name,modifiedTime,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
            expected=(200,),
            transform=lambda d: d.get("files", []),
        )

    def search_documents(self, query: str, max_results: int = 50) -> Result:
        """Search for Google Docs by name. ``query`` is a fragment matched
        against the document title."""
        # Drive's q-query syntax: combine name contains with mimeType filter.
        q = (
            f"name contains '{query}' "
            "and mimeType='application/vnd.google-apps.document' "
            "and trashed=false"
        )
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files",
            headers=self._auth_header(),
            params={
                "q": q,
                "pageSize": max_results,
                "fields": "files(id,name,modifiedTime,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
            expected=(200,),
            transform=lambda d: d.get("files", []),
        )

    def delete_document(self, document_id: str) -> Result:
        """Delete a Google Doc (moves to Drive trash)."""
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{document_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "document_id": document_id},
        )

    # ----- batchUpdate helper -----

    def _batch_update(
        self, document_id: str, requests: List[Dict[str, Any]], transform=None
    ) -> Result:
        return http_request(
            "POST",
            f"{DOCS_API_BASE}/documents/{document_id}:batchUpdate",
            headers=self._headers(),
            json={"requests": requests},
            expected=(200,),
            transform=transform
            or (
                lambda d: {"document_id": document_id, "replies": d.get("replies", [])}
            ),
        )

    # ----- Content: insert / delete -----

    def insert_text(self, document_id: str, text: str, index: int) -> Result:
        """Insert text at a specific UTF-16 index. Index 1 is the start of the body."""
        return self._batch_update(
            document_id,
            [{"insertText": {"location": {"index": index}, "text": text}}],
            transform=lambda _d: {
                "inserted": True,
                "document_id": document_id,
                "index": index,
            },
        )

    def delete_content_range(
        self, document_id: str, start_index: int, end_index: int
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "deleteContentRange": {
                        "range": {"startIndex": start_index, "endIndex": end_index}
                    }
                }
            ],
            transform=lambda _d: {"deleted": True, "document_id": document_id},
        )

    # ----- Styling: text + paragraph -----

    def update_text_style(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        strikethrough: Optional[bool] = None,
        font_size_pt: Optional[float] = None,
        font_family: Optional[str] = None,
        foreground_color_hex: Optional[str] = None,
        background_color_hex: Optional[str] = None,
        link_url: Optional[str] = None,
    ) -> Result:
        """Apply text-level styling to a range. ``*_hex`` are '#RRGGBB' strings.

        Only supplied parameters are applied; the rest stay untouched.
        """
        text_style: Dict[str, Any] = {}
        fields: List[str] = []
        if bold is not None:
            text_style["bold"] = bold
            fields.append("bold")
        if italic is not None:
            text_style["italic"] = italic
            fields.append("italic")
        if underline is not None:
            text_style["underline"] = underline
            fields.append("underline")
        if strikethrough is not None:
            text_style["strikethrough"] = strikethrough
            fields.append("strikethrough")
        if font_size_pt is not None:
            text_style["fontSize"] = {"magnitude": font_size_pt, "unit": "PT"}
            fields.append("fontSize")
        if font_family is not None:
            text_style["weightedFontFamily"] = {"fontFamily": font_family}
            fields.append("weightedFontFamily")
        if foreground_color_hex is not None:
            text_style["foregroundColor"] = {
                "color": {"rgbColor": _hex_to_rgb(foreground_color_hex)}
            }
            fields.append("foregroundColor")
        if background_color_hex is not None:
            text_style["backgroundColor"] = {
                "color": {"rgbColor": _hex_to_rgb(background_color_hex)}
            }
            fields.append("backgroundColor")
        if link_url is not None:
            text_style["link"] = {"url": link_url}
            fields.append("link")
        if not fields:
            return {"error": "no_style_fields"}
        return self._batch_update(
            document_id,
            [
                {
                    "updateTextStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "textStyle": text_style,
                        "fields": ",".join(fields),
                    }
                }
            ],
            transform=lambda _d: {"styled": True, "document_id": document_id},
        )

    def update_paragraph_style(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        named_style_type: Optional[str] = None,
        alignment: Optional[str] = None,
        line_spacing: Optional[float] = None,
        keep_with_next: Optional[bool] = None,
    ) -> Result:
        """Apply paragraph-level styling to a range.

        ``named_style_type``: NORMAL_TEXT, TITLE, SUBTITLE, HEADING_1..HEADING_6.
        ``alignment``: START, CENTER, END, JUSTIFIED.
        ``line_spacing`` is a percentage (100 = single spacing).
        """
        para_style: Dict[str, Any] = {}
        fields: List[str] = []
        if named_style_type is not None:
            para_style["namedStyleType"] = named_style_type
            fields.append("namedStyleType")
        if alignment is not None:
            para_style["alignment"] = alignment
            fields.append("alignment")
        if line_spacing is not None:
            para_style["lineSpacing"] = line_spacing
            fields.append("lineSpacing")
        if keep_with_next is not None:
            para_style["keepWithNext"] = keep_with_next
            fields.append("keepWithNext")
        if not fields:
            return {"error": "no_style_fields"}
        return self._batch_update(
            document_id,
            [
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "paragraphStyle": para_style,
                        "fields": ",".join(fields),
                    }
                }
            ],
            transform=lambda _d: {"styled": True, "document_id": document_id},
        )

    # ----- Lists -----

    def create_paragraph_bullets(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bullet_preset: str = "BULLET_DISC_CIRCLE_SQUARE",
    ) -> Result:
        """Turn paragraphs in a range into a bulleted/numbered list.

        ``bullet_preset`` examples: BULLET_DISC_CIRCLE_SQUARE,
        BULLET_ARROW_DIAMOND_DISC, NUMBERED_DECIMAL_NESTED, NUMBERED_DECIMAL_ALPHA_ROMAN,
        BULLET_CHECKBOX.
        """
        return self._batch_update(
            document_id,
            [
                {
                    "createParagraphBullets": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "bulletPreset": bullet_preset,
                    }
                }
            ],
            transform=lambda _d: {"bullets_created": True, "document_id": document_id},
        )

    def delete_paragraph_bullets(
        self, document_id: str, start_index: int, end_index: int
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "deleteParagraphBullets": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                    }
                }
            ],
            transform=lambda _d: {"bullets_removed": True, "document_id": document_id},
        )

    # ----- Tables -----

    def insert_table(
        self, document_id: str, rows: int, columns: int, index: int
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "insertTable": {
                        "rows": rows,
                        "columns": columns,
                        "location": {"index": index},
                    }
                }
            ],
            transform=lambda _d: {
                "table_inserted": True,
                "document_id": document_id,
                "rows": rows,
                "columns": columns,
            },
        )

    def insert_table_row(
        self,
        document_id: str,
        table_start_index: int,
        row_index: int,
        column_index: int,
        insert_below: bool = True,
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "insertTableRow": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start_index},
                            "rowIndex": row_index,
                            "columnIndex": column_index,
                        },
                        "insertBelow": insert_below,
                    }
                }
            ],
            transform=lambda _d: {"row_inserted": True, "document_id": document_id},
        )

    def insert_table_column(
        self,
        document_id: str,
        table_start_index: int,
        row_index: int,
        column_index: int,
        insert_right: bool = True,
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "insertTableColumn": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start_index},
                            "rowIndex": row_index,
                            "columnIndex": column_index,
                        },
                        "insertRight": insert_right,
                    }
                }
            ],
            transform=lambda _d: {"column_inserted": True, "document_id": document_id},
        )

    def delete_table_row(
        self,
        document_id: str,
        table_start_index: int,
        row_index: int,
        column_index: int,
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "deleteTableRow": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start_index},
                            "rowIndex": row_index,
                            "columnIndex": column_index,
                        },
                    }
                }
            ],
            transform=lambda _d: {"row_deleted": True, "document_id": document_id},
        )

    def delete_table_column(
        self,
        document_id: str,
        table_start_index: int,
        row_index: int,
        column_index: int,
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "deleteTableColumn": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start_index},
                            "rowIndex": row_index,
                            "columnIndex": column_index,
                        },
                    }
                }
            ],
            transform=lambda _d: {"column_deleted": True, "document_id": document_id},
        )

    def merge_table_cells(
        self,
        document_id: str,
        table_start_index: int,
        row_index: int,
        column_index: int,
        row_span: int,
        column_span: int,
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "mergeTableCells": {
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": row_index,
                                "columnIndex": column_index,
                            },
                            "rowSpan": row_span,
                            "columnSpan": column_span,
                        }
                    }
                }
            ],
            transform=lambda _d: {"merged": True, "document_id": document_id},
        )

    def unmerge_table_cells(
        self,
        document_id: str,
        table_start_index: int,
        row_index: int,
        column_index: int,
        row_span: int,
        column_span: int,
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "unmergeTableCells": {
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": row_index,
                                "columnIndex": column_index,
                            },
                            "rowSpan": row_span,
                            "columnSpan": column_span,
                        }
                    }
                }
            ],
            transform=lambda _d: {"unmerged": True, "document_id": document_id},
        )

    # ----- Images -----

    def insert_inline_image(
        self,
        document_id: str,
        image_uri: str,
        index: int,
        width_pt: Optional[float] = None,
        height_pt: Optional[float] = None,
    ) -> Result:
        req: Dict[str, Any] = {
            "uri": image_uri,
            "location": {"index": index},
        }
        if width_pt is not None and height_pt is not None:
            req["objectSize"] = {
                "width": {"magnitude": width_pt, "unit": "PT"},
                "height": {"magnitude": height_pt, "unit": "PT"},
            }
        return self._batch_update(
            document_id,
            [{"insertInlineImage": req}],
            transform=lambda d: {
                "document_id": document_id,
                "image_object_id": (d.get("replies") or [{}])[0]
                .get("insertInlineImage", {})
                .get("objectId"),
            },
        )

    def replace_image(
        self, document_id: str, image_object_id: str, image_uri: str
    ) -> Result:
        return self._batch_update(
            document_id,
            [{"replaceImage": {"imageObjectId": image_object_id, "uri": image_uri}}],
            transform=lambda _d: {"replaced": True, "document_id": document_id},
        )

    # ----- Structure: page/section breaks, headers/footers, named ranges -----

    def insert_page_break(self, document_id: str, index: int) -> Result:
        return self._batch_update(
            document_id,
            [{"insertPageBreak": {"location": {"index": index}}}],
            transform=lambda _d: {
                "page_break_inserted": True,
                "document_id": document_id,
            },
        )

    def insert_section_break(
        self, document_id: str, index: int, section_type: str = "NEXT_PAGE"
    ) -> Result:
        """``section_type``: CONTINUOUS or NEXT_PAGE."""
        return self._batch_update(
            document_id,
            [
                {
                    "insertSectionBreak": {
                        "location": {"index": index},
                        "sectionType": section_type,
                    }
                }
            ],
            transform=lambda _d: {
                "section_break_inserted": True,
                "document_id": document_id,
            },
        )

    def create_header(self, document_id: str, header_type: str = "DEFAULT") -> Result:
        return self._batch_update(
            document_id,
            [{"createHeader": {"type": header_type}}],
            transform=lambda d: {
                "document_id": document_id,
                "header_id": (d.get("replies") or [{}])[0]
                .get("createHeader", {})
                .get("headerId"),
            },
        )

    def create_footer(self, document_id: str, footer_type: str = "DEFAULT") -> Result:
        return self._batch_update(
            document_id,
            [{"createFooter": {"type": footer_type}}],
            transform=lambda d: {
                "document_id": document_id,
                "footer_id": (d.get("replies") or [{}])[0]
                .get("createFooter", {})
                .get("footerId"),
            },
        )

    def delete_header(self, document_id: str, header_id: str) -> Result:
        return self._batch_update(
            document_id,
            [{"deleteHeader": {"headerId": header_id}}],
            transform=lambda _d: {"deleted": True, "document_id": document_id},
        )

    def delete_footer(self, document_id: str, footer_id: str) -> Result:
        return self._batch_update(
            document_id,
            [{"deleteFooter": {"footerId": footer_id}}],
            transform=lambda _d: {"deleted": True, "document_id": document_id},
        )

    def create_named_range(
        self, document_id: str, name: str, start_index: int, end_index: int
    ) -> Result:
        return self._batch_update(
            document_id,
            [
                {
                    "createNamedRange": {
                        "name": name,
                        "range": {"startIndex": start_index, "endIndex": end_index},
                    }
                }
            ],
            transform=lambda d: {
                "document_id": document_id,
                "named_range_id": (d.get("replies") or [{}])[0]
                .get("createNamedRange", {})
                .get("namedRangeId"),
            },
        )

    def delete_named_range(
        self,
        document_id: str,
        name: Optional[str] = None,
        named_range_id: Optional[str] = None,
    ) -> Result:
        if name:
            req = {"deleteNamedRange": {"name": name}}
        elif named_range_id:
            req = {"deleteNamedRange": {"namedRangeId": named_range_id}}
        else:
            return {"error": "name_or_id_required"}
        return self._batch_update(
            document_id,
            [req],
            transform=lambda _d: {"deleted": True, "document_id": document_id},
        )

    # ----- File-level (Drive) ops -----

    def copy_document(self, document_id: str, new_title: str) -> Result:
        """Make a copy of an existing doc with a new title."""
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files/{document_id}/copy",
            headers=self._headers(),
            json={"name": new_title},
            expected=(200,),
            transform=lambda d: {
                "document_id": d.get("id"),
                "title": d.get("name"),
                "url": f"https://docs.google.com/document/d/{d.get('id')}/edit",
            },
        )

    def export_document(
        self, document_id: str, mime_type: str, dest_path: str
    ) -> Result:
        """Export a doc as PDF / DOCX / ODT / etc. and save to ``dest_path``.

        Common ``mime_type`` values:
          - application/pdf
          - application/vnd.openxmlformats-officedocument.wordprocessingml.document  (DOCX)
          - application/vnd.oasis.opendocument.text  (ODT)
          - text/plain
          - text/html
        """
        import httpx

        try:
            with httpx.stream(
                "GET",
                f"{DRIVE_API_BASE}/files/{document_id}/export",
                headers=self._auth_header(),
                params={"mimeType": mime_type},
                follow_redirects=True,
                timeout=60.0,
            ) as r:
                if r.status_code != 200:
                    return {
                        "error": f"http_{r.status_code}",
                        "details": r.read().decode("utf-8", "replace")[:300],
                    }
                with open(dest_path, "wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            return {
                "ok": True,
                "result": {
                    "saved_to": dest_path,
                    "document_id": document_id,
                    "mime_type": mime_type,
                },
            }
        except Exception as e:
            return {"error": "export_failed", "details": str(e)}


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> Dict[str, float]:
    """Convert '#RRGGBB' / 'RRGGBB' to Google API rgbColor dict (0-1 floats)."""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    return {
        "red": int(h[0:2], 16) / 255.0,
        "green": int(h[2:4], 16) / 255.0,
        "blue": int(h[4:6], 16) / 255.0,
    }
