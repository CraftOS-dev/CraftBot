# -*- coding: utf-8 -*-
"""The capability catalog describes every action set (prompt audit T7).

183 of the catalog's sets used to read "Custom action set: <name>", one line
per integration sub-set. Every set is now described from data that already
exists: an application set by its declaration, an MCP server's set by its
config, an integration's sets by its provider, listed together on one line.
Which integration owns a set is read from where its actions come from (the
adapter's declarations, the bridged platform directories), never from the
set's name. These tests pin:

* on the real registry: every set is described, every set name is still in
  the catalog, ownership is right where names mislead, and the catalog is
  the same on every render;
* a set described nowhere is described by its actions, an MCP set by its
  server's config;
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
print("CATALOG-JSON " + json.dumps({
    "sets": action_set_manager.list_all_sets(),
    "catalog": action_set_manager.format_sets_for_prompt(exclude_core=True),
    "again": action_set_manager.format_sets_for_prompt(exclude_core=True),
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


def _listed_sets(catalog: str) -> set:
    """The set names a catalog lists: "- <set>: <description>" lines, and
    "- <Integration> (<what it does>): <set>, <set>, ..." lines."""
    names = set()
    for line in catalog.splitlines():
        if not line.startswith("- "):
            continue
        head, _, rest = line[2:].partition(": ")
        if " " not in head and "(" not in head:
            names.add(head)
        else:
            names.update(line.rpartition("): ")[2].split(", "))
    return names


def test_every_set_name_is_still_in_the_catalog(real):
    assert _listed_sets(real["catalog"]) == set(real["sets"]) - {"core"}


def test_ownership_comes_from_where_the_actions_live(real):
    lines = {line.split(" (")[0]: line for line in real["catalog"].splitlines()}
    assert "lark_sheets" in lines["- Lark Drive"]
    assert "lark_sheets" not in lines["- Lark"]
    telegram = lines["- Telegram"]
    assert "Telegram Bot" in telegram and "Telegram (User)" in telegram
    assert "telegram_user" in telegram


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


def test_a_bridged_platform_lists_all_its_sets_on_one_line(fake):
    catalog = fake.format_sets_for_prompt(exclude_core=True)
    (line,) = [ln for ln in catalog.splitlines() if ln.startswith("- Telegram")]
    assert line.endswith(": telegram, telegram_messages")  # its own set first
    assert "- telegram_messages:" not in catalog
    assert "- core:" not in catalog


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
