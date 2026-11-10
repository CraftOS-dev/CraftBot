"""The existing operator skill reaches restored app chats without affecting Main."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_core.core.session import Session, SessionType
from app.agent_base import AgentBase


@pytest.mark.parametrize(
    "kind,key",
    [
        (SessionType.AGENT_APP, '["home","/app","app"]'),
        (SessionType.AGENT_APP, None),
        (SessionType.MAIN, None),
        (SessionType.CHAT, None),
    ],
)
def test_operator_is_loaded_and_unloaded_for_registry_app_turns_only(kind, key):
    agent = AgentBase.__new__(AgentBase)
    agent.session_manager = SimpleNamespace(add_skill=Mock(), remove_skill=Mock())
    agent._user_skill_action_sets = Mock(return_value=[])
    session = Session(id="session", type=kind, agent_app_framework_key=key)
    payload = {"workflow_skills": ["chosen-skill"]}
    asyncio.run(agent._apply_workflow_capabilities(session, payload))
    expected = ["chosen-skill", "framework-operator"] if key else ["chosen-skill"]
    assert [
        call.args[1] for call in agent.session_manager.add_skill.call_args_list
    ] == expected
    agent._remove_workflow_capabilities(session, payload)
    assert [
        call.args[1] for call in agent.session_manager.remove_skill.call_args_list
    ] == expected


def test_explicitly_loaded_operator_remains_loaded_after_the_turn():
    agent = AgentBase.__new__(AgentBase)
    agent.session_manager = SimpleNamespace(add_skill=Mock(), remove_skill=Mock())
    agent._user_skill_action_sets = Mock(return_value=[])
    session = Session(
        id="app",
        type=SessionType.AGENT_APP,
        agent_app_framework_key='["home","/app","app"]',
        selected_skills=["framework-operator"],
    )
    payload = {}
    asyncio.run(agent._apply_workflow_capabilities(session, payload))
    agent._remove_workflow_capabilities(session, payload)
    agent.session_manager.remove_skill.assert_not_called()
    assert session.selected_skills == ["framework-operator"]
