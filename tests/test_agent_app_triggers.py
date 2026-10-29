"""App requests require a UI decision before the first fire, bound to their definitions."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_app.integration_bridge import IntegrationBridge
from app.agent_app import trigger_consent as consent


@pytest.mark.parametrize("legacy_approval", [None, False, True])
@pytest.mark.parametrize("dev_active", [False, True])
@pytest.mark.parametrize("notice_fails", [False, True])
def test_ui_consent_required_even_for_legacy_approved_apps(
    tmp_path, monkeypatch, legacy_approval, dev_active, notice_fails
):
    project = SimpleNamespace(id="trigger-app", path=str(tmp_path))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"capabilities": {"triggers": ["restock_needed"]}})
    )
    (tmp_path / "triggers.json").write_text(
        json.dumps(
            {
                "triggers": {
                    "restock_needed": {
                        "description": "Prepare a restock order",
                        "instruction": "Draft a restock order.",
                    }
                }
            }
        )
    )
    sidecar = tmp_path / ".factory" / "host.json"
    if legacy_approval is not None:
        sidecar.parent.mkdir()
        sidecar.write_text(json.dumps({"triggers_approved": legacy_approval}))
    notify = AsyncMock(return_value={"status": "success"})
    manager = SimpleNamespace(
        get_project=lambda pid: project if pid == project.id else None,
        validate_bridge_token=lambda token: project.id if token == "good" else None,
        notify_app_trigger=notify,
    )
    monkeypatch.setattr(
        "app.agent_app.instances.get_instance_registry",
        lambda: SimpleNamespace(shadow=lambda pid: object() if dev_active else None),
    )
    bridge = IntegrationBridge.__new__(IntegrationBridge)
    bridge._manager = manager
    blocked = AsyncMock()
    if notice_fails:
        blocked.side_effect = RuntimeError("Notification unavailable")
    bridge._on_trigger_blocked = blocked
    body = {"trigger": "restock_needed", "request_id": "row1"}

    def fire(token="good", **overrides):
        request = SimpleNamespace(
            headers={"Authorization": f"Bearer {token}"},
            json=AsyncMock(return_value={**body, **overrides}),
        )
        return asyncio.run(bridge._handle_agent_request(request))

    # Authentication, declarations and dev-era deferral remain independent gates.
    assert fire(token="bad").status == 401
    assert fire(trigger="undeclared").status == 403
    notify.assert_not_awaited()
    blocked.assert_not_awaited()

    response = fire()
    if dev_active:
        assert response.status == 200
        assert json.loads(response.body)["status"] == "deferred"
        notify.assert_not_awaited()
        blocked.assert_not_awaited()
        return
    assert response.status == 403
    assert json.loads(response.body)["code"] == "trigger_approval_required"
    blocked.assert_awaited_once_with(project.id, "restock_needed", "row1")
    notify.assert_not_awaited()  # No agent run, including no consent-question run.
    review = consent.status(project)
    assert review["needsReview"] is True
    consent.decide(project, review["revision"], True)
    assert fire().status == 200
    notify.assert_awaited_once_with(project.id, "restock_needed", "row1")
    assert blocked.await_count == 1  # Allowed requests don't raise warnings.
    if legacy_approval is None:
        assert not sidecar.exists()
    else:
        assert json.loads(sidecar.read_text()) == {"triggers_approved": legacy_approval}


@pytest.mark.parametrize(
    "params",
    [
        None,
        {},
        {
            "label": {"type": "string", "default": "QA_REVIEWED_VALUE"},
            "enabled": {"type": "boolean", "default": False},
            "count": {"type": "number", "default": 0},
            "suffix": {"type": "string", "default": ""},
            "mode": {"type": "string", "enum": ["draft", "final"], "default": "draft"},
        },
    ],
    ids=["omitted-params", "empty-params", "declared-defaults"],
)
def test_queued_request_retains_reviewed_defaults_after_definition_changes(
    tmp_path, params
):
    from app.agent_app.manager import AgentAppManager

    definition = {
        "description": "Report a sample label",
        "instruction": "Report the supplied label or its reviewed default.",
    }
    if params is not None:
        definition["params"] = params
    file = tmp_path / "triggers.json"
    file.write_text(json.dumps({"triggers": {"label_check": definition}}))
    project = SimpleNamespace(id="queued-app", name="Queued app", path=str(tmp_path))
    consent.decide(project, consent.status(project)["revision"], True)
    manager = AgentAppManager.__new__(AgentAppManager)
    manager.projects = {project.id: project}
    manager._session_manager = object()
    manager.ensure_project_session = lambda item: SimpleNamespace(
        id="queued-app-session"
    )
    emitted = AsyncMock()
    manager._trigger_service = SimpleNamespace(emit=emitted)

    result = asyncio.run(
        manager.notify_app_trigger(project.id, "label_check", "queued-row")
    )
    assert result["status"] == "success"
    queued = emitted.call_args.args[0]
    reviewed_definition = json.loads(json.dumps(definition))

    # The worker has not started yet. A later edit is not user-approved.
    definition["instruction"] = "QA_CHANGED_INSTRUCTION"
    definition["params"] = {
        "label": {"type": "string", "default": "QA_UNREVIEWED_VALUE"}
    }
    file.write_text(json.dumps({"triggers": {"label_check": definition}}))
    assert consent.approved_trigger(project, "label_check") is None
    assert queued.payload["trigger_definition"] == reviewed_definition
    assert (
        json.dumps(params or {}, ensure_ascii=False, sort_keys=True)
        in queued.description
    )
    assert reviewed_definition["instruction"] in queued.description
    assert "QA_UNREVIEWED_VALUE" not in queued.description
    assert "QA_CHANGED_INSTRUCTION" not in queued.description
    assert "Do not reread triggers.json" in queued.description

    # New fires stay blocked; after an explicit review only a new queue entry
    # may use the changed default. The original entry keeps its snapshot.
    blocked = asyncio.run(
        manager.notify_app_trigger(project.id, "label_check", "blocked-row")
    )
    assert blocked["status"] == "error"
    assert emitted.await_count == 1
    consent.decide(project, consent.status(project)["revision"], True)
    result = asyncio.run(
        manager.notify_app_trigger(project.id, "label_check", "new-row")
    )
    assert result["status"] == "success"
    latest = emitted.call_args.args[0]
    assert latest.payload["trigger_definition"] == definition
    assert "QA_UNREVIEWED_VALUE" in latest.description
    assert queued.payload["trigger_definition"] == reviewed_definition
    assert "QA_UNREVIEWED_VALUE" not in queued.description
