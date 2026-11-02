"""T16/T17: exercise the shared result path without a server or a model."""

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent_core.core.event_stream.event import EventRecord, EventType
from agent_core.core.impl.action.manager import ActionManager, _to_json
from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.impl.event_stream.manager import EventStreamManager
from agent_core.core.impl.mcp.server import MCPServerConnection


def _call(response):
    server = MCPServerConnection(SimpleNamespace(name="fixture"))
    server._transport = SimpleNamespace(
        is_connected=True, send_request=AsyncMock(return_value=response)
    )
    result = asyncio.run(server.call_tool("arbitrary_tool", {"id": 42}))
    server._transport.send_request.assert_awaited_once_with(
        "tools/call", {"name": "arbitrary_tool", "arguments": {"id": 42}}
    )
    return result


@pytest.mark.parametrize(
    ("is_error", "content", "structured"),
    [
        (True, [{"type": "text", "text": "Denied"}], {"record_id": "r-42"}),
        (False, [], {"record_id": "r-42"}),
        (False, [{"type": "text", "text": "Result"}], False),
        (True, [], 0),
        (False, None, None),
        (False, [{"type": "text", "text": ""}], {}),
        (False, [], []),
        (False, [{"type": "text", "text": "Result"}], ""),
    ],
)
def test_tool_signals_and_values_are_preserved(is_error, content, structured):
    native = {
        "content": content,
        "isError": is_error,
        "structuredContent": structured,
        "_meta": {"cursor": None},
    }
    before = copy.deepcopy(native)
    output = _call({"result": native})
    assert output["status"] == ("error" if is_error else "success")
    assert output["isError"] is is_error
    assert output["structuredContent"] == structured
    assert type(output["structuredContent"]) is type(structured)
    assert output["_meta"] == native["_meta"]
    if content:
        assert output["raw_content"] == content
    else:
        assert "raw_content" not in output  # legacy no-content contract
    assert output["result"] == (content[0]["text"] if content else native)
    assert native == before


def test_absent_fields_are_not_invented_and_text_is_not_a_status_signal():
    output = _call(
        {"result": {"content": [{"type": "text", "text": "error: quoted log text"}]}}
    )
    assert output["status"] == "success"
    assert not {"isError", "structuredContent", "_meta"} & output.keys()
    assert "raw_content" not in _call({"result": {"structuredContent": None}})


def test_mixed_media_keeps_blocks_annotations_and_metadata():
    blocks = [
        {"type": "text", "text": "first", "annotations": {"audience": ["user"]}},
        {"type": "image", "data": "fixture", "mimeType": "image/png"},
        {
            "type": "resource",
            "resource": {"uri": "fixture://r", "text": "source\n  text"},
        },
        {"type": "text", "text": "last"},
    ]
    output = _call({"result": {"content": blocks, "structuredContent": {"id": "r"}}})
    assert output["result"] == "first\nlast"
    assert output["raw_content"] == blocks
    assert output["structuredContent"] == {"id": "r"}


def test_jsonrpc_error_keeps_the_existing_contract():
    assert _call({"error": {"message": "bad request", "code": -32602}}) == {
        "status": "error",
        "message": "bad request",
        "code": -32602,
    }


def test_nontext_only_result_retains_the_original_result_object():
    native = {
        "content": [{"type": "image", "data": "fixture", "mimeType": "image/png"}],
        "structuredContent": None,
        "_meta": False,
    }
    result = _call({"result": native})
    assert result["result"] == native
    assert result["raw_content"] == native["content"]
    assert result["structuredContent"] is None and result["_meta"] is False
    null_content = _call({"result": {"content": None}})
    absent_content = _call({"result": {}})
    assert null_content["result"] == {"content": None}
    assert absent_content["result"] == {}


def test_compact_serializer_preserves_values_order_strings_and_fallbacks():
    value = {
        "z": "def f():\r\n\treturn 0\n",
        "a": '{\n  "nested": true\n}',
        "unicode": "日本語",
        "values": [False, 0, None, [], {}],
    }
    rendered = _to_json(value, compact=True)
    assert json.loads(rendered) == value
    assert list(json.loads(rendered)) == list(value)
    assert "\n" not in rendered
    assert len(rendered) < len(_to_json(value))
    assert json.loads(_to_json({"path": Path("fixture")}, compact=True)) == {
        "path": "fixture"
    }
    circular = []
    circular.append(circular)
    assert _to_json(circular, compact=True) == str(circular)


def test_mcp_failure_reaches_action_status_and_new_compact_event():
    output = _call(
        {
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "Denied"}],
                "structuredContent": {"record_id": "r-42"},
            }
        }
    )
    streams = EventStreamManager(llm=None)
    stream = streams.create_stream("fixture")
    old = 'Action old completed with output: {\n  "value": 1\n}.'
    stream.log("action_end", old, event_type=EventType.ACTION_END)
    stream.mark_session_synced("test")
    on_end = Mock()
    manager = ActionManager(
        action_library=Mock(),
        llm_interface=Mock(),
        db_interface=Mock(),
        event_stream_manager=streams,
        context_engine=Mock(),
        state_manager=Mock(),
        on_action_end=on_end,
    )
    manager.execute_atomic_action = AsyncMock(return_value=output)
    action = SimpleNamespace(
        name="tool",
        display_name="Tool",
        platform_overrides={},
        code="",
        irreversible=False,
        action_type="atomic",
    )
    returned = asyncio.run(
        manager.execute_action(action, "", "", session_id="fixture", input_data={})
    )
    assert returned == output
    assert on_end.call_args.args[3] == "error"
    event = stream.tail_events[-1].event
    assert event.action_output == output
    body = event.message.removeprefix("Action tool completed with output: ")[:-1]
    assert json.loads(body) == output and "\n" not in body
    assert "failed" in event.display_message
    assert old in stream.to_prompt_snapshot()
    assert old not in stream.get_delta_events("test")[0]
    # Cold restore and post-fold rendering reuse the stored representation.
    restored = EventStream(llm=None)
    restored.tail_events = [
        EventRecord.from_dict(json.loads(json.dumps(r.to_dict())))
        for r in stream.tail_events
    ]
    assert restored.to_prompt_snapshot() == stream.to_prompt_snapshot()
    restored.head_summary = "Previous work"
    assert event.message in restored.to_prompt_snapshot()
