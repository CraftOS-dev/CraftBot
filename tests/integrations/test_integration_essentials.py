"""Just-in-time essentials matching (word boundaries, bare tokens,
specific-key suppression, provider GUIDANCE.md sourcing)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def essentials():
    path = REPO / "app" / "data" / "action" / "integrations" / "_integration_essentials.py"
    spec = importlib.util.spec_from_file_location("test_essentials_mod", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ids(essentials, message):
    return re.findall(
        r"^### (\S+)", essentials.get_essentials_for_message(message), re.M
    )


def test_bare_calendar_matches_calendar_integrations(essentials):
    # The original bug this file exists to fix: only "google calendar"
    # matched; "what's on my school calendar" injected nothing.
    ids = _ids(essentials, "what's on my school calendar")
    assert "google_calendar" in ids
    assert "lark_calendar" in ids  # ambiguous bare word → both candidates


def test_bare_docs_drive_youtube_match(essentials):
    assert _ids(essentials, "open that docs file") == ["google_docs"]
    assert set(_ids(essentials, "upload it to drive")) == {
        "google_drive",
        "lark_drive",
    }
    assert _ids(essentials, "check youtube comments") == ["google_youtube"]


def test_word_boundaries_prevent_false_positives(essentials):
    assert _ids(essentials, "the doctor said to check docker drivers") == []
    assert _ids(essentials, "the online documentation") == []


def test_specific_key_suppresses_generic_family_token(essentials):
    assert _ids(essentials, "open my google docs") == ["google_docs"]
    assert _ids(essentials, "lark calendar event") == ["lark_calendar"]


def test_v2_guidance_is_sourced_with_multi_account_rules(essentials):
    block = essentials.get_essentials_for_message("send a gmail to alice")
    assert "### gmail" in block
    # The provider GUIDANCE.md multi-account rules reach the router.
    assert "account" in block
    assert "primary" in block.lower()


def test_no_mention_no_block(essentials):
    assert essentials.get_essentials_for_message("what's the weather?") == ""
    assert essentials.get_essentials_for_message("") == ""


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
        block = essentials.get_essentials_for_message("check my gmail")
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
        block = essentials.get_essentials_for_message("check my gmail")
        assert "Connected accounts:" not in block
    finally:
        bootstrap.reset_system()


def test_email_synonym_matches_mail_integrations(essentials):
    ids = _ids(essentials, "any updates for my job email?")
    assert "gmail" in ids or "outlook" in ids
