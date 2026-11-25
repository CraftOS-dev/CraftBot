"""Write-only MCP secrets for the settings editors (#185): env values and
stdio arguments are never sent to a client, and the form editor keeps a
stored value when its field is left empty.

They all write through ``mcp_settings`` and the runtime's validation, and
none of them may hand an env or header value to the browser, the chat, or an
exported bundle.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

import app.ui_layer.settings.mcp_settings as mcp_settings
import app.ui_layer.settings.profile_bundle as profile_bundle

SECRET = "sk-settings-SENTINEL-7777"
OTHER_SECRET = "sk-other-SENTINEL-8888"


@pytest.fixture
def config_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "mcp_config.json"
    monkeypatch.setattr(mcp_settings, "MCP_CONFIG_PATH", path)
    monkeypatch.setattr(profile_bundle, "MCP_CONFIG_PATH", path)
    return path


def write(path: Path, servers: List[Dict[str, Any]], **top) -> None:
    path.write_text(json.dumps({"mcp_servers": servers, **top}), encoding="utf-8")


def read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stitch(**overrides) -> Dict[str, Any]:
    entry = {
        "name": "stitch",
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"X-Api-Key": "${STITCH_KEY}", "X-Literal": SECRET},
        "env": {"STITCH_KEY": SECRET},
        "enabled": True,
    }
    entry.update(overrides)
    return entry


# ───────────────────────── Listing never carries secrets ────────────────────


def test_list_reports_env_and_headers_without_values(config_path):
    write(config_path, [stitch(), {"name": "local", "command": "x", "env": {"T": ""}}])
    servers = {s["name"]: s for s in mcp_settings.list_mcp_servers()}
    assert SECRET not in json.dumps(servers)
    http = servers["stitch"]
    assert http["transport"] == "http"
    assert http["env"] == {"STITCH_KEY": True}
    assert http["headers"] == [
        {"name": "X-Api-Key", "uses": ["STITCH_KEY"]},
        {"name": "X-Literal", "uses": []},
    ]
    assert http["needs_config"] is False
    assert servers["local"]["missing_env"] == ["T"]
    assert servers["local"]["needs_config"] is True


def test_env_status_names_keys_only(config_path):
    write(config_path, [stitch(env={"STITCH_KEY": SECRET, "UNUSED": ""})])
    assert mcp_settings.get_server_env_status("stitch") == {
        "STITCH_KEY": True,
        "UNUSED": False,
    }
    assert mcp_settings.get_server_env_status("missing") is None


# ───────────────────────── Editing from the form (write-only) ───────────────


def test_saving_the_form_keeps_unchanged_secrets_without_seeing_them(config_path):
    write(config_path, [stitch(custom="kept")])
    ok, message = mcp_settings.save_mcp_server(
        {
            "name": "stitch",
            "description": "Design tool",
            "url": None,  # keep
            "timeout": 60,
            "headers": [
                {"name": "x-api-key", "value": None},  # keep (case-insensitive)
                {"name": "X-Team", "value": "design"},  # new
            ],  # X-Literal omitted: removed
            "env": [{"key": "STITCH_KEY", "value": None}],
        },
        create=False,
    )
    assert ok, message
    (saved,) = read(config_path)["mcp_servers"]
    assert saved["headers"] == {"x-api-key": "${STITCH_KEY}", "X-Team": "design"}
    assert saved["env"] == {"STITCH_KEY": SECRET}
    assert saved["url"] == "https://mcp.example.com/mcp"
    assert saved["description"] == "Design tool"
    assert saved["timeout"] == 60
    assert saved["custom"] == "kept"


def test_keeping_a_value_that_does_not_exist_is_an_error(config_path):
    write(config_path, [stitch()])
    before = config_path.read_bytes()
    ok, message = mcp_settings.save_mcp_server(
        {"name": "stitch", "headers": [{"name": "X-New", "value": None}]}, create=False
    )
    assert ok is False and "Enter a value for header 'X-New'" in message
    assert config_path.read_bytes() == before


def test_an_invalid_form_is_not_saved_and_the_error_has_no_secret(config_path):
    write(config_path, [stitch()])
    before = config_path.read_bytes()
    ok, message = mcp_settings.save_mcp_server(
        {
            "name": "stitch",
            "headers": [{"name": "X-Api-Key", "value": f"{SECRET}\r\nInjected: 1"}],
        },
        create=False,
    )
    assert ok is False and "control character" in message
    assert SECRET not in message
    assert config_path.read_bytes() == before


def test_creating_from_the_form_and_refusing_duplicates(config_path):
    write(config_path, [])
    form = {
        "name": "new",
        "transport": "http",
        "url": "https://new.example.com/mcp",
        "headers": [{"name": "Authorization", "value": "Bearer ${T}"}],
        "env": [{"key": "T", "value": SECRET}],
        "enabled": True,
    }
    assert mcp_settings.save_mcp_server(form, create=True)[0]
    ok, message = mcp_settings.save_mcp_server(form, create=True)
    assert ok is False and "already exists" in message
    (saved,) = read(config_path)["mcp_servers"]
    assert saved["env"] == {"T": SECRET}


def test_editing_a_missing_or_invalid_server(config_path):
    write(config_path, [stitch(url="ftp://x")])
    assert (
        "not found" in mcp_settings.save_mcp_server({"name": "nope"}, create=False)[1]
    )
    assert (
        "invalid entry"
        in mcp_settings.save_mcp_server({"name": "stitch"}, create=False)[1]
    )


# ───────────────────────── Browser handlers ─────────────────────────────────


@pytest.fixture
def adapter(monkeypatch):
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    sent: List[Dict[str, Any]] = []
    instance = object.__new__(BrowserAdapter)

    async def broadcast(message):
        sent.append(message)

    instance._broadcast = broadcast
    # MCP is not running in these tests: no live reload is scheduled.
    from app.mcp import mcp_client

    monkeypatch.setattr(type(mcp_client), "config", property(lambda self: None))
    return instance, sent


def test_browser_list_and_env_carry_no_values(config_path, adapter):
    instance, sent = adapter
    write(config_path, [stitch()])
    asyncio.run(instance._handle_mcp_list())
    asyncio.run(instance._handle_mcp_get_env("stitch"))
    assert sent[0]["type"] == "mcp_list" and sent[0]["data"]["success"]
    assert sent[1] == {
        "type": "mcp_get_env",
        "data": {"success": True, "name": "stitch", "env": {"STITCH_KEY": True}},
    }
    assert SECRET not in json.dumps(sent)


def test_browser_save_server_validates_and_refreshes(config_path, adapter):
    instance, sent = adapter
    write(config_path, [stitch()])
    asyncio.run(
        instance._handle_mcp_save_server(
            {"name": "stitch", "headers": [{"name": "X-Api-Key", "value": None}]}, False
        )
    )
    asyncio.run(
        instance._handle_mcp_save_server({"name": "stitch", "url": "ftp://x"}, False)
    )
    assert sent[0]["type"] == "mcp_save_server" and sent[0]["data"]["success"] is True
    assert sent[1]["type"] == "mcp_list"
    assert sent[2]["data"]["success"] is False
    assert "http:// or https://" in sent[2]["data"]["message"]
    assert SECRET not in json.dumps(sent)
    assert read(config_path)["mcp_servers"][0]["url"] == "https://mcp.example.com/mcp"


def test_stdio_arguments_are_never_listed_and_kept_on_edit(config_path):
    # Arguments often carry tokens (--api-key ...): write-only like env.
    write(
        config_path,
        [{"name": "local", "command": "srv", "args": ["--api-key", SECRET]}],
    )
    (server,) = mcp_settings.list_mcp_servers()
    assert server["args"] is None and server["args_count"] == 2
    assert SECRET not in json.dumps(server)
    assert mcp_settings.save_mcp_server(
        {"name": "local", "description": "d", "args": None}, create=False
    )[0]
    assert read(config_path)["mcp_servers"][0]["args"] == ["--api-key", SECRET]
    assert mcp_settings.save_mcp_server(
        {"name": "local", "description": "d"}, create=False
    )[0]
    assert read(config_path)["mcp_servers"][0]["args"] == ["--api-key", SECRET]
    assert mcp_settings.save_mcp_server(
        {"name": "local", "args": ["--port", "1"]}, create=False
    )[0]
    assert read(config_path)["mcp_servers"][0]["args"] == ["--port", "1"]


# ── Review fixes (#542) ──


def test_the_form_never_replaces_an_unreadable_config(config_path):
    broken = '{"mcp_servers": [%s,]}' % json.dumps(stitch())
    config_path.write_text(broken, encoding="utf-8")
    ok, message = mcp_settings.save_mcp_server(
        {"name": "new", "transport": "http", "url": "https://h/mcp", "env": []},
        create=True,
    )
    assert ok is False and "nothing was saved" in message
    assert SECRET not in message
    assert config_path.read_text(encoding="utf-8") == broken


def test_a_duplicate_env_key_is_refused_and_the_stored_value_kept(config_path):
    write(config_path, [stitch()])
    ok, message = mcp_settings.save_mcp_server(
        {
            "name": "stitch",
            "transport": "http",
            "env": [
                {"key": "STITCH_KEY", "value": None},
                {"key": "STITCH_KEY", "value": ""},
            ],
        },
        create=False,
    )
    assert ok is False and "listed twice" in message
    assert read(config_path)["mcp_servers"][0]["env"]["STITCH_KEY"] == SECRET


def test_a_header_listed_twice_in_any_case_is_refused(config_path):
    write(config_path, [stitch()])
    ok, message = mcp_settings.save_mcp_server(
        {
            "name": "stitch",
            "transport": "http",
            "headers": [
                {"name": "X-Literal", "value": None},
                {"name": "x-literal", "value": "other"},
            ],
        },
        create=False,
    )
    assert ok is False and "listed twice" in message
    assert read(config_path)["mcp_servers"][0]["headers"]["X-Literal"] == SECRET


def test_switching_away_from_http_keeps_the_saved_headers(config_path):
    write(config_path, [stitch()])
    ok, _ = mcp_settings.save_mcp_server(
        {
            "name": "stitch",
            "transport": "sse",
            "url": None,
            "env": [{"key": "STITCH_KEY", "value": None}],
        },
        create=False,
    )
    assert ok
    saved = read(config_path)["mcp_servers"][0]
    assert saved["transport"] == "sse"
    assert saved["headers"] == stitch()["headers"]  # kept, not applied
    (listed,) = mcp_settings.list_mcp_servers()
    assert [h["name"] for h in listed["headers"]] == ["X-Api-Key", "X-Literal"]
    assert SECRET not in json.dumps(listed)
    # Switching back with the rows left as they are restores them.
    ok, _ = mcp_settings.save_mcp_server(
        {
            "name": "stitch",
            "transport": "http",
            "url": None,
            "headers": [
                {"name": "X-Api-Key", "value": None},
                {"name": "X-Literal", "value": None},
            ],
            "env": [{"key": "STITCH_KEY", "value": None}],
        },
        create=False,
    )
    assert ok
    assert read(config_path)["mcp_servers"][0]["headers"] == stitch()["headers"]
