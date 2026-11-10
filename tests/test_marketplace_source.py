"""CraftBot's marketplace preference is forwarded to the upstream CLI."""
from app.agent_app import marketplace_source as source


def test_settings_branch_is_used_when_environment_override_is_absent(monkeypatch):
    monkeypatch.delenv("CRAFTBOT_MARKETPLACE_REF", raising=False)
    monkeypatch.setattr("app.config.get_marketplace_ref", lambda: "staging")
    assert source.ref() == "staging"


def test_configured_branch_is_preserved_across_fallback(monkeypatch):
    monkeypatch.setenv("CRAFTBOT_MARKETPLACE_REF", " preview ")
    monkeypatch.setattr("app.config.get_marketplace_ref", lambda: "staging")
    assert source.ref() == "preview"
