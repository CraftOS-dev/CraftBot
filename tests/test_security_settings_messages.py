"""Settings > Security over the UI websocket (browser_adapter routing)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.security import audit
from app.security.policy import SecurityStore, set_store_for_tests
from app.ui_layer.adapters.browser_adapter import BrowserAdapter


@pytest.fixture
def adapter(tmp_path):
    set_store_for_tests(SecurityStore(tmp_path / "security.json"))
    audit.set_log_for_tests(audit.AuditLog(tmp_path / "audit.jsonl"))
    stub = SimpleNamespace(_broadcast=AsyncMock())
    yield stub
    set_store_for_tests(None)
    audit.set_log_for_tests(None)


def _send(stub, msg_type, data=None):
    asyncio.run(BrowserAdapter._handle_security_message(stub, msg_type, data or {}))
    return stub._broadcast.await_args.args[0]


def test_level_change_is_broadcast_to_every_window(adapter):
    reply = _send(adapter, "security_set_level", {"level": "enhanced"})
    assert reply["type"] == "security_state"
    assert reply["data"]["policy"]["protect_secret_files"] is True


def test_refused_change_still_carries_current_settings(adapter):
    reply = _send(adapter, "security_update", {"changes": {"auto_mode": "off"}})
    assert reply["data"]["success"] is False and reply["data"]["error"]
    assert reply["data"]["policy"]["auto_mode"] is True


def test_auto_mode_off_and_pending_approvals_list(adapter):
    reply = _send(adapter, "security_update", {"changes": {"auto_mode": False}})
    assert reply["data"]["policy"]["auto_mode"] is False
    reply = _send(adapter, "security_approvals_list")
    assert reply == {"type": "security_approvals_pending", "data": {"success": True, "requests": []}}


def test_security_check_runs(adapter):
    reply = _send(adapter, "security_check_run")
    ids = {c["id"] for c in reply["data"]["checks"]}
    assert {"secret_files_private", "ui_local_only", "audit_log_intact", "security_level", "auto_mode"} <= ids


def test_every_check_runs_without_error(adapter):
    reply = _send(adapter, "security_check_run")
    checks = reply["data"]["checks"]
    assert len(checks) == 12
    assert not [c for c in checks if c["title"] == "Check could not run"], checks
