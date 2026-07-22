# -*- coding: utf-8 -*-
"""Unit tests for SessionTriggerQueue — the per-session ordering primitive:
due-time gating, priority preemption among due triggers, and QueueClosed
semantics on session deletion."""

import asyncio
import time

import pytest

from agent_core.core.impl.trigger.session_queue import (
    QueueClosed,
    SessionTriggerQueue,
)
from agent_core.core.trigger import Trigger


def run(coro):
    return asyncio.run(coro)


def trig(desc, *, fire_at=None, priority=50, session_id="s1"):
    return Trigger(
        fire_at=fire_at if fire_at is not None else time.time(),
        priority=priority,
        next_action_description=desc,
        session_id=session_id,
    )


class TestOrdering:
    def test_fifo_among_equal_priority_due(self, tmp_path):
        async def scenario():
            q = SessionTriggerQueue("s1")
            now = time.time() - 1
            await q.put(trig("first", fire_at=now))
            await q.put(trig("second", fire_at=now))
            a = await asyncio.wait_for(q.get(), timeout=2)
            b = await asyncio.wait_for(q.get(), timeout=2)
            assert (a.next_action_description, b.next_action_description) == (
                "first",
                "second",
            )

        run(scenario())

    def test_priority_preempts_among_due(self):
        # A user message (low priority number) beats a continuation that
        # became due earlier.
        async def scenario():
            q = SessionTriggerQueue("s1")
            await q.put(trig("continuation", fire_at=time.time() - 10, priority=5))
            await q.put(trig("user message", fire_at=time.time() - 1, priority=3))
            first = await asyncio.wait_for(q.get(), timeout=2)
            second = await asyncio.wait_for(q.get(), timeout=2)
            assert first.next_action_description == "user message"
            assert second.next_action_description == "continuation"

        run(scenario())

    def test_future_trigger_not_delivered_until_due(self):
        async def scenario():
            q = SessionTriggerQueue("s1")
            await q.put(trig("later", fire_at=time.time() + 60))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(q.get(), timeout=0.2)
            assert await q.size() == 1  # still queued, not lost

        run(scenario())

    def test_due_trigger_delivered_after_wait(self):
        async def scenario():
            q = SessionTriggerQueue("s1")
            await q.put(trig("soon", fire_at=time.time() + 0.15))
            got = await asyncio.wait_for(q.get(), timeout=2)
            assert got.next_action_description == "soon"
            assert time.time() >= got.fire_at

        run(scenario())

    def test_due_beats_earlier_but_not_yet_due(self):
        # An eligible trigger is delivered even when a not-yet-due one has
        # a smaller priority number.
        async def scenario():
            q = SessionTriggerQueue("s1")
            await q.put(trig("future-urgent", fire_at=time.time() + 60, priority=1))
            await q.put(trig("due-now", fire_at=time.time() - 1, priority=50))
            got = await asyncio.wait_for(q.get(), timeout=2)
            assert got.next_action_description == "due-now"

        run(scenario())


class TestClose:
    def test_get_raises_queue_closed_after_close(self):
        async def scenario():
            q = SessionTriggerQueue("s1")
            await q.close()
            with pytest.raises(QueueClosed):
                await q.get()

        run(scenario())

    def test_waiting_getter_unblocked_by_close(self):
        async def scenario():
            q = SessionTriggerQueue("s1")

            async def getter():
                with pytest.raises(QueueClosed):
                    await q.get()

            task = asyncio.create_task(getter())
            await asyncio.sleep(0.05)  # let the getter block
            await q.close()
            await asyncio.wait_for(task, timeout=2)

        run(scenario())

    def test_put_after_close_raises(self):
        async def scenario():
            q = SessionTriggerQueue("s1")
            await q.close()
            with pytest.raises(QueueClosed):
                await q.put(trig("late"))

        run(scenario())

    def test_close_returns_discarded_and_notifies_listener(self):
        evicted_calls = []

        class Listener:
            def on_evicted(self, evicted, replacement):
                evicted_calls.append((list(evicted), replacement))

        async def scenario():
            q = SessionTriggerQueue("s1")
            q.set_lifecycle_listener(Listener())
            t1 = trig("a", fire_at=time.time() + 60)
            t2 = trig("b", fire_at=time.time() + 120)
            await q.put(t1)
            await q.put(t2)
            discarded = await q.close()
            assert set(id(t) for t in discarded) == {id(t1), id(t2)}
            assert len(evicted_calls) == 1
            assert evicted_calls[0][1] is None
            assert await q.size() == 0

        run(scenario())


class TestIntrospection:
    def test_size_list_and_has_pending(self):
        async def scenario():
            q = SessionTriggerQueue("s1")
            assert not q.has_pending()
            await q.put(trig("a"))
            await q.put(trig("b", fire_at=time.time() + 60))
            assert q.has_pending()
            assert await q.size() == 2
            descs = {
                t.next_action_description for t in await q.list_triggers()
            }
            assert descs == {"a", "b"}

        run(scenario())
