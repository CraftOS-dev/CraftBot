"""Bounded declarative canvas operations over a user-paired plugin channel."""

from __future__ import annotations

import functools
import base64
import json
import math
import re
import tempfile
from pathlib import Path

from .canvas_bridge import CanvasError, bridge
from .canvas_commands import EDIT_COMMANDS, READ_COMMANDS, references, validate_command


def canvas_result(fn):
    @functools.wraps(fn)
    async def wrapped(self, *args, **kwargs):
        try:
            return {"ok": True, "result": await fn(self, *args, **kwargs)}
        except CanvasError as exc:
            return {"error": str(exc), "details": exc.details}
        except (ValueError, TypeError) as exc:
            return {"error": str(exc)}
        except OSError:
            return {
                "error": "Cannot access the local canvas image file or output directory. Check file permissions and available space."
            }
        except (RecursionError, OverflowError):
            return {
                "error": "Canvas input exceeds supported nesting or numeric bounds."
            }

    return wrapped


def number(value, label, low=-100000, high=100000):
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not low <= value <= high
        or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be a finite number from {low} to {high}.")
    return value


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("fill must be a #RRGGBB color.")
    return {
        **{k: int(value[i : i + 2], 16) / 255 for k, i in zip("rgb", (1, 3, 5))},
        "a": 1,
    }


def validate_node_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_:;.]{1,100}", value):
        raise ValueError("Provide a canvas node id returned by a canvas operation.")
    return value


COMMON = {"name", "x", "y", "width", "height", "fill", "corner_radius"}
TEXT = {"text", "font_size", "font_weight"}
LAYOUT = {"layout", "padding", "gap"}


def validate_properties(spec, *, kind=None):
    if not isinstance(spec, dict) or not spec:
        raise ValueError("Node properties must be a non-empty object.")
    allowed = COMMON | TEXT | LAYOUT
    if set(spec) - allowed:
        raise ValueError(
            "Unsupported canvas properties: " + ", ".join(sorted(set(spec) - allowed))
        )
    if kind and (
        (kind != "TEXT" and set(spec) & TEXT)
        or (kind != "FRAME" and set(spec) & LAYOUT)
        or (kind == "TEXT" and "corner_radius" in spec)
    ):
        raise ValueError(
            "Text properties require TEXT; layout requires FRAME; corner radius requires FRAME or RECTANGLE."
        )
    for key in ("name", "text"):
        if key in spec and (
            not isinstance(spec[key], str)
            or len(spec[key]) > (10000 if key == "text" else 200)
        ):
            raise ValueError(f"{key} must be a bounded string.")
    for key in (
        "x",
        "y",
        "width",
        "height",
        "font_size",
        "corner_radius",
        "padding",
        "gap",
    ):
        if key in spec:
            low, high = (
                (1, 10000)
                if key in {"width", "height"}
                else (1, 512)
                if key == "font_size"
                else (0, 10000)
                if key in {"corner_radius", "padding", "gap"}
                else (-100000, 100000)
            )
            number(spec[key], key, low, high)
    if "fill" in spec:
        color(spec["fill"])
    if "font_weight" in spec and (
        isinstance(spec["font_weight"], bool)
        or spec["font_weight"] not in range(100, 901, 100)
    ):
        raise ValueError("font_weight must be 100, 200, …, 900.")
    if "layout" in spec and spec["layout"] not in {"NONE", "HORIZONTAL", "VERTICAL"}:
        raise ValueError("layout must be NONE, HORIZONTAL or VERTICAL.")


def validate_design(design):
    if not isinstance(design, dict):
        raise ValueError("design must be an object describing one root FRAME.")
    try:
        if len(json.dumps(design, allow_nan=False).encode()) > 128 * 1024:
            raise ValueError("Design exceeds 128 KiB.")
    except (TypeError, RecursionError) as exc:
        raise ValueError("Design must contain JSON data.") from exc
    count = 0

    def visit(spec, depth):
        nonlocal count
        count += 1
        if count > 100 or depth > 8:
            raise ValueError("Design supports at most 100 nodes and 8 levels.")
        if not isinstance(spec, dict):
            raise ValueError("Every design node must be an object.")
        kind = spec.get("type", "FRAME" if depth == 1 else "RECTANGLE")
        if kind not in {"FRAME", "RECTANGLE", "TEXT"} or (
            depth == 1 and kind != "FRAME"
        ):
            raise ValueError(
                "Use a root FRAME containing FRAME, RECTANGLE or TEXT nodes."
            )
        validate_properties(
            {k: v for k, v in spec.items() if k not in {"type", "children"}}
            or {"name": kind},
            kind=kind,
        )
        children = spec.get("children", [])
        if not isinstance(children, list) or (children and kind != "FRAME"):
            raise ValueError("Only FRAME nodes may contain a children array.")
        for child in children:
            visit(child, depth + 1)

    visit(design, 1)


class FigmaCanvasMixin:
    @canvas_result
    async def canvas_capabilities(self):
        return {
            "read_commands": READ_COMMANDS,
            "edit_commands": EDIT_COMMANDS,
            "batch_limit": 30,
            "instructions": "Use read_figma_canvas_details(command, params) for inspection and edit_figma_canvas(actions) for editing. Each action has command, params, and optional as alias; later node-id fields may reference $alias. Params use upstream camelCase names. For image files use set_figma_canvas_image; export live PNG with export_figma_canvas_image.",
            "limits": "The published plugin controls available capabilities. No arbitrary JavaScript, new cloud files, vector authoring, variable authoring, or component-definition creation. Text creation uses Inter. Keep the plugin and target page open.",
        }

    @staticmethod
    def _canvas_bound(value):
        remaining, truncated = 1000, False

        def walk(item, depth=0):
            nonlocal remaining, truncated
            remaining -= 1
            if remaining < 0 or depth > 12:
                truncated = True
                return None
            if isinstance(item, dict):
                result = {}
                for key, child in item.items():
                    if remaining <= 0:
                        truncated = True
                        break
                    result[key] = walk(child, depth + 1)
                return result
            if isinstance(item, list):
                result = []
                for child in item:
                    if remaining <= 0:
                        truncated = True
                        break
                    result.append(walk(child, depth + 1))
                return result
            if isinstance(item, str) and len(item) > 10000:
                truncated = True
                return item[:10000]
            return item

        return {"data": walk(value), "truncated": truncated}

    @canvas_result
    async def canvas_details(self, command: str, params=None):
        params = {} if params is None else params
        validate_command(command, params, READ_COMMANDS)
        if any(value.startswith("$") for value in references(params)):
            raise ValueError(
                "Read commands require actual node ids, not batch aliases."
            )
        manager, peer = bridge(), getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        async with peer.lock:
            await self._canvas_target(manager, peer)
            return self._canvas_bound(
                await manager.command(self, peer, command, params)
            )

    @canvas_result
    async def edit_canvas(self, actions: list):
        if not isinstance(actions, list) or not 1 <= len(actions) <= 30:
            raise ValueError("actions must contain 1–30 command objects.")
        if len(json.dumps(actions, allow_nan=False).encode()) > 128 * 1024:
            raise ValueError("Canvas actions exceed 128 KiB.")
        declared = set()
        for action in actions:
            if not isinstance(action, dict) or set(action) - {
                "command",
                "params",
                "as",
            }:
                raise ValueError(
                    "Each action supports command, params and optional as alias."
                )
            command, params = action.get("command"), action.get("params", {})
            validate_command(command, params, EDIT_COMMANDS)
            for value in references(params):
                if value.startswith("$") and value[1:] not in declared:
                    raise ValueError(
                        "Node aliases must refer to an earlier creation or clone action."
                    )
            alias = action.get("as")
            if alias is not None:
                if (
                    not isinstance(alias, str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", alias)
                    or alias in declared
                    or not (command.startswith("create_") or command == "clone_node")
                ):
                    raise ValueError(
                        "Unique as aliases are supported on creation and clone actions only."
                    )
                declared.add(alias)
        manager, peer = bridge(), getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        aliases, completed = {}, []
        async with peer.lock:
            await self._canvas_target(manager, peer)
            try:
                for index, action in enumerate(actions):
                    command = action["command"]
                    params = dict(action.get("params", {}))
                    for key in (
                        "nodeId",
                        "parentId",
                        "componentId",
                        "sourceInstanceId",
                    ):
                        if isinstance(params.get(key), str) and params[key].startswith(
                            "$"
                        ):
                            params[key] = aliases[params[key][1:]]
                    for key in ("nodeIds", "targetNodeIds"):
                        if key in params:
                            params[key] = [
                                aliases[v[1:]] if v.startswith("$") else v
                                for v in params[key]
                            ]
                    if "nodeId" in params and command != "set_focus":
                        node = await manager.command(
                            self, peer, "get_node_info", {"nodeId": params["nodeId"]}
                        )
                        if not isinstance(node, dict) or node.get("type") in {
                            "DOCUMENT",
                            "PAGE",
                            "CANVAS",
                        }:
                            raise CanvasError("Only design nodes can be edited.")
                    result = await manager.command(self, peer, command, params)
                    completed.append(
                        {
                            "index": index,
                            "command": command,
                            **self._canvas_bound(result),
                        }
                    )
                    if "as" in action:
                        if not isinstance(result, dict) or not result.get("id"):
                            raise CanvasError(
                                "Plugin returned no created node id. Inspect the canvas before repeating.",
                                state="unknown",
                            )
                        aliases[action["as"]] = result["id"]
                return {
                    "completed_actions": completed,
                    "node_aliases": aliases,
                    "page_id": self._canvas_page,
                }
            except CanvasError as exc:
                raise CanvasError(
                    str(exc),
                    **{
                        **exc.details,
                        "partial": True,
                        "completed_actions": completed,
                        "node_aliases": aliases,
                        "failed_index": index,
                        "recovery": "Inspect completed actions and request_id before retrying; writes are never replayed or rolled back.",
                    },
                ) from exc
            finally:
                self._cache.clear()

    @canvas_result
    async def set_canvas_image(
        self, node_id: str, image_path: str, scale_mode: str = "FILL"
    ):
        target = validate_node_id(node_id)
        if scale_mode not in {"FILL", "FIT", "CROP", "TILE"}:
            raise ValueError("scale_mode must be FILL, FIT, CROP or TILE.")
        source = Path(image_path)
        if not source.is_absolute() or not source.is_file():
            raise ValueError(
                "image_path must identify an existing absolute local image file."
            )
        if source.stat().st_size > 5 * 1024 * 1024:
            raise ValueError("Image exceeds the 5 MiB canvas transfer limit.")
        with source.open("rb") as stream:
            data = stream.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024 or not (
            data.startswith(
                (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")
            )
            or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        ):
            raise ValueError("Use a PNG, JPG, GIF or WebP image up to 5 MiB.")
        manager, peer = bridge(), getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        async with peer.lock:
            await self._canvas_target(manager, peer)
            try:
                return await manager.command(
                    self,
                    peer,
                    "set_image_fill",
                    {
                        "nodeId": target,
                        "imageBase64": base64.b64encode(data).decode(),
                        "scaleMode": scale_mode,
                    },
                )
            finally:
                self._cache.clear()

    @canvas_result
    async def export_canvas_image(
        self, node_id: str, output_dir: str, scale: float = 1
    ):
        target = validate_node_id(node_id)
        number(scale, "scale", 0.01, 4)
        directory = Path(output_dir)
        if not directory.is_absolute():
            raise ValueError("output_dir must be an absolute directory.")
        manager, peer = bridge(), getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        async with peer.lock:
            await self._canvas_target(manager, peer)
            result = await manager.command(
                self, peer, "export_node_as_image", {"nodeId": target, "scale": scale}
            )
        encoded = result.get("imageData") if isinstance(result, dict) else None
        if not isinstance(encoded, str) or len(encoded) > 7 * 1024 * 1024:
            raise ValueError("Plugin returned no bounded PNG image data.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("Plugin returned invalid PNG encoding.") from exc
        if len(data) > 5 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(
                "Plugin export is not a PNG within the 5 MiB transfer limit."
            )
        directory.mkdir(parents=True, exist_ok=True)
        output = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="figma-canvas-", suffix=".png", dir=directory, delete=False
            ) as stream:
                output = Path(stream.name)
                stream.write(data)
        except OSError:
            if output is not None:
                output.unlink(missing_ok=True)
            raise
        return {
            "node_id": target,
            "path": str(output),
            "bytes": len(data),
            "format": "png",
            "scale": scale,
        }

    @canvas_result
    async def start_canvas(self):
        self._load()  # Only an account-bound client can start or claim a session.
        return await bridge().start(self)

    @canvas_result
    async def connect_canvas(self, channel: str):
        if not isinstance(channel, str):
            raise ValueError("channel must be the string shown in the plugin.")
        manager = bridge()
        peer = manager.claim(self, channel.strip())
        async with peer.lock:
            document = await manager.command(self, peer, "get_document_info")
            page = (document or {}).get("currentPage", {})
            if not page.get("id"):
                raise CanvasError("Plugin returned no current page id.")
            self._canvas_peer = peer
            self._canvas_page = page["id"]
        return {
            "connected": True,
            "channel": peer.channel,
            "document": document,
            "target": "The open Figma plugin document and current page; REST default_file_key does not select a canvas target.",
        }

    @canvas_result
    async def canvas_status(self, request_id: str = ""):
        manager = bridge()
        peer = getattr(self, "_canvas_peer", None)
        if request_id:
            if (
                not peer
                or not isinstance(request_id, str)
                or request_id not in peer.history
            ):
                raise CanvasError(
                    "Request id is unknown to this account's canvas session."
                )
            return {"request_id": request_id, **peer.history[request_id]}
        connected = bool(
            peer
            and manager.peers.get(peer.channel) is peer
            and not peer.socket.closed
            and peer.owner() is self
        )
        return {
            "started": self in manager.owners,
            "connected": connected,
            "channel": peer.channel if connected else None,
            "page_id": getattr(self, "_canvas_page", None) if connected else None,
        }

    async def _canvas_target(self, manager, peer):
        manager.check(self, peer)
        doc = await manager.command(self, peer, "get_document_info")
        if (doc or {}).get("currentPage", {}).get("id") != self._canvas_page:
            raise CanvasError(
                "Figma page changed. Reconnect the channel explicitly before editing the new page."
            )
        return doc

    @canvas_result
    async def read_canvas(self, node_ids=None):
        if node_ids is not None:
            if not isinstance(node_ids, list) or not 1 <= len(node_ids) <= 20:
                raise ValueError("node_ids must contain 1–20 canvas ids.")
            node_ids = [validate_node_id(value) for value in node_ids]
        manager = bridge()
        peer = getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        async with peer.lock:
            doc = await self._canvas_target(manager, peer)
            if node_ids is None:
                selection = await manager.command(self, peer, "get_selection")
                # Plugin page overview lists only immediate children.
                children = doc.get("children", [])
                doc["children"] = children[:500]
                return {
                    "document": doc,
                    "selection": selection,
                    "truncated": len(children) > 500,
                }
            nodes = {}
            for value in node_ids:
                nodes[value] = {
                    "document": await manager.command(
                        self, peer, "get_node_info", {"nodeId": value}
                    )
                }
            return self._bound_document({"ok": True, "result": {"nodes": nodes}})[
                "result"
            ]

    @canvas_result
    async def create_design(self, design: dict):
        validate_design(design)  # Whole-tree validation happens before any mutation.
        manager = bridge()
        peer = getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        created = []
        async with peer.lock:
            await self._canvas_target(manager, peer)
            try:

                async def create(spec, parent=None, root=False):
                    kind = spec.get("type", "FRAME" if root else "RECTANGLE")
                    params = {
                        "name": spec.get("name", kind),
                        "x": spec.get("x", 0),
                        "y": spec.get("y", 0),
                    }
                    if parent:
                        params["parentId"] = parent
                    if kind == "TEXT":
                        params.update(
                            text=spec.get("text", "Text"),
                            fontSize=spec.get("font_size", 16),
                            fontWeight=spec.get("font_weight", 400),
                            fontColor=color(spec.get("fill", "#111827")),
                        )
                    else:
                        params.update(
                            width=spec.get("width", 100), height=spec.get("height", 100)
                        )
                    if kind == "FRAME":
                        params.update(
                            fillColor=color(spec.get("fill", "#FFFFFF")),
                            layoutMode=spec.get("layout", "NONE"),
                            itemSpacing=spec.get("gap", 0),
                        )
                        for side in ("Top", "Right", "Bottom", "Left"):
                            params["padding" + side] = spec.get("padding", 0)
                    result = await manager.command(
                        self, peer, "create_" + kind.lower(), params
                    )
                    if not isinstance(result, dict) or not result.get("id"):
                        raise CanvasError(
                            "Plugin returned no created node id; inspect the canvas before repeating the write.",
                            state="unknown",
                        )
                    created.append(
                        {
                            "id": result["id"],
                            "name": result.get("name", params["name"]),
                            "type": kind,
                        }
                    )
                    if kind == "RECTANGLE" and "fill" in spec:
                        await manager.command(
                            self,
                            peer,
                            "set_fill_color",
                            {"nodeId": result["id"], "color": color(spec["fill"])},
                        )
                    if "corner_radius" in spec:
                        await manager.command(
                            self,
                            peer,
                            "set_corner_radius",
                            {"nodeId": result["id"], "radius": spec["corner_radius"]},
                        )
                    if kind == "TEXT" and ("width" in spec or "height" in spec):
                        await manager.command(
                            self,
                            peer,
                            "resize_node",
                            {
                                "nodeId": result["id"],
                                "width": spec.get("width", result.get("width", 100)),
                                "height": spec.get("height", result.get("height", 20)),
                            },
                        )
                    for child in spec.get("children", []):
                        await create(child, result["id"])
                    return result["id"]

                root_id = await create(design, root=True)
                return {
                    "root_id": root_id,
                    "created_nodes": created,
                    "page_id": self._canvas_page,
                }
            except CanvasError as exc:
                raise CanvasError(
                    str(exc),
                    **{
                        **exc.details,
                        "partial": True,
                        "created_nodes": created,
                        "recovery": "Inspect these nodes and any request_id before retrying. Writes are not automatically replayed or rolled back.",
                    },
                ) from exc
            finally:
                self._cache.clear()

    @canvas_result
    async def update_canvas_node(self, node_id: str, properties: dict):
        target = validate_node_id(node_id)
        # Only properties supported for existing nodes. Creation controls text font/layout.
        if not isinstance(properties, dict) or set(properties) - COMMON - {"text"}:
            raise ValueError(
                "Updates support name, x/y, width/height, fill, corner_radius and text."
            )
        validate_properties(properties)
        for first, second in (("x", "y"), ("width", "height")):
            if (first in properties) != (second in properties):
                raise ValueError(
                    f"Provide {first} and {second} together; the plugin read API returns absolute bounds, not local geometry."
                )
        manager = bridge()
        peer = getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        completed = []
        async with peer.lock:
            await self._canvas_target(manager, peer)
            existing = await manager.command(
                self, peer, "get_node_info", {"nodeId": target}
            )
            if not isinstance(existing, dict) or existing.get("type") in {
                "DOCUMENT",
                "PAGE",
                "CANVAS",
            }:
                raise CanvasError("Only design nodes can be updated.")
            kind = existing.get("type")
            if "text" in properties and kind != "TEXT":
                raise ValueError("text requires a TEXT node.")
            if "corner_radius" in properties and kind not in {
                "FRAME",
                "RECTANGLE",
                "COMPONENT",
                "INSTANCE",
            }:
                raise ValueError("This node does not support corner_radius.")
            commands = []
            if "name" in properties:
                commands.append(("rename_node", {"name": properties["name"]}))
            if "x" in properties or "y" in properties:
                commands.append(
                    (
                        "move_node",
                        {
                            "x": properties.get("x", existing.get("x", 0)),
                            "y": properties.get("y", existing.get("y", 0)),
                        },
                    )
                )
            if "width" in properties or "height" in properties:
                commands.append(
                    (
                        "resize_node",
                        {
                            "width": properties.get(
                                "width", existing.get("width", 100)
                            ),
                            "height": properties.get(
                                "height", existing.get("height", 100)
                            ),
                        },
                    )
                )
            if "text" in properties:
                commands.append(("set_text_content", {"text": properties["text"]}))
            if "fill" in properties:
                commands.append(
                    ("set_fill_color", {"color": color(properties["fill"])})
                )
            if "corner_radius" in properties:
                commands.append(
                    ("set_corner_radius", {"radius": properties["corner_radius"]})
                )
            try:
                for command, params in commands:
                    await manager.command(
                        self, peer, command, {"nodeId": target, **params}
                    )
                    completed.append(command)
                return {"node_id": target, "updated": list(properties)}
            except CanvasError as exc:
                raise CanvasError(
                    str(exc),
                    **{
                        **exc.details,
                        "partial": True,
                        "node_id": target,
                        "completed_commands": completed,
                    },
                ) from exc
            finally:
                self._cache.clear()

    @canvas_result
    async def delete_canvas_node(self, node_id: str):
        target = validate_node_id(node_id)
        manager = bridge()
        peer = getattr(self, "_canvas_peer", None)
        manager.check(self, peer)
        async with peer.lock:
            await self._canvas_target(manager, peer)
            existing = await manager.command(
                self, peer, "get_node_info", {"nodeId": target}
            )
            if not isinstance(existing, dict) or existing.get("type") in {
                "DOCUMENT",
                "PAGE",
                "CANVAS",
            }:
                raise CanvasError(
                    "Pages and documents cannot be deleted by this integration."
                )
            try:
                result = await manager.command(
                    self, peer, "delete_node", {"nodeId": target}
                )
                return {"deleted_node_id": target, "result": result}
            finally:
                self._cache.clear()

    @canvas_result
    async def stop_canvas(self):
        await bridge().stop(self)
        self._canvas_peer = None
        self._canvas_page = None
        return {"connected": False}
