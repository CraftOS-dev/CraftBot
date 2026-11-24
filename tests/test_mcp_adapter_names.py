"""Generated MCP tool handlers keep server and tool names as plain strings.

A tool's name comes from the MCP server and may contain quotes, newlines
or backslashes. The generated handler must hold it unchanged as a string,
both when the action is defined and when the agent calls it.
"""

from __future__ import annotations

from typing import Dict

import pytest

from agent_core.core.impl.mcp.adapter import MCPActionAdapter
from agent_core.core.impl.mcp.server import MCPTool


@pytest.mark.parametrize(
    "tool_name",
    [
        'x"; open(MARKER, "w").close(); _ = "',
        'x"\nopen(MARKER, "w").close()\n_ = "',
        'y"""\nopen(MARKER, "w").close()\n"""',
        "z\\\nopen(MARKER, 'w').close()",
    ],
)
def test_names_with_quotes_and_newlines_stay_strings(tmp_path, tool_name):
    marker = tmp_path / "marker"
    name = tool_name.replace("MARKER", repr(str(marker)))
    handler, source = MCPActionAdapter.create_mcp_handler_with_source(
        f'srv"{name}', name
    )
    compile(source, "<mcp handler>", "exec")  # still valid Python
    namespace: Dict = {}
    exec(source, namespace)  # how the action system defines it
    assert not marker.exists()
    code = namespace["mcp_handler"].__code__
    assert name in code.co_consts and f'srv"{name}' in code.co_consts
    # ...and how it runs it when the agent uses the tool. The call itself
    # fails (no MCP client here); what matters is that the name did not run.
    namespace["mcp_handler"]({})
    handler({})
    assert not marker.exists()


def test_a_registered_tool_with_quotes_in_its_name_round_trips(tmp_path):
    tool = MCPTool(name='echo"; import os #', description="d", input_schema={})
    action = MCPActionAdapter.mcp_tool_to_registered_action("srv", tool, "mcp_srv")
    assert action.metadata.name == 'mcp_srv_echo"; import os #'
    assert 'echo"; import os #' in action.handler.__code__.co_consts
