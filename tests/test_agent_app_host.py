"""The Agent App host starts one manager per process, before any interface."""

import asyncio

import pytest

from app.agent_app import _state, host


class _FakeManager:
    instances = []

    def __init__(self, workspace_root):
        self.workspace_root = workspace_root
        self.calls = []
        _FakeManager.instances.append(self)

    def bind_session_manager(self, session_manager, trigger_service):
        self.calls.append(("bind", session_manager, trigger_service))

    def cleanup_on_startup(self):
        self.calls.append(("cleanup",))

    def start_watchdog(self):
        self.calls.append(("watchdog",))

    async def auto_launch_projects(self):
        self.calls.append(("auto_launch",))


class _FakeSessionManager:
    def __init__(self):
        self.hooks = []

    def add_post_update_todos_hook(self, hook):
        self.hooks.append(hook)


class _FakeActionManager:
    _on_action_start = None
    _on_action_end = None


class _FakeAgent:
    def __init__(self):
        self.session_manager = _FakeSessionManager()
        self.trigger_service = object()
        self.action_manager = _FakeActionManager()


@pytest.fixture
def fresh_host(monkeypatch):
    monkeypatch.setattr(host, "AgentAppManager", _FakeManager)
    monkeypatch.setattr(_state, "_manager", None)
    _FakeManager.instances.clear()
    yield
    _state._manager = None


def test_host_starts_one_manager_and_wires_the_agent(fresh_host):
    agent = _FakeAgent()

    async def scenario():
        manager = host.start_agent_app_host(agent)
        await asyncio.sleep(0)  # let the auto-launch task run
        return manager

    manager = asyncio.run(scenario())
    assert _state.get_agent_app_manager() is manager
    assert [c[0] for c in manager.calls] == [
        "bind",
        "cleanup",
        "watchdog",
        "auto_launch",
    ]
    assert manager.calls[0][1] is agent.session_manager
    assert len(agent.session_manager.hooks) == 1
    assert agent.action_manager._on_action_start is not None
    assert agent.action_manager._on_action_end is not None


def test_a_second_host_is_refused(fresh_host):
    agent = _FakeAgent()

    async def scenario():
        host.start_agent_app_host(agent)
        with pytest.raises(RuntimeError, match="already running"):
            host.start_agent_app_host(agent)

    asyncio.run(scenario())
    assert len(_FakeManager.instances) == 1
