# -*- coding: utf-8 -*-
"""Phase 3 tests: SessionRouter decisions and durable message parking
(crash-during-routing recovery)."""

import asyncio
import json

from app.triggers import SessionRouter, TriggerSource, TriggerSpec
from app.triggers.service import TriggerService
from app.triggers.store import TriggerStore

from agent_core.core.impl.trigger.queue import TriggerQueue


def run(coro):
    return asyncio.run(coro)


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    async def generate_response_async(
        self, system_prompt: str, user_prompt: str, prompt_name=None, **_kwargs
    ):
        self.calls += 1
        self.last_system_prompt = system_prompt
        self.last_prompt = user_prompt
        self.last_prompt_name = prompt_name
        return self.response


ROUTING_PROMPT = (
    "{item_type}|{item_content}|{source_platform}|{existing_sessions}|"
    "{current_living_ui_id}|{recent_conversation}"
)


class TestSessionRouter:
    def test_route_to_existing_session(self):
        llm = FakeLLM(json.dumps({"action": "route", "session_id": "abc123"}))
        router = SessionRouter(llm, ROUTING_PROMPT)
        result = run(router.route("message", "continue that task", "sessions"))
        assert result["session_id"] == "abc123"
        assert llm.last_prompt_name == "ROUTE_TO_SESSION"
        assert llm.calls == 1

    def test_new_session_decision(self):
        llm = FakeLLM(json.dumps({"action": "new", "session_id": "new"}))
        router = SessionRouter(llm, ROUTING_PROMPT)
        result = run(router.route("message", "do something else", "sessions"))
        assert result["action"] == "new"

    def test_action_field_backfilled(self):
        # Old-style response without "action" — inferred from session_id.
        llm = FakeLLM(json.dumps({"session_id": "abc123"}))
        router = SessionRouter(llm, ROUTING_PROMPT)
        result = run(router.route("message", "x", "sessions"))
        assert result["action"] == "route"

    def test_garbage_response_defaults_to_new(self):
        llm = FakeLLM("not json at all {{{")
        router = SessionRouter(llm, ROUTING_PROMPT)
        result = run(router.route("message", "x", "sessions"))
        assert result == {
            "action": "new",
            "session_id": "new",
            "reason": "Failed to parse routing response",
        }

    def test_format_sessions_empty(self):
        router = SessionRouter(FakeLLM(""), ROUTING_PROMPT)
        assert router.format_sessions_for_routing([]) == "No existing sessions."

    def test_queue_never_calls_llm(self, tmp_path):
        # Phase 3 invariant: the queue has no routing — an LLM passed to its
        # deprecated ctor param is never invoked on put/get.
        llm = FakeLLM(json.dumps({"action": "new"}))
        queue = TriggerQueue(llm=llm)
        store = TriggerStore(db_path=str(tmp_path / "s.db"))
        service = TriggerService(store, queue)

        async def scenario():
            # No session_id at all — the pre-#321 queue would have routed this.
            await service.emit(
                TriggerSpec(
                    source=TriggerSource.USER_MESSAGE,
                    description="hello",
                    session_id="s1",
                )
            )
            await asyncio.wait_for(service.next(), timeout=2)

        run(scenario())
        assert llm.calls == 0


class TestDurableParking:
    def make_stack(self, tmp_path):
        store = TriggerStore(db_path=str(tmp_path / "sessions.db"))
        queue = TriggerQueue()
        service = TriggerService(store, queue)
        return store, queue, service

    def parked_spec(self):
        return TriggerSpec(
            source=TriggerSource.USER_MESSAGE,
            description="Please perform action that best suit this user chat "
            "you just received: send the report",
            priority=3,
            payload={"user_message": "send the report", "platform": "Telegram"},
        )

    def test_park_records_without_enqueue(self, tmp_path):
        store, queue, service = self.make_stack(tmp_path)

        async def scenario():
            row_id = service.park(self.parked_spec())
            assert store.get(row_id)["status"] == "PENDING"
            assert store.get(row_id)["session_id"] is None
            assert await queue.size() == 0  # parked, not queued
            return row_id

        run(scenario())

    def test_settled_park_does_not_rehydrate(self, tmp_path):
        async def scenario():
            store, queue, service = self.make_stack(tmp_path)
            row_id = service.park(self.parked_spec())
            # message delivered into a new session's row
            result = await service.emit(
                TriggerSpec(
                    source=TriggerSource.USER_MESSAGE,
                    description="delivered",
                    session_id="abc123",
                )
            )
            service.settle_parked(row_id, delivered_as=result.trigger_id)
            row = store.get(row_id)
            assert row["status"] == "DONE"
            assert row["superseded_by"] == result.trigger_id

        run(scenario())

    def test_crash_during_routing_recovers_message(self, tmp_path):
        # The Phase 3 headline: park → crash before routing finishes →
        # next boot re-delivers the message as a fresh session.
        async def scenario():
            store, queue, service = self.make_stack(tmp_path)
            row_id = service.park(self.parked_spec())
            # crash: routing LLM call never completed, nothing was settled

            store2, queue2, service2 = self.make_stack(tmp_path)  # restart
            requeued = await service2.rehydrate()
            assert requeued == 1

            trig = await asyncio.wait_for(service2.next(), timeout=2)
            assert trig.id == row_id
            assert trig.session_id  # assigned a fresh session on recovery
            assert "send the report" in trig.next_action_description
            assert store2.get(row_id)["session_id"] == trig.session_id

            await service2.ack(trig)
            assert store2.get(row_id)["status"] == "DONE"

        run(scenario())
