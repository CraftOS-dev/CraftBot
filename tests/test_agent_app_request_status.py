"""What the app-requests banner reads about an app's waiting requests.

An app whose requests were allowed asks again once its source changes. The
banner then says its new or changed requests are off until reviewed; for an
app never allowed, it says its requests are off.
"""

import asyncio
from types import SimpleNamespace

from app.agent_app import framework_bridge
from app.agent_app.framework_bridge import FrameworkBridge


class _Store:
    def __init__(self):
        self.rows = {}

    def all(self, kind):
        return [value for (k, _), value in self.rows.items() if k == kind]

    def get(self, kind, key):
        return self.rows.get((kind, key))

    def put(self, kind, key, value):
        self.rows[(kind, key)] = value


def _status(monkeypatch, grant):
    async def selected(path, app_id):
        return {"status": "running"}

    async def attach(path, app_id):
        return {}

    async def revision(path, app_id):
        return "source-now"

    async def pending(cli, path, app_id):
        return [{"id": "tsk_1", "capability": "triage"}]

    store = _Store()
    store.put("attachment", "key", grant)
    bridge = FrameworkBridge(
        SimpleNamespace(store=store, selected=selected, attach=attach)
    )
    bridge.revision = revision
    monkeypatch.setattr(
        framework_bridge.framework,
        "configured_cli",
        lambda: SimpleNamespace(home="home"),
    )
    monkeypatch.setattr(framework_bridge, "app_key", lambda home, path, app_id: "key")
    monkeypatch.setattr(framework_bridge, "pending_tasks", pending)
    return asyncio.run(bridge.request_status("app", "app-id"))


def test_an_allowed_app_that_changed_asks_again_as_changed(monkeypatch):
    status = _status(
        monkeypatch, {"tasksAllowed": True, "capabilityFingerprint": "source-before"}
    )
    assert status["permissionRequired"] and status["needsReview"]
    assert status["changed"] is True
    assert status["requests"] == ["triage"]


def test_an_app_never_allowed_is_not_a_change(monkeypatch):
    status = _status(monkeypatch, {"tasksAllowed": False})
    assert status["permissionRequired"] and status["needsReview"]
    assert status["changed"] is False


def test_an_allowed_unchanged_app_needs_nothing(monkeypatch):
    status = _status(
        monkeypatch, {"tasksAllowed": True, "capabilityFingerprint": "source-now"}
    )
    assert not status["permissionRequired"]
    assert status["changed"] is False
