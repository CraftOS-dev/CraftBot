"""Output contracts independent of a provider's wire format."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal


@dataclass(frozen=True)
class OutputIntent:
    format: Literal["text", "ocr", "json"] = "text"
    schema: dict[str, Any] | None = None

    def __post_init__(self):
        if self.format not in ("text", "ocr", "json"):
            raise ValueError(f"Unsupported output format: {self.format}")
        if self.schema is not None:
            if self.format != "json":
                raise ValueError("A JSON schema requires JSON output")
            from jsonschema.validators import validator_for

            validator_for(self.schema).check_schema(self.schema)

    def system_prompt(self, original: str | None) -> str | None:
        if self.format == "text":
            return original
        instruction = (
            "Extract all text exactly as it appears, preserving line breaks. "
            "Return only raw text without commentary or markdown."
        )
        if self.format == "json":
            instruction = (
                "Return a valid JSON object only, without markdown or commentary."
            )
            if self.schema is not None:
                instruction += " The JSON must satisfy this schema: " + json.dumps(
                    self.schema
                )
        return "\n\n".join(part for part in (original, instruction) if part)

    def validate(self, content: str) -> str:
        if self.format == "json":
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object from the model")
            if self.schema is not None:
                from jsonschema import validate

                validate(value, self.schema)
        return content
