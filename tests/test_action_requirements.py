# -*- coding: utf-8 -*-
"""An action's pip requirements are settled once per process, off the loop.

Every web_fetch / web_search call used to run ``pip show`` on the event loop
for a package whose import name differs from its pip name (beautifulsoup4,
google-api-python-client): ~1.5 s per call with the UI frozen, and a batch of
ten parallel calls started 1.5 s apart (observed 2026-11-16).
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from agent_core.core.impl.action import executor


def test_a_requirement_is_checked_once_per_process(monkeypatch):
    monkeypatch.setattr(executor, "_SETTLED_REQUIREMENTS", set())
    calls = []
    monkeypatch.setattr(
        executor.subprocess, "check_call", lambda cmd, **kw: calls.append(cmd)
    )

    for _ in range(3):
        executor._ensure_requirements(["not-importable-pkg", "DDGS"])

    # One pip show for the package; the class-like name is never a pip call.
    assert [cmd[3:5] for cmd in calls] == [["show", "--quiet"]]


def test_a_failed_install_is_tried_again(monkeypatch):
    monkeypatch.setattr(executor, "_SETTLED_REQUIREMENTS", set())
    calls = []

    def fail(cmd, **kw):
        calls.append(cmd[3])
        raise OSError("offline")

    monkeypatch.setattr(executor.subprocess, "check_call", fail)
    executor._ensure_requirements(["not-importable-pkg"])
    executor._ensure_requirements(["not-importable-pkg"])
    assert calls == ["show", "install", "show", "install"]


def test_requirements_are_checked_off_the_event_loop(monkeypatch):
    threads = []
    monkeypatch.setattr(
        executor,
        "_ensure_requirements",
        lambda requirements: threads.append(threading.current_thread()),
    )

    async def run_action(*args):
        return {"status": "success"}

    monkeypatch.setattr(executor, "_atomic_action_internal_async", run_action)
    action = SimpleNamespace(
        name="web_fetch",
        code="",
        execution_mode="internal",
        mode="CLI",
        requirements=["beautifulsoup4"],
        timeout=None,
    )

    result = asyncio.run(executor.ActionExecutor().execute_atomic_action(action, {}))
    assert result == {"status": "success"}
    assert threads and threads[0] is not threading.main_thread()
