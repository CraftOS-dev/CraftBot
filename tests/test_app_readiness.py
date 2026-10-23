"""Readiness deadlines use wall time and don't block or outlive a dead child."""

import asyncio
from types import SimpleNamespace
import pytest
from app.agent_app.manager import AgentAppManager


def test_hung_probe_obeys_total_deadline_and_keeps_loop_responsive():
    async def run():
        manager = AgentAppManager.__new__(AgentAppManager)
        ticks = []

        async def probe():
            await asyncio.Event().wait()

        async def tick():
            for _ in range(5):
                ticks.append(True)
                await asyncio.sleep(0.01)

        start = asyncio.get_running_loop().time()
        result, _ = await asyncio.gather(manager._probe_ready(probe, 0.15), tick())
        assert result is False
        assert 0.12 <= asyncio.get_running_loop().time() - start < 0.5
        assert len(ticks) == 5

    asyncio.run(run())


@pytest.mark.parametrize("strategy", ["tcp", "http_get", "process_alive"])
def test_dead_process_is_not_probed_or_retried(strategy):
    async def run():
        manager = AgentAppManager.__new__(AgentAppManager)
        assert not await manager._check_health_with_strategy(
            {"strategy": strategy, "url": "http://127.0.0.1:1"},
            1,
            SimpleNamespace(poll=lambda: 7),
            timeout=10,
        )

    asyncio.run(run())


def test_cancellation_reaches_active_probe():
    async def run():
        manager = AgentAppManager.__new__(AgentAppManager)
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def probe():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(manager._probe_ready(probe, 10))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(run())


def test_healthy_probe_slower_than_half_a_second_can_finish_within_deadline():
    async def run():
        manager = AgentAppManager.__new__(AgentAppManager)

        async def probe():
            await asyncio.sleep(0.6)
            return True

        assert await manager._probe_ready(probe, 1)

    asyncio.run(run())


def test_process_exit_cancels_an_inflight_probe():
    async def run():
        manager = AgentAppManager.__new__(AgentAppManager)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        status = [None]

        async def probe():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(
            manager._probe_ready(probe, 10, SimpleNamespace(poll=lambda: status[0]))
        )
        await entered.wait()
        status[0] = 1
        assert not await asyncio.wait_for(task, 1)
        assert cancelled.is_set()

    asyncio.run(run())
