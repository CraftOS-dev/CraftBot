import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_app import trigger_consent as consent
from app.ui_layer.adapters.browser_adapter import BrowserAdapter


@pytest.fixture
def project(tmp_path):
    project = SimpleNamespace(id="consent-test", path=str(tmp_path))
    write_triggers(
        project,
        {
            "summarize": {
                "description": "Summarize notes",
                "instruction": "Summarize the notes.",
            }
        },
    )
    return project


def write_triggers(project, definitions):
    from pathlib import Path

    (Path(project.path) / "triggers.json").write_text(
        json.dumps({"triggers": definitions}), encoding="utf-8"
    )


def test_decline_is_remembered_and_can_be_reconsidered(project):
    review = consent.status(project)
    assert review["required"] and review["needsReview"]
    declined = consent.decide(project, review["revision"], False)
    assert declined["required"] and not declined["needsReview"]
    assert consent.approved_trigger(project, "summarize") is None
    allowed = consent.decide(project, declined["revision"], True)
    assert not allowed["required"] and not allowed["needsReview"]
    # A fresh object/process reads the durable decision; no restart prompt.
    assert consent.status(SimpleNamespace(id=project.id, path=project.path)) == allowed
    consent.decide(project, allowed["revision"], False)
    assert consent.approved_trigger(project, "summarize") is None
    assert not consent.status(project)["needsReview"]


def test_new_and_changed_requests_require_review_but_unchanged_stays_allowed(project):
    consent.decide(project, consent.status(project)["revision"], True)
    definitions = {
        "summarize": {
            "description": "Summarize notes",
            "instruction": "Summarize the notes.",
        },
        "send": {"description": "Send a summary", "instruction": "Email the summary."},
    }
    write_triggers(project, definitions)
    assert consent.status(project)["needsReview"]
    assert consent.approved_trigger(project, "summarize")
    assert consent.approved_trigger(project, "send") is None
    consent.decide(project, consent.status(project)["revision"], True)
    definitions["summarize"]["instruction"] = "Publish the notes publicly."
    write_triggers(project, definitions)
    assert consent.approved_trigger(project, "summarize") is None
    assert consent.approved_trigger(project, "send")
    assert (
        next(
            t for t in consent.status(project)["triggers"] if t["name"] == "summarize"
        )["change"]
        == "changed"
    )


def test_stale_dialog_cannot_approve_new_instructions(project):
    old_review = consent.status(project)
    write_triggers(project, {"summarize": {"instruction": "Email all the notes."}})
    with pytest.raises(consent.TriggerConsentError, match="changed"):
        consent.decide(project, old_review["revision"], True)
    assert consent.approved_trigger(project, "summarize") is None
    assert consent.status(project)["needsReview"]


def test_review_discloses_parameter_definitions_and_changed_defaults(project):
    definition = {
        "description": "Email a summary",
        "instruction": "Email the summary to recipient.",
        "params": {
            "recipient": {
                "type": "string",
                "description": "Who receives the summary",
                "required": True,
                "default": "original@example.test",
            },
            "enabled": {"type": "boolean", "default": False},
            "count": {"type": "number", "default": 0},
            "suffix": {"type": "string", "default": ""},
            "mode": {"type": "string", "enum": ["draft", "final"]},
        },
    }
    write_triggers(project, {"send": definition})
    initial = consent.status(project)
    assert initial["triggers"][0]["params"] == definition["params"]
    consent.decide(project, initial["revision"], True)

    definition["params"]["recipient"]["default"] = "changed@example.test"
    write_triggers(project, {"send": definition})
    changed = consent.status(project)
    assert changed["needsReview"]
    assert changed["triggers"][0]["change"] == "changed"
    assert (
        changed["triggers"][0]["instruction"] == initial["triggers"][0]["instruction"]
    )
    assert changed["triggers"][0]["params"] == definition["params"]
    assert (
        initial["triggers"][0]["params"]["recipient"]["default"]
        == "original@example.test"
    )
    assert consent.approved_trigger(project, "send") is None
    with pytest.raises(consent.TriggerConsentError, match="changed"):
        consent.decide(project, initial["revision"], True)
    allowed = consent.decide(project, changed["revision"], True)
    assert allowed["triggers"][0]["params"] == definition["params"]
    assert consent.approved_trigger(project, "send")["params"] == definition["params"]


def test_corrupt_definitions_and_consent_fail_closed(project):
    from pathlib import Path

    consent.decide(project, consent.status(project)["revision"], True)
    (Path(project.path) / ".factory/trigger-consent.json").write_text("bad json")
    assert consent.approved_trigger(project, "summarize") is None
    (Path(project.path) / "triggers.json").write_text("bad json")
    assert consent.status(project)["error"]
    with pytest.raises(consent.TriggerConsentError):
        consent.approved_trigger(project, "summarize")


def test_apps_without_requests_need_no_dialog(project):
    write_triggers(project, {})
    assert not consent.status(project)["needsReview"]
    assert not consent.status(project)["required"]


def test_authenticated_ui_handler_rejects_stale_review_and_broadcasts_decision(project):
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._agent_app_manager = SimpleNamespace(get_project=lambda pid: project)
    adapter._broadcast = AsyncMock()
    adapter._handle_agent_app_list = AsyncMock()
    revision = consent.status(project)["revision"]
    asyncio.run(
        adapter._handle_agent_app_trigger_consent(
            {
                "projectId": project.id,
                "revision": "stale",
                "allow": True,
                "requestId": "stale-request",
            }
        )
    )
    assert adapter._broadcast.call_args.args[0]["data"]["success"] is False
    assert adapter._broadcast.call_args.args[0]["data"]["requestId"] == "stale-request"
    assert consent.approved_trigger(project, "summarize") is None
    asyncio.run(
        adapter._handle_agent_app_trigger_consent(
            {
                "projectId": project.id,
                "revision": revision,
                "allow": True,
                "requestId": "allow-request",
            }
        )
    )
    result = adapter._broadcast.call_args.args[0]["data"]
    assert result["success"] and not result["consent"]["required"]
    assert result["requestId"] == "allow-request"
    adapter._handle_agent_app_list.assert_awaited_once()


def test_copied_publisher_approval_does_not_authorize_another_app(project):
    consent.decide(project, consent.status(project)["revision"], True)
    imported = SimpleNamespace(id="different-import", path=project.path)
    assert consent.approved_trigger(imported, "summarize") is None
    assert consent.status(imported)["needsReview"]


def test_failed_ui_save_preserves_correlation_and_does_not_grant(project, monkeypatch):
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._agent_app_manager = SimpleNamespace(get_project=lambda pid: project)
    adapter._broadcast = AsyncMock()
    adapter._handle_agent_app_list = AsyncMock()

    def fail_save(*args):
        raise OSError("Consent storage is read-only")

    monkeypatch.setattr(consent, "decide", fail_save)
    asyncio.run(
        adapter._handle_agent_app_trigger_consent(
            {
                "projectId": project.id,
                "revision": consent.status(project)["revision"],
                "allow": True,
                "requestId": "failed-save-request",
            }
        )
    )
    result = adapter._broadcast.call_args.args[0]["data"]
    assert result["success"] is False
    assert result["requestId"] == "failed-save-request"
    assert "read-only" in result["error"]
    assert result["consent"]["needsReview"]
    assert consent.approved_trigger(project, "summarize") is None
    adapter._handle_agent_app_list.assert_not_awaited()


def test_acquiring_an_app_clears_any_shipped_approval(project):
    from app.agent_app.manager import AgentAppManager

    consent.decide(project, consent.status(project)["revision"], True)
    manager = AgentAppManager.__new__(AgentAppManager)
    manager.projects = {}
    manager._save_projects = lambda: None
    manager.ensure_project_session = lambda p: None
    project.craftbot_version = "test"
    manager._register_acquired(project, delivered=False)
    assert consent.approved_trigger(project, "summarize") is None
    assert consent.status(project)["needsReview"]
