# -*- coding: utf-8 -*-
"""Asking the user a question is not walking out of the room.

Regression cover for 2026-09-02 13:26 (brainstorm_graph 4fa24e8b). The agent
asked "should the research suggestions be generated locally from the idea
text, or should they come from the existing AI/API flow?", offering three
suggested responses. The run parked as waiting_for_user — and in the SAME
SECOND the factory called it a surrender and dispatched a resume mission:

    13:26:02  AGENT ASKS THE USER A QUESTION
    13:26:02  run parked: waiting_for_user
    13:26:02  REDISPATCH - machine calls it a surrender
    13:27:36  AGENT ASKS THE SAME QUESTION AGAIN
    13:27:36  REDISPATCH - again
    13:28:16  USER ANSWERS
    13:28:18  USER ANSWERS (the duplicate)
    13:28:22  STUCK - surrender budget spent

The two spurious resumes also re-read the codebase into the same session
stream, taking it from 22k to 162k tokens; the run finally died on a single
211,460-token request against a 200,000 cap.
"""

import asyncio
import types

import pytest

from app.data.action.send_message import send_message


def _send(**kw):
    kw.setdefault("message", "Local or AI flow?")
    kw.setdefault("simulated_mode", True)
    return asyncio.run(send_message(kw))


class TestSendMessageDeclaresIntent:
    def test_a_question_with_options_is_awaiting_an_answer(self):
        out = _send(suggested_responses=["Local", "AI flow", "You choose"])
        assert out["end_turn"] is True
        assert out["awaiting_answer"] is True

    def test_a_plain_final_message_is_not(self):
        # Nothing offered to answer: this really is the agent stopping.
        out = _send()
        assert out["end_turn"] is True
        assert out["awaiting_answer"] is False

    def test_a_progress_message_is_not(self):
        out = _send(continue_work=True, suggested_responses=["a", "b"])
        assert out["end_turn"] is False
        assert out["awaiting_answer"] is False

    def test_blank_options_do_not_count(self):
        assert _send(suggested_responses=["", "   "])["awaiting_answer"] is False


class TestTheSignalSurvivesTheMerge:
    def _agent(self):
        from app.agent_base import AgentBase

        return AgentBase.__new__(AgentBase)

    def test_a_single_action_carries_it(self):
        merged = self._agent()._merge_action_outputs(
            [{"status": "ok", "end_turn": True, "awaiting_answer": True}]
        )
        assert merged["run_ends"] is True
        assert merged["awaiting_answer"] is True

    def test_a_parallel_batch_carries_it(self):
        merged = self._agent()._merge_action_outputs(
            [
                {"status": "ok", "end_turn": True, "awaiting_answer": False},
                {"status": "ok", "end_turn": True, "awaiting_answer": True},
            ]
        )
        assert merged["awaiting_answer"] is True

    def test_a_batch_with_no_question_does_not_claim_one(self):
        merged = self._agent()._merge_action_outputs(
            [
                {"status": "ok", "end_turn": True},
                {"status": "ok", "end_turn": True},
            ]
        )
        assert merged["awaiting_answer"] is False


@pytest.mark.parametrize("awaiting_answer", [False, True])
def test_ended_run_cleans_up_without_scheduling_a_continuation(monkeypatch, awaiting_answer):
    from unittest.mock import AsyncMock, Mock
    from app.agent_base import AgentBase
    from app.agent_app import framework_host

    bridge = types.SimpleNamespace(ended=AsyncMock())
    monkeypatch.setattr(framework_host, "get_host", lambda: types.SimpleNamespace(bridge=bridge))
    agent = types.SimpleNamespace(
        state_manager=types.SimpleNamespace(bump_event_stream=Mock()),
        session_manager=types.SimpleNamespace(touch_session=Mock()),
        _check_agent_limits=AsyncMock(return_value=True),
        _on_run_end=AsyncMock(),
        trigger_service=types.SimpleNamespace(emit=AsyncMock()),
    )
    session = types.SimpleNamespace(id="app-chat")
    trigger = types.SimpleNamespace(payload={"run_source": "framework_workflow"})
    asyncio.run(AgentBase._finalize_turn(agent, session, trigger, {
        "run_ends": True, "awaiting_answer": awaiting_answer,
    }))
    agent._on_run_end.assert_awaited_once_with(session, trigger.payload)
    bridge.ended.assert_awaited_once_with(session.id, awaiting_answer=awaiting_answer)
    agent.trigger_service.emit.assert_not_called()
