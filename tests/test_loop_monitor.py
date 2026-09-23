"""Tests for the UI layer's event-loop stall detector."""

import asyncio
import threading
import time

from app.ui_layer.diagnostics.loop_monitor import (
    ORIGIN_OUTSIDE_UI_LAYER,
    LoopStallMonitor,
)


def _block_for(seconds: float) -> None:
    time.sleep(seconds)


def _run_loop_in_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def _start_monitor(loop, **kwargs) -> LoopStallMonitor:
    monitor = LoopStallMonitor(**kwargs)
    started = threading.Event()

    def start() -> None:
        monitor.start()
        started.set()

    loop.call_soon_threadsafe(start)
    assert started.wait(2)
    return monitor


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_records_a_blocking_callback_with_duration_and_stack():
    loop, thread = _run_loop_in_thread()
    monitor = _start_monitor(loop, threshold=0.1, interval=0.02)
    try:
        time.sleep(0.2)  # let the monitor see a healthy loop first
        loop.call_soon_threadsafe(_block_for, 0.45)

        assert _wait_for(lambda: monitor.snapshot()["stalls"] == 1)
        snapshot = monitor.snapshot()
        stall = snapshot["recent"][0]

        assert stall["durationMs"] >= 350
        assert stall["origin"] == ORIGIN_OUTSIDE_UI_LAYER
        assert any("in _block_for" in frame for frame in stall["samples"][0])
        assert snapshot["byOrigin"] == {ORIGIN_OUTSIDE_UI_LAYER: 1}
        assert snapshot["buckets"]["<1s"] == 1
    finally:
        monitor.stop()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)


def test_healthy_loop_records_nothing():
    loop, thread = _run_loop_in_thread()
    monitor = _start_monitor(loop, threshold=0.2, interval=0.02)
    try:
        time.sleep(0.5)
        snapshot = monitor.snapshot()
        assert snapshot["running"] is True
        assert snapshot["stalls"] == 0
        assert snapshot["recent"] == []
    finally:
        monitor.stop()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
