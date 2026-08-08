"""Test-time logging: capture LLM calls, format the agent's event stream,
and write per-test log files under ``tests/e2e/logs/``.

The recording itself uses ``record_llm_calls`` — an async context manager
that wraps both LLM methods (regular and session-cached). ``run_scenario``
in [helpers.py](tests/e2e/_harness/helpers.py) enters it before driving
the agent so every prompt + response gets stashed on
``agent._test_llm_calls`` for ``save_trace_log`` to render afterwards.

Public API
----------

- ``record_llm_calls(agent)`` — async context manager. Captures every
  LLM call into ``agent._test_llm_calls`` for the duration of the block.
- ``format_agent_trace(agent)`` — chronological merge of the main +
  per-task event streams as a single human-readable string.
- ``save_trace_log(agent, *, test_name=None, extra={})`` — write a
  ``.log`` file containing the trace plus the full LLM transcript
  (system prompt, user prompt, response per call). Returns the path.
"""

from __future__ import annotations

import datetime
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from app.agent_base import AgentBase


# Logs live at ``tests/e2e/logs/``. This file is in
# ``tests/e2e/_harness/``, so go up one more level than the module.
TEST_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


@asynccontextmanager
async def record_llm_calls(agent: AgentBase):
    """Capture every LLM call the agent makes during the ``with`` block.

    Wraps both ``generate_response_async`` (conversation-mode path) and
    ``generate_response_with_session_async`` (task-mode path with session
    caching). Each call is appended to ``agent._test_llm_calls`` as::

        {"ts": float, "path": str, "system_prompt": str,
         "user_prompt": str, "response": str}

    Originals are restored on exit so the agent stays reusable.

    This is the only seam through which we can see the actual prompts —
    they're not written to the event stream or to disk anywhere else.
    """
    agent._test_llm_calls = []
    orig_gen = agent.llm.generate_response_async
    orig_session_gen = getattr(agent.llm, "generate_response_with_session_async", None)

    async def _spy_gen(system_prompt=None, user_prompt=None, log_response=True):
        resp = await orig_gen(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            log_response=log_response,
        )
        agent._test_llm_calls.append(
            {
                "ts": time.time(),
                "path": "generate_response_async",
                "system_prompt": system_prompt or "",
                "user_prompt": user_prompt or "",
                "response": str(resp),
            }
        )
        return resp

    agent.llm.generate_response_async = _spy_gen

    if orig_session_gen is not None:

        async def _spy_session(*args, **kwargs):
            resp = await orig_session_gen(*args, **kwargs)
            agent._test_llm_calls.append(
                {
                    "ts": time.time(),
                    "path": "generate_response_with_session_async",
                    "system_prompt": kwargs.get("system_prompt_for_new_session", "")
                    or "",
                    "user_prompt": kwargs.get("user_prompt", "") or "",
                    "response": str(resp),
                }
            )
            return resp

        agent.llm.generate_response_with_session_async = _spy_session

    try:
        yield
    finally:
        agent.llm.generate_response_async = orig_gen
        if orig_session_gen is not None:
            agent.llm.generate_response_with_session_async = orig_session_gen


@asynccontextmanager
async def record_action_calls(agent: AgentBase):
    """Capture every action the agent invokes during the ``with`` block.

    Wraps ``agent.action_manager.execute_action`` and records the action's
    name on ``agent._test_actions_called`` (a list, in invocation order).

    Why not just walk the event stream? Task-mode action_start events are
    written to the TASK stream, not the main stream. When a task ends,
    the task stream's events are flushed and the stream may be removed
    from ``event_stream_manager._task_streams``, so reading after the
    fact misses everything inside the task. This spy captures every
    invocation as it happens, so it survives the task lifecycle.
    """
    agent._test_actions_called = []
    orig = agent.action_manager.execute_action

    async def _spy(action, *args, **kwargs):
        try:
            agent._test_actions_called.append(action.name)
        except Exception:
            pass
        return await orig(action, *args, **kwargs)

    agent.action_manager.execute_action = _spy
    try:
        yield
    finally:
        agent.action_manager.execute_action = orig


def actions_called(agent: AgentBase) -> list[str]:
    """List of action names the agent invoked during the scenario, in
    invocation order. Populated by ``record_action_calls`` (entered by
    ``run_scenario``)."""
    return list(getattr(agent, "_test_actions_called", []) or [])


def assert_action_called(
    agent: AgentBase,
    expected: str,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Pass iff ``expected`` is among the actions the agent invoked.

    Always writes a per-test log file first (so the trace is on disk for
    inspection whether the assertion passes or fails), prints the log
    path, then asserts. The failure message includes the full trace and
    the list of actions actually called.
    """
    called = actions_called(agent)
    log_extra = {"actions_called": called, "expecting": expected}
    if extra:
        log_extra.update(extra)
    log_path = save_trace_log(agent, extra=log_extra)
    print(f"\nagent trace: {log_path}")
    assert expected in called, (
        f"agent never called {expected!r}. Actions called: {called}. "
        f"trace: {log_path}\n\n" + format_agent_trace(agent)
    )


def format_agent_trace(agent: AgentBase, *, limit_per_stream: int = 200) -> str:
    """Chronological, human-readable timeline of everything the agent
    recorded during the run.

    Walks the in-memory main stream + per-task streams (``run_scenario``
    clears these at the start of each test, so output is scoped to THIS
    run — not polluted by prior runs the way the on-disk EVENT.md would
    be).

    Each line:  ``HH:MM:SS  [STREAM]  KIND  SEVERITY  message``
    """
    streams: list[tuple[str, Any]] = []
    for sid, stream in agent.event_stream_manager.get_all_streams_with_ids():
        label = "main" if sid == "main" else f"session:{sid[:8]}"
        streams.append((label, stream))

    records: list[tuple[str, Any]] = []
    for label, stream in streams:
        for rec in (stream.tail_events or [])[-limit_per_stream:]:
            records.append((label, rec))
    records.sort(key=lambda lr: lr[1].ts)

    lines: list[str] = []
    for label, rec in records:
        ev = rec.event
        ts = ev.ts.strftime("%H:%M:%S")
        msg = (ev.message or "").replace("\n", " | ")
        if len(msg) > 240:
            msg = msg[:237] + "..."
        repeat = f" ×{rec.repeat_count}" if rec.repeat_count > 1 else ""
        lines.append(
            f"{ts}  [{label:14}]  {ev.kind:18}  {ev.severity:5}  {msg}{repeat}"
        )

    return "\n".join(lines) if lines else "(no events recorded)"


def _resolve_test_name(test_name: str | None) -> str:
    """Pick a filename-safe test name, defaulting to pytest's current test."""
    if not test_name:
        current = os.environ.get("PYTEST_CURRENT_TEST", "")
        # PYTEST_CURRENT_TEST looks like: "tests/e2e/file.py::test_func (call)"
        if "::" in current:
            test_name = current.split("::", 1)[1].split(" ", 1)[0]
        else:
            test_name = "trace"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", test_name).strip("_") or "trace"


def save_trace_log(
    agent: AgentBase,
    *,
    test_name: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a per-test log file containing the agent's event trace +
    every LLM call captured during the run.

    File path:
        ``tests/e2e/logs/<test_name>_<UTC YYYYMMDD_HHMMSS>.log``

    Test name auto-derived from ``PYTEST_CURRENT_TEST`` if not given.
    ``extra`` becomes "# KEY: value" header lines.

    Returns the written path so tests can print it or attach to a
    failure message.
    """
    TEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    name = _resolve_test_name(test_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    path = TEST_LOG_DIR / f"{name}_{stamp}.log"

    llm_calls = getattr(agent, "_test_llm_calls", []) or []

    parts: list[str] = []
    parts.append(f"# test: {name}")
    parts.append(f"# written: {now.isoformat()}")
    parts.append(f"# llm_calls: {len(llm_calls)}")
    if extra:
        for k, v in extra.items():
            parts.append(f"# {k}: {v}")
    parts.append("")
    parts.append("=" * 78)
    parts.append("AGENT TRACE (event streams; chronological)")
    parts.append("=" * 78)
    parts.append(format_agent_trace(agent))

    if llm_calls:
        parts.append("")
        parts.append("=" * 78)
        parts.append(
            f"LLM TRANSCRIPT ({len(llm_calls)} call{'s' if len(llm_calls) != 1 else ''})"
        )
        parts.append("=" * 78)
        for i, c in enumerate(llm_calls, 1):
            ts = datetime.datetime.fromtimestamp(
                c["ts"], datetime.timezone.utc
            ).strftime("%H:%M:%S")
            parts.append("")
            parts.append(f"--- call {i}/{len(llm_calls)} @ {ts}  via {c['path']} ---")
            parts.append("")
            parts.append(f"SYSTEM PROMPT ({len(c['system_prompt'])} chars):")
            parts.append(c["system_prompt"] or "(empty)")
            parts.append("")
            parts.append(f"USER PROMPT ({len(c['user_prompt'])} chars):")
            parts.append(c["user_prompt"] or "(empty)")
            parts.append("")
            parts.append(f"RESPONSE ({len(c['response'])} chars):")
            parts.append(c["response"] or "(empty)")

    path.write_text("\n".join(parts), encoding="utf-8")
    return path
