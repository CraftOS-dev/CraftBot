"""service.py status readers consult the v2 AccountSet store (PR #419).

A fresh multi-account connect writes only ``<id>.accounts.json`` — never
the legacy ``<id>.json`` the legacy readers check — so is_connected /
list_connected / get_integration_info must not report a connected
platform as disconnected.
"""

from __future__ import annotations

import pytest

from craftos_integrations import service
from craftos_integrations.config import ConfigStore
from craftos_integrations.core.accounts import AccountManager
from craftos_integrations.core.storage import FileCredentialStore


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    return tmp_path


def test_v2_accounts_reads_accountset_document(project_root):
    assert service._stored_accounts("discord") == []

    mgr = AccountManager(FileCredentialStore())
    mgr.upsert_account("discord", "1468495569671557153", {"bot_token": "x"})
    mgr.set_alias("discord", "1468495569671557153", "main-bot")

    assert service._stored_accounts("discord") == [
        {"display": "main-bot", "id": "1468495569671557153"}
    ]


def test_is_connected_true_from_v2_store_without_legacy_file(project_root):
    mgr = AccountManager(FileCredentialStore())
    mgr.upsert_account("discord", "1468495569671557153", {"bot_token": "x"})

    # No legacy discord.json exists under this root — before the bridge
    # this returned False while the listener happily received messages.
    assert not (project_root / ".credentials" / "discord.json").exists()
    assert service.is_connected("discord") is True


def test_get_integration_info_reports_v2_accounts(project_root):
    mgr = AccountManager(FileCredentialStore())
    mgr.upsert_account("discord", "1468495569671557153", {"bot_token": "x"})
    mgr.set_alias("discord", "1468495569671557153", "main-bot")

    import asyncio

    info = asyncio.run(service.get_integration_info("discord"))
    assert info is not None
    assert info["connected"] is True
    assert info["accounts"] == [{"display": "main-bot", "id": "1468495569671557153"}]
