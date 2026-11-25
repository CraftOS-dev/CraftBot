"""MCP server configuration: the http transport, headers and safe saving (#185).

Structure is validated when an entry is built; ``${NAME}`` references in
headers are resolved at connect time from that server's own ``env`` only.
Nothing here may put an env or header value into an error message.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.core.impl.mcp.config import (
    DEFAULT_HTTP_TIMEOUT,
    MCPConfig,
    MCPConfigError,
    MCPServerConfig,
    redact_url,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-config-SENTINEL-4242"


def http(**overrides) -> dict:
    entry = {
        "name": "remote",
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
    }
    entry.update(overrides)
    return entry


def build(**overrides) -> MCPServerConfig:
    return MCPServerConfig.from_dict(http(**overrides))


# ───────────────────────── Backward compatibility ───────────────────────────


def test_every_shipped_server_entry_still_loads_unchanged():
    path = PROJECT_ROOT / "app" / "config" / "mcp_config.default.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    config = MCPConfig.from_dict(raw)
    assert config.invalid_servers == []
    assert len(config.mcp_servers) == len(raw["mcp_servers"])
    # A load/save round trip does not change any shipped entry.
    assert config.to_dict()["mcp_servers"] == [
        MCPServerConfig.from_dict(e).to_dict() for e in raw["mcp_servers"]
    ]
    for before, after in zip(raw["mcp_servers"], config.to_dict()["mcp_servers"]):
        for key, value in before.items():
            assert after[key] == value


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_existing_url_transports_keep_their_lenient_url_check(transport):
    # Unchanged: sse/websocket only require a url to be present.
    server = MCPServerConfig.from_dict(
        {"name": "x", "transport": transport, "url": "localhost:9000/sse"}
    )
    assert server.url == "localhost:9000/sse"
    with pytest.raises(MCPConfigError, match="'url' is not specified"):
        MCPServerConfig.from_dict({"name": "x", "transport": transport})


def test_mcp_config_error_is_a_value_error_for_existing_callers():
    assert issubclass(MCPConfigError, ValueError)


# ───────────────────────── Transport ────────────────────────────────────────


@pytest.mark.parametrize(
    "spelling", ["http", "HTTP", " http ", "streamable_http", "streamable-http"]
)
def test_http_transport_spellings_normalise_to_http(spelling):
    server = build(transport=spelling)
    assert server.transport == "http"
    assert server.to_dict()["transport"] == "http"


def test_unknown_transport_is_rejected_with_the_valid_choices():
    with pytest.raises(MCPConfigError) as excinfo:
        build(transport="grpc")
    assert "stdio, sse, websocket, http" in str(excinfo.value)


@pytest.mark.parametrize(
    "url, message",
    [
        (None, "not specified"),
        ("", "not specified"),
        ("ftp://mcp.example.com/mcp", "http:// or https://"),
        ("ws://mcp.example.com/mcp", "http:// or https://"),
        ("mcp.example.com/mcp", "http:// or https://"),
        ("https:///mcp", "no host"),
        ("https://mcp.example.com:99999/mcp", "not a valid URL"),
        ("https://user:pw@mcp.example.com/mcp", "not in the url"),
        ("https://mcp.example.com/mcp#frag", "fragment"),
        ("https://mcp.example.com/m cp", "without spaces"),
        (" https://mcp.example.com/mcp", "without spaces"),
    ],
)
def test_http_url_validation(url, message):
    with pytest.raises(MCPConfigError, match=message):
        build(url=url)


def test_http_url_errors_never_echo_the_url():
    # A query string may carry a key; the message names the server only.
    with pytest.raises(MCPConfigError) as excinfo:
        build(url=f"ftp://mcp.example.com/mcp?key={SECRET}")
    assert SECRET not in str(excinfo.value)


def test_http_urls_with_ports_ipv6_and_query_are_accepted():
    for url in (
        "http://127.0.0.1:8123/mcp",
        "https://[::1]:8443/mcp",
        "https://mcp.example.com/mcp?region=eu",
    ):
        assert build(url=url).url == url


# ───────────────────────── Headers ──────────────────────────────────────────


def test_headers_are_kept_per_server_and_saved():
    server = build(headers={"Authorization": "Bearer ${TOKEN}", "X-Team": "a"})
    assert server.headers == {"Authorization": "Bearer ${TOKEN}", "X-Team": "a"}
    assert server.to_dict()["headers"] == server.headers
    # Not shared with another instance (no mutable default leakage).
    other = build(name="other")
    assert other.headers == {}
    assert server.headers is not other.headers


@pytest.mark.parametrize(
    "headers, message",
    [
        ("Bearer x", "must be an object"),
        ({"Bad Header": "x"}, "invalid header name"),
        ({"X-Ok:": "x"}, "invalid header name"),
        ({"": "x"}, "invalid header name"),
        ({"X-Num": 5}, "must be a string"),
        ({"X-Split": "a\r\nInjected: 1"}, "control character"),
        ({"X-Null": "a\x00b"}, "control character"),
        ({"X-Ref": "${UNCLOSED"}, "malformed reference"),
        ({"X-Ref": "${1BAD}"}, "malformed reference"),
        ({"Authorization": "a", "authorization": "b"}, "given twice"),
    ],
)
def test_invalid_headers_are_rejected(headers, message):
    with pytest.raises(MCPConfigError, match=message):
        build(headers=headers)


@pytest.mark.parametrize(
    "name",
    [
        "Accept",
        "content-type",
        "Content-Length",
        "Host",
        "Mcp-Session-Id",
        "MCP-Protocol-Version",
        "Last-Event-ID",
        "Transfer-Encoding",
    ],
)
def test_transport_owned_headers_cannot_be_configured(name):
    with pytest.raises(MCPConfigError, match="set by the transport"):
        build(headers={name: "x"})


def test_header_errors_never_echo_the_value():
    with pytest.raises(MCPConfigError) as excinfo:
        build(headers={"Authorization": f"Bearer {SECRET}\r\nX: y"})
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize(
    "entry, kept",
    [
        (
            {
                "name": "a",
                "transport": "stdio",
                "command": "npx",
                "args": ["x"],
                "timeout": 60000,
            },
            {"timeout": 60000},
        ),
        (
            {
                "name": "b",
                "transport": "sse",
                "url": "https://h/sse",
                "headers": {"Authorization": "Bearer t"},
            },
            {"headers": {"Authorization": "Bearer t"}},
        ),
        (
            {
                "name": "c",
                "transport": "websocket",
                "url": "wss://h/ws",
                "headers": {"bad name": "x"},
                "timeout": "soon",
            },
            {"headers": {"bad name": "x"}, "timeout": "soon"},
        ),
    ],
)
def test_http_only_keys_on_other_transports_still_load_and_are_ignored(entry, kept):
    # Earlier versions ignored these keys outside http, so such entries must
    # keep loading after an upgrade: not applied, not validated, kept as-is.
    config = MCPConfig.from_dict({"mcp_servers": [entry]})
    assert config.invalid_servers == []
    (server,) = config.mcp_servers
    assert server.headers == {} and server.timeout is None
    saved = server.to_dict()
    for key, value in kept.items():
        assert saved[key] == value


def test_http_only_keys_kept_on_sse_apply_again_after_switching_to_http():
    entry = {
        "name": "b",
        "transport": "sse",
        "url": "https://h/mcp",
        "headers": {"Authorization": "Bearer t"},
        "timeout": 45,
    }
    saved = MCPServerConfig.from_dict(entry).to_dict()
    switched = MCPServerConfig.from_dict({**saved, "transport": "http"})
    assert switched.headers == {"Authorization": "Bearer t"}
    assert switched.timeout == 45


def test_ignoring_http_only_keys_warns_once_without_header_values():
    from loguru import logger

    entry = {
        "name": "warned-once",
        "transport": "sse",
        "url": "https://h/sse",
        "headers": {"Authorization": f"Bearer {SECRET}"},
    }
    lines = []
    sink = logger.add(lambda m: lines.append(str(m)), level="WARNING")
    try:
        MCPServerConfig.from_dict(entry)
        MCPServerConfig.from_dict(entry)  # a reload: no second warning
    finally:
        logger.remove(sink)
    warnings = [line for line in lines if "only apply to the http transport" in line]
    assert len(warnings) == 1
    assert SECRET not in "".join(lines)


def test_a_tab_is_allowed_in_a_header_value():
    assert build(headers={"X": "a\tb"}).headers == {"X": "a\tb"}


# ───────────────────────── Resolving ${NAME} ────────────────────────────────


def test_references_resolve_from_the_servers_own_env():
    server = build(
        headers={"Authorization": "Bearer ${TOKEN}", "X-Pair": "${A}-${B}"},
        env={"TOKEN": SECRET, "A": "1", "B": "2"},
    )
    assert server.resolve_headers() == {
        "Authorization": f"Bearer {SECRET}",
        "X-Pair": "1-2",
    }
    assert server.header_env_refs() == ["TOKEN", "A", "B"]


def test_references_never_fall_back_to_the_process_environment(monkeypatch):
    # An imported or agent-written config must not be able to send a key
    # from the app's own environment to a remote host.
    monkeypatch.setenv("TOKEN", SECRET)
    server = build(headers={"Authorization": "Bearer ${TOKEN}"})
    with pytest.raises(MCPConfigError) as excinfo:
        server.resolve_headers()
    assert "TOKEN" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize("env", [{}, {"TOKEN": ""}, {"TOKEN": None}])
def test_missing_or_empty_references_fail_instead_of_sending_empty(env):
    server = build(headers={"Authorization": "Bearer ${TOKEN}"}, env=env)
    with pytest.raises(MCPConfigError, match="set TOKEN in this server's env"):
        server.resolve_headers()


def test_every_missing_reference_is_named_once():
    server = build(headers={"A": "${ONE}${TWO}", "B": "${ONE}"})
    with pytest.raises(MCPConfigError) as excinfo:
        server.resolve_headers()
    assert "set ONE, TWO in" in str(excinfo.value)


def test_a_literal_empty_header_value_fails_at_connect():
    server = build(headers={"X-Key": ""})
    with pytest.raises(MCPConfigError, match="resolves to an empty value"):
        server.resolve_headers()


def test_a_resolved_value_with_a_line_break_is_rejected_without_echo():
    server = build(
        headers={"Authorization": "${TOKEN}"}, env={"TOKEN": f"{SECRET}\nX: y"}
    )
    with pytest.raises(MCPConfigError) as excinfo:
        server.resolve_headers()
    assert "line break" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)


# ───────────────────────── Timeout ──────────────────────────────────────────


def test_timeout_defaults_and_bounds():
    assert build().timeout is None
    assert build().effective_timeout == DEFAULT_HTTP_TIMEOUT
    assert build(timeout=5).effective_timeout == 5.0
    for bad in (0, -1, 301, float("inf"), float("nan"), True, "10"):
        with pytest.raises(MCPConfigError, match="timeout"):
            build(timeout=bad)


# ───────────────────────── Saving never loses entries ───────────────────────


def test_unknown_fields_survive_a_round_trip():
    raw = {
        "mcp_servers": [http(future_option={"a": 1}, note="keep me")],
        "auto_connect": False,
        "schema_version": 2,
    }
    saved = MCPConfig.from_dict(raw).to_dict()
    assert saved["mcp_servers"][0]["future_option"] == {"a": 1}
    assert saved["mcp_servers"][0]["note"] == "keep me"
    assert saved["schema_version"] == 2
    assert saved["auto_connect"] is False


def test_invalid_entries_are_kept_in_place_and_reported(tmp_path):
    raw = {
        "mcp_servers": [
            {"name": "a", "command": "a"},
            http(name="broken", url="ftp://x/mcp"),
            {"transport": "stdio", "command": "noname"},
            {"name": "b", "command": "b"},
        ]
    }
    config = MCPConfig.from_dict(raw)
    assert [s.name for s in config.mcp_servers] == ["a", "b"]
    assert [(e.name, e.index) for e in config.invalid_servers] == [
        ("broken", 1),
        (None, 2),
    ]
    assert "missing 'name'" in config.invalid_servers[1].error

    path = tmp_path / "mcp_config.json"
    config.save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["mcp_servers"] == [
        MCPServerConfig.from_dict(raw["mcp_servers"][0]).to_dict(),
        raw["mcp_servers"][1],
        raw["mcp_servers"][2],
        MCPServerConfig.from_dict(raw["mcp_servers"][3]).to_dict(),
    ]


def test_a_duplicate_name_is_kept_as_invalid_and_the_first_wins():
    config = MCPConfig.from_dict(
        {"mcp_servers": [http(), http(url="https://other.example.com/mcp")]}
    )
    assert len(config.mcp_servers) == 1
    assert config.mcp_servers[0].url == "https://mcp.example.com/mcp"
    assert "duplicate server name 'remote'" in config.invalid_servers[0].error
    assert len(config.to_dict()["mcp_servers"]) == 2


def test_an_invalid_entry_blocks_adding_the_same_name_and_can_be_replaced():
    config = MCPConfig.from_dict(
        {"mcp_servers": [{"name": "a", "command": "a"}, http(url="ftp://x")]}
    )
    assert config.add_server(build()) is False
    assert config.replace_server(build()) is True
    assert config.invalid_servers == []
    assert [s.name for s in config.mcp_servers] == ["a", "remote"]


def test_remove_also_deletes_invalid_entries_with_that_name():
    config = MCPConfig.from_dict({"mcp_servers": [http(url="ftp://x")]})
    assert config.remove_server("remote") is True
    assert config.to_dict()["mcp_servers"] == []


def test_non_object_entries_and_files_are_handled():
    config = MCPConfig.from_dict({"mcp_servers": ["oops", 3]})
    assert len(config.invalid_servers) == 2
    with pytest.raises(MCPConfigError):
        MCPConfig.from_dict({"mcp_servers": {"not": "a list"}})
    with pytest.raises(MCPConfigError):
        MCPConfig.from_dict(["not", "an", "object"])


# ───────────────────────── Fingerprint ──────────────────────────────────────


def test_connection_fingerprint_tracks_only_what_changes_the_connection():
    base = build(headers={"A": "1"})
    assert (
        base.connection_fingerprint()
        == build(
            headers={"A": "1"}, description="new text", enabled=False
        ).connection_fingerprint()
    )
    for change in (
        {"url": "https://other.example.com/mcp"},
        {"headers": {"A": "2"}},
        {"env": {"K": "v"}},
        {"timeout": 9},
    ):
        assert build(**{"headers": {"A": "1"}, **change}).connection_fingerprint() != (
            base.connection_fingerprint()
        )


# ───────────────────────── redact_url ───────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://mcp.example.com/mcp", "https://mcp.example.com/mcp"),
        ("https://mcp.example.com:8443/mcp", "https://mcp.example.com:8443/mcp"),
        (
            f"https://u:{SECRET}@mcp.example.com/mcp?key={SECRET}#x",
            "https://mcp.example.com/mcp (credentials/query hidden)",
        ),
        ("https://[::1]:9000/mcp", "https://[::1]:9000/mcp"),
        ("", ""),
        (None, ""),
    ],
)
def test_redact_url(url, expected):
    assert redact_url(url) == expected
