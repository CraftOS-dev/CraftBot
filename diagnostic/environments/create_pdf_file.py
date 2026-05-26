"""Diagnostic environment for the "create pdf file" action."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def _build_stub_modules(output_marker: str) -> Dict[str, types.ModuleType]:
    modules: Dict[str, types.ModuleType] = {}

    markdown2_mod = types.ModuleType("markdown2")

    def markdown(text: str) -> str:
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        html_parts = [f"<p>{line}</p>" for line in lines]
        return "".join(html_parts)

    markdown2_mod.markdown = markdown  # type: ignore[attr-defined]
    modules["markdown2"] = markdown2_mod

    fpdf_mod = types.ModuleType("fpdf")

    class HTMLMixin:  # noqa: D401 - simple stub
        """Lightweight stand-in for the real HTML mixin."""

    class FPDF:
        def __init__(self) -> None:
            self._html: list[str] = []

        def set_auto_page_break(self, auto: bool = True, margin: int = 0) -> None:  # noqa: ARG002
            self._auto = auto
            self._margin = margin

        def add_page(self) -> None:
            self._html.append("<page>")

        def write_html(self, html: str) -> None:
            self._html.append(html)

        def output(self, file_path: str) -> None:
            content = output_marker + "\n" + "\n".join(self._html)
            Path(file_path).write_text(content, encoding="utf-8")

    fpdf_mod.FPDF = FPDF  # type: ignore[attr-defined]
    fpdf_mod.HTMLMixin = HTMLMixin  # type: ignore[attr-defined]
    modules["fpdf"] = fpdf_mod

    fpdf2_mod = types.ModuleType("fpdf2")
    fpdf2_mod.FPDF = FPDF  # type: ignore[attr-defined]
    modules["fpdf2"] = fpdf2_mod

    return modules


def prepare_create_pdf(tmp_path: Path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001
    file_path = tmp_path / "document.pdf"
    content = "Diagnostic PDF content."
    modules = _build_stub_modules("PDF-STUB")

    return PreparedEnv(
        input_overrides={
            "file_path": str(file_path),
            "content": content,
        },
        extra_modules=modules,
        context={
            "file_path": str(file_path),
            "marker": "PDF-STUB",
            "expected_text": content,
        },
    )


def validate_create_pdf(
    result: ExecutionResult,
    input_data: Mapping[str, Any],  # noqa: ARG001
    context: Mapping[str, Any],
) -> Tuple[str, str]:
    output = result.parsed_output or {}
    if not isinstance(output, Mapping):
        return "incorrect result", "Expected JSON object output."

    if output.get("status") != "success":
        message = output.get("message", "No message provided")
        return "error", f"Action reported failure: {message}"

    expected_path = context.get("file_path")
    if output.get("path") != expected_path:
        return (
            "incorrect result",
            f"Path mismatch. expected={expected_path} actual={output.get('path')}",
        )

    pdf_path = Path(expected_path)
    if not pdf_path.exists():
        return "error", "PDF file was not created."

    contents = pdf_path.read_text(encoding="utf-8")
    if context.get("marker") not in contents:
        return "incorrect result", "Stub PDF marker missing from output file."

    if context.get("expected_text") not in contents:
        return "incorrect result", "PDF content missing expected text."

    return "passed", "PDF file created with stub backend."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="create pdf file",
        base_input={},
        prepare=prepare_create_pdf,
        validator=validate_create_pdf,
    )
