"""Delegated tasks cannot inherit the owner's prompt or expand host tools."""

import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

from agent_core.core.session.session import Session
from agent_core.core.impl.session.manager import SessionManager
from agent_core.core.state.session import StateSession
from agent_core.core.impl.context.engine import ContextEngine
from app.agent_app.framework_commands import TaskAuthority, task_authority


def test_isolation_survives_session_roundtrip_and_tool_compilation():
    session = Session(id="task", title="App task", isolated_app_task=True)
    restored = Session.from_dict(session.to_dict())
    SessionManager._compile_actions(restored)
    assert restored.isolated_app_task
    assert set(restored.compiled_actions) == {
        "agent_app_framework_command",
        "send_message",
        "end_turn",
    }


def test_all_prompt_paths_exclude_owner_context(monkeypatch):
    engine = ContextEngine.__new__(ContextEngine)
    state = SimpleNamespace(current_session=SimpleNamespace(isolated_app_task=True))
    monkeypatch.setattr(StateSession, "bound", lambda: state)
    for key in (
        "agent_info",
        "user_profile",
        "soul",
        "language_instruction",
        "role_info",
        "environmental_context",
        "file_system_context",
        "capability_catalog",
    ):
        monkeypatch.setattr(
            engine,
            f"create_system_{key}",
            Mock(side_effect=AssertionError("owner context accessed")),
        )
    monkeypatch.setattr(engine, "create_system_policy", lambda: "POLICY")
    assert engine.make_prompt(user_flags={"query": False}) == ("POLICY", "")


@pytest.mark.parametrize("isolated", [True, False])
def test_executor_rejects_host_tool_even_when_model_requests_it(monkeypatch, isolated):
    from app.agent_base import AgentBase

    agent = SimpleNamespace(
        session_manager=SimpleNamespace(
            get=lambda sid: SimpleNamespace(isolated_app_task=isolated)
        ),
        action_manager=SimpleNamespace(execute_actions_parallel=AsyncMock()),
    )

    async def check():
        token = task_authority.set(
            TaskAuthority("http://127.0.0.1:8123", "t", "secret")
        )
        try:
            result = await AgentBase._execute_actions(
                agent,
                [(SimpleNamespace(name="run_shell"), {"command": "anything"})],
                SimpleNamespace(),
                "",
                "task",
            )
            assert result["status"] == "error"
            agent.action_manager.execute_actions_parallel.assert_not_awaited()
        finally:
            task_authority.reset(token)

    asyncio.run(check())
