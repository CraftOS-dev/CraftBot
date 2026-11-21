"""Session loop failure logging (issue #224, Phase 0).

Covers the three Phase 0 items: the runtime summary logged once at startup,
boot success/failure brackets, and the session (trigger consumer) loop's
exits — including the regression where a turn error containing braces
crashed loguru inside the failure handler and killed the loop silently.

No test sleeps for timing: loops are driven by events, and every wait has a
generous hang guard only.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from loguru import logger

from agent_core.core.trigger import Trigger
from app.startup_diagnostics import format_exception_details
from app.triggers.runtime import SessionRuntimeManager

SECRET = "sk-test-SENTINEL-0123456789"
HANG_GUARD_S = 10


@pytest.fixture
def log_lines():
    """Capture loguru output synchronously (no enqueue) as plain text.

    diagnose/backtrace are on, as in the app's own sinks, so a test proves
    that nothing reaching the log can expand local variable values.
    """
    lines: list[str] = []
    sink = logger.add(
        lambda m: lines.append(str(m)),
        level="DEBUG",
        format="{level}|{message}\n{exception}",
        backtrace=True,
        diagnose=True,
    )
    try:
        yield lines
    finally:
        logger.remove(sink)


def _joined(lines: list[str]) -> str:
    return "\n".join(lines)


def _fail_holding_a_secret():
    api_key = SECRET  # noqa: F841 — a local the traceback must not reveal
    raise RuntimeError("provider rejected the request")


def test_exception_details_include_the_traceback_but_no_local_values(log_lines):
    with pytest.raises(RuntimeError) as excinfo:
        _fail_holding_a_secret()
    text = format_exception_details(excinfo.value)
    assert "Traceback (most recent call last)" in text
    assert "_fail_holding_a_secret" in text
    assert "RuntimeError: provider rejected the request" in text
    assert SECRET not in text

    # Logged through a diagnose=True sink, as the app does: still no secret.
    logger.error(f"failed: {text}")
    assert SECRET not in _joined(log_lines)


class _Service:
    """Minimal TriggerService stand-in recording settlement."""

    def __init__(self, fail_claim: bool = False):
        self.fail_claim = fail_claim
        self.acked: list[str] = []
        self.nacked: list[tuple[str, str]] = []

    def claim(self, trig):
        if self.fail_claim:
            raise RuntimeError("store unavailable")

    async def ack(self, trig):
        self.acked.append(trig.next_action_description)

    async def nack(self, trig, error):
        self.nacked.append((trig.next_action_description, error))

    def on_evicted(self, *args):
        pass


def _trigger(desc: str, session_id: str = "s1") -> Trigger:
    return Trigger(time.time(), 1, desc, session_id=session_id, source="test")


def test_turn_error_with_braces_is_logged_nacked_and_the_loop_survives(log_lines):
    """Regression: `exc_info=True` made loguru str.format() the message, so
    an error text containing braces raised KeyError inside the handler — the
    loop died, the rows were never nacked, and nothing was logged."""

    async def scenario():
        done = asyncio.Event()
        bad_started = asyncio.Event()
        ran: list[str] = []

        async def react(trig):
            ran.append(trig.next_action_description)
            if trig.next_action_description == "bad":
                bad_started.set()
                raise RuntimeError("bad {'id': 1}")
            done.set()

        runtime = SessionRuntimeManager(react)
        service = _Service()
        runtime.bind_service(service)
        await runtime.start()
        await runtime.dispatch(_trigger("bad"))
        # Dispatch the second trigger only once the first is claimed, so the
        # two are not aggregated into one turn.
        await asyncio.wait_for(bad_started.wait(), HANG_GUARD_S)
        await runtime.dispatch(_trigger("good"))
        await asyncio.wait_for(done.wait(), HANG_GUARD_S)
        loop_alive = not runtime._loops["s1"].done()
        await runtime.stop()
        return ran, service, loop_alive

    ran, service, loop_alive = asyncio.run(scenario())
    assert ran == ["bad", "good"]
    assert loop_alive
    assert [desc for desc, _ in service.nacked] == ["bad"]
    assert service.acked == ["good"]

    failed = [line for line in log_lines if "Turn failed for s1" in line]
    assert len(failed) == 1
    assert "bad {'id': 1}" in failed[0]
    assert "Traceback (most recent call last)" in failed[0]
    assert "exited unexpectedly" not in _joined(log_lines)


def test_stop_finalizer_error_with_braces_is_logged_and_the_loop_survives(
    log_lines,
):
    """Regression: the force-stop path's finalize-failure log had the same
    `exc_info=True` + f-string bug. A finalizer error containing braces
    raised KeyError inside the handler and killed the session loop, so the
    next trigger for that session never ran."""

    async def scenario():
        in_turn = asyncio.Event()
        after_ran = asyncio.Event()
        ran: list[str] = []

        async def react(trig):
            ran.append(trig.next_action_description)
            if trig.next_action_description == "after":
                after_ran.set()
                return
            in_turn.set()
            await asyncio.Event().wait()  # runs until the stop cancels it

        async def failing_finalizer(session_id):
            api_key = SECRET  # noqa: F841 — must not reach the log
            raise RuntimeError("finalize {'k': 1}")

        runtime = SessionRuntimeManager(react)
        service = _Service()
        runtime.bind_service(service)
        runtime.set_stop_finalizer(failing_finalizer)
        await runtime.start()
        await runtime.dispatch(_trigger("long"))
        await asyncio.wait_for(in_turn.wait(), HANG_GUARD_S)

        # Returns once the stop has fully settled (finalizer included).
        stopped = await asyncio.wait_for(runtime.request_stop("s1"), HANG_GUARD_S)
        loop_alive_after_stop = not runtime._loops["s1"].done()

        await runtime.dispatch(_trigger("after"))
        await asyncio.wait_for(after_ran.wait(), HANG_GUARD_S)
        await runtime.stop()
        return stopped, loop_alive_after_stop, ran, service

    stopped, loop_alive, ran, service = asyncio.run(scenario())
    assert stopped is True
    assert loop_alive
    assert ran == ["long", "after"]
    # A user stop acks the stopped turn's rows; the next turn acks normally.
    assert service.acked == ["long", "after"]
    assert service.nacked == []

    text = _joined(log_lines)
    failed = [line for line in log_lines if "Stop finalize failed for s1" in line]
    assert len(failed) == 1
    assert failed[0].startswith("ERROR|")
    assert "finalize {'k': 1}" in failed[0]
    assert "Traceback (most recent call last)" in failed[0]
    assert "failing_finalizer" in failed[0]
    assert "exited unexpectedly" not in text
    assert SECRET not in text
