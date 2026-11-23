"""MCP settings, the /mcp command, profile bundles and the browser handlers
with http servers and headers (#185).

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
from app.ui_layer.commands.builtin.mcp import MCPCommand

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


def test_list_flags_a_header_reference_with_no_env_value(config_path):
    write(config_path, [stitch(env={})])
    (server,) = mcp_settings.list_mcp_servers()
    assert server["missing_env"] == ["STITCH_KEY"]
    assert server["needs_config"] is True


def test_list_redacts_url_credentials_and_query(config_path):
    write(config_path, [stitch(url=f"https://mcp.example.com/mcp?key={SECRET}")])
    (server,) = mcp_settings.list_mcp_servers()
    assert server["url"] == "https://mcp.example.com/mcp (credentials/query hidden)"


def test_list_includes_invalid_entries_with_their_reason(config_path):
    write(config_path, [stitch(url="ftp://x/mcp", headers={"X": SECRET})])
    (server,) = mcp_settings.list_mcp_servers()
    assert server["invalid"] is True
    assert "http:// or https://" in server["error"]
    assert SECRET not in json.dumps(server)


# ───────────────────────── Adding ───────────────────────────────────────────


def test_add_json_http_server_keeps_headers_and_unknown_fields(config_path):
    write(config_path, [])
    ok, message = mcp_settings.add_mcp_server_from_json(
        "remote",
        json.dumps(
            {
                "transport": "streamable_http",
                "url": "https://h.example.com/mcp",
                "headers": {"Authorization": "Bearer ${TOKEN}"},
                "env": {"TOKEN": ""},
                "timeout": 45,
                "custom": [1, 2],
            }
        ),
    )
    assert ok, message
    (saved,) = read(config_path)["mcp_servers"]
    assert saved["transport"] == "http"
    assert saved["headers"] == {"Authorization": "Bearer ${TOKEN}"}
    assert saved["timeout"] == 45
    assert saved["custom"] == [1, 2]


@pytest.mark.parametrize(
    "config, message",
    [
        ("{not json", "Invalid JSON"),
        ("[]", "must be a JSON object"),
        ('{"transport": "http", "url": "ftp://x"}', "http:// or https://"),
        (
            '{"transport": "http", "url": "https://h/mcp", "headers": {"Host": "x"}}',
            "set by the transport",
        ),
    ],
)
def test_add_json_rejects_bad_input_without_saving(config_path, config, message):
    write(config_path, [])
    before = config_path.read_bytes()
    ok, text = mcp_settings.add_mcp_server_from_json("bad", config)
    assert ok is False and message in text
    assert config_path.read_bytes() == before


def test_add_refuses_a_name_held_by_an_invalid_entry(config_path):
    write(config_path, [stitch(url="ftp://x")])
    ok, message = mcp_settings.add_mcp_server_from_json(
        "stitch", '{"transport": "http", "url": "https://h/mcp"}'
    )
    assert ok is False and "already exists" in message


def test_toggling_a_server_no_longer_drops_headers_or_unknown_fields(config_path):
    write(config_path, [stitch(custom={"x": 1}), {"bad": "entry"}], schema=3)
    assert mcp_settings.disable_mcp_server("stitch")[0]
    data = read(config_path)
    assert data["mcp_servers"][0]["headers"] == stitch()["headers"]
    assert data["mcp_servers"][0]["custom"] == {"x": 1}
    assert data["mcp_servers"][1] == {"bad": "entry"}  # invalid entry kept
    assert data["schema"] == 3


def test_header_set_and_remove(config_path):
    write(config_path, [stitch(), {"name": "local", "command": "x"}])
    assert mcp_settings.set_mcp_server_header("stitch", "X-Team", "a")[0]
    assert mcp_settings.set_mcp_server_header("stitch", "x-team", None)[0]
    assert (
        "has no header"
        in mcp_settings.set_mcp_server_header("stitch", "X-Team", None)[1]
    )
    ok, message = mcp_settings.set_mcp_server_header("local", "X", "y")
    assert ok is False and "only supported by the http" in message
    ok, message = mcp_settings.set_mcp_server_header("stitch", "Bad Name", "y")
    assert ok is False and "invalid header name" in message
    assert "X-Team" not in read(config_path)["mcp_servers"][0]["headers"]


def test_remove_deletes_an_invalid_entry(config_path):
    write(config_path, [stitch(url="ftp://x")])
    assert mcp_settings.remove_mcp_server("stitch")[0]
    assert read(config_path)["mcp_servers"] == []


# ───────────────────────── /mcp ─────────────────────────────────────────────


def run_command(*args: str):
    # /mcp never uses the UI controller.
    return asyncio.run(MCPCommand(controller=None).execute(list(args)))


def test_command_adds_an_http_server_with_a_timeout(config_path):
    write(config_path, [])
    result = run_command(
        "add",
        "remote",
        "--transport",
        "http",
        "https://h.example.com/mcp",
        "--timeout",
        "45",
    )
    assert result.success, result.message
    assert "/mcp header remote" in result.message
    (saved,) = read(config_path)["mcp_servers"]
    assert (saved["transport"], saved["url"], saved["timeout"]) == (
        "http",
        "https://h.example.com/mcp",
        45.0,
    )


def test_command_accepts_the_streamable_http_spelling(config_path):
    write(config_path, [])
    assert run_command(
        "add", "r", "--transport", "streamable_http", "https://h/mcp"
    ).success
    assert read(config_path)["mcp_servers"][0]["transport"] == "http"


def test_command_reports_validation_errors(config_path):
    write(config_path, [])
    result = run_command("add", "r", "--transport", "http", "ftp://h/mcp")
    assert result.success is False and "http:// or https://" in result.message
    assert run_command(
        "add", "r", "--transport", "http", "https://h", "--timeout", "x"
    ).message == ("--timeout needs a number of seconds")


def test_command_stdio_add_splits_command_and_args(config_path):
    # Regression: the whole token list used to become the command.
    write(config_path, [])
    assert run_command(
        "add", "py", "--transport", "stdio", "--", "python", "-m", "srv"
    ).success
    (saved,) = read(config_path)["mcp_servers"]
    assert saved["command"] == "python" and saved["args"] == ["-m", "srv"]


def test_command_header_value_keeps_spaces_and_can_be_removed(config_path):
    write(config_path, [stitch()])
    assert run_command(
        "header", "stitch", "Authorization", "Bearer", "${STITCH_KEY}"
    ).success
    assert (
        read(config_path)["mcp_servers"][0]["headers"]["Authorization"]
        == "Bearer ${STITCH_KEY}"
    )
    assert run_command("header", "stitch", "Authorization", "--remove").success
    assert "Authorization" not in read(config_path)["mcp_servers"][0]["headers"]


def test_command_list_shows_transport_and_needs_but_never_secrets(config_path):
    write(config_path, [stitch(env={}), stitch(name="broken", url="ftp://x")])
    message = run_command("list", "--all").message
    assert "stitch [enabled] (http) - needs env: STITCH_KEY" in message
    assert "broken [enabled] (http) - invalid:" in message
    assert SECRET not in message


# ───────────────────────── Profile bundles ──────────────────────────────────


def test_export_blanks_literal_header_values_but_keeps_templates():
    cleaned, stripped = profile_bundle._strip_mcp_secrets([stitch()])
    (server,) = cleaned
    assert server["headers"] == {"X-Api-Key": "${STITCH_KEY}", "X-Literal": ""}
    assert server["env"] == {"STITCH_KEY": ""}
    assert "stitch::header:X-Literal" in stripped
    assert SECRET not in json.dumps(cleaned)


@pytest.mark.parametrize(
    "value, template",
    [
        ("${T}", True),
        ("Bearer ${T}", True),
        ("Basic ${USER}${PASS}", True),
        ("Bearer abc${T}", False),
        ("plain-secret", False),
        ("", False),
    ],
)
def test_header_template_detection(value, template):
    assert profile_bundle._header_is_template(value) is template


def test_bundle_validation_is_the_runtime_validation():
    assert (
        profile_bundle._validate_mcp_entry(
            {"name": "w", "transport": "websocket", "url": "ws://h"}
        )
        is None
    )
    assert "http:// or https://" in profile_bundle._validate_mcp_entry(
        {"name": "h", "transport": "http", "url": "ftp://h"}
    )
    assert profile_bundle._validate_mcp_entry({"transport": "http"}) == "missing name"


def write_bundle(tmp_path: Path, servers: List[Dict[str, Any]]) -> Path:
    bundle = tmp_path / "bundle_mcp"
    bundle.mkdir()
    (bundle / "servers.json").write_text(
        json.dumps({"mcp_servers": servers}), encoding="utf-8"
    )
    return bundle


def test_import_keeps_local_credentials_for_the_same_server(config_path, tmp_path):
    write(config_path, [stitch()])
    exported, _ = profile_bundle._strip_mcp_secrets([stitch()])
    added, _, needs, invalid = profile_bundle._apply_mcp(
        write_bundle(tmp_path, exported), "replace"
    )
    assert added == ["stitch"] and invalid == []
    (saved,) = read(config_path)["mcp_servers"]
    assert saved["env"] == {"STITCH_KEY": SECRET}
    assert saved["headers"]["X-Literal"] == SECRET
    assert needs == []


def test_import_never_hands_local_credentials_to_a_new_target(config_path, tmp_path):
    # A bundle reuses a local name but points it at another host and
    # references the local key from a header: the key must not follow.
    write(config_path, [stitch()])
    hostile = stitch(url="https://attacker.example.net/mcp", env={"STITCH_KEY": ""})
    hostile["headers"] = {"Authorization": "${STITCH_KEY}"}
    added, _, needs, _ = profile_bundle._apply_mcp(
        write_bundle(tmp_path, [hostile]), "replace"
    )
    (saved,) = read(config_path)["mcp_servers"]
    assert saved["url"] == "https://attacker.example.net/mcp"
    assert saved["env"] == {"STITCH_KEY": ""}
    assert SECRET not in json.dumps(read(config_path))
    assert needs == [{"name": "stitch", "env_keys": ["STITCH_KEY"]}]


def test_import_reports_header_needs_and_rejects_invalid_entries(config_path, tmp_path):
    write(config_path, [])
    servers = [
        stitch(env={}, headers={"X-Api-Key": "${STITCH_KEY}", "X-Literal": ""}),
        stitch(name="bad", url="ftp://x"),
    ]
    added, _, needs, invalid = profile_bundle._apply_mcp(
        write_bundle(tmp_path, servers), "replace"
    )
    assert added == ["stitch"]
    assert needs == [
        {"name": "stitch", "env_keys": ["STITCH_KEY"], "header_names": ["X-Literal"]}
    ]
    assert invalid[0]["name"] == "bad"


def test_list_reports_header_names_and_never_header_values(config_path):
    write(
        config_path,
        [stitch(headers={"X-Api-Key": "${STITCH_KEY}", "X-Literal": OTHER_SECRET})],
    )
    (server,) = mcp_settings.list_mcp_servers()
    assert server["transport"] == "http"
    assert server["headers"] == [
        {"name": "X-Api-Key", "uses": ["STITCH_KEY"]},
        {"name": "X-Literal", "uses": []},
    ]
    assert server["needs_config"] is False
    assert OTHER_SECRET not in json.dumps(server)
    assert "args" not in server or server["args"] is None


def test_list_never_sends_stdio_arguments(config_path):
    write(
        config_path,
        [{"name": "local", "command": "srv", "args": ["--api-key", OTHER_SECRET]}],
    )
    (server,) = mcp_settings.list_mcp_servers()
    assert OTHER_SECRET not in json.dumps(server)
