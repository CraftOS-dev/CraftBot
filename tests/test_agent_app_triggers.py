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
def test_ui_consent_required_even_for_legacy_approved_apps(
    tmp_path, monkeypatch, legacy_approval, dev_active
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

    response = fire()
    if dev_active:
        assert response.status == 200
        assert json.loads(response.body)["status"] == "deferred"
        notify.assert_not_awaited()
        return
    assert response.status == 403
    assert json.loads(response.body)["code"] == "trigger_approval_required"
    notify.assert_not_awaited()  # No agent run, including no consent-question run.
    review = consent.status(project)
    assert review["needsReview"] is True
    consent.decide(project, review["revision"], True)
    assert fire().status == 200
    notify.assert_awaited_once_with(project.id, "restock_needed", "row1")
    if legacy_approval is None:
        assert not sidecar.exists()
    else:
        assert json.loads(sidecar.read_text()) == {"triggers_approved": legacy_approval}
