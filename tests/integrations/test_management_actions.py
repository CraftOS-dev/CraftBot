"""Agent-facing integration-management actions routed through the integration system.

Covers the legacy-decommission cutover for the 10 multi-account providers:
- check_integration_status reads connection state + accounts from
  IntegrationSystem.list_accounts (plan-§6 line format + structured array),
- connect_integration's manual-token path validates like the legacy
  handler login but stores via IntegrationSystem.store_credential,
- disconnect_integration removes accounts (targeted and disconnect-all).

Loads app/data/action/integrations/integration_management.py the way the
action loader does (file-location import) and drives the registered
handlers directly against a tmp-rooted credential store.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def action_registry():
    """Import the management-action module once; return the action registry."""
    from agent_core.core.action_framework.registry import registry_instance

    path = (
        REPO / "app" / "data" / "action" / "integrations" / "integration_management.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_integration_management_mod", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_integration_management_mod"] = module
    spec.loader.exec_module(module)
    return registry_instance


def _run(action_registry, name, input_data):
    handler = action_registry.get_action_implementation(name).handler
    result = handler(input_data)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return result


@pytest.fixture
def system(tmp_path, monkeypatch):
    """Singleton system pointed at a tmp credentials dir."""
    from craftos_integrations.config import ConfigStore

    import app.integrations as bootstrap

    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    bootstrap.reset_system()
    yield bootstrap.get_system()
    bootstrap.reset_system()


@pytest.fixture
def gmail_two_accounts(system):
    def cred(email):
        return {"email": email, "access_token": f"tok-{email}"}

    system.store_credential("gmail", "a@x.com", cred("a@x.com"))
    system.store_credential("gmail", "b@y.com", cred("b@y.com"))
    system.set_alias("gmail", "b@y.com", "school")
    return system


# ── check_integration_status ─────────────────────────────────────────────


def test_status_shows_v2_accounts(action_registry, gmail_two_accounts):
    result = _run(
        action_registry, "check_integration_status", {"integration_id": "gmail"}
    )
    assert result["status"] == "success"
    assert result["connected"] is True
    assert result["accounts"] == [
        {"identity": "a@x.com", "alias": None, "isPrimary": True, "listen": True},
        {"identity": "b@y.com", "alias": "school", "isPrimary": False, "listen": True},
    ]
    # Shared plan-§6 status-line format.
    assert "- a@x.com (a@x.com) [primary]" in result["message"]
    assert "- school (b@y.com)" in result["message"]
    assert "2 account(s)" in result["message"]


def test_status_v2_not_connected(action_registry, system):
    result = _run(
        action_registry, "check_integration_status", {"integration_id": "slack"}
    )
    assert result["status"] == "success"
    assert result["connected"] is False
    assert result["accounts"] == []
    assert "not connected" in result["message"]


def test_status_normalizes_aliases_to_v2_ids(action_registry, gmail_two_accounts):
    # 'mail' → gmail via the alias table; still served by the integration system.
    result = _run(
        action_registry, "check_integration_status", {"integration_id": "mail"}
    )
    assert result["connected"] is True
    assert len(result["accounts"]) == 2


# ── connect_integration (manual token → account store) ────────────────────────


def test_slack_token_connect_stores_through_v2(
    action_registry, system, monkeypatch, tmp_path
):
    import craftos_integrations.providers.slack.client as slack_mod

    calls = []

    def fake_slack_call(method, path, headers, **kw):
        calls.append((method, path, headers))
        return {"ok": True, "team_id": "T999", "team": "Acme"}

    monkeypatch.setattr(slack_mod, "_slack_call", fake_slack_call)

    result = _run(
        action_registry,
        "connect_integration",
        {
            "integration_id": "slack",
            "credentials": {"bot_token": "xoxb-test-token"},
            "auth_method": "token",
        },
    )
    assert result == {
        "status": "success",
        "message": "Slack connected: Acme (T999)",
        "auth_type": "token",
    }
    # Verified exactly like the legacy login: auth.test with the bot token.
    assert calls == [("POST", "auth.test", {"Authorization": "Bearer xoxb-test-token"})]
    # Stored through the integration system under the team-id identity...
    accounts = system.list_accounts("slack")
    assert [a.identity for a in accounts] == ["t999"]
    stored = system.accounts.credential_for("slack", "t999")
    assert stored["bot_token"] == "xoxb-test-token"
    assert stored["workspace_id"] == "T999"
    assert stored["team_name"] == "Acme"


def test_slack_token_connect_rejects_bad_token(action_registry, system):
    result = _run(
        action_registry,
        "connect_integration",
        {
            "integration_id": "slack",
            "credentials": {"bot_token": "not-a-slack-token"},
            "auth_method": "token",
        },
    )
    assert result["status"] == "error"
    assert "xoxb-" in result["message"]
    assert system.list_accounts("slack") == []


def test_slack_token_connect_auth_failure_stores_nothing(
    action_registry, system, monkeypatch
):
    import craftos_integrations.providers.slack.client as slack_mod

    monkeypatch.setattr(
        slack_mod, "_slack_call", lambda *a, **k: {"error": "invalid_auth"}
    )
    result = _run(
        action_registry,
        "connect_integration",
        {
            "integration_id": "slack",
            "credentials": {"bot_token": "xoxb-revoked"},
            "auth_method": "token",
        },
    )
    assert result["status"] == "error"
    assert "invalid_auth" in result["message"]
    assert system.list_accounts("slack") == []


def test_notion_token_connect_captures_bot_identity(
    action_registry, system, monkeypatch
):
    """A pasted integration token is verified via /users/me and the bot's
    workspace/bot ids are captured into the credential, so the account gets
    a real identity — a second workspace's token becomes a second account
    instead of silently replacing the first (the old LEGACY-sentinel
    behavior this test used to pin)."""
    import craftos_integrations.providers.notion.client as notion_mod

    monkeypatch.setattr(
        notion_mod,
        "_notion_call",
        lambda method, path, headers, **kw: {
            "id": "BOT-123",
            "bot": {"workspace_name": "Acme WS", "workspace_id": "WS-9"},
        },
    )
    result = _run(
        action_registry,
        "connect_integration",
        {
            "integration_id": "notion",
            "credentials": {"token": "secret_abc"},
            "auth_method": "token",
        },
    )
    assert result == {
        "status": "success",
        "message": "Notion connected: Acme WS",
        "auth_type": "token",
    }
    accounts = system.list_accounts("notion")
    assert [a.identity for a in accounts] == ["ws-9"]
    assert system.accounts.credential_for("notion", "ws-9") == {
        "token": "secret_abc",
        "bot_id": "BOT-123",
        "workspace_id": "WS-9",
    }


def test_identity_less_token_connect_is_rejected(action_registry, system, monkeypatch):
    """When verification can't produce an identity, the connect is refused —
    storing under the UNIDENTIFIED sentinel would let the next identity-less
    connect overwrite this account's credential."""
    import craftos_integrations.providers.notion.client as notion_mod

    monkeypatch.setattr(
        notion_mod,
        "_notion_call",
        lambda method, path, headers, **kw: {"bot": {"workspace_name": "Acme WS"}},
    )
    result = _run(
        action_registry,
        "connect_integration",
        {
            "integration_id": "notion",
            "credentials": {"token": "secret_abc"},
            "auth_method": "token",
        },
    )
    assert result["status"] == "error"
    assert "overwritten" in result["message"]
    assert system.list_accounts("notion") == []


def test_hubspot_token_connect_uses_hub_id_identity(
    action_registry, system, monkeypatch
):
    import app.data.action.integrations._helpers as helpers_mod  # noqa: F401

    def fake_request(method, url, headers=None, expected=None, **kw):
        assert url.endswith("/account-info/v3/details")
        assert headers == {"Authorization": "Bearer pat-na1-xyz"}
        return {"result": {"portalId": 424242, "uiDomain": "app.hubspot.com"}}

    # The verifier resolves `request` from craftos_integrations.helpers at
    # call time.
    import craftos_integrations.helpers as ci_helpers

    monkeypatch.setattr(ci_helpers, "request", fake_request)

    result = _run(
        action_registry,
        "connect_integration",
        {
            "integration_id": "hubspot",
            "credentials": {"access_token": "pat-na1-xyz"},
            "auth_method": "token",
        },
    )
    assert result["status"] == "success"
    assert "app.hubspot.com" in result["message"]
    accounts = system.list_accounts("hubspot")
    assert [a.identity for a in accounts] == ["424242"]
    stored = system.accounts.credential_for("hubspot", "424242")
    assert stored["access_token"] == "pat-na1-xyz"
    assert stored["auth_kind"] == "token"


# ── disconnect_integration ───────────────────────────────────────────────


def test_disconnect_all_removes_every_account(
    action_registry, gmail_two_accounts, tmp_path
):
    """Disconnect with no account_id removes them all, and they stay removed.

    A pre-multi-account ``gmail.json`` sitting alongside used to be able to
    resurrect the account through the upgrade migration; that format and its
    migration were removed on 2026-08-26, so the file is now inert.
    """
    legacy = tmp_path / ".credentials" / "gmail.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"email": "a@x.com", "access_token": "stale"}')

    result = _run(
        action_registry, "disconnect_integration", {"integration_id": "gmail"}
    )
    assert result["status"] == "success"
    assert "2 account(s)" in result["message"]
    assert gmail_two_accounts.list_accounts("gmail") == []
    assert gmail_two_accounts.list_accounts("gmail") == []  # no resurrection


def test_disconnect_targeted_account_by_alias(action_registry, gmail_two_accounts):
    result = _run(
        action_registry,
        "disconnect_integration",
        {"integration_id": "gmail", "account_id": "school"},
    )
    assert result["status"] == "success"
    assert "b@y.com" in result["message"]
    remaining = gmail_two_accounts.list_accounts("gmail")
    assert [a.identity for a in remaining] == ["a@x.com"]
    assert remaining[0].is_primary


def test_disconnect_v2_id_with_nothing_connected(action_registry, system):
    result = _run(
        action_registry, "disconnect_integration", {"integration_id": "slack"}
    )
    assert result["status"] == "error"
    assert "not connected" in result["message"].lower()
