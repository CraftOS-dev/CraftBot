"""Supported upstream commands, without vendoring or executing plugin code.

Wire names and fields follow grab/cursor-talk-to-figma-mcp's MIT-licensed
src/cursor_mcp_plugin/code.js. Keep this catalog and protocol tests together.
"""

from __future__ import annotations

import math
import re


def string(limit=200, **extra):
    return {"type": "string", "maxLength": limit, **extra}


def numeric(low=-100000, high=100000):
    return {"type": "number", "minimum": low, "maximum": high}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


ID = string(100, pattern=r"^(?:[A-Za-z0-9_:;.]+|\$[A-Za-z][A-Za-z0-9_]{0,39})$")
IDS = {"type": "array", "items": ID, "minItems": 1, "maxItems": 20}
COLOR = obj({key: numeric(0, 1) for key in "rgba"}, "rgb")
GEOMETRY = {
    "name": string(),
    "x": numeric(),
    "y": numeric(),
    "width": numeric(1, 10000),
    "height": numeric(1, 10000),
}
NODE = {"nodeId": ID}

READ_COMMANDS = {
    "get_styles": obj({}),
    "get_local_components": obj({}),
    "read_my_design": obj({}),
    "scan_text_nodes": obj(NODE, ("nodeId",)),
    "scan_nodes_by_types": obj(
        {
            **NODE,
            "types": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": enum(
                    "FRAME",
                    "RECTANGLE",
                    "TEXT",
                    "ELLIPSE",
                    "VECTOR",
                    "LINE",
                    "COMPONENT",
                    "COMPONENT_SET",
                    "INSTANCE",
                    "SECTION",
                    "GROUP",
                ),
            },
        },
        ("nodeId", "types"),
    ),
    "get_annotations": obj({**NODE, "includeCategories": {"type": "boolean"}}),
    "get_instance_overrides": obj({"instanceNodeId": ID}),
    "get_reactions": obj({"nodeIds": IDS}, ("nodeIds",)),
}

EDIT_COMMANDS = {
    "create_rectangle": obj({**GEOMETRY, "parentId": ID}),
    "create_frame": obj(
        {
            **GEOMETRY,
            "parentId": ID,
            "fillColor": COLOR,
            "layoutMode": enum("NONE", "HORIZONTAL", "VERTICAL"),
            "itemSpacing": numeric(0, 10000),
            **{
                "padding" + side: numeric(0, 10000)
                for side in ("Top", "Right", "Bottom", "Left")
            },
        }
    ),
    "create_text": obj(
        {
            "name": string(),
            "text": string(10000),
            "x": numeric(),
            "y": numeric(),
            "parentId": ID,
            "fontSize": numeric(1, 512),
            "fontWeight": {"type": "number", "enum": list(range(100, 901, 100))},
            "fontColor": COLOR,
        }
    ),
    "create_section": obj(GEOMETRY),
    "create_component_instance": obj(
        {
            "componentId": ID,
            "componentKey": string(100),
            "parentId": ID,
            "x": numeric(),
            "y": numeric(),
        }
    ),
    "clone_node": obj({**NODE, "x": numeric(), "y": numeric()}, ("nodeId",)),
    "set_parent": obj(
        {
            **NODE,
            "parentId": ID,
            "x": numeric(),
            "y": numeric(),
            "index": {"type": "integer", "minimum": 0, "maximum": 10000},
        },
        ("nodeId", "parentId"),
    ),
    "rename_node": obj({**NODE, "name": string()}, ("nodeId", "name")),
    "move_node": obj({**NODE, "x": numeric(), "y": numeric()}, ("nodeId", "x", "y")),
    "resize_node": obj(
        {**NODE, "width": numeric(1, 10000), "height": numeric(1, 10000)},
        ("nodeId", "width", "height"),
    ),
    "set_text_content": obj({**NODE, "text": string(10000)}, ("nodeId", "text")),
    "set_fill_color": obj({**NODE, "color": COLOR}, ("nodeId", "color")),
    "set_stroke_color": obj(
        {**NODE, "color": COLOR, "weight": numeric(0, 1000)}, ("nodeId", "color")
    ),
    "set_corner_radius": obj(
        {**NODE, "radius": numeric(0, 10000)}, ("nodeId", "radius")
    ),
    "set_layout_mode": obj(
        {
            **NODE,
            "layoutMode": enum("NONE", "HORIZONTAL", "VERTICAL"),
            "layoutWrap": enum("NO_WRAP", "WRAP"),
        },
        ("nodeId", "layoutMode"),
    ),
    "set_padding": obj(
        {
            **NODE,
            **{
                "padding" + side: numeric(0, 10000)
                for side in ("Top", "Right", "Bottom", "Left")
            },
        },
        ("nodeId",),
    ),
    "set_axis_align": obj(
        {
            **NODE,
            "primaryAxisAlignItems": enum("MIN", "MAX", "CENTER", "SPACE_BETWEEN"),
            "counterAxisAlignItems": enum("MIN", "MAX", "CENTER", "BASELINE"),
        },
        ("nodeId",),
    ),
    "set_layout_sizing": obj(
        {
            **NODE,
            "layoutSizingHorizontal": enum("FIXED", "HUG", "FILL"),
            "layoutSizingVertical": enum("FIXED", "HUG", "FILL"),
        },
        ("nodeId",),
    ),
    "set_item_spacing": obj(
        {
            **NODE,
            "itemSpacing": numeric(0, 10000),
            "counterAxisSpacing": numeric(0, 10000),
        },
        ("nodeId",),
    ),
    "set_annotation": obj(
        {**NODE, "labelMarkdown": string(10000), "categoryId": string(100)},
        ("nodeId", "labelMarkdown"),
    ),
    "set_instance_overrides": obj(
        {"targetNodeIds": IDS, "sourceInstanceId": ID},
        ("targetNodeIds", "sourceInstanceId"),
    ),
    "set_focus": obj(NODE, ("nodeId",)),
    "set_selections": obj({"nodeIds": IDS}, ("nodeIds",)),
}


def validate(value, schema, path="params"):
    """Validate the small catalog schema vocabulary; no new runtime dependency."""
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object.")
        properties = schema["properties"]
        unknown = set(value) - properties.keys()
        missing = set(schema["required"]) - value.keys()
        if unknown or missing:
            raise ValueError(
                f"{path}: unsupported fields {sorted(unknown)}; missing fields {sorted(missing)}."
            )
        for key, item in value.items():
            validate(item, properties[key], f"{path}.{key}")
    elif kind == "array":
        if (
            not isinstance(value, list)
            or not schema["minItems"] <= len(value) <= schema["maxItems"]
        ):
            raise ValueError(
                f"{path} must contain {schema['minItems']}–{schema['maxItems']} items."
            )
        for item in value:
            validate(item, schema["items"], path)
    elif kind == "string":
        if not isinstance(value, str) or len(value) > schema.get("maxLength", 10000):
            raise ValueError(f"{path} must be a bounded string.")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path} must be a node id or an earlier $alias.")
    elif kind in {"number", "integer"}:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (kind == "integer" and not isinstance(value, int))
            or not schema.get("minimum", -100000)
            <= value
            <= schema.get("maximum", 100000)
            or not math.isfinite(value)
        ):
            raise ValueError(
                f"{path} must be a finite {kind} within its documented bounds."
            )
    elif kind == "boolean" and not isinstance(value, bool):
        raise ValueError(f"{path} must be boolean.")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}.")


def validate_command(command, params, catalog):
    if not isinstance(command, str) or command not in catalog:
        raise ValueError(
            "Unsupported command. Read get_figma_canvas_capabilities for supported commands."
        )
    validate(params, catalog[command])
    if command == "create_component_instance" and bool(
        params.get("componentId")
    ) == bool(params.get("componentKey")):
        raise ValueError("Provide exactly one componentId or componentKey.")
    if command in {"clone_node", "set_parent"} and ("x" in params) != ("y" in params):
        raise ValueError("Provide x and y together.")
    if (
        command
        in {"set_padding", "set_axis_align", "set_layout_sizing", "set_item_spacing"}
        and len(params) < 2
    ):
        raise ValueError("Provide at least one property to change.")


def references(params):
    for key, value in params.items():
        if key in {
            "nodeId",
            "parentId",
            "componentId",
            "instanceNodeId",
            "sourceInstanceId",
        }:
            yield value
        elif key in {"nodeIds", "targetNodeIds"}:
            yield from value
