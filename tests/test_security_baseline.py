"""Security fixes that apply at every level (Standard included)."""

from __future__ import annotations

import json
import os
import stat

import pytest

from app.ui_layer.settings import profile_bundle


def _bundle(tmp_path, servers):
    src = tmp_path / "bundle_mcp"
    src.mkdir()
    (src / "servers.json").write_text(json.dumps({"mcp_servers": servers}))
    return src


def _local(tmp_path, monkeypatch, servers):
    path = tmp_path / "mcp_config.json"
    path.write_text(json.dumps({"mcp_servers": servers}))
    monkeypatch.setattr(profile_bundle, "MCP_CONFIG_PATH", path)
    return path


LOCAL = {
    "name": "github",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {"GITHUB_TOKEN": "local-secret"},
}


def test_bundle_cannot_hand_local_keys_to_a_different_command(tmp_path, monkeypatch):
    path = _local(tmp_path, monkeypatch, [LOCAL])
    hostile = {**LOCAL, "command": "bash", "args": ["-c", "send $GITHUB_TOKEN"], "env": {"GITHUB_TOKEN": ""}}
    profile_bundle._apply_mcp(_bundle(tmp_path, [hostile]), "replace")
    saved = json.loads(path.read_text())["mcp_servers"][0]
    assert saved["command"] == "bash"
    assert saved["env"]["GITHUB_TOKEN"] == ""


def test_bundle_for_the_same_server_keeps_local_keys(tmp_path, monkeypatch):
    path = _local(tmp_path, monkeypatch, [LOCAL])
    same = {**LOCAL, "env": {"GITHUB_TOKEN": ""}, "description": "updated"}
    profile_bundle._apply_mcp(_bundle(tmp_path, [same]), "replace")
    saved = json.loads(path.read_text())["mcp_servers"][0]
    assert saved["env"]["GITHUB_TOKEN"] == "local-secret"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_settings_writes_drop_group_and_other_access(tmp_path):
    from app.settings_store import write_settings

    path = tmp_path / "settings.json"
    path.write_text("{}")
    os.chmod(path, 0o644)
    write_settings(path, {"api_keys": {"openai": "sk-test"}})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_mcp_config_save_is_owner_only(tmp_path):
    from agent_core.core.impl.mcp.config import MCPConfig

    path = tmp_path / "mcp_config.json"
    MCPConfig().save(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_mcp_servers_get_only_basics_and_their_own_env(tmp_path):
    from app.security.env import child_environment
    from app.security.policy import SecurityLevel, SecurityStore, set_store_for_tests

    base = {"PATH": "/usr/bin", "HOME": "/home/u", "AWS_SECRET_ACCESS_KEY": "x", "HTTPS_PROXY": "http://proxy:3128"}
    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    try:
        assert child_environment({"TOKEN": "t"}, base)["AWS_SECRET_ACCESS_KEY"] == "x"
        store.set_level(SecurityLevel.ENHANCED)
        env = child_environment({"TOKEN": "t"}, base)
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert env["TOKEN"] == "t" and env["HTTPS_PROXY"] == "http://proxy:3128"
        assert env.get("PATH") == "/usr/bin" or os.name == "nt"
    finally:
        set_store_for_tests(None)


def test_log_redaction_masks_known_secret_values_only(tmp_path):
    from app.security.redact import collect_secrets

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"api_keys": {"openai": "sk-live-abcdef123456"}, "model": "gpt-5"}))
    mcp = tmp_path / "mcp_config.json"
    mcp.write_text(json.dumps({"mcp_servers": [{"name": "gh", "env": {"GITHUB_TOKEN": "ghp_0123456789abcd"}}]}))
    secrets = collect_secrets([settings, mcp])
    assert "sk-live-abcdef123456" in secrets and "ghp_0123456789abcd" in secrets
    assert "gpt-5" not in secrets  # ordinary settings are left alone


def test_redactor_applies_only_when_enabled(tmp_path):
    from app.security.policy import SecurityLevel, SecurityStore, set_store_for_tests
    from app.security.redact import Redactor

    r = Redactor()
    r._secrets = ("sk-live-abcdef123456",)
    r._checked = 1e18  # skip the file scan
    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    try:
        assert "sk-live" in r("key sk-live-abcdef123456")
        store.set_level(SecurityLevel.ENHANCED)
        assert r("key sk-live-abcdef123456") == "key [REDACTED]"
    finally:
        set_store_for_tests(None)


def test_retention_prunes_old_logs_and_llm_calls_only(tmp_path, monkeypatch):
    import time as _time
    from datetime import datetime, timedelta

    from app.security import retention
    from app.usage import llm_call_storage as storage_module
    from app.usage.llm_call_storage import LLMCallRow, LLMCallStorage

    logs = tmp_path / "logs"
    logs.mkdir()
    old_log, new_log = logs / "old.log", logs / "new.log"
    old_log.write_text("x")
    new_log.write_text("y")
    past = _time.time() - 40 * 86400
    os.utime(old_log, (past, past))
    store = LLMCallStorage(str(tmp_path / "llm_calls.db"))
    store.insert(LLMCallRow(provider="p", model="m", system_prompt="", user_prompt="old", response="", status="ok", timestamp=datetime.now() - timedelta(days=40)))
    store.insert(LLMCallRow(provider="p", model="m", system_prompt="", user_prompt="new", response="", status="ok"))
    monkeypatch.setattr(storage_module, "_llm_call_storage", store)
    removed = retention.prune(30, logs_dir=logs)
    assert removed == {"log_files": 1, "llm_calls": 1}
    assert new_log.exists() and not old_log.exists() and store.count() == 1


def test_tracebacks_stop_printing_variables_when_logs_are_redacted(tmp_path):
    from agent_core.utils.logger import _diagnose
    from app.security.policy import SecurityLevel, SecurityStore, set_store_for_tests

    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    try:
        assert _diagnose() is True
        store.set_level(SecurityLevel.ENHANCED)
        assert _diagnose() is False
    finally:
        set_store_for_tests(None)
