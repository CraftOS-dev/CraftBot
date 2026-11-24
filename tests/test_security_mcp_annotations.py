"""MCP tools get their security effects from the standard tool annotations."""

from agent_core.core.impl.mcp.adapter import MCPActionAdapter
from agent_core.core.impl.mcp.server import MCPTool


def _action(annotations):
    tool = MCPTool.from_dict({"name": "t", "inputSchema": {}, "annotations": annotations})
    return MCPActionAdapter.mcp_tool_to_registered_action("srv", tool, "mcp_srv").metadata


def test_read_only_tool_has_no_effect():
    meta = _action({"readOnlyHint": True})
    assert meta.effects == [] and meta.result_source == "network"


def test_unannotated_tool_follows_the_spec_defaults():
    meta = _action(None)
    assert meta.effects == ["send_external"] and meta.result_source == "network"


def test_closed_world_writer_counts_as_writing_files():
    meta = _action({"openWorldHint": False})
    assert meta.effects == ["write_files"] and meta.result_source == "local"
