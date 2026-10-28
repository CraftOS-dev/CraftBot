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
            {"projectId": project.id, "revision": "stale", "allow": True}
        )
    )
    assert adapter._broadcast.call_args.args[0]["data"]["success"] is False
    assert consent.approved_trigger(project, "summarize") is None
    asyncio.run(
        adapter._handle_agent_app_trigger_consent(
            {"projectId": project.id, "revision": revision, "allow": True}
        )
    )
    result = adapter._broadcast.call_args.args[0]["data"]
    assert result["success"] and not result["consent"]["required"]
    adapter._handle_agent_app_list.assert_awaited_once()


def test_copied_publisher_approval_does_not_authorize_another_app(project):
    consent.decide(project, consent.status(project)["revision"], True)
    imported = SimpleNamespace(id="different-import", path=project.path)
    assert consent.approved_trigger(imported, "summarize") is None
    assert consent.status(imported)["needsReview"]


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
