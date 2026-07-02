# -*- coding: utf-8 -*-
"""
Tests for the LLM-call capture substrate (issue #322, P1).

Covers the storage layer and the interface-level capture flow: the per-call
context (`_llm_call_ctx`) set at the public entry must reach the capture
chokepoint (`_call_log_to_db`), survive `asyncio.to_thread`, and stay isolated
across concurrent calls.
"""

import asyncio
import os
import tempfile

from agent_core.core.impl.llm.interface import LLMInterface
from app.usage.llm_call_storage import LLMCallStorage, LLMCallRow


def _make_storage():
    db = os.path.join(tempfile.mkdtemp(), "llm_calls.db")
    return LLMCallStorage(db_path=db, max_rows=3)


def test_storage_insert_recent_and_cap():
    s = _make_storage()
    for i in range(5):
        s.insert(
            LLMCallRow(
                provider="gemini",
                model="gemini-2.5-pro",
                system_prompt="sys",
                user_prompt=f"u{i}",
                response="{}",
                status="success",
                input_tokens=100 + i,
                output_tokens=10,
                cached_tokens=50,
                latency_ms=1234,
                prompt_name="SELECT_ACTION_IN_TASK",
                call_type="action_selection",
            )
        )
    # max_rows=3 → oldest pruned
    assert s.count() == 3
    newest = s.recent(1)[0]
    assert newest["user_prompt"] == "u4"
    assert newest["prompt_name"] == "SELECT_ACTION_IN_TASK"
    assert newest["cached_tokens"] == 50


def _interface_with_sink(captured):
    return LLMInterface(
        provider="gemini",
        model="gemini-2.5-pro",
        deferred=True,
        record_llm_call=lambda r: captured.append(r),
    )


def test_capture_reads_context_and_latency():
    captured = []
    llm = _interface_with_sink(captured)
    llm._begin_call(
        prompt_name="SELECT_ACTION_IN_TASK",
        call_type="action_selection",
        task_id="task-9",
    )
    llm._call_log_to_db(
        "sys", "user", '{"action":"task_start"}', "success", 1200, 30,
        cached_tokens=900,
    )
    assert len(captured) == 1
    rec = captured[0]
    assert rec.prompt_name == "SELECT_ACTION_IN_TASK"
    assert rec.call_type == "action_selection"
    assert rec.task_id == "task-9"
    assert rec.input_tokens == 1200 and rec.cached_tokens == 900
    assert rec.latency_ms >= 0


def test_context_survives_to_thread_and_isolates_concurrency():
    captured = []
    llm = _interface_with_sink(captured)

    def worker():
        llm._call_log_to_db("s", "u", "resp", "success", 10, 5, cached_tokens=3)

    async def main():
        llm._begin_call(prompt_name="ROUTE_TO_SESSION")
        await asyncio.to_thread(worker)

        async def one(name):
            llm._begin_call(prompt_name=name)
            await asyncio.to_thread(worker)

        await asyncio.gather(one("A"), one("B"))

    asyncio.run(main())
    names = [r.prompt_name for r in captured]
    assert names[0] == "ROUTE_TO_SESSION"
    assert set(names[1:]) == {"A", "B"}  # no cross-call clobber


def test_capture_disabled_when_no_hook():
    # No record_llm_call hook → _call_log_to_db must not raise.
    llm = LLMInterface(provider="gemini", model="gemini-2.5-pro", deferred=True)
    llm._begin_call(prompt_name="X")
    llm._call_log_to_db("s", "u", "r", "success", 1, 1)
