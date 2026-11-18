# -*- coding: utf-8 -*-
"""Every action says how the chat shows its runs.

The chat shows a run as one line: an icon (an integration's logo, or a
lucide icon), the action's name, and the value of the action's
``display_param``. Each action and provider operation declares that
parameter explicitly (None when none says what a call does), it is one of
its inputs, and it never shows a credential.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LUCIDE_TYPES = ROOT / "app/ui_layer/browser/frontend/node_modules/lucide-react/dist/lucide-react.d.ts"
CREDENTIAL = re.compile(r"password|secret|access_token|api_key|private_key", re.I)
DEFINERS = {"action", "client_op", "Operation", "_op", "_urn_op"}


@pytest.fixture(scope="module")
def registry():
    from agent_core.core.action_framework.loader import load_actions_from_directories
    from agent_core.core.action_framework.registry import registry_instance

    load_actions_from_directories(
        base_dir=str(ROOT), paths_to_scan=[os.path.join("app", "data", "action")]
    )
    return registry_instance


@pytest.fixture(scope="module")
def provider_ids():
    from craftos_integrations.providers import default_providers

    return {provider.id for provider in default_providers()}


def _definitions(path: Path):
    """(line, name, keywords) of each literal-named action definition."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if fname not in DEFINERS:
            continue
        name = next(
            (
                kw.value.value
                for kw in node.keywords
                if kw.arg == "name" and isinstance(kw.value, ast.Constant)
            ),
            None,
        )
        if name is None and fname != "action" and node.args:
            first = node.args[0]
            name = first.value if isinstance(first, ast.Constant) else None
        if isinstance(name, str):
            yield node.lineno, name, {kw.arg for kw in node.keywords}


def test_every_definition_declares_its_display_param():
    files = list((ROOT / "app/data/action").rglob("*.py")) + list(
        (ROOT / "craftos_integrations/providers").rglob("*.py")
    )
    missing = [
        f"{path.relative_to(ROOT)}:{line} {name}"
        for path in files
        for line, name, keywords in _definitions(path)
        if "display_param" not in keywords
    ]
    assert missing == []


def test_every_action_shows_an_input_that_is_no_credential(registry):
    wrong = []
    for name, impls in registry.list_all_actions().items():
        meta = next(iter(impls.values())).metadata
        param = meta.display_param
        if param is None:
            continue
        if param not in (meta.input_schema or {}):
            wrong.append(f"{name}: {param} is not an input")
        elif CREDENTIAL.search(param):
            wrong.append(f"{name}: {param} is a credential")
    assert wrong == []


def test_every_action_has_a_logo_or_a_real_icon(registry, provider_ids):
    icons = None
    if LUCIDE_TYPES.exists():
        icons = set(
            re.findall(r"declare const (\w+): LucideIcon;", LUCIDE_TYPES.read_text("utf-8"))
        )
    wrong = []
    for name, impls in registry.list_all_actions().items():
        meta = next(iter(impls.values())).metadata
        if meta.integration:
            if meta.integration not in provider_ids:
                wrong.append(f"{name}: unknown integration {meta.integration}")
        elif not meta.icon:
            wrong.append(f"{name}: neither integration nor icon")
        elif icons is not None and meta.icon not in icons:
            wrong.append(f"{name}: {meta.icon} is not a lucide icon")
    assert wrong == []


def test_the_chat_gets_the_display_by_name(registry):
    from agent_core.core.action_framework import action_row_display

    assert action_row_display("web_search") == {"displayParam": "query", "icon": "Search"}
    assert action_row_display("Web search") == action_row_display("web_search")
    assert action_row_display("List github issues")["integration"] == "github"
    # Declared as showing no input: the chat must not guess one.
    assert action_row_display("mini_browser_click") == {
        "displayParam": None,
        "icon": "MousePointerClick",
    }
    assert action_row_display("no_such_action") == {}


def test_mcp_tools_show_their_first_required_text_input():
    from agent_core.core.impl.mcp.adapter import MCPActionAdapter

    schema = {
        "limit": {"type": "integer", "required": True},
        "notes": {"type": "string", "required": False},
        "path": {"type": "string", "required": True},
    }
    assert MCPActionAdapter._display_param(schema) == "path"
    assert MCPActionAdapter._display_param({"notes": {"type": "string"}}) == "notes"
    assert MCPActionAdapter._display_param({}) is None
