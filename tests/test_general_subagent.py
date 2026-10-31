"""General worker wiring and execution with real tools and scripted LLM decisions."""

import asyncio
import json
import platform
import runpy
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent_core import load_actions_from_directories, registry_instance
from agent_core.core.action import Action
from agent_core.core.impl.action.manager import ActionManager
from app.event_stream import EventStreamManager
from app.internal_action_interface import InternalActionInterface
from app.subagent import SubAgentManager, SubAgentRunner, get_subagent_definition

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registry():
    load_actions_from_directories(
        base_dir=str(REPO_ROOT), paths_to_scan=["app/data/action"]
    )
    return registry_instance


def test_definition_is_discovered_with_resolvable_tools(registry):
    definition = get_subagent_definition("general_agent")
    for name in definition.actions:
        assert registry.find_action_by_name(name) is not None, name
    assert definition.actions.count("sub_task_end") == 1
    assert {"read_file", "write_file", "stream_edit", "run_shell"} <= set(
        definition.actions
    )
    assert not {"spawn_subagent", "send_message", "add_action_sets", "use_skill"} & set(
        definition.actions
    )
    prompt = definition.system_prompt.format(action_list="TOOLS", output_format="JSON")
    assert "TOOLS" in prompt and "JSON" in prompt
    spawn = registry.find_action_by_name("spawn_subagent")
    assert "general_agent" in spawn["input_schema"]["agent_type"]["enum"]
    assert definition.description in spawn["description"]
    assert spawn["parallelizable"] is True


@pytest.mark.parametrize("system", ["Windows", "Linux", "Darwin"])
def test_definition_only_offers_powershell_on_windows(monkeypatch, system):
    register = Mock()
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr("app.subagent.registry.register_subagent", register)
    runpy.run_path(str(REPO_ROOT / "app/subagent/definitions/general_agent.py"))
    register.assert_called_once()
    actions = register.call_args.kwargs["actions"]
    assert "run_shell" in actions
    assert ("run_powershell" in actions) == (system == "Windows")


@pytest.fixture
def runtime(registry, monkeypatch):
    llm = Mock()
    events = EventStreamManager(llm=llm)
    manager = SubAgentManager(event_stream_manager=events, llm_interface=llm)
    library = SimpleNamespace(
        retrieve_action=lambda name: Action.from_dict(
            registry.find_action_by_name(name)
        )
    )
    actions = ActionManager(
        action_library=library,
        llm_interface=llm,
        db_interface=Mock(),
        event_stream_manager=events,
        context_engine=Mock(),
        state_manager=Mock(),
    )
    runner = SubAgentRunner(manager, actions, library, events, llm)
    monkeypatch.setattr(InternalActionInterface, "subagent_manager", manager)
    return SimpleNamespace(
        llm=llm, events=events, manager=manager, actions=actions, runner=runner
    )


@pytest.mark.parametrize(
    ("peer_type", "peer_status"),
    [
        ("general_agent", "completed"),
        ("research_agent", "completed"),
        ("general_agent", "failed"),
    ],
)
def test_parallel_workers_use_real_tools_and_isolate_context(
    runtime, monkeypatch, tmp_path, peer_type, peer_status
):
    workers = []
    decisions = {}
    prompts = {}
    outputs = []
    for index, agent_type in enumerate(("general_agent", peer_type)):
        marker = f"private-worker-{index}"
        source = tmp_path / f"input-{index}.txt"
        source.write_text(marker, encoding="utf-8")
        output = tmp_path / f"output-{index}.txt"
        sub = runtime.manager.spawn(agent_type, query=marker, parent_task_id="parent")
        workers.append(sub)
        prompts[sub.id] = []
        steps = [{"action_name": "read_file", "parameters": {"file_path": str(source)}}]
        if agent_type == "general_agent":
            steps.append(
                {
                    "action_name": "write_file",
                    "parameters": {"file_path": str(output), "content": marker},
                }
            )
            outputs.append((output, marker))
        steps.append(
            {
                "action_name": "sub_task_end",
                "parameters": {
                    "status": peer_status if index else "completed",
                    "result": marker,
                },
            }
        )
        decisions[sub.id] = deque(steps)

    ready = set()

    async def invoke(sub, user_prompt, system_prompt):
        prompts[sub.id].append(user_prompt)
        # Neither worker can proceed unless the existing runner runs both
        # concurrently; no live provider or timing-based assertion is needed.
        ready.add(sub.id)
        while len(ready) < len(workers):
            await asyncio.sleep(0)
        return json.dumps(decisions[sub.id].popleft())

    monkeypatch.setattr(runtime.runner, "_invoke_llm", invoke)

    async def run():
        return await asyncio.wait_for(
            asyncio.gather(*(runtime.runner.run_to_completion(sub) for sub in workers)),
            timeout=15,
        )

    results = asyncio.run(run())
    assert [sub.status for sub in results] == ["completed", peer_status]
    assert [sub.result for sub in results] == [sub.query for sub in workers]
    for path, marker in outputs:
        assert path.read_text(encoding="utf-8") == marker
    for index, sub in enumerate(workers):
        assert sub.query in prompts[sub.id][0]
        assert workers[1 - index].query not in "\n".join(prompts[sub.id])
        assert not runtime.events.has_stream(sub.id)
        runtime.llm.end_all_session_caches.assert_any_call(sub.id)
    assert runtime.actions.inflight_ids() == set()


def test_general_worker_cannot_delegate_or_message(runtime):
    sub = runtime.manager.spawn("general_agent", query="Read-only analysis")
    execute = AsyncMock()
    runtime.runner.action_manager = SimpleNamespace(execute_action=execute)

    async def run():
        for name in ("spawn_subagent", "send_message"):
            await runtime.runner._dispatch_action(
                sub, {"action_name": name, "parameters": {}}
            )

    try:
        asyncio.run(run())
        execute.assert_not_awaited()
        log = runtime.events.snapshot_by_id(sub.id)
        assert "Disallowed action" in log
        assert "spawn_subagent" in log and "send_message" in log
    finally:
        runtime.manager.release(sub.id)
