"""CraftBot adapter: generated @action wrappers + the one-time legacy
upgrade migration.

Loads app/data/action/integrations/craftbot_adapter.py exactly the way the
action loader does (file-location import — app/data/action is not a
package) and verifies the central account injection end-to-end.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def adapter_registry():
    """Import the adapter once; return the agent_core action registry."""
    from agent_core.core.action_framework.registry import registry_instance

    path = REPO / "app" / "data" / "action" / "integrations" / "craftbot_adapter.py"
    spec = importlib.util.spec_from_file_location("test_craftbot_adapter_mod", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_craftbot_adapter_mod"] = module
    spec.loader.exec_module(module)
    return registry_instance


def _all_ops():
    from craftos_integrations.providers import default_providers

    return [(p, op) for p in default_providers() for op in p.operations()]


def test_every_operation_registered_with_injected_account(adapter_registry):
    ops = _all_ops()
    assert len(ops) >= 397
    missing, no_account = [], []
    for provider, op in ops:
        registered = adapter_registry.get_action_implementation(op.name)
        if registered is None:
            missing.append(op.name)
            continue
        if "account" not in registered.metadata.input_schema:
            no_account.append(op.name)
        assert registered.metadata.irreversible == op.destructive, op.name
        assert registered.metadata.parallelizable == op.parallelizable, op.name
        assert registered.metadata.action_sets == list(op.tags), op.name
    assert not missing, f"operations not registered as actions: {missing[:10]}"
    assert not no_account, f"actions without injected account: {no_account[:10]}"


@pytest.fixture
def live_system(tmp_path, monkeypatch):
    """Point the singleton system at a tmp credentials dir with 2 accounts."""
    from craftos_integrations.config import ConfigStore

    import app.integrations as bootstrap

    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    bootstrap.reset_system()
    system = bootstrap.get_system()
    cred = lambda email: {"email": email, "access_token": f"tok-{email}"}
    system.store_credential("gmail", "a@x.com", cred("a@x.com"))
    system.store_credential("gmail", "b@y.com", cred("b@y.com"))
    system.set_alias("gmail", "b@y.com", "school")
    yield system
    bootstrap.reset_system()


def _handler(adapter_registry, name):
    return adapter_registry.get_action_implementation(name).handler


def test_generated_action_routes_account_to_client(
    adapter_registry, live_system, monkeypatch
):
    from craftos_integrations.providers.gmail.provider import BoundGmailClient

    seen = []
    monkeypatch.setattr(
        BoundGmailClient,
        "list_emails",
        lambda self, n=5, unread_only=True: (
            seen.append((self._cred.email, n)) or {"ok": True, "result": ["m"]}
        ),
    )
    handler = _handler(adapter_registry, "list_gmail")
    result = asyncio.run(handler({"count": 2, "account": "school"}))
    assert result == {"status": "success", "result": ["m"]}
    assert seen == [("b@y.com", 2)]


def test_generated_action_bad_account_is_self_correcting(
    adapter_registry, live_system
):
    handler = _handler(adapter_registry, "list_gmail")
    result = asyncio.run(handler({"account": "ghost"}))
    assert result["status"] == "error"
    assert "No gmail account matches 'ghost'" in result["message"]
    assert "a@x.com" in result["message"]  # enumerates choices


def test_generated_action_not_connected(adapter_registry, live_system):
    handler = _handler(adapter_registry, "list_slack_channels")
    result = asyncio.run(handler({}))
    assert result["status"] == "error"
    assert "not connected" in result["message"]


# ── one-time legacy upgrade migration (through the real bootstrap) ──────


def test_migration_imports_legacy_file_then_doc_is_source_of_truth(
    tmp_path, monkeypatch
):
    from craftos_integrations.config import ConfigStore

    import app.integrations as bootstrap

    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    bootstrap.reset_system()
    system = bootstrap.get_system()
    # Pre-multi-account install (≤ V1.4.2): only a legacy file exists → first contact
    # migrates it into an AccountSet document...
    legacy = tmp_path / ".credentials"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "notion.json").write_text(json.dumps({"token": "t"}), encoding="utf-8")
    assert len(system.list_accounts("notion")) == 1
    # ...after which the document is the sole source of truth: deleting the
    # legacy file no longer reads as a logout.
    (legacy / "notion.json").unlink()
    assert len(system.list_accounts("notion")) == 1
    bootstrap.reset_system()


def test_pure_v2_single_account_is_stable(live_system, tmp_path):
    # Slack was connected purely via the integration system (no legacy file ever existed).
    live_system.store_credential("slack", "t123", {"team_id": "T123"})
    assert len(live_system.list_accounts("slack")) == 1
    assert len(live_system.list_accounts("slack")) == 1  # and stays stable
