# -*- coding: utf-8 -*-
"""A chat-started Agent App setup survives the popup being closed.

Regression cover for issue #448: the setup questions lived only in the
browser, so closing the popup lost them, and the agent kept asking the user to
answer questions nobody could see. The setup is now a persisted PendingSetup
that ends only on finalize, cancel, or deletion of the chat that started it
(docs/plans/agent-app-setup-resume-plan.md).
"""

import asyncio
import json
import threading
import types

import pytest

from app.agent_app.pending_setups import PendingSetup, PendingSetupRegistry
from app.triggers import TriggerSource


def _setup(wizard_id="chat_1", session="s1", name="Stock Forecaster", t=1.0):
    return PendingSetup(
        wizard_id=wizard_id,
        origin_session_id=session,
        name=name,
        config={"name": name, "description": "d"},
        questions=[{"id": "q1", "question": "Which data?"}],
        created_at=t,
    )


@pytest.fixture
def registry(tmp_path):
    return PendingSetupRegistry(tmp_path / "agent_app_pending_setups.json")


# ── registry ────────────────────────────────────────────────────────────────


def test_round_trips_across_restarts(tmp_path, registry):
    registry.add(_setup())
    reloaded = PendingSetupRegistry(tmp_path / "agent_app_pending_setups.json")
    assert reloaded.get("chat_1") == _setup()


def test_find_ignores_case_and_whitespace_but_not_session(registry):
    registry.add(_setup(name="Stock  Forecaster"))
    assert registry.find("s1", " stock forecaster ").wizard_id == "chat_1"
    assert registry.find("s2", "Stock Forecaster") is None
    assert registry.find("s1", "Other App") is None


def test_remove_returns_the_record_once(registry):
    registry.add(_setup())
    assert registry.remove("chat_1").wizard_id == "chat_1"
    assert registry.remove("chat_1") is None
    assert registry.list() == []


def test_remove_for_session_only_touches_that_session(registry):
    registry.add(_setup("chat_a", session="s1"))
    registry.add(_setup("chat_b", session="s2"))
    removed = registry.remove_for_session("s1")
    assert [s.wizard_id for s in removed] == ["chat_a"]
    assert [s.wizard_id for s in registry.list()] == ["chat_b"]


def test_list_is_oldest_first(registry):
    registry.add(_setup("chat_new", t=2.0))
    registry.add(_setup("chat_old", t=1.0))
    assert [s.wizard_id for s in registry.list()] == ["chat_old", "chat_new"]


def test_missing_or_corrupt_file_loads_empty(tmp_path):
    path = tmp_path / "agent_app_pending_setups.json"
    assert PendingSetupRegistry(path).list() == []
    path.write_text("{not json", encoding="utf-8")
    assert PendingSetupRegistry(path).list() == []
    path.write_text(json.dumps({"setups": [{"noWizardId": 1}]}), encoding="utf-8")
    assert PendingSetupRegistry(path).list() == []


def test_concurrent_adds_are_all_persisted(tmp_path, registry):
    threads = [
        threading.Thread(target=registry.add, args=(_setup(f"chat_{i}", t=i),))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    reloaded = PendingSetupRegistry(tmp_path / "agent_app_pending_setups.json")
    assert len(reloaded.list()) == 20


# ── agent_app_scaffold ──────────────────────────────────────────────────────


class _Wizard:
    def __init__(self, questions):
        self.questions = questions
        self.calls = 0

    async def generate_interview(self, config, image_notes, allow_empty=False):
        self.calls += 1
        return list(self.questions)


@pytest.fixture
def scaffold_env(monkeypatch, registry):
    """The scaffold action with a stub manager, interviewer and browser."""
    import app.agent_app as agent_app_pkg

    manager = types.SimpleNamespace(pending_setups=registry)
    interviewer = _Wizard([{"id": "q1", "question": "Which data?"}])
    opened = []

    async def _open(payload):
        opened.append(payload)
        return True

    monkeypatch.setattr(agent_app_pkg, "get_agent_app_manager", lambda: manager)
    monkeypatch.setattr(agent_app_pkg, "broadcast_agent_app_wizard_open", _open)
    import app.agent_app.wizard as wizard_mod

    monkeypatch.setattr(wizard_mod, "generate_interview", interviewer.generate_interview)
    return types.SimpleNamespace(registry=registry, interviewer=interviewer, opened=opened)


def _scaffold(session="s1", name="Stock Forecaster"):
    from app.data.action.agent_app_actions import agent_app_scaffold

    return asyncio.run(
        agent_app_scaffold(
            {"name": name, "description": "Forecasts stocks.", "_session_id": session}
        )
    )


def test_scaffold_persists_the_setup_and_opens_it(scaffold_env):
    out = _scaffold()
    assert out["status"] == "success" and "project_id" not in out
    assert "Resume setup" in out["message"]
    [setup] = scaffold_env.registry.list()
    assert setup.origin_session_id == "s1"
    assert scaffold_env.opened == [setup.to_dict()]


def test_scaffold_again_reopens_the_same_questions(scaffold_env):
    _scaffold()
    out = _scaffold(name="stock forecaster")
    assert scaffold_env.interviewer.calls == 1, "no second interview call"
    assert len(scaffold_env.registry.list()) == 1
    first, second = scaffold_env.opened
    assert first == second
    assert out["message"].startswith("Reopened the pending setup.")


def test_scaffold_without_a_browser_keeps_no_record(scaffold_env, monkeypatch):
    import app.agent_app as agent_app_pkg

    async def _no_browser(payload):
        return False

    async def _create_project(**kwargs):
        raise RuntimeError("stop here: build path reached")

    monkeypatch.setattr(agent_app_pkg, "broadcast_agent_app_wizard_open", _no_browser)
    agent_app_pkg.get_agent_app_manager().create_project = _create_project
    out = _scaffold()
    assert out["status"] == "error" and "build path reached" in out["message"]
    assert scaffold_env.registry.list() == []


# ── cancel handler ──────────────────────────────────────────────────────────


class _Triggers:
    def __init__(self):
        self.specs = []

    async def emit(self, spec):
        self.specs.append(spec)


def _adapter(registry):
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    sent = []

    async def _broadcast(message):
        sent.append(message)

    fake = types.SimpleNamespace(
        _agent_app_manager=types.SimpleNamespace(
            pending_setups=registry, _trigger_service=_Triggers()
        ),
        _broadcast=_broadcast,
    )
    cancel = BrowserAdapter._handle_agent_app_setup_cancel.__get__(fake)
    list_message = BrowserAdapter._agent_app_setup_list_message.__get__(fake)
    return fake, sent, cancel, list_message


def test_cancel_drops_the_setup_and_tells_the_origin_chat(registry):
    registry.add(_setup())
    fake, sent, cancel, _ = _adapter(registry)
    asyncio.run(cancel({"wizardId": "chat_1"}))
    assert registry.list() == []
    [spec] = fake._agent_app_manager._trigger_service.specs
    assert spec.source == TriggerSource.AGENT_APP_SETUP_CANCELLED
    assert spec.session_id == "s1"
    assert sent == [
        {"type": "agent_app_setup_cancel", "data": {"success": True, "wizardId": "chat_1"}}
    ]


def test_cancel_of_an_unknown_setup_notifies_nobody(registry):
    fake, sent, cancel, _ = _adapter(registry)
    asyncio.run(cancel({"wizardId": "chat_gone"}))
    assert fake._agent_app_manager._trigger_service.specs == []
    assert sent[0]["data"]["success"] is False


def test_setup_list_message_carries_every_pending_setup(registry):
    registry.add(_setup())
    _, _, _, list_message = _adapter(registry)
    assert list_message() == {
        "type": "agent_app_setup_list",
        "data": {"setups": [_setup().to_dict()]},
    }
