"""Real local WebSocket protocol tests without a Figma login or vendor server."""

import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.figma import FigmaProvider
from craftos_integrations.providers.figma import canvas
from craftos_integrations.providers.figma.canvas import validate_design
from craftos_integrations.providers.figma.canvas_bridge import CanvasBridge, CanvasError
from craftos_integrations.providers.figma.client import FigmaClient, FigmaConfig

CANVAS_NAMES = {
    "start_figma_canvas",
    "connect_figma_canvas",
    "get_figma_canvas_status",
    "read_figma_canvas",
    "create_figma_design",
    "update_figma_canvas_node",
    "delete_figma_canvas_node",
    "stop_figma_canvas",
    "get_figma_canvas_capabilities",
    "read_figma_canvas_details",
    "edit_figma_canvas",
    "set_figma_canvas_image",
    "export_figma_canvas_image",
}

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aCWQAAAAASUVORK5CYII="
)


class PublishedPluginPeer:
    """Independent protocol fixture returning the published plugin's REST-shaped nodes."""

    def __init__(self):
        self.commands = []
        self.nodes = {}
        self.page = "0:1"
        self.fail = None
        self.delay = 0
        self.nested_fail = None

    async def run(self, socket):
        async for packet in socket:
            data = packet.json()
            if data["type"] != "broadcast":
                continue
            message = data["message"]
            assert set(message) == {"id", "command", "params"}
            assert len(message["id"]) == 32
            command, params = message["command"], message["params"]
            self.commands.append((command, params))
            if self.delay:
                await asyncio.sleep(self.delay)
            reply = {"id": message["id"]}
            if command == self.fail:
                reply["error"] = "Plugin operation refused"
            elif command == self.nested_fail:
                reply["result"] = {
                    "success": False,
                    "error": "Native plugin validation failed",
                }
            elif command == "get_document_info":
                reply["result"] = {
                    "currentPage": {"id": self.page, "name": "Page 1"},
                    "children": list(self.nodes.values()),
                }
            elif command == "get_selection":
                reply["result"] = {"selectionCount": 0, "selection": []}
            elif command.startswith("create_"):
                key = f"10:{len(self.nodes) + 1}"
                self.nodes[key] = {
                    "id": key,
                    "type": command[7:].upper(),
                    "name": params.get("name", "Node"),
                    "characters": params.get("text"),
                    "absoluteBoundingBox": {
                        "x": 20,
                        "y": 40,
                        "width": params.get("width", 100),
                        "height": params.get("height", 20),
                    },
                }
                reply["result"] = {
                    "id": key,
                    "name": params.get("name", "Node"),
                    "width": 100,
                    "height": 20,
                }
            elif command == "get_node_info":
                reply["result"] = self.nodes.get(
                    params["nodeId"], {"id": self.page, "type": "CANVAS"}
                )
            elif command == "delete_node":
                self.nodes.pop(params["nodeId"], None)
                reply["result"] = {"id": params["nodeId"]}
            elif command == "clone_node":
                key = f"10:{len(self.nodes) + 1}"
                self.nodes[key] = {**self.nodes[params["nodeId"]], "id": key}
                reply["result"] = {"id": key}
            elif command == "export_node_as_image":
                reply["result"] = {
                    "imageData": base64.b64encode(PNG).decode(),
                    "mimeType": "image/png",
                }
            else:
                reply["result"] = {"id": params.get("nodeId")}
            await socket.send_json(
                {"type": "message", "channel": data["channel"], "message": reply}
            )


@asynccontextmanager
async def plugin(manager, *, channel="browser01"):
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(
            f"http://localhost:{manager.port}/",
            headers={"Origin": "https://www.figma.com"},
        ) as socket:
            await socket.send_json({"type": "join", "channel": channel})
            welcome = await socket.receive_json()
            assert welcome["type"] == "system" and welcome["channel"] == channel
            peer = PublishedPluginPeer()
            task = asyncio.create_task(peer.run(socket))
            try:
                yield peer, socket
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def client():
    value = FigmaClient()
    value.bind_credential(
        {"user_id": "123", "access_token": "SECRET_MUST_STAY_LOCAL"}, lambda _: None
    )
    return value


def test_every_canvas_operation_routes_through_real_wire(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "craftos_integrations.providers.figma.client.load_config",
        lambda *args: FigmaConfig(),
    )

    async def scenario():
        manager = CanvasBridge()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        system = IntegrationSystem(
            store=FileCredentialStore(root=tmp_path), providers=[FigmaProvider()]
        )
        system.store_credential(
            "figma", "123", {"user_id": "123", "access_token": "SECRET_MUST_STAY_LOCAL"}
        )
        account = system.client_for("figma", "123")
        await manager.start(account, port=0)
        seen = set()

        async def execute(name, **inputs):
            result = await system.execute("figma", name, inputs)
            assert result["status"] == "success", result
            seen.add(name)
            return result["result"]

        try:
            await execute("start_figma_canvas")
            async with plugin(manager) as (remote, _):
                connected = await execute("connect_figma_canvas", channel="browser01")
                assert connected["document"]["currentPage"]["id"] == "0:1"
                assert (await execute("get_figma_canvas_status"))["connected"]
                await execute("read_figma_canvas")
                created = await execute(
                    "create_figma_design",
                    design={
                        "type": "FRAME",
                        "name": "Card",
                        "width": 640,
                        "height": 480,
                        "layout": "VERTICAL",
                        "padding": 24,
                        "gap": 16,
                        "children": [
                            {
                                "type": "TEXT",
                                "name": "Heading",
                                "text": "Native text",
                                "font_size": 32,
                                "font_weight": 700,
                            },
                            {
                                "type": "RECTANGLE",
                                "name": "Button",
                                "fill": "#2563EB",
                                "corner_radius": 12,
                            },
                        ],
                    },
                )
                assert [item["type"] for item in created["created_nodes"]] == [
                    "FRAME",
                    "TEXT",
                    "RECTANGLE",
                ]
                assert (
                    remote.commands[3][0] == "get_document_info"
                )  # Target checked before mutation.
                frame_params = next(
                    p for c, p in remote.commands if c == "create_frame"
                )
                assert (
                    frame_params["layoutMode"] == "VERTICAL"
                    and frame_params["paddingTop"] == 24
                )
                text_params = next(p for c, p in remote.commands if c == "create_text")
                assert (
                    text_params["parentId"] == created["root_id"]
                    and text_params["text"] == "Native text"
                )
                read = await execute("read_figma_canvas", node_ids=[created["root_id"]])
                assert read["nodes"][created["root_id"]]["document"]["type"] == "FRAME"
                account._cache["stale"] = "value"
                text_id = created["created_nodes"][1]["id"]
                await execute(
                    "update_figma_canvas_node",
                    node_id=text_id,
                    properties={
                        "text": "Revised",
                        "name": "Title",
                        "fill": "#FFFFFF",
                        "x": 10,
                        "y": 20,
                        "width": 220,
                        "height": 48,
                    },
                )
                assert not account._cache
                assert (
                    "move_node",
                    {"nodeId": text_id, "x": 10, "y": 20},
                ) in remote.commands
                await execute(
                    "delete_figma_canvas_node",
                    node_id=created["created_nodes"][2]["id"],
                )
                assert len(remote.nodes) == 2
                capabilities = await execute("get_figma_canvas_capabilities")
                assert "set_layout_mode" in capabilities["edit_commands"]
                await execute("read_figma_canvas_details", command="get_styles")
                await execute(
                    "edit_figma_canvas",
                    actions=[
                        {
                            "command": "clone_node",
                            "params": {"nodeId": text_id, "x": 50, "y": 50},
                            "as": "copy",
                        },
                        {
                            "command": "set_stroke_color",
                            "params": {
                                "nodeId": "$copy",
                                "color": {"r": 1, "g": 0, "b": 0},
                                "weight": 2,
                            },
                        },
                        {
                            "command": "set_layout_mode",
                            "params": {
                                "nodeId": created["root_id"],
                                "layoutMode": "HORIZONTAL",
                            },
                        },
                    ],
                )
                image_path = tmp_path / "input.png"
                image_path.write_bytes(PNG)
                await execute(
                    "set_figma_canvas_image",
                    node_id=created["root_id"],
                    image_path=str(image_path),
                    scale_mode="FIT",
                )
                exported = await execute(
                    "export_figma_canvas_image",
                    node_id=created["root_id"],
                    output_dir=str(tmp_path),
                )
                assert Path(exported["path"]).read_bytes() == PNG
                assert any(
                    c == "set_image_fill" and base64.b64decode(p["imageBase64"]) == PNG
                    for c, p in remote.commands
                )
                assert "SECRET_MUST_STAY_LOCAL" not in str(remote.commands)
            await execute("stop_figma_canvas")
            assert seen == CANVAS_NAMES
        finally:
            await manager.stop(account)

    asyncio.run(scenario())


def test_channel_account_isolation_and_page_switch_guard(monkeypatch):
    async def scenario():
        manager, first, second = CanvasBridge(), client(), client()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        await manager.start(first, port=0)
        await manager.start(second)
        try:
            async with plugin(manager) as (remote, _):
                assert (await first.connect_canvas("browser01"))["ok"]
                assert (
                    "another account"
                    in (await second.connect_canvas("browser01"))["error"]
                )
                assert (
                    "disconnected"
                    in (await second.create_design({"type": "FRAME"}))["error"]
                )
                remote.page = "0:2"
                result = await first.create_design({"type": "FRAME"})
                assert "page changed" in result["error"]
                assert not any(c.startswith("create_") for c, _ in remote.commands)
                assert (await first.connect_canvas("browser01"))["ok"]
                assert (await first.create_design({"type": "FRAME"}))["ok"]
                assert (
                    "cannot be deleted"
                    in (await first.delete_canvas_node("0:2"))["error"]
                )
        finally:
            await manager.stop(first)
            assert (
                manager.runner
            )  # Stopping one account cannot stop another owner's relay.
            await manager.stop(second)

    asyncio.run(scenario())


def test_partial_creation_retains_node_ids_and_never_replays(monkeypatch):
    async def scenario():
        manager, account = CanvasBridge(), client()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        await manager.start(account, port=0)
        try:
            async with plugin(manager) as (remote, _):
                await account.connect_canvas("browser01")
                remote.fail = "create_text"
                result = await account.create_design(
                    {"name": "Partial", "children": [{"type": "TEXT", "text": "Hello"}]}
                )
                assert result["details"]["partial"]
                assert result["details"]["created_nodes"] == [
                    {"id": "10:1", "name": "Partial", "type": "FRAME"}
                ]
                assert sum(c == "create_text" for c, _ in remote.commands) == 1
                status = await account.canvas_status(result["details"]["request_id"])
                assert status["result"]["state"] == "error"
                assert len(remote.nodes) == 1
        finally:
            await manager.stop(account)

    asyncio.run(scenario())


def test_timeout_is_unknown_and_late_reply_can_be_inspected(monkeypatch):
    async def scenario():
        manager, account = CanvasBridge(), client()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        await manager.start(account, port=0)
        try:
            async with plugin(manager) as (remote, _):
                await account.connect_canvas("browser01")
                peer = account._canvas_peer
                remote.delay = 0.05
                with pytest.raises(CanvasError) as captured:
                    await manager.command(
                        account, peer, "create_frame", {"name": "Once"}, timeout=0.005
                    )
                request_id = captured.value.details["request_id"]
                assert peer.history[request_id]["state"] == "unknown"
                # Await the actual protocol reply, without sending another command.
                for _ in range(30):
                    if peer.history[request_id]["state"] == "completed":
                        break
                    await asyncio.sleep(0.01)
                assert (await account.canvas_status(request_id))["result"][
                    "state"
                ] == "completed"
                assert sum(c == "create_frame" for c, _ in remote.commands) == 1
        finally:
            await manager.stop(account)

    asyncio.run(scenario())


def test_bridge_rejects_other_origins_duplicate_channels_and_peer_commands():
    async def scenario():
        manager, owner = CanvasBridge(), client()
        await manager.start(owner, port=0)
        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://localhost:{manager.port}/"
                with pytest.raises(aiohttp.WSServerHandshakeError) as rejected:
                    await session.ws_connect(
                        url, headers={"Origin": "https://evil.example"}
                    )
                assert rejected.value.status == 403
                async with plugin(manager):
                    async with session.ws_connect(url) as duplicate:
                        await duplicate.send_json(
                            {"type": "join", "channel": "browser01"}
                        )
                        assert (
                            await duplicate.receive()
                        ).type == aiohttp.WSMsgType.CLOSE
                    async with session.ws_connect(url) as attacker:
                        await attacker.send_json(
                            {"type": "join", "channel": "attacker"}
                        )
                        await attacker.receive_json()
                        await attacker.send_json(
                            {
                                "type": "message",
                                "channel": "attacker",
                                "message": {"id": "a", "command": "delete_node"},
                            }
                        )
                        assert (
                            await attacker.receive()
                        ).type == aiohttp.WSMsgType.CLOSE
                        assert manager.peers["browser01"].history == {}
        finally:
            await manager.stop(owner)

    asyncio.run(scenario())


def test_disconnect_during_write_records_unknown_and_blocks_further_writes(monkeypatch):
    async def scenario():
        manager, account = CanvasBridge(), client()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        await manager.start(account, port=0)
        try:
            async with plugin(manager) as (remote, socket):
                await account.connect_canvas("browser01")
                peer = account._canvas_peer
                remote.delay = 10
                pending = asyncio.create_task(
                    manager.command(
                        account, peer, "create_frame", {"name": "Uncertain"}
                    )
                )
                for _ in range(30):
                    if any(c == "create_frame" for c, _ in remote.commands):
                        break
                    await asyncio.sleep(0.01)
                await socket.close()
                with pytest.raises(CanvasError) as captured:
                    await pending
                request_id = captured.value.details["request_id"]
                assert (await account.canvas_status(request_id))["result"][
                    "state"
                ] == "unknown"
                assert not (await account.canvas_status())["result"]["connected"]
                assert (
                    "disconnected"
                    in (await account.create_design({"type": "FRAME"}))["error"]
                )
                assert sum(c == "create_frame" for c, _ in remote.commands) == 1
        finally:
            await manager.stop(account)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "design",
    [
        [],
        {"type": "TEXT"},
        {"type": "ELLIPSE"},
        {"type": "FRAME", "width": 0},
        {"type": "FRAME", "width": True},
        {"type": "FRAME", "height": float("nan")},
        {"type": "FRAME", "fill": "red"},
        {"type": "FRAME", "script": "eval()"},
        {"type": "FRAME", "layout": "DIAGONAL"},
        {"type": "FRAME", "children": [{"type": "TEXT", "font_weight": 450}]},
        {"type": "FRAME", "children": [{"type": "RECTANGLE", "text": "Wrong"}]},
        {"type": "FRAME", "children": [{"type": "TEXT", "children": [{}]}]},
        {"type": "FRAME", "children": [{}] * 100},
        {"type": "FRAME", "name": "x" * 201},
    ],
)
def test_entire_design_is_validated_before_any_network(design):
    with pytest.raises(ValueError):
        validate_design(design)
    # No bridge exists; returning a validation error proves no canvas mutation.
    result = asyncio.run(client().create_design(design))
    assert "error" in result and "disconnected" not in result["error"]


def test_deep_design_and_partial_geometry_update_are_rejected():
    design = {"type": "FRAME"}
    for _ in range(8):
        design = {"type": "FRAME", "children": [design]}
    with pytest.raises(ValueError, match="levels"):
        validate_design(design)
    result = asyncio.run(client().update_canvas_node("1:2", {"x": 12}))
    assert "together" in result["error"]


def test_operation_coverage_and_write_replay_flags():
    operations = [
        op for op in FigmaProvider().operations() if "figma_canvas" in op.tags
    ]
    assert {op.name for op in operations} == CANVAS_NAMES
    for op in operations:
        if op.name in {
            "create_figma_design",
            "update_figma_canvas_node",
            "delete_figma_canvas_node",
            "edit_figma_canvas",
            "set_figma_canvas_image",
        }:
            assert op.destructive and not op.parallelizable


@pytest.mark.parametrize(
    "actions",
    [
        [],
        [{"command": "eval", "params": {"script": "deleteEverything()"}}],
        [{"command": "clone_node", "params": {"nodeId": "$missing"}}],
        [
            {
                "command": "set_stroke_color",
                "params": {"nodeId": "1:2", "color": {"r": 2, "g": 0, "b": 0}},
            }
        ],
        [
            {"command": "create_frame", "params": {}},
            {"command": "set_padding", "params": {"nodeId": "1:2", "paddingTop": -1}},
        ],
        [{"command": "clone_node", "params": {"nodeId": "1:2", "x": 20}}],
        [{"command": "create_component_instance", "params": {}}],
        [
            {
                "command": "set_layout_mode",
                "params": {"nodeId": "1:2", "layoutMode": "DIAGONAL"},
            }
        ],
        [{"command": "create_frame", "params": {"width": float("inf")}}],
        [
            {"command": "create_frame", "params": {}, "as": "a"},
            {"command": "create_frame", "params": {}, "as": "a"},
        ],
        [{"command": "delete_node", "params": {"nodeId": "1:2"}}],
    ],
)
def test_advanced_batch_preflight_rejects_all_actions_before_any_mutation(actions):
    outcome = asyncio.run(client().edit_canvas(actions))
    assert "error" in outcome and "disconnected" not in outcome["error"]


def test_advanced_batch_reports_native_nested_errors_and_protects_pages(monkeypatch):
    async def scenario():
        manager, account = CanvasBridge(), client()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        await manager.start(account, port=0)
        try:
            async with plugin(manager) as (remote, _):
                await account.connect_canvas("browser01")
                remote.nested_fail = "set_annotation"
                result = await account.edit_canvas(
                    [
                        {
                            "command": "create_frame",
                            "params": {"name": "New"},
                            "as": "root",
                        },
                        {
                            "command": "set_annotation",
                            "params": {"nodeId": "$root", "labelMarkdown": "QA"},
                        },
                        {
                            "command": "rename_node",
                            "params": {"nodeId": "$root", "name": "Must not run"},
                        },
                    ]
                )
                assert result["details"]["failed_index"] == 1
                assert result["details"]["node_aliases"] == {"root": "10:1"}
                assert "Native plugin validation failed" in result["error"]
                assert not any(
                    command == "rename_node" for command, _ in remote.commands
                )
                status = await account.canvas_status(result["details"]["request_id"])
                assert status["result"]["state"] == "error"
                before = len(remote.commands)
                outcome = await account.edit_canvas(
                    [
                        {
                            "command": "rename_node",
                            "params": {"nodeId": "0:1", "name": "Forbidden"},
                        }
                    ]
                )
                assert "Only design nodes" in outcome["error"]
                assert not any(
                    command == "rename_node" for command, _ in remote.commands[before:]
                )
        finally:
            await manager.stop(account)

    asyncio.run(scenario())


def test_canvas_read_results_and_asset_status_history_are_bounded():
    output = FigmaClient._canvas_bound(
        {"nodes": [{"id": str(i), "characters": "x" * 20000} for i in range(1000)]}
    )
    assert output["truncated"] and len(output["data"]["nodes"]) < 1000
    from craftos_integrations.providers.figma.canvas_bridge import Peer

    peer = Peer(None, "test")
    peer.record("export", {"state": "completed", "result": {"imageData": "a" * 100000}})
    assert peer.history["export"] == {"state": "completed", "result_omitted": True}


def test_settings_canvas_controls_resolve_accounts_and_never_dispatch_design_writes(
    tmp_path, monkeypatch
):
    from app.ui_layer.settings.figma_canvas import control_canvas

    async def scenario():
        manager = CanvasBridge()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        system = IntegrationSystem(
            store=FileCredentialStore(root=tmp_path), providers=[FigmaProvider()]
        )
        system.store_credential(
            "figma", "123", {"user_id": "123", "access_token": "SECRET"}
        )
        account = system.client_for("figma", "123")
        await manager.start(account, port=0)
        data = {"account": "123", "request_id": "ui-request"}
        try:
            assert (await control_canvas(system, {**data, "action": "start"}))[
                "started"
            ]
            async with plugin(manager):
                result = await control_canvas(
                    system, {**data, "action": "connect", "channel": "browser01"}
                )
                assert (
                    result["success"]
                    and result["connected"]
                    and result["request_id"] == "ui-request"
                )
                assert (await control_canvas(system, {**data, "action": "status"}))[
                    "connected"
                ]
                denied = await control_canvas(
                    system, {**data, "action": "create_frame"}
                )
                assert not denied["success"]
                wrong = await control_canvas(
                    system, {**data, "account": "unknown", "action": "stop"}
                )
                assert not wrong["success"] and manager.runner
                stopped = await control_canvas(system, {**data, "action": "stop"})
                assert (
                    stopped["success"]
                    and not stopped["started"]
                    and not stopped["connected"]
                )
        finally:
            await manager.stop(account)

    asyncio.run(scenario())


def test_published_command_contract_covers_every_advertised_advanced_workflow(
    monkeypatch,
):
    """Wire examples independently transcribed from upstream command handlers."""

    async def scenario():
        manager, account = CanvasBridge(), client()
        monkeypatch.setattr(canvas, "bridge", lambda: manager)
        await manager.start(account, port=0)
        try:
            async with plugin(manager) as (remote, _):
                await account.connect_canvas("browser01")
                # These examples use upstream field names, including layout,
                # library keys, RGBA colors and per-axis sizing.
                cases = [
                    ("create_frame", {"name": "Card", "width": 640, "height": 480}),
                    ("create_rectangle", {"name": "Shape", "parentId": "10:1"}),
                    (
                        "create_text",
                        {
                            "name": "Title",
                            "text": "Hello",
                            "parentId": "10:1",
                            "fontWeight": 700,
                        },
                    ),
                    ("create_section", {"name": "Section"}),
                    (
                        "create_component_instance",
                        {"componentKey": "published-key", "parentId": "10:1"},
                    ),
                    ("clone_node", {"nodeId": "10:2", "x": 20, "y": 20}),
                    ("set_parent", {"nodeId": "10:2", "parentId": "10:1", "index": 0}),
                    ("rename_node", {"nodeId": "10:2", "name": "Button"}),
                    ("move_node", {"nodeId": "10:2", "x": 10, "y": 30}),
                    ("resize_node", {"nodeId": "10:2", "width": 100, "height": 40}),
                    ("set_text_content", {"nodeId": "10:3", "text": "Revised"}),
                    (
                        "set_fill_color",
                        {"nodeId": "10:2", "color": {"r": 1, "g": 0, "b": 0, "a": 0.5}},
                    ),
                    (
                        "set_stroke_color",
                        {
                            "nodeId": "10:2",
                            "color": {"r": 0, "g": 0, "b": 1},
                            "weight": 2,
                        },
                    ),
                    ("set_corner_radius", {"nodeId": "10:2", "radius": 8}),
                    (
                        "set_layout_mode",
                        {
                            "nodeId": "10:1",
                            "layoutMode": "HORIZONTAL",
                            "layoutWrap": "WRAP",
                        },
                    ),
                    (
                        "set_padding",
                        {"nodeId": "10:1", "paddingTop": 20, "paddingRight": 10},
                    ),
                    (
                        "set_axis_align",
                        {
                            "nodeId": "10:1",
                            "primaryAxisAlignItems": "CENTER",
                            "counterAxisAlignItems": "MIN",
                        },
                    ),
                    (
                        "set_layout_sizing",
                        {
                            "nodeId": "10:1",
                            "layoutSizingHorizontal": "FIXED",
                            "layoutSizingVertical": "HUG",
                        },
                    ),
                    (
                        "set_item_spacing",
                        {"nodeId": "10:1", "itemSpacing": 12, "counterAxisSpacing": 24},
                    ),
                    ("set_annotation", {"nodeId": "10:2", "labelMarkdown": "**QA**"}),
                    (
                        "set_instance_overrides",
                        {"targetNodeIds": ["10:5"], "sourceInstanceId": "10:5"},
                    ),
                    ("set_focus", {"nodeId": "10:1"}),
                    ("set_selections", {"nodeIds": ["10:1", "10:2"]}),
                ]
                result = await account.edit_canvas(
                    [
                        {"command": command, "params": params}
                        for command, params in cases
                    ]
                )
                assert result.get("ok"), result
                assert len(result["result"]["completed_actions"]) == len(cases)
                assert [
                    (c, p)
                    for c, p in remote.commands
                    if c not in {"get_document_info", "get_node_info"}
                ] == cases
                read_cases = [
                    ("get_styles", {}),
                    ("get_local_components", {}),
                    ("read_my_design", {}),
                    ("scan_text_nodes", {"nodeId": "10:1"}),
                    (
                        "scan_nodes_by_types",
                        {"nodeId": "10:1", "types": ["TEXT", "RECTANGLE"]},
                    ),
                    ("get_annotations", {"nodeId": "10:2", "includeCategories": True}),
                    ("get_instance_overrides", {"instanceNodeId": "10:5"}),
                    ("get_reactions", {"nodeIds": ["10:1"]}),
                ]
                for command, params in read_cases:
                    assert (await account.canvas_details(command, params)).get("ok")
                    assert remote.commands[-1] == (command, params)
                capabilities = (await account.canvas_capabilities())["result"]
                assert {c for c, _ in cases} == set(capabilities["edit_commands"])
                assert {c for c, _ in read_cases} == set(capabilities["read_commands"])
        finally:
            await manager.stop(account)

    asyncio.run(scenario())
