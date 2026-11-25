"""Startup and lifecycle diagnostics (issue #224, Phase 0).

Covers the three Phase 0 items: the runtime summary logged once at startup,
boot success/failure brackets, and the session (trigger consumer) loop's
exits — including the regression where a turn error containing braces
crashed loguru inside the failure handler and killed the loop silently.

No test sleeps for timing: loops are driven by events, and every wait has a
generous hang guard only.
"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from agent_core.core.trigger import Trigger
from app.startup_diagnostics import (
    describe_runtime,
    format_exception_details,
    format_runtime_summary,
    log_runtime_info,
)
from app.triggers.runtime import SessionRuntimeManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


# ───────────────────────── Runtime summary ──────────────────────────────────


def test_runtime_summary_reports_the_effective_python_version():
    info = describe_runtime()
    assert info["python"] == platform.python_version()
    assert info["implementation"] == platform.python_implementation()
    assert set(info) == {
        "python",
        "implementation",
        "os",
        "arch",
        "frozen",
        "wait_for_shim",
        "nest_asyncio",
    }


def test_runtime_info_is_logged_once_as_one_line(log_lines):
    log_runtime_info(logger)
    startup = [line for line in log_lines if "[STARTUP] Runtime:" in line]
    assert len(startup) == 1
    assert f"python={platform.python_version()}" in startup[0]
    assert startup[0].startswith("INFO|")


def test_runtime_summary_reflects_shim_and_nest_asyncio_state(monkeypatch):
    async def _compat_wait_for(fut, timeout):  # same name the shim uses
        return await fut

    monkeypatch.setattr(asyncio, "wait_for", _compat_wait_for)
    monkeypatch.setattr(asyncio, "_nest_patched", True, raising=False)
    info = describe_runtime()
    assert info["wait_for_shim"] == "active"
    assert info["nest_asyncio"] == "applied"

    async def wait_for(fut, timeout):
        return await fut

    monkeypatch.setattr(asyncio, "wait_for", wait_for)
    monkeypatch.delattr(asyncio, "_nest_patched", raising=False)
    info = describe_runtime()
    assert info["wait_for_shim"] == "inactive"
    assert info["nest_asyncio"] == "not applied"


def test_runtime_summary_contains_no_environment_paths_or_identity(monkeypatch):
    monkeypatch.setenv("CRAFTBOT_TEST_SECRET", SECRET)
    summary = format_runtime_summary(describe_runtime())
    assert SECRET not in summary
    assert sys.executable not in summary
    assert sys.prefix not in summary
    assert str(Path.home()) not in summary
    node = platform.node()
    if node:
        assert node not in summary


# ───────────────────────── Exception rendering ──────────────────────────────


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


# ───────────────────────── Boot brackets ────────────────────────────────────


def _boot_stub(sequence):
    from app.agent_base import AgentBase

    stub = SimpleNamespace(_boot_sequence=sequence)
    return lambda **kw: AgentBase.boot(stub, **kw)


def test_boot_logs_start_and_finish_on_success(log_lines):
    calls = []

    async def sequence(*, verbose, phase):
        calls.append(verbose)

    asyncio.run(_boot_stub(sequence)(verbose=False))
    text = _joined(log_lines)
    assert calls == [False]
    assert "[BOOT] Boot sequence started" in text
    assert "[BOOT] Boot sequence finished in" in text
    assert "[BOOT] Boot failed" not in text


def test_boot_failure_names_the_failing_component_and_propagates(log_lines):
    """Runs the real _boot_sequence (only the components are stubbed), so its
    step markers must feed the phase boot() reports. The component raises
    from a frame holding a secret, with braces in its message."""
    from unittest.mock import AsyncMock

    from app.agent_base import AgentBase

    error = RuntimeError("mcp config unreadable {'path': 1}")

    async def failing_mcp():
        api_key = SECRET  # noqa: F841 — must not reach the log
        raise error

    stub = SimpleNamespace(
        _initialize_config_watcher=AsyncMock(),
        _initialize_mcp=AsyncMock(side_effect=failing_mcp),
    )
    stub._boot_sequence = lambda **kw: AgentBase._boot_sequence(stub, **kw)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(AgentBase.boot(stub, verbose=False))
    assert excinfo.value is error
    stub._initialize_config_watcher.assert_awaited_once()

    text = _joined(log_lines)
    failed = [line for line in log_lines if "[BOOT] Boot failed" in line]
    assert len(failed) == 1
    assert failed[0].startswith("ERROR|")
    assert "during 'Connecting to MCP servers'" in failed[0]
    assert "RuntimeError: mcp config unreadable {'path': 1}" in failed[0]
    assert "Traceback (most recent call last)" in failed[0]
    assert "failing_mcp" in failed[0]
    assert "[BOOT] Boot sequence finished" not in text
    assert SECRET not in text


def test_boot_cancellation_propagates_without_a_failure_log(log_lines):
    async def sequence(*, verbose, phase):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_boot_stub(sequence)(verbose=False))
    text = _joined(log_lines)
    assert "[BOOT] Boot failed" not in text
    assert "[BOOT] Boot sequence finished" not in text


# ───────────────────────── Session (trigger consumer) loop ──────────────────


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


async def _settle_loop(task: asyncio.Task) -> None:
    """Wait for a loop task to finish, then let its done-callbacks run."""
    await asyncio.wait({task}, timeout=HANG_GUARD_S)
    assert task.done(), "session loop did not finish"
    await asyncio.sleep(0)


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


def test_normal_shutdown_logs_cancellation_and_no_crash(log_lines):
    async def scenario():
        done = asyncio.Event()

        async def react(trig):
            done.set()

        runtime = SessionRuntimeManager(react)
        runtime.bind_service(_Service())
        await runtime.start()
        await runtime.dispatch(_trigger("work"))
        await asyncio.wait_for(done.wait(), HANG_GUARD_S)
        task = runtime._loops["s1"]
        await runtime.stop()
        await asyncio.sleep(0)
        return task

    task = asyncio.run(scenario())
    assert task.cancelled()
    text = _joined(log_lines)
    assert "[SessionRuntime] Loop started for session s1" in text
    assert text.count("[SessionRuntime] Loop cancelled for session s1") == 1
    assert "exited unexpectedly" not in text
    assert "[SessionRuntime] Stopped" in text


def test_removing_a_session_logs_its_loop_cancellation(log_lines):
    async def scenario():
        done = asyncio.Event()

        async def react(trig):
            done.set()

        runtime = SessionRuntimeManager(react)
        await runtime.start()
        await runtime.dispatch(_trigger("work", session_id="s2"))
        await asyncio.wait_for(done.wait(), HANG_GUARD_S)
        await runtime.remove_session("s2")
        await asyncio.sleep(0)
        await runtime.stop()

    asyncio.run(scenario())
    assert "[SessionRuntime] Loop cancelled for session s2" in _joined(log_lines)


def test_an_unexpected_loop_exception_is_logged_and_still_propagates(log_lines):
    """claim() runs outside the turn's try: an error there ends the loop. It
    used to vanish (stop() swallows it); it must now be logged, and the task
    must still carry the original exception."""

    async def scenario():
        async def react(trig):  # never reached
            raise AssertionError("turn should not run")

        runtime = SessionRuntimeManager(react)
        runtime.bind_service(_Service(fail_claim=True))
        await runtime.start()
        await runtime.dispatch(_trigger("work"))
        task = runtime._loops["s1"]
        await _settle_loop(task)
        await runtime.stop()
        return task

    task = asyncio.run(scenario())
    assert not task.cancelled()
    assert isinstance(task.exception(), RuntimeError)
    crashed = [line for line in log_lines if "exited unexpectedly" in line]
    assert len(crashed) == 1
    assert crashed[0].startswith("ERROR|")
    assert "Loop for session s1" in crashed[0]
    assert "RuntimeError: store unavailable" in crashed[0]
    assert "Traceback (most recent call last)" in crashed[0]


def test_a_crashed_loop_restarts_on_the_next_trigger(log_lines):
    """Behaviour is unchanged by the logging: a dead loop is replaced on the
    next dispatch, as before."""

    async def scenario():
        done = asyncio.Event()
        service = _Service(fail_claim=True)

        async def react(trig):
            done.set()

        runtime = SessionRuntimeManager(react)
        runtime.bind_service(service)
        await runtime.start()
        await runtime.dispatch(_trigger("first"))
        await _settle_loop(runtime._loops["s1"])
        service.fail_claim = False
        await runtime.dispatch(_trigger("second"))
        await asyncio.wait_for(done.wait(), HANG_GUARD_S)
        await runtime.stop()
        return service

    service = asyncio.run(scenario())
    assert service.acked == ["second"]


# ───────────────────────── Entry point (subprocess) ─────────────────────────

_MAIN_SCRIPT = textwrap.dedent(
    """
    import asyncio, sys
    import app.main as m
    from loguru import logger

    logger.add(sys.stdout, level="DEBUG", format="{level}|{message}",
               backtrace=True, diagnose=True)

    SECRET = sys.argv[1]
    m._initial_settings = lambda: (
        "openai", SECRET, None, None, None, None, None, None, True
    )
    m._parse_cli_args = lambda: {}

    class Boom(Exception):
        pass

    def failing_agent(**kwargs):
        raise Boom("constructor failed")

    m.AgentBase = failing_agent
    try:
        asyncio.run(m.main_async())
    except Boom:
        print("PROPAGATED Boom")
    """
)


def test_main_logs_runtime_once_and_construction_failure_without_secrets(tmp_path):
    """Run the real entry module in a child process: importing app.main has
    process-wide side effects (warning filters, SSL shims) that must not leak
    into this test session."""
    env = dict(os.environ, CRAFTBOT_HOME=str(tmp_path), PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", _MAIN_SCRIPT, SECRET],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    out = result.stdout + result.stderr
    assert "PROPAGATED Boom" in result.stdout, out[-3000:]
    assert result.stdout.count("[STARTUP] Runtime:") == 1
    assert f"python={platform.python_version()}" in result.stdout
    assert "[STARTUP] Agent construction failed: Boom: constructor failed" in out
    assert "Traceback (most recent call last)" in result.stdout
    assert SECRET not in out
