# -*- coding: utf-8 -*-
"""Every action parameter declares whether it is required (prompt audit T9).

The action list told the model "required" or "optional" for each parameter
by searching its description for "default" or "optional": a parameter whose
description happened to say "defaults to" was shown optional, and one the
handler cannot run without but described without those words was shown
required or the reverse. The flag is now declared on every schema, decided
from the code that runs the action, and the formatter prints only what is
declared. These tests pin:

* on the real registry: every parameter of every action (hand-written,
  bridged integrations with their injected ``account``, generated provider
  operations) declares a bool ``required``;
* the formatter prints the declared flag and never reads the description;
* MCP tools declare it from their JSON Schema's ``required`` list.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_core.core.action_framework.formatting import format_action_candidates
from agent_core.core.impl.mcp.adapter import MCPActionAdapter

REPO = Path(__file__).resolve().parents[1]

_UNDECLARED = """
import json, sys
sys.path.insert(0, ".")
from agent_core.core.action_framework.loader import load_actions_from_directories
load_actions_from_directories(paths_to_scan=["app/data/action"])
from app.data.action.integrations.account_bridge import inject_account_schemas
inject_account_schemas()
from agent_core.core.action_framework.registry import ActionRegistry
params, undeclared = 0, []
for name, impls in ActionRegistry()._registry.items():
    for registered in impls.values():
        for param, schema in (registered.metadata.input_schema or {}).items():
            params += 1
            if not isinstance(schema, dict) or not isinstance(schema.get("required"), bool):
                undeclared.append(name + "." + param)
print("REQUIRED-JSON " + json.dumps({"params": params, "undeclared": undeclared}))
"""


@pytest.fixture(scope="module")
def real():
    """Every registered parameter, read in a subprocess so loading every
    action does not touch this process's registry."""
    out = subprocess.run(
        [sys.executable, "-B", "-c", _UNDECLARED],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    line = next(
        (ln for ln in out.stdout.splitlines() if ln.startswith("REQUIRED-JSON ")),
        None,
    )
    assert line, out.stderr[-2000:]
    return json.loads(line[len("REQUIRED-JSON ") :])


def test_every_real_parameter_declares_required(real):
    assert real["params"] > 4000  # the whole registry was read
    assert real["undeclared"] == [], (
        f"Declare \"required\": True/False on these parameters, decided by "
        f"what the handler does without them: {real['undeclared'][:50]}"
    )


# ── the formatter ────────────────────────────────────────────────────────────


def _render(schema):
    candidate = {"name": "act", "description": "", "input_schema": schema}
    return json.loads(format_action_candidates([candidate]))[0]["params"]


def test_the_declared_flag_is_printed():
    params = _render(
        {
            "path": {"type": "string", "required": True, "description": "File."},
            "limit": {"type": "integer", "required": False, "description": "Rows."},
        }
    )
    assert params == {
        "path": "string, required - File.",
        "limit": "integer, optional - Rows.",
    }


def test_the_description_never_decides_it():
    params = _render(
        {
            "mode": {
                "type": "string",
                "required": True,
                "description": "Optional in name only; defaults are not used.",
            },
            "query": {
                "type": "string",
                "required": False,
                "description": "The search text.",
            },
        }
    )
    assert params["mode"].startswith("string, required - ")
    assert params["query"].startswith("string, optional - ")


def test_an_undeclared_parameter_gets_no_label():
    params = _render(
        {"note": {"type": "string", "description": "Optional, default empty."}}
    )
    assert params == {"note": "string - Optional, default empty."}


# ── MCP tools ────────────────────────────────────────────────────────────────


def test_mcp_tools_declare_it_from_their_json_schema():
    schema = MCPActionAdapter.convert_json_schema_to_input_schema(
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["path"],
        }
    )
    assert schema["path"]["required"] is True
    assert schema["encoding"]["required"] is False
