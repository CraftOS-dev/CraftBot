"""Environment and validation for the "read pdf file" action."""

from __future__ import annotations

import textwrap
import types
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def _create_sample_pdf(path: Path) -> None:
    pdf_bytes = textwrap.dedent(
        """\
        %PDF-1.4
        1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj
        2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj
        3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj
        4 0 obj <</Length 44>> stream
        BT /F1 24 Tf 72 120 Td (Hello diagnostic PDF) Tj ET
        endstream
        endobj
        5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj
        xref
        0 6
        0000000000 65535 f
        0000000010 00000 n
        0000000060 00000 n
        0000000117 00000 n
        0000000240 00000 n
        0000000339 00000 n
        trailer <</Size 6 /Root 1 0 R>>
        startxref
        408
        %%EOF
        """
    ).encode("utf-8")
    path.write_bytes(pdf_bytes)


def prepare_read_pdf(tmp_path: Path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001
    pdf_path = tmp_path / "sample.pdf"
    _create_sample_pdf(pdf_path)
    modules: Dict[str, types.ModuleType] = {}

    docling_pkg = types.ModuleType("docling")
    docling_pkg.__path__ = []  # type: ignore[attr-defined]
    document_converter_mod = types.ModuleType("docling.document_converter")

    class _DummyDocument:
        def __init__(self, source: str) -> None:
            self._source = source

        def export_to_dict(self) -> Mapping[str, Any]:
            return {
                "origin": {
                    "filename": Path(self._source).name,
                    "mimetype": "application/pdf",
                },
                "version": "diagnostic-1.0",
                "pages": [
                    {
                        "page_no": 1,
                        "size": {"width": 200.0, "height": 200.0},
                    }
                ],
                "texts": [
                    {
                        "text": "Hello diagnostic PDF",
                        "label": "text",
                        "prov": [
                            {
                                "page_no": 1,
                                "bbox": {
                                    "l": 0,
                                    "t": 200,
                                    "r": 200,
                                    "b": 0,
                                    "coord_origin": "BOTTOMLEFT",
                                },
                            }
                        ],
                    }
                ],
            }

    class DocumentConverter:
        def convert(self, source: str):  # noqa: D401
            if not Path(source).exists():
                raise FileNotFoundError(source)
            return types.SimpleNamespace(document=_DummyDocument(source))

    document_converter_mod.DocumentConverter = DocumentConverter  # type: ignore[attr-defined]
    docling_pkg.document_converter = document_converter_mod  # type: ignore[attr-defined]

    modules["docling"] = docling_pkg
    modules["docling.document_converter"] = document_converter_mod

    return PreparedEnv(
        input_overrides={"file_path": str(pdf_path)},
        extra_modules=modules,
        context={"pdf_path": str(pdf_path)},
    )


def validate_read_pdf(
    result: ExecutionResult,
    input_data: Mapping[str, Any],  # noqa: ARG001 - included for consistency
    context: Mapping[str, Any],
) -> Tuple[str, str]:
    output = result.parsed_output or {}
    if not isinstance(output, Mapping):
        return "incorrect result", "Expected dictionary output."

    if output.get("status") != "success":
        message = output.get("message", "No reason provided")
        return "error", f"Action reported failure: {message}"

    content = output.get("content")
    if not isinstance(content, Mapping):
        return "incorrect result", "Expected 'content' to be a mapping."

    elements = content.get("elements", [])
    if not isinstance(elements, list) or not elements:
        return "incorrect result", "PDF content did not include any elements."

    any_text = any(
        "Hello diagnostic PDF" in str(elem.get("text", "")) for elem in elements
    )
    if not any_text:
        return "incorrect result", "Expected text not found in extracted elements."

    return "passed", "PDF content extracted successfully."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="read pdf file",
        base_input={},
        prepare=prepare_read_pdf,
        validator=validate_read_pdf,
    )
