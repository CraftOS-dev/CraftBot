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


class TestTheSupervisorRespectsTheDecision:
    @pytest.fixture
    def host(self, monkeypatch, tmp_path):
        """A FactoryHost with a real open Arc for one project."""
        from app.factory.engine import ARC_BUILD, Arc
        from app.factory.host_craftbot import FactoryHost

        h = FactoryHost()
        arc = Arc(tmp_path / "arc.json")
        arc.open(ARC_BUILD)
        monkeypatch.setattr(h, "arc_for", lambda _pid: arc)
        kicks = []
        monkeypatch.setattr(h, "kick", lambda _pid="": kicks.append("kick"))
        return h, arc, kicks

    def test_a_parked_question_pauses_the_arc(self, host):
        h, arc, kicks = host
        h.on_run_end("4fa24e8b", {}, awaiting_answer=True)
        assert arc.paused and arc.paused["by"] == "question"
        assert kicks == [], "a parked question must not wake the supervisor"

    def test_the_supervisor_never_acts_on_a_parked_question(self, host):
        # There is no deadline either: a timer here would be the system
        # deciding how long the agent may wait — and the only thing a resume
        # can do with an unanswered question is ask it again, which is the
        # original bug this file exists for.
        h, arc, _kicks = host
        h.on_run_end("4fa24e8b", {}, awaiting_answer=True)
        arc._d["last_activity_at"] = 0.0  # hours idle — still the user's move
        arc.save()
        project = types.SimpleNamespace(
            id="4fa24e8b", name="Brainstorm Graph", path=".", session_id="lui_x"
        )
        assert h._tick_project("4fa24e8b", project) is False

    def test_the_answer_is_the_wakeup(self, host):
        # The user replies -> that run ends -> the pause clears and the
        # supervisor is kicked; the arc carries on as normal.
        h, arc, kicks = host
        h.on_run_end("4fa24e8b", {}, awaiting_answer=True)
        h.on_run_end("4fa24e8b", {})
        assert arc.paused is None
        assert kicks == ["kick"]

    def test_a_real_surrender_only_kicks_the_supervisor(self, host):
        # Run-end records facts; the ONE dispatch decision point is the
        # supervisor tick, where backoff and the stall cap live.
        h, arc, kicks = host
        h.on_run_end("4fa24e8b", {})
        assert kicks == ["kick"]
        assert arc.paused is None

    def test_a_user_stop_is_recorded_as_intent(self, host):
        h, arc, _kicks = host
        h._emit_chat = lambda pid, text: None
        h.pause_by_user("4fa24e8b")
        assert arc.paused and arc.paused["by"] == "user"
        arc._d["last_activity_at"] = 0.0
        arc.save()
        project = types.SimpleNamespace(
            id="4fa24e8b", name="Brainstorm Graph", path=".", session_id="lui_x"
        )
        assert h._tick_project("4fa24e8b", project) is False, (
            "the stop button is a stop, not a deferral"
        )
