# -*- coding: utf-8 -*-

import asyncio

from agent_core.core.action import Action
from app.subagent.runner import SubAgentRunner
from app.subagent.types import SubAgent


class _FakeActionLibrary:
    def __init__(self):
        self.action = Action(
            name="sub_task_end",
            description="End sub-agent",
            action_type="atomic",
            mode="CLI",
        )

    def retrieve_action(self, action_name):
        if action_name == self.action.name:
            return self.action
        return None


class _FakeActionManager:
    def __init__(self):
        self.calls = []

    async def execute_action(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "success"}


def _make_runner():
    action_manager = _FakeActionManager()
    runner = SubAgentRunner(
        subagent_manager=None,
        action_manager=action_manager,
        action_library=_FakeActionLibrary(),
        event_stream_manager=None,
        llm_interface=None,
    )
    return runner, action_manager


def _make_subagent():
    return SubAgent(
        id="sub_test",
        agent_type="research_agent",
        parent_task_id="parent_test",
        query="test query",
        compiled_actions=["sub_task_end"],
    )


def test_dispatch_action_accepts_params_alias():
    runner, action_manager = _make_runner()
    payload = {"status": "completed", "result": "done"}

    asyncio.run(
        runner._dispatch_action(
            _make_subagent(),
            {"action_name": "sub_task_end", "params": payload},
        )
    )

    assert action_manager.calls[0]["input_data"] == payload
    assert action_manager.calls[0]["session_id"] == "sub_test"


def test_dispatch_action_prefers_parameters_key():
    runner, action_manager = _make_runner()

    asyncio.run(
        runner._dispatch_action(
            _make_subagent(),
            {
                "action_name": "sub_task_end",
                "parameters": {"status": "failed", "result": "primary"},
                "params": {"status": "completed", "result": "alias"},
            },
        )
    )

    assert action_manager.calls[0]["input_data"] == {
        "status": "failed",
        "result": "primary",
    }
