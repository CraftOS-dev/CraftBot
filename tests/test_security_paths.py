"""File guard: protected secret stores and confined writes (Settings > Security)."""

from __future__ import annotations

import os

import pytest

from app.security import paths as guard
from app.security.policy import SecurityLevel, SecurityStore, set_store_for_tests


@pytest.fixture
def layout(tmp_path, monkeypatch):
    import app.config as config
    from app import paths

    cfg = tmp_path / "app" / "config"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text('{"api_keys": {"openai": "sk-secret"}}')
    workspace = tmp_path / "agent_file_system" / "workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(config, "APP_CONFIG_PATH", cfg)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "AGENT_FILE_SYSTEM_PATH", tmp_path / "agent_file_system")
    monkeypatch.setattr(config, "AGENT_WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path)
    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    yield store, cfg, workspace
    set_store_for_tests(None)


def test_standard_level_guards_nothing(layout):
    _, cfg, _ = layout
    assert guard.check_file_access(cfg / "settings.json", write=False) is None


def test_enhanced_protects_keys_from_file_tools(layout):
    store, cfg, _ = layout
    store.set_level(SecurityLevel.ENHANCED)
    from app.data.action.read_file import read_file

    out = read_file({"file_path": str(cfg / "settings.json")})
    assert out["status"] == "error" and "protected" in out["message"]
    assert "sk-secret" not in str(out)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlink_does_not_get_around_the_guard(layout, tmp_path):
    store, cfg, workspace = layout
    store.set_level(SecurityLevel.ENHANCED)
    link = workspace / "innocent.txt"
    link.symlink_to(cfg / "settings.json")
    assert guard.check_file_access(link, write=False)


def test_user_added_paths_are_protected(layout, tmp_path):
    store, _, _ = layout
    secret_dir = tmp_path / "my-keys"
    secret_dir.mkdir()
    store.set_level(SecurityLevel.ENHANCED)
    store.update({"extra_protected_paths": [str(secret_dir)]})
    assert guard.check_file_access(secret_dir / "id_rsa", write=False)


def test_strict_confines_writes_to_the_workspace(layout, tmp_path):
    store, _, workspace = layout
    store.set_level(SecurityLevel.STRICT)
    assert guard.check_file_access(workspace / "notes.md", write=True) is None
    assert guard.check_file_access(tmp_path / "elsewhere.txt", write=True)
    assert guard.check_file_access(tmp_path / "elsewhere.txt", write=False) is None
    allowed = tmp_path / "projects"
    store.update({"workspace_paths": [str(allowed)]})
    assert guard.check_file_access(allowed / "a.txt", write=True) is None
