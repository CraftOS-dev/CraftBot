"""TypeScript type generation from config/schema.json (Pillar 1 extended
to the frontend: entity types are GENERATED, never hand-written).

When the agent writes config/schema.json, the platform regenerates
frontend/types.gen.ts — one interface per entity, matching the engine's
wire format exactly (camelCase, id/createdAt/updatedAt included, optional
fields nullable). The agent imports from './types.gen' and never spends a
single token authoring or re-reading entity type definitions, and
frontend/backend type drift becomes structurally impossible.

Deterministic, no LLM involved, fail-silent (generation must never break a
build; a schema error already fails loudly at the backend import).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

_TS_TYPES = {
    "string": "string",
    "text": "string",
    "integer": "number",
    "float": "number",
    "boolean": "boolean",
    "datetime": "string",  # ISO-8601 on the wire
    "json": "any",
    "ref": "number",
    # enum renders as a union of its literal values (see _ts_type)
}


def _ts_type(f: Dict[str, Any]) -> str:
    if f.get("type") == "enum" and isinstance(f.get("values"), list):
        return " | ".join(json.dumps(v) for v in f["values"]) or "string"
    return _TS_TYPES.get(f.get("type"), "any")


def _snake(name: str) -> str:
    import re

    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def _plural(name: str, spec: Dict[str, Any]) -> str:
    """Mirror of the engine's route pluralization."""
    if spec.get("plural"):
        return str(spec["plural"])
    lower = _snake(name)
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return lower + "es"
    if lower.endswith("y") and lower[-2] not in "aeiou":
        return lower[:-1] + "ies"
    return lower + "s"

_HEADER = """\
/**
 * GENERATED from config/schema.json — DO NOT EDIT.
 *
 * One interface per declared entity, matching the backend wire format
 * exactly (camelCase; id/createdAt/updatedAt are automatic). Regenerated
 * by the platform every time config/schema.json is written.
 *
 * Import entity types from here:  import type { Card } from '../types.gen'
 * App-specific NON-entity types still go in types.ts.
 */
"""


def render_types(schema: Dict[str, Any]) -> str:
    lines = [_HEADER]
    entities = schema.get("entities", {}) or {}
    if not entities:
        lines.append("// No entities declared yet — define them in config/schema.json.")
        lines.append("export {}")
        return "\n".join(lines) + "\n"
    for entity_name, spec in entities.items():
        desc = spec.get("description")
        if desc:
            lines.append(f"/** {desc} */")
        lines.append(f"export interface {entity_name} {{")
        lines.append("  id: number")
        for fname, f in (spec.get("fields") or {}).items():
            if not isinstance(f, dict):
                continue
            ts = _ts_type(f)
            optional = "" if f.get("required") else " | null"
            lines.append(f"  {fname}: {ts}{optional}")
        lines.append("  createdAt: string | null")
        lines.append("  updatedAt: string | null")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_SCHEMA_HEADER = """\
/**
 * GENERATED from config/schema.json — DO NOT EDIT.
 *
 * Runtime entity metadata for the schema-aware presets (EntityForm,
 * EntityTable): field types/required/enum values and each entity's REST
 * route segment. Regenerated with types.gen.ts on every schema write.
 */
"""


def render_schema_meta(schema: Dict[str, Any]) -> str:
    entities = schema.get("entities", {}) or {}
    meta: Dict[str, Any] = {}
    for entity_name, spec in entities.items():
        fields = {}
        for fname, f in (spec.get("fields") or {}).items():
            if not isinstance(f, dict):
                continue
            entry: Dict[str, Any] = {"type": f.get("type", "json")}
            if f.get("required"):
                entry["required"] = True
            if f.get("unique"):
                entry["unique"] = True
            if f.get("values"):
                entry["values"] = f["values"]
            if f.get("entity"):
                entry["entity"] = f["entity"]
            fields[fname] = entry
        meta[entity_name] = {
            "plural": _plural(entity_name, spec),
            "fields": fields,
        }
    body = json.dumps(meta, indent=2)
    return (
        _SCHEMA_HEADER
        + "\nexport const ENTITIES = "
        + body
        + " as const\n\nexport type EntityName = keyof typeof ENTITIES\n"
    )


def regenerate_types(project_root: Path) -> bool:
    """Regenerate frontend/types.gen.ts + frontend/schema.gen.ts from
    config/schema.json. Returns True when written. Fail-silent."""
    try:
        schema_file = Path(project_root) / "config" / "schema.json"
        if not schema_file.exists():
            return False
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        front = Path(project_root) / "frontend"
        (front / "types.gen.ts").write_text(render_types(schema), encoding="utf-8")
        (front / "schema.gen.ts").write_text(
            render_schema_meta(schema), encoding="utf-8"
        )
        logger.info(f"[LIVING_UI:TYPEGEN] regenerated types.gen.ts + schema.gen.ts")
        return True
    except Exception as exc:
        logger.debug(f"[LIVING_UI:TYPEGEN] skipped: {exc}")
        return False
