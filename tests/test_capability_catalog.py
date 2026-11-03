# -*- coding: utf-8 -*-
"""Every action set is described, and the catalog names them all (prompt
audit T7, then the 2026-11-01 prompt benchmark).

183 sets used to read "Custom action set: <name>". Every set is now described
from data that already exists: an application set by its declaration, an MCP
server's set by its config, an integration's sets by its provider. Which
integration owns a set is read from where its actions come from (the
adapter's declarations, the bridged platform directories), never from the
set's name. The descriptions reach the agent through list_action_sets; the
Capability Catalog in the system prompt lists set and skill names only (the
benchmark found the descriptions there added tokens and no quality). These
tests pin:

* on the real registry: every set is described, the catalog names every set
  (names only) and renders the same every time, and ownership is right where
  names mislead;
* a set described nowhere is described by its actions, an MCP set by its
  server's config, a bridged platform's sets by the platform;
* list_action_sets can list the actions of the sets asked for.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.action.action_set import ActionSetManager, action_set_manager

REPO = Path(__file__).resolve().parents[1]

_RENDER = """
import json, sys
sys.path.insert(0, ".")
from agent_core.core.action_framework.loader import load_actions_from_directories
load_actions_from_directories(paths_to_scan=["app/data/action"])
from app.action.action_set import action_set_manager
from agent_core.core.impl.context.engine import ContextEngine
engine = ContextEngine.__new__(ContextEngine)
print("CATALOG-JSON " + json.dumps({
    "sets": action_set_manager.list_all_sets(),
    "catalog": engine.create_system_capability_catalog(),
    "again": engine.create_system_capability_catalog(),
}))
"""


@pytest.fixture(scope="module")
def real():
    """The catalog of the real action registry, rendered in a subprocess so
    loading every action does not touch this process's registry."""
    out = subprocess.run(
        [sys.executable, "-B", "-c", _RENDER],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    line = next(
        (ln for ln in out.stdout.splitlines() if ln.startswith("CATALOG-JSON ")), None
    )
    assert line, out.stderr[-2000:]
    return json.loads(line[len("CATALOG-JSON ") :])


def test_every_real_set_is_described(real):
    undescribed = [
        name for name, text in real["sets"].items() if text.startswith("Actions: ")
    ]
    assert undescribed == [], (
        f"Describe these action sets (DEFAULT_SET_DESCRIPTIONS, or an "
        f"integration's provider): {undescribed}"
    )
    assert not any("Custom action set" in text for text in real["sets"].values())


def _catalog_set_names(catalog: str) -> list:
    """The set names on the catalog's action-set line."""
    lines = catalog.splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith("Action sets you can load"))
    return lines[i + 1].split(", ")


def test_the_catalog_names_every_set_and_nothing_else(real):
    names = _catalog_set_names(real["catalog"])
    assert names == sorted(set(real["sets"]) - {"core"})
    for description in real["sets"].values():
        assert description not in real["catalog"]


def test_ownership_comes_from_where_the_actions_live(real):
    sets = real["sets"]
    assert sets["lark_sheets"].startswith("Lark Drive:")
    assert sets["lark"].startswith("Lark:")
    telegram = sets["telegram_user"]
    assert "Telegram Bot" in telegram and "Telegram (User)" in telegram


def test_the_catalog_renders_the_same_every_time(real):
    assert real["catalog"] == real["again"]


# ── a fake registry ──────────────────────────────────────────────────────────


def _handler(path_parts):
    """A function whose source file is the given path (as a bridged action's
    file under app/data/action/integrations/<dir>/ would be)."""
    namespace = {}
    exec(compile("def handler(): pass", os.path.join(*path_parts), "exec"), namespace)
    return namespace["handler"]


def _impl(name, sets, path_parts=("app", "data", "action", "misc.py")):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, action_sets=sets),
        handler=_handler(path_parts),
    )


@pytest.fixture
def fake(monkeypatch):
    impls = [
        _impl("send_message", ["core"]),
        _impl("generate_image", ["content_creation", "image"]),
        _impl("my_a", ["my_custom_set"]),
        _impl("my_b", ["my_custom_set"]),
        _impl(
            "telegram_send",
            ["telegram", "telegram_messages"],
            (
                "app",
                "data",
                "action",
                "integrations",
                "telegram",
                "telegram_actions.py",
            ),
        ),
        _impl("mcp_fs_read", ["mcp_fs"]),
    ]
    monkeypatch.setattr(
        ActionSetManager, "_registered", staticmethod(lambda: iter(impls))
    )
    monkeypatch.setattr(action_set_manager, "_integration_sets", {})
    monkeypatch.setattr(
        ActionSetManager,
        "_mcp_set_descriptions",
        staticmethod(lambda: {"mcp_fs": "Read files of the workspace"}),
    )
    return action_set_manager


def test_a_set_described_nowhere_is_described_by_its_actions(fake):
    assert fake.list_all_sets()["my_custom_set"] == "Actions: my_a, my_b"


def test_an_mcp_set_is_described_by_its_server(fake):
    assert fake.list_all_sets()["mcp_fs"] == "Read files of the workspace"


def test_a_bridged_platform_describes_all_its_sets(fake):
    sets = fake.list_all_sets()
    assert sets["telegram"] == sets["telegram_messages"]
    assert sets["telegram"].startswith("Telegram")


def test_a_declared_provider_set_is_listed_under_its_provider(fake):
    fake.declare_integration_set("gmail_drafts", "gmail")
    fake.declare_integration_set("gmail", "gmail")
    assert fake.integration_sets()["gmail"] == ["gmail_drafts", "gmail"]
    name, what = fake.integration_description("gmail")
    assert name == "Gmail" and what


def test_mcp_sets_are_described_from_the_server_config(monkeypatch):
    import app.mcp as mcp_module

    servers = {
        "fs": SimpleNamespace(
            config=SimpleNamespace(resolved_action_set_name="mcp_fs", description="")
        ),
        "web": SimpleNamespace(
            config=SimpleNamespace(
                resolved_action_set_name="mcp_web", description="Fetch pages"
            )
        ),
    }
    monkeypatch.setattr(mcp_module, "mcp_client", SimpleNamespace(servers=servers))
    assert ActionSetManager._mcp_set_descriptions() == {
        "mcp_fs": "Tools of the 'fs' MCP server",
        "mcp_web": "Fetch pages",
    }


def test_list_action_sets_lists_the_actions_of_the_sets_asked_for(fake, monkeypatch):
    from app.internal_action_interface import InternalActionInterface

    monkeypatch.setattr(InternalActionInterface, "session_manager", None)
    monkeypatch.setattr(
        action_set_manager,
        "get_actions_in_set",
        lambda name: {"my_custom_set": ["my_a", "my_b"]}.get(name, []),
    )
    result = InternalActionInterface.list_action_sets(sets=["my_custom_set"])
    assert result["set_actions"] == {"my_custom_set": ["my_a", "my_b"]}
    assert "set_actions" not in InternalActionInterface.list_action_sets()
