"""Sub-agent starts and ends reach lifecycle observers (subagent_link)."""

import asyncio
import json
import types

from app.subagent import manager as subagent_manager
from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from app.ui_layer.adapters.ws_channel import ClientChannel


class _FakeStreams:
    def create_stream(self, *_args, **_kwargs):
        pass

    def log(self, *_args, **_kwargs):
        pass


def test_spawn_and_end_notify_observers(monkeypatch):
    seen = []
    observer = lambda event, sub: seen.append((event, sub.id, sub.parent_task_id, sub.status))
    monkeypatch.setattr(subagent_manager, "_LIFECYCLE_OBSERVERS", [])
    monkeypatch.setattr(
        subagent_manager,
        "get_subagent_definition",
        lambda name: types.SimpleNamespace(compiled_actions=[]),
    )
    subagent_manager.add_lifecycle_observer(observer)
    subagent_manager.add_lifecycle_observer(observer)  # added once only

    mgr = subagent_manager.SubAgentManager(_FakeStreams(), llm_interface=None)
    sub = mgr.spawn(agent_type="walk_verify", query="check it", parent_task_id="chat-1")
    mgr.end(sub.id, "completed", "done")
    mgr.end(sub.id, "completed", "again")  # idempotent: no second end

    assert seen == [
        ("spawn", sub.id, "chat-1", "running"),
        ("end", sub.id, "chat-1", "completed"),
    ]


def test_a_failing_observer_never_breaks_a_spawn(monkeypatch):
    def broken(event, sub):
        raise RuntimeError("boom")

    monkeypatch.setattr(subagent_manager, "_LIFECYCLE_OBSERVERS", [broken])
    monkeypatch.setattr(
        subagent_manager,
        "get_subagent_definition",
        lambda name: types.SimpleNamespace(compiled_actions=[]),
    )
    mgr = subagent_manager.SubAgentManager(_FakeStreams(), llm_interface=None)
    assert mgr.spawn(agent_type="x", query="q", parent_task_id="main").id.startswith("sub_")


def test_adapter_sends_subagent_link_only_to_capable_clients(monkeypatch):
    class _Ws:
        def __init__(self):
            self.sent = []

        async def send_str(self, text):
            self.sent.append(json.loads(text))

        async def close(self):
            pass

    async def scenario():
        from app.state.agent_state import STATE

        monkeypatch.setattr(STATE, "main_loop", asyncio.get_running_loop(), raising=False)
        browser_ws, terminal_ws = _Ws(), _Ws()
        browser, terminal = ClientChannel(browser_ws), ClientChannel(terminal_ws)
        terminal.declare("terminal", ["subagent_link"])
        adapter = types.SimpleNamespace(_channels={browser_ws: browser, terminal_ws: terminal})
        adapter._broadcast_capable = lambda cap, msg: BrowserAdapter._broadcast_capable(adapter, cap, msg)
        sub = types.SimpleNamespace(id="sub_1", parent_task_id="chat-1", agent_type="walk_verify", status="running")
        BrowserAdapter._on_subagent_lifecycle(adapter, "spawn", sub)
        await asyncio.sleep(0.05)
        await browser.close()
        await terminal.close()
        return browser_ws.sent, terminal_ws.sent

    browser_sent, terminal_sent = asyncio.run(scenario())
    assert browser_sent == []
    assert terminal_sent == [
        {
            "type": "subagent_link",
            "data": {"subId": "sub_1", "parentId": "chat-1", "agentType": "walk_verify", "state": "running"},
        }
    ]
