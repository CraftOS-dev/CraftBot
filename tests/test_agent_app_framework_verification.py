"""Framework verification through the real child/action runtime, offline."""

import asyncio
import json
import shutil
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import pytest

from agent_core import registry_instance
from agent_core.core.impl.action.library import ActionLibrary
from app.agent_app import framework, framework_verification as verification
from app.agent_app.framework_cli import CLIResult
from app.agent_app.framework_commands import command
from app.event_stream import EventStreamManager
from app.database_interface import DatabaseInterface
from app.internal_action_interface import InternalActionInterface as I
from app.subagent import SubAgentManager, SubAgentRunner, get_subagent_definition
from agent_core.core.impl.action.manager import ActionManager
from tests import test_agent_app_framework_host as host_tests

REPO = Path(__file__).resolve().parents[1]
fixture = host_tests.fixture


@pytest.fixture
def runtime(fixture, tmp_path, monkeypatch):
    host, cli, row = fixture
    # Reproduce startup with a separate STATE tree retaining the old binding.
    # Loading straight from REPO hid the production regression: that old action
    # omits the caller id and queues verify back into the builder indefinitely.
    actions_dir = tmp_path / "state/app/data/action"
    shutil.copytree(
        REPO / "app/data/action", actions_dir,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    stale_action = actions_dir / "agent_app_framework_actions.py"
    stale_source = stale_action.read_text(encoding="utf-8").replace(
        "            parent_session_id=parent_session_id,\n", ""
    )
    stale_action.write_text(stale_source, encoding="utf-8")
    monkeypatch.setattr(registry_instance, "_registry", {})
    database = DatabaseInterface(data_dir=str(actions_dir.parent))
    assert stale_action.read_text(encoding="utf-8") == stale_source
    llm = Mock()
    events = EventStreamManager(llm=llm)
    manager = SubAgentManager(events, llm)
    library = ActionLibrary(llm, database)
    actions = ActionManager(library, llm, Mock(), events, Mock(), Mock())
    for key, value in {
        "subagent_manager": manager,
        "action_manager": actions,
        "action_library": library,
        "event_stream_manager": events,
        "llm_interface": llm,
    }.items():
        monkeypatch.setattr(I, key, value)
    attached = asyncio.run(host.attach(row["path"], row["id"]))
    parent = host.agent.session_manager.get(attached["sessionId"])
    parent.workspace_dir = str(tmp_path / "evidence")
    events.create_stream(parent.id)
    events.log(kind="message", message="PRIVATE BUILDER ASSUMPTION", task_id=parent.id)
    state = Path(row["path"], ".a2app")
    state.mkdir()
    stamp = {"fingerprint": "candidate", "budgetChecked": True, "at": "now"}
    (state / "gate-pass.json").write_text(json.dumps(stamp))
    (state / "dev.json").write_text(
        json.dumps(
            {
                "pid": 999,
                "url": "http://127.0.0.1:8124",
                "port": 8124,
                "startedAt": "now",
            }
        )
    )
    requirements = Path(row["path"], "reference", "requirements.md")
    requirements.parent.mkdir()
    requirements.write_text(
        "# Requirements\n## Features\n- Persist a checklist item.", encoding="utf-8"
    )
    # Read the real shipped skill without changing the framework bundle.
    with ZipFile(REPO / "app/vendor/agent-app/agent-app-framework.zip") as bundle:
        member = next(
            name
            for name in bundle.namelist()
            if name.endswith("skills/walk-verify/SKILL.md")
        )
        skill = bundle.read(member).decode("utf-8")
    source = tmp_path / "installed-skill" / "SKILL.md"
    source.parent.mkdir()
    source.write_text(skill, encoding="utf-8")
    monkeypatch.setattr(
        verification,
        "skill_sources",
        AsyncMock(return_value={"framework-walk-verify": source}),
    )
    cli.run.return_value = CLIResult(0, '{"modules":[]}', "")
    return SimpleNamespace(
        host=host,
        cli=cli,
        row=row,
        parent=parent,
        manager=manager,
        events=events,
        library=library,
        actions=actions,
        llm=llm,
        state=state,
        stamp=stamp,
        skill=skill,
        source=source,
        requirements=requirements,
    )


async def run(runtime):
    # Includes source extraction, injected parent id and nested action execution.
    return await runtime.actions.execute_action(
        runtime.library.retrieve_action("agent_app_framework_workflow"),
        "",
        "",
        session_id=runtime.parent.id,
        is_running_task=True,
        input_data={
            "activity": "verify",
            "request": "Check all requirements independently",
            "path": runtime.row["path"],
            "app_id": runtime.row["id"],
        },
    )


def test_real_child_returns_verdict_in_parent_without_a_new_chat(runtime, monkeypatch):
    decisions = deque(
        [
            {
                "action_name": "read_file",
                "parameters": {"file_path": str(runtime.requirements)},
            },
            {
                "action_name": "agent_app_framework_command",
                "parameters": {"surface": "a2app", "args": [runtime.row["path"]]},
            },
            {
                "action_name": "sub_task_end",
                "parameters": {
                    "status": "completed",
                    "result": json.dumps(
                        {
                            "verdict": "pass",
                            "evidence": "Test fixture: UI paths and stored state checked.",
                        }
                    ),
                },
            },
        ]
    )
    prompts = []

    async def invoke(self, sub, user_prompt, system_prompt):
        prompts.append(user_prompt)
        assert sub.parent_task_id == runtime.parent.id
        assert runtime.host.verification(runtime.row["path"])["verdict"] == "incomplete"
        return json.dumps(decisions.popleft())

    monkeypatch.setattr(SubAgentRunner, "_invoke_llm", invoke)
    result = asyncio.run(run(runtime))
    assert result["status"] == "success", result
    assert result["sessionId"] == runtime.parent.id
    child = runtime.manager.get(result["childTaskId"])
    assert child.agent_type == "framework_walk_verify" and child.iterations == 3
    assert result["verification"]["verdict"] == "pass"
    assert result["verification"]["status"] == "completed"
    assert runtime.skill in child.query and str(runtime.source.parent) in child.query
    assert "PRIVATE BUILDER ASSUMPTION" not in "\n".join(prompts)
    assert "Persist a checklist item" in "\n".join(prompts[1:])
    assert len(runtime.host.agent.session_manager.sessions) == 1
    runtime.host.agent.trigger_service.emit.assert_not_called()
    assert not runtime.events.has_stream(child.id)
    assert runtime.events.has_stream(runtime.parent.id)
    runtime.llm.end_all_session_caches.assert_called_once_with(child.id)
    assert runtime.actions.inflight_ids() == set()
    assert verification.verification_target.get() is None
    runtime.host.require_verified(runtime.row["path"])
    with pytest.raises(PermissionError):
        runtime.host.report_verification(runtime.parent.id, "pass", "Self-grading")
    with pytest.raises(PermissionError, match="already ended"):
        runtime.host.report_verification(child.id, "pass", "Late report")
    asyncio.run(runtime.host.verification_reported(result["verification"]))
    runtime.host.agent.trigger_service.emit.assert_not_called()
    (runtime.state / "gate-pass.json").write_text(
        '{"fingerprint":"next candidate", "budgetChecked":true}'
    )
    with pytest.raises(ValueError):
        runtime.host.require_verified(runtime.row["path"])


def test_child_has_resolvable_tools_and_cannot_delegate_or_grade_itself(runtime):
    definition = get_subagent_definition("framework_walk_verify")
    for name in definition.actions:
        assert registry_instance.find_action_by_name(name) is not None, name
    assert {
        "mini_browser_navigate",
        "read_file",
        "agent_app_framework_command",
        "sub_task_end",
    } <= set(definition.actions)
    assert not {
        "spawn_subagent",
        "send_message",
        "agent_app_framework_verification",
        "agent_app_framework_workflow",
        "write_file",
    } & set(definition.actions)
    assert "TOOLS" in definition.system_prompt.format(
        action_list="TOOLS", output_format="JSON"
    )
    assert definition.early_end_guard(None, {"result": "Looks good"})
    assert definition.early_end_guard(
        None, {"result": '{"verdict":"pass","evidence":""}'}
    )
    assert (
        definition.early_end_guard(
            None, {"result": '{"verdict":"blocked","evidence":"Browser unavailable"}'}
        )
        is None
    )


@pytest.mark.parametrize(
    "outcome",
    [
        "defects",
        "blocked",
        "incomplete",
        "timeout",
        "error",
        "malformed",
        "changed",
        "stopped",
        "restarted",
    ],
)
def test_nonpass_or_changed_candidate_never_allows_promotion(
    runtime, monkeypatch, outcome
):
    async def finish(self, sub):
        verdict = outcome if outcome in {"defects", "blocked", "incomplete"} else "pass"
        result = json.dumps(
            {"verdict": verdict, "evidence": "Recorded fixture findings"}
        )
        status = outcome if outcome in {"timeout", "error"} else "completed"
        if outcome == "malformed":
            result = "No structured verdict"
        if outcome == "changed":
            (runtime.state / "gate-pass.json").write_text(
                '{"fingerprint":"other","budgetChecked":true}'
            )
        if outcome == "stopped":
            (runtime.state / "dev.json").unlink()
        if outcome == "restarted":
            (runtime.state / "dev.json").write_text('{"url":"http://127.0.0.1:9000"}')
        sub.terminate(status, result)

    monkeypatch.setattr(SubAgentRunner, "run_to_completion", finish)
    result = asyncio.run(run(runtime))
    assert result["verification"]["verdict"] != "pass", result
    with pytest.raises(ValueError):
        runtime.host.require_verified(runtime.row["path"])
    assert len(runtime.host.agent.session_manager.sessions) == 1
    assert not runtime.host.verification_runs
    assert not runtime.events.has_stream(result["childTaskId"])


@pytest.mark.parametrize("cancel_by", ["parent", "close", "reset"])
def test_cancellation_revokes_old_pass_and_cleans_up_child(
    runtime, monkeypatch, cancel_by
):
    async def check():
        ready = asyncio.Event()
        target = None

        async def wait(self, sub):
            nonlocal target
            target = verification.verification_target.get()
            ready.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(SubAgentRunner, "run_to_completion", wait)
        runtime.host.store.put(
            "verification",
            str(Path(runtime.row["path"]).resolve()),
            {"verdict": "pass", "stamp": runtime.stamp},
        )
        task = asyncio.create_task(run(runtime))
        await asyncio.wait_for(ready.wait(), timeout=5)
        with pytest.raises(ValueError):
            runtime.host.require_verified(runtime.row["path"])
        with pytest.raises(RuntimeError, match="already running"):
            await runtime.host.workflow(
                "verify",
                "Duplicate",
                runtime.row["path"],
                runtime.row["id"],
                parent_session_id=runtime.parent.id,
            )
        if cancel_by == "close":
            await runtime.host.close()
        elif cancel_by == "reset":
            # Stop before reset's unrelated app/file removal; exercise its
            # real cancellation stage without deleting the fixture's receipts.
            monkeypatch.setattr(
                framework,
                "list_apps",
                AsyncMock(side_effect=RuntimeError("reset snapshot stop")),
            )
            with pytest.raises(RuntimeError, match="reset snapshot stop"):
                await runtime.host.reset_apps()
        else:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        (child,) = runtime.manager.subagents.values()
        assert child.status == "failed"
        assert not runtime.events.has_stream(child.id)
        assert not runtime.host.verification_runs
        assert target.active is False
        assert verification.verification_target.get() is None
        assert runtime.host.verification(runtime.row["path"])["verdict"] == "incomplete"
        assert (
            runtime.host.store.get("verification_session", child.id)["status"]
            == "failed"
        )

    asyncio.run(check())


def test_verifier_command_is_bound_to_unchanged_dev_target(runtime):
    target = verification.VerificationTarget(
        runtime.row["path"],
        runtime.stamp,
        verification.read_dev(runtime.row["path"]),
        runtime.host,
    )

    async def check():
        token = verification.verification_target.set(target)
        try:
            for surface, args in [
                ("agent-app", [target.path, "promote"]),
                ("a2app", ["http://127.0.0.1:8123"]),
                ("a2app", [target.path, "credential"]),
                ("a2app", [str(Path(target.path).parent)]),
            ]:
                with pytest.raises(PermissionError):
                    await command(surface, args)
            runtime.cli.run.assert_not_awaited()
            assert (await command("a2app", [target.path]))["status"] == "success"
            (runtime.state / "dev.json").unlink()
            with pytest.raises(ValueError, match="dev instance"):
                await command("a2app", [target.path])
            assert runtime.cli.run.await_count == 1
        finally:
            verification.verification_target.reset(token)

    asyncio.run(check())


def test_runner_setup_failure_returns_blocked_and_releases_child(runtime, monkeypatch):
    monkeypatch.setattr(
        SubAgentRunner,
        "_register_session",
        Mock(side_effect=RuntimeError("provider unavailable")),
    )
    result = asyncio.run(run(runtime))
    assert result["verification"]["verdict"] == "blocked", result
    assert "provider unavailable" in result["verification"]["evidence"]
    assert not runtime.events.has_stream(result["childTaskId"])


@pytest.mark.parametrize("missing", ["runtime", "dev", "skill"])
def test_missing_prerequisites_do_not_create_a_verification_chat(
    runtime, monkeypatch, missing
):
    if missing == "runtime":
        monkeypatch.setattr(I, "subagent_manager", None)
    elif missing == "dev":
        (runtime.state / "dev.json").unlink()
    else:
        runtime.source.unlink()
    result = asyncio.run(run(runtime))
    assert result["status"] == "error", result
    assert len(runtime.host.agent.session_manager.sessions) == 1
    assert not runtime.manager.subagents
    assert not runtime.host.verification_runs


@pytest.mark.parametrize("flag", ["resetting", "closing"])
def test_reset_or_shutdown_during_selection_does_not_spawn_late_child(runtime, monkeypatch, flag):
    async def select(path, app_id):
        setattr(runtime.host, flag, True)
        return runtime.row

    monkeypatch.setattr(runtime.host, "selected", select)
    try:
        result = asyncio.run(run(runtime))
        assert result["status"] == "error", result
        assert "reset or shutdown" in result["message"]
        assert not runtime.manager.subagents
        assert not runtime.host.verification_runs
    finally:
        setattr(runtime.host, flag, False)
