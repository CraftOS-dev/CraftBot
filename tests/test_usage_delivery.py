"""Usage ownership, concurrency, cancellation and durable shutdown contracts."""

import asyncio
from contextvars import ContextVar
import threading
from types import SimpleNamespace
import pytest

from agent_core.core.hooks.usage import (
    dispatch_usage,
    drain_usage,
    to_thread_with_usage,
)
from agent_core.core.hooks.types import UsageEventData


@pytest.mark.parametrize("kind", ["image", "video"])
def test_generation_wrappers_share_usage_context_and_delivery(kind):
    from agent_core.core.impl.image_gen.interface import ImageGenInterface
    from agent_core.core.impl.video_gen.interface import VideoGenInterface

    cls = ImageGenInterface if kind == "image" else VideoGenInterface
    iface = cls.__new__(cls)
    session = ContextVar("generation_session")
    events = []

    async def hook(event):
        events.append((session.get(), event))

    iface._report_usage = hook

    def generate(**kwargs):
        iface._report_usage_async(
            provider="test", model=kind, input_tokens=4, output_tokens=5
        )
        return ["synthetic"]

    setattr(iface, "generate_" + kind, generate)

    async def run():
        session.set("owner")
        result = await getattr(iface, "generate_" + kind + "_async")()
        assert result == ["synthetic"]

    asyncio.run(run())
    assert len(events) == 1
    assert events[0][0] == "owner"
    assert events[0][1].input_tokens == 4


def test_workers_deliver_once_in_their_request_context_on_the_owner_loop():
    session = ContextVar("test_session")
    events = []

    async def run():
        owner = asyncio.get_running_loop()

        async def hook(value):
            assert asyncio.get_running_loop() is owner
            await asyncio.sleep(0)
            events.append((session.get(), value))

        async def request(key):
            token = session.set(key)
            try:
                await to_thread_with_usage(dispatch_usage, hook, key)
                assert (key, key) in events  # delivery precedes successful return
            finally:
                session.reset(token)

        await asyncio.gather(*(request(str(i)) for i in range(20)))
        await drain_usage()

    asyncio.run(run())
    assert sorted(events) == sorted((str(i), str(i)) for i in range(20))


def test_cancelled_request_worker_and_usage_are_drained_before_shutdown():
    entered, release = threading.Event(), threading.Event()
    events = []

    async def hook(value):
        events.append(value)

    def worker():
        entered.set()
        assert release.wait(5)
        dispatch_usage(hook, "completed")

    async def run():
        task = asyncio.create_task(to_thread_with_usage(worker))
        await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        release.set()
        await drain_usage()

    asyncio.run(run())
    assert events == ["completed"]


def test_failed_hook_is_observable_and_is_not_retried(caplog):
    calls = []

    async def hook(event):
        calls.append(event)
        raise RuntimeError("storage unavailable")

    async def run():
        await to_thread_with_usage(dispatch_usage, hook, "one")
        await drain_usage()

    asyncio.run(run())
    assert calls == ["one"]
    assert "Usage delivery failed" in caplog.text


def test_sync_and_async_reporter_calls_across_threads_flush_without_loss():
    from app.usage.reporter import UsageReporter

    saved = []
    reporter = UsageReporter(
        SimpleNamespace(
            insert_events_batch=lambda batch: saved.extend(batch) or len(batch)
        )
    )

    def report(i):
        dispatch_usage(reporter.report, UsageEventData("vlm", "test", str(i), i, 1))

    async def run():
        await asyncio.gather(*(asyncio.to_thread(report, i) for i in range(30)))
        await reporter.shutdown()

    asyncio.run(run())
    assert sorted(event.model for event in saved) == sorted(str(i) for i in range(30))
    assert reporter.get_stats()["buffered"] == 0


def test_shutdown_can_drain_usage_owned_by_another_running_loop():
    entered, release = threading.Event(), threading.Event()
    delivered, errors = [], []

    async def hook(event):
        delivered.append(event)

    def worker():
        entered.set()
        assert release.wait(5)
        dispatch_usage(hook, "foreign")

    def other_loop():
        try:
            asyncio.run(to_thread_with_usage(worker))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=other_loop)
    thread.start()
    try:
        assert entered.wait(5)

        async def run():
            drain = asyncio.create_task(drain_usage())
            await asyncio.sleep(0)  # let shutdown observe the in-flight foreign task
            release.set()
            await asyncio.wait_for(drain, 2)

        asyncio.run(run())
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert not errors
    assert delivered == ["foreign"]
