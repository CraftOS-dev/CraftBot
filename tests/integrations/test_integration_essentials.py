"""Integration guidance delivered with an integration's action schemas
(provider GUIDANCE.md sourcing, connected-accounts note, provider ids)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def essentials():
    path = (
        REPO / "app" / "data" / "action" / "integrations" / "_integration_essentials.py"
    )
    spec = importlib.util.spec_from_file_location("test_essentials_mod", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ids(block):
    return re.findall(r"^### (\S+)", block, re.M)


def test_provider_ids_are_the_provider_directories(essentials):
    ids = essentials.integration_ids()
    assert {"gmail", "google_calendar", "discord"} <= ids
    assert not any(i.startswith(("_", ".")) for i in ids)
    assert "__pycache__" not in ids


@pytest.mark.parametrize(
    "set_names,expected",
    [
        (["github", "github_workflows", "github_releases"], {"github"}),
        (["stripe_disputes", "jira_attachments"], {"stripe", "jira"}),
        (["google_calendar_admin"], {"google_calendar"}),
        (["githubish", "custom_github", "document_processing"], set()),
        ([], set()),
    ],
)
def test_provider_ids_for_action_sets(essentials, set_names, expected):
    assert essentials.integration_ids_for_action_sets(iter(set_names)) == expected


def test_subgroups_use_the_longest_provider_id(essentials, monkeypatch):
    monkeypatch.setattr(
        essentials, "integration_ids", lambda: {"google", "google_calendar"}
    )
    assert essentials.integration_ids_for_action_sets(
        ["google_calendar", "google_calendar_admin", "google_other"]
    ) == {"google_calendar", "google"}


def test_v2_guidance_is_sourced_with_multi_account_rules(essentials):
    block = essentials.get_essentials_for_integrations(["gmail"])
    assert _ids(block) == ["gmail"]
    # The provider GUIDANCE.md multi-account rules reach the model.
    assert "account" in block
    assert "primary" in block.lower()


def test_one_heading_per_integration_in_stable_order(essentials):
    block = essentials.get_essentials_for_integrations(
        ["google_calendar", "gmail", "gmail"]
    )
    assert _ids(block) == ["gmail", "google_calendar"]


def test_no_guidance_no_block(essentials):
    assert essentials.get_essentials_for_integrations([]) == ""
    assert essentials.get_essentials_for_integrations(["not_an_integration"]) == ""


def test_connected_accounts_injected_into_essentials(essentials, tmp_path, monkeypatch):
    from craftos_integrations.config import ConfigStore

    import app.integrations as bootstrap

    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    bootstrap.reset_system()
    system = bootstrap.get_system()
    system.store_credential(
        "gmail", "a@x.com", {"email": "a@x.com", "access_token": "t"}
    )
    system.store_credential(
        "gmail", "b@y.com", {"email": "b@y.com", "access_token": "t"}
    )
    system.set_alias("gmail", "b@y.com", "job search")
    try:
        block = essentials.get_essentials_for_integrations(["gmail"])
        assert "Connected accounts:" in block
        assert "a@x.com" in block and "[primary]" in block
        assert 'b@y.com (alias: "job search")' in block
    finally:
        bootstrap.reset_system()


def test_essentials_without_accounts_have_no_note(essentials, tmp_path, monkeypatch):
    from craftos_integrations.config import ConfigStore

    import app.integrations as bootstrap

    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    bootstrap.reset_system()
    try:
        block = essentials.get_essentials_for_integrations(["gmail"])
        assert "Connected accounts:" not in block
    finally:
        bootstrap.reset_system()
