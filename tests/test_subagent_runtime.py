# -*- coding: utf-8 -*-
"""A sub-agent works like the main agent, on a context of its own.

It decides with the main agent's ActionRouter and AgentStep and runs actions
with the same ActionManager, against a scripted LLM and real tools. These
tests pin:

* its context: the type's prompt and actions, the query once in the first
  request, then only new events; nothing of another agent's context;
* the main loop's behaviour it inherits: parallel batches, retry feedback as
  the next turn, reasoning in the stream referred to (not repeated), folds;
* its own rules: only its actions run, the early-end guard (not on the final
  turn), the budget statement and warning, the turn and time caps;
* its lifecycle: a workspace inside the spawning session's, Stop cancels it,
  and a finished sub-agent is released and forgotten.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_core import load_actions_from_directories, registry_instance
from agent_core.core.action import Action
from agent_core.core.event_stream.event import EventType
from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.action.manager import ActionManager
from agent_core.core.impl.llm.interface import LLMContextOverflowError
from app import config as app_config
from app.event_stream import EventStreamManager
from app.internal_action_interface import InternalActionInterface
from app.subagent import (
    SubAgentDefinition,
    SubAgentManager,
    SubAgentRunner,
    get_subagent_definition,
    list_subagent_names,
)
from app.subagent import registry as registry_module

REPO_ROOT = Path(__file__).resolve().parent.parent


def _reply(*actions, reasoning="Next step."):
    return json.dumps(
        {
            "reasoning": reasoning,
            "actions": [
                {"action_name": name, "parameters": params} for name, params in actions
            ],
        }
    )


def _end(result="done", status="completed"):
    return _reply(("sub_task_end", {"status": status, "result": result}))


class _FakeLLM:
    """Answers each sub-agent's requests from its script (``replies[sub_id]``,
    else ``replies[None]``): a reply string, an exception to raise, or a
    callable (sync or async) returning either."""

    def __init__(self):
        self.replies = {}
        self.sent = {}
        self.caches = {}
        self.resets = 0
        self.fits = True
        self.on_history = []
        self.standalone = 0
        self.ended = []

    def create_session_cache(self, task_id, call_type, system_prompt):
        self.caches[task_id] = system_prompt
        return task_id

    def has_session_cache(self, task_id, call_type):
        return task_id in self.caches

    def reset_session_history(self, task_id, call_type):
        self.resets += 1

    def fits_context(self, task_id, call_type, system_prompt, pending):
        return self.fits

    def input_budget(self):
        return 1_000_000

    def session_turn_recorded(self, task_id, call_type):
        return True

    def checkpoint_session(self, *args):
        pass

    def end_all_session_caches(self, task_id):
        self.ended.append(task_id)
        self.caches.pop(task_id, None)

    async def generate_response_with_session_async(
        self,
        task_id,
        call_type,
        user_prompt,
        system_prompt_for_new_session=None,
        prompt_name=None,
        call_metadata=None,
    ):
        self.sent.setdefault(task_id, []).append(
            {
                "user": user_prompt,
                "system": system_prompt_for_new_session,
                "metadata": call_metadata,
                "prompt_name": prompt_name,
            }
        )
        script = self.replies.get(task_id) or self.replies[None]
        reply = script.popleft()
        if callable(reply):
            reply = reply()
            if asyncio.iscoroutine(reply):
                reply = await reply
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def generate_side_response_with_session(
        self, task_id, call_type, user_prompt, system_prompt, **kwargs
    ):
        self.on_history.append(task_id)
        return '{"summary": "SUMMARY ON HISTORY"}'

    def generate_response(self, *args, **kwargs):
        self.standalone += 1
        return "STANDALONE SUMMARY"

    def script(self, sub_id, *replies):
        self.replies[sub_id] = deque(replies)


@pytest.fixture(scope="module")
def registry():
    load_actions_from_directories(
        base_dir=str(REPO_ROOT), paths_to_scan=["app/data/action"]
    )
    return registry_instance


@pytest.fixture
def runtime(registry, tmp_path, monkeypatch):
    llm = _FakeLLM()
    events = EventStreamManager(llm=llm)
    # The router finds a session's stream through the global registry.
    monkeypatch.setattr(router_module, "get_event_stream_manager", lambda: events)

    def retrieve(name):
        found = registry.find_action_by_name(name)
        return Action.from_dict(found) if found else None

    library = SimpleNamespace(retrieve_action=retrieve)
    actions = ActionManager(
        action_library=library,
        llm_interface=llm,
        db_interface=Mock(),
        event_stream_manager=events,
        context_engine=Mock(),
        state_manager=Mock(),
    )
    parent = SimpleNamespace(id="parent", workspace_dir=str(tmp_path / "parent"))
    main = SimpleNamespace(id="main", workspace_dir=str(tmp_path / "main"))
    sessions = SimpleNamespace(
        get=lambda sid: parent if sid == "parent" else None, main=main
    )
    manager = SubAgentManager(events, llm, library, actions, sessions)
    monkeypatch.setattr(InternalActionInterface, "subagent_manager", manager)

    # What each stream held when it was released (streams go with the run).
    released = {}
    events.add_removal_listener(
        lambda sid, stream: released.__setitem__(sid, list(stream.tail_events))
    )
    return SimpleNamespace(
        llm=llm, events=events, manager=manager, actions=actions, released=released
    )


def _spawn(runtime, agent_type="general_agent", query="Read the file.", parent="parent"):
    return runtime.manager.spawn(agent_type, query, parent_session_id=parent)


def _run(runtime, *subs):
    async def go():
        return await asyncio.wait_for(
            asyncio.gather(*(runtime.manager.run(sub) for sub in subs)), timeout=30
        )

    return asyncio.run(go())


def _tiny(monkeypatch, name="tiny_agent", **overrides):
    """A test-only type: general_agent's actions with small caps."""
    general = get_subagent_definition("general_agent")
    fields = {
        "name": name,
        "description": "test type",
        "system_prompt": "You are a test sub-agent.",
        "actions": general.actions,
        "max_iterations": 10,
        "max_wall_seconds": 60,
        **overrides,
    }
    monkeypatch.setitem(registry_module._REGISTRY, name, SubAgentDefinition(**fields))
    return name


# ── context ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_type", list_subagent_names())
def test_every_type_decides_on_its_own_prompt_and_actions(runtime, agent_type):
    sub = _spawn(runtime, agent_type)
    try:
        runner = SubAgentRunner(runtime.manager, sub)
        system = runner.context.make_prompt()[0]
        instructions = runner.router.decision_instructions(sub.id)
        definition = get_subagent_definition(agent_type)
        assert system.startswith(definition.system_prompt.strip())
        assert "<current_date>" in system
        for name in definition.actions:
            assert f'"name":"{name}"' in instructions, name
        assert '"actions": [' in instructions  # the main agent's reply format
        # Nothing of the main agent's own rules or catalog.
        assert "Message Routing" not in system + instructions
        assert "capability_catalog" not in system + instructions
    finally:
        runtime.manager.release(sub.id)


def test_the_first_request_holds_the_query_once_then_only_new_events(
    runtime, tmp_path
):
    source = tmp_path / "input.txt"
    source.write_text("FILE-CONTENT-MARKER", encoding="utf-8")
    query = "Read input.txt and report its content."
    sub = _spawn(runtime, query=query)
    runtime.llm.script(
        sub.id,
        _reply(("read_file", {"file_path": str(source)}), reasoning="Read it first."),
        _end("FILE-CONTENT-MARKER"),
    )
    _run(runtime, sub)

    first, second = runtime.llm.sent[sub.id]
    assert first["metadata"] == {"request": "full", "reason": "first"}
    assert first["user"].count(query) == 1
    assert "Budget: up to 40 turns and 15 minutes" in first["user"]
    assert first["prompt_name"] == "SUBAGENT_GENERAL_AGENT"
    assert "general-purpose sub-agent" in first["system"]

    assert second["metadata"] == {"request": "delta"}
    assert query not in second["user"]
    assert "FILE-CONTENT-MARKER" in second["user"]
    # The reply the history ends with is referred to, not repeated.
    assert "input as in your reply above" in second["user"]
    assert "Read it first." not in second["user"]
    assert runtime.llm.resets == 1  # only the first request started a history

    kinds = [r.event.event_type for r in runtime.released[sub.id]]
    assert EventType.REASONING in kinds
    assert (sub.status, sub.result, sub.iterations) == (
        "completed",
        "FILE-CONTENT-MARKER",
        2,
    )


def test_parallel_sub_agents_keep_their_contexts_apart(runtime, tmp_path):
    subs, ready = [], set()
    for index in range(2):
        marker = f"private-worker-{index}"
        source = tmp_path / f"input-{index}.txt"
        source.write_text(marker, encoding="utf-8")
        output = tmp_path / f"output-{index}.txt"
        sub = _spawn(runtime, query=marker)
        subs.append((sub, output, marker))

        async def first_turn(sub=sub, source=source, output=output, marker=marker):
            # Neither proceeds until both are running: they run concurrently.
            ready.add(sub.id)
            while len(ready) < 2:
                await asyncio.sleep(0)
            return _reply(
                ("read_file", {"file_path": str(source)}),
                ("write_file", {"file_path": str(output), "content": marker}),
            )

        runtime.llm.script(sub.id, first_turn, _end(marker))

    _run(runtime, *(sub for sub, _, _ in subs))

    for index, (sub, output, marker) in enumerate(subs):
        other = subs[1 - index][2]
        sent = "\n".join(r["user"] for r in runtime.llm.sent[sub.id])
        assert other not in sent
        assert output.read_text(encoding="utf-8") == marker
        assert (sub.status, sub.result, sub.iterations) == ("completed", marker, 2)
    assert runtime.actions.inflight_ids() == set()


# ── the main loop's behaviour ────────────────────────────────────────────────


def test_a_reply_that_does_not_parse_is_corrected_as_the_next_turn(runtime):
    sub = _spawn(runtime)
    runtime.llm.script(sub.id, "not json at all", _end())
    _run(runtime, sub)

    first, retry = runtime.llm.sent[sub.id]
    assert retry["metadata"] == {"request": "correction"}
    assert retry["user"].startswith("Previous attempt 1 failed to parse")
    assert sub.query not in retry["user"]
    assert runtime.llm.resets == 1
    assert (sub.status, sub.iterations) == ("completed", 1)


def test_prose_around_the_reply_costs_no_retry(runtime):
    sub = _spawn(runtime)
    runtime.llm.script(sub.id, f"I'll finish now.\n```json\n{_end()}\n```")
    _run(runtime, sub)
    assert len(runtime.llm.sent[sub.id]) == 1
    assert sub.status == "completed"


def _work(runtime, sub, n=100):
    for i in range(n):
        runtime.events.log("action_end", f"page {i} " + "x " * 50, task_id=sub.id)


@pytest.fixture
def small_keep(monkeypatch):
    settings = {"context": {"keep_recent_tokens": 500}}
    monkeypatch.setattr(app_config, "get_settings", lambda *a, **k: settings)


def test_a_request_that_would_not_fit_folds_on_the_history(
    runtime, tmp_path, small_keep
):
    source = tmp_path / "input.txt"
    source.write_text("content", encoding="utf-8")
    read = _reply(("read_file", {"file_path": str(source)}))
    sub = _spawn(runtime)

    def work_then_read():
        _work(runtime, sub)  # carried by the next request
        return read

    def overflow_next_then_read():
        runtime.llm.fits = False
        return read

    runtime.llm.script(
        sub.id, work_then_read, overflow_next_then_read, lambda: _end()
    )
    _run(runtime, sub)

    folded = runtime.llm.sent[sub.id][2]
    assert runtime.llm.on_history == [sub.id] and runtime.llm.standalone == 0
    assert folded["metadata"] == {"request": "full", "reason": "fold"}
    assert "SUMMARY ON HISTORY" in folded["user"]
    assert folded["user"].count(sub.query) == 1
    assert sub.status == "completed"


def test_a_refused_request_folds_once_and_is_resent_whole(
    runtime, tmp_path, small_keep
):
    source = tmp_path / "input.txt"
    source.write_text("content", encoding="utf-8")
    read = _reply(("read_file", {"file_path": str(source)}))
    sub = _spawn(runtime)

    def work_then_read():
        _work(runtime, sub)
        return read

    runtime.llm.script(
        sub.id,
        work_then_read,
        read,
        LLMContextOverflowError("request too large"),
        _end(),
    )
    _run(runtime, sub)

    resent = runtime.llm.sent[sub.id][3]
    assert runtime.llm.standalone == 1 and runtime.llm.on_history == []
    assert resent["metadata"] == {"request": "full", "reason": "overflow"}
    assert "STANDALONE SUMMARY" in resent["user"]
    assert resent["user"].count(sub.query) == 1
    assert sub.status == "completed"


# ── its own rules ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["send_message", "spawn_subagent"])
def test_an_action_outside_its_definition_never_runs(runtime, name):
    sub = _spawn(runtime)
    runtime.llm.script(sub.id, _reply((name, {"message": "hi"})), _end())
    _run(runtime, sub)

    delta = runtime.llm.sent[sub.id][1]["user"]
    assert f"'{name}' is not one of your actions" in delta
    assert f"Running action {name}" not in delta
    assert sub.status == "completed"


def test_the_early_end_guard_refuses_until_the_final_turn(runtime, monkeypatch):
    refused = "Return the verdict as JSON."
    agent_type = _tiny(
        monkeypatch, max_iterations=3, early_end_guard=lambda sub, params: refused
    )
    sub = _spawn(runtime, agent_type)
    runtime.llm.script(sub.id, _end("first"), _end("second"), _end("third"))
    _run(runtime, sub)

    sent = runtime.llm.sent[sub.id]
    assert refused in sent[1]["user"] and refused in sent[2]["user"]
    # The final turn ends: the guard can never trap a run into the cap.
    assert (sub.status, sub.result, sub.iterations) == ("completed", "third", 3)


def test_the_turn_cap_ends_the_run_and_warns_once_before(runtime, tmp_path, monkeypatch):
    source = tmp_path / "input.txt"
    source.write_text("content", encoding="utf-8")
    sub = _spawn(runtime, _tiny(monkeypatch, max_iterations=10))
    runtime.llm.script(
        sub.id, *[_reply(("read_file", {"file_path": str(source)}))] * 10
    )
    _run(runtime, sub)

    warned = [
        i
        for i, r in enumerate(runtime.llm.sent[sub.id])
        if "Turn budget: 2 of 10 turns left" in r["user"]
    ]
    assert warned == [8]  # turn 9: a fifth of the turns left
    assert "Budget: up to 10 turns" in runtime.llm.sent[sub.id][0]["user"]
    assert (sub.status, sub.iterations) == ("failed", 10)
    assert "used all 10 turns" in sub.result


def test_the_time_cap_cancels_the_call_in_flight(runtime, monkeypatch):
    sub = _spawn(runtime, _tiny(monkeypatch, max_wall_seconds=0.2))

    async def never():
        await asyncio.sleep(30)

    runtime.llm.script(sub.id, never)
    _run(runtime, sub)
    assert sub.status == "timeout"
    assert not runtime.events.has_stream(sub.id)


def test_an_unavailable_llm_ends_the_run_with_its_cause(runtime):
    from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError

    sub = _spawn(runtime)
    runtime.llm.script(sub.id, LLMConsecutiveFailureError(5))
    _run(runtime, sub)
    assert sub.status == "failed" and sub.iterations == 1
    assert "stopped on an error" in sub.result


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_its_workspace_is_inside_the_spawning_session(runtime, tmp_path):
    child = _spawn(runtime)
    orphan = _spawn(runtime, parent="unknown")
    try:
        streams = runtime.events
        assert Path(streams.get_stream_by_id(child.id).temp_dir) == (
            tmp_path / "parent" / child.id
        )
        assert Path(streams.get_stream_by_id(orphan.id).temp_dir) == (
            tmp_path / "main" / orphan.id
        )
        assert (tmp_path / "parent" / child.id).is_dir()
    finally:
        runtime.manager.release(child.id)
        runtime.manager.release(orphan.id)


def test_a_finished_sub_agent_is_released_and_forgotten(runtime):
    sub = _spawn(runtime)
    runtime.llm.script(sub.id, _end())
    _run(runtime, sub)
    assert runtime.manager.get(sub.id) is None
    assert not runtime.events.has_stream(sub.id)
    assert sub.id in runtime.llm.ended
    # Released after sub_task_end's own action_end, which follows the end.
    kinds = [r.event.kind for r in runtime.released[sub.id]]
    assert kinds[-2:] == ["subagent_end", "action_end"]


def test_stopping_the_spawning_run_stops_the_sub_agent(runtime):
    sub = _spawn(runtime)
    started = asyncio.Event()

    async def hang():
        started.set()
        await asyncio.sleep(30)

    runtime.llm.script(sub.id, hang)

    async def go():
        task = asyncio.create_task(runtime.manager.run(sub))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert sub.status == "failed"
    assert "stopped with the run that spawned it" in sub.result
    assert runtime.manager.get(sub.id) is None
    assert not runtime.events.has_stream(sub.id)


def test_spawn_subagent_runs_on_the_spawning_loop_and_returns_the_result(runtime):
    from app.data.action.spawn_subagent import spawn_subagent

    runtime.llm.script(None, _end("THE RESULT"))
    output = asyncio.run(
        spawn_subagent(
            {
                "agent_type": "general_agent",
                "query": "Answer.",
                "_session_id": "parent",
            }
        )
    )
    assert output["status"] == "completed"
    assert output["result"] == "THE RESULT"
    assert output["iterations"] == 1
    assert runtime.manager.get(output["child_task_id"]) is None
