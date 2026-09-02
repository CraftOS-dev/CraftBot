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
        """A FactoryHost whose machine always wants a redispatch."""
        from app.factory.appfactory import BUILDING, transition
        from app.factory.engine import Caps, Machine
        from app.factory.host_craftbot import get_factory_host

        machine = Machine(transition, tmp_path / "state.json", BUILDING, Caps())
        assert machine.needs_redispatch(), "fixture must reproduce the condition"

        h = get_factory_host()
        monkeypatch.setattr(h, "machine_for", lambda _pid: machine)
        monkeypatch.setattr(h, "_sidecar_read", lambda _pid: {})
        deferred, dispatched = [], []
        monkeypatch.setattr(
            h,
            "_defer_run_end",
            lambda pid, delay, reason: deferred.append((delay, reason)),
        )
        monkeypatch.setattr(
            h,
            "_project",
            lambda _pid: (
                dispatched.append("dispatched")
                or types.SimpleNamespace(
                    id="4fa24e8b", name="Brainstorm Graph", path="."
                )
            ),
        )
        return h, deferred, dispatched

    def test_a_parked_question_is_not_redispatched(self, host):
        h, _deferred, dispatched = host
        h.on_run_end("4fa24e8b", {}, awaiting_answer=True)
        assert dispatched == []

    def test_there_is_no_deadline_on_the_agent_s_decision(self, host):
        # Not deferred either. A timer here would be the system deciding how
        # long the agent may wait — and the only thing a resume can do with an
        # unanswered question is ask it again, which is the original bug.
        h, deferred, dispatched = host
        h.on_run_end("4fa24e8b", {}, awaiting_answer=True)
        assert deferred == []
        assert dispatched == []

    def test_the_answer_is_the_wakeup(self, host):
        # The user replies -> that run ends -> this hook is re-entered with
        # no question outstanding -> the arc carries on as normal.
        h, _deferred, dispatched = host
        h.on_run_end("4fa24e8b", {}, awaiting_answer=True)
        h.on_run_end("4fa24e8b", {})
        assert dispatched == ["dispatched"]

    def test_a_real_surrender_still_redispatches(self, host):
        h, _deferred, dispatched = host
        h.on_run_end("4fa24e8b", {})
        assert dispatched == ["dispatched"]

    def test_the_default_is_unchanged_for_every_other_caller(self, host):
        # on_run_end's new parameter must not alter existing call sites.
        h, _deferred, dispatched = host
        h.on_run_end("4fa24e8b", {"factory_mission_id": "m1"})
        assert dispatched == ["dispatched"]
