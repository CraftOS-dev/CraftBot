"""Framework actions must survive CraftBot's source extraction and execution.

Set CRAFTBOT_TEST_AGENT_APP_PACKAGE to also run against an unchanged built CLI.
All framework profiles here are disposable; no user registry is queried.
"""

import asyncio
import json
import os
import shutil
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_core.core.action_framework.loader import load_actions_from_directories
from agent_core.core.action_framework.registry import registry_instance
from agent_core.core.impl.action.executor import _atomic_action_internal_async
from app.agent_app import framework
from app.agent_app.framework_cli import AgentAppCLI, CLIResult

ACTION = "agent_app_framework_list"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def action_json(tmp_path, monkeypatch):
    # Discover the shipped asset through the real loader, in isolation from
    # unrelated integrations and from the other tests' singleton registry.
    assets = tmp_path / "actions"
    assets.mkdir()
    shutil.copy2(REPO / "app/data/action/agent_app_framework_actions.py", assets)
    monkeypatch.setattr(registry_instance, "_registry", {})
    monkeypatch.setitem(sys.modules, "actions_agent_app_framework_actions_py", None)
    load_actions_from_directories(base_dir=str(tmp_path), paths_to_scan=["actions"])
    return registry_instance.find_action_by_name(ACTION)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAFTBOT_AGENT_APP_PACKAGE", str(tmp_path / "built package"))
    monkeypatch.setenv("A2APP_HOME", str(tmp_path / "framework home"))


def execute(action_json, payload=None):
    return asyncio.run(
        _atomic_action_internal_async(
            ACTION, action_json["code"], payload or {}, action_json["mode"]
        )
    )


def test_action_is_discoverable_and_simulation_needs_no_package(
    action_json, monkeypatch
):
    assert action_json["execution_mode"] == "internal"
    assert action_json["parallelizable"] is True
    assert registry_instance.get_action_implementation(ACTION).metadata.action_sets == [
        "agent_app"
    ]
    assert action_json["code"].lstrip().startswith("async def ")
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE")
    assert execute(action_json, {"simulated_mode": True})["status"] == "success"


@pytest.mark.parametrize(
    "name,payload,target",
    [
        (
            "agent_app_framework_command",
            {"surface": "a2app", "args": ["http://127.0.0.1:8123", "notes"]},
            "command",
        ),
        (
            "agent_app_framework_workflow",
            {
                "activity": "modify",
                "request": "Add filtering",
                "path": "app",
                "app_id": "id",
            },
            "workflow",
        ),
        (
            "agent_app_framework_verification",
            {"operation": "status", "path": "app"},
            "verification",
        ),
    ],
)
def test_all_native_actions_survive_source_extraction(
    action_json, monkeypatch, name, payload, target
):
    from types import SimpleNamespace
    from app.agent_app import framework_commands, framework_host
    from unittest.mock import Mock

    callback = (
        Mock(return_value={"verdict": "incomplete"})
        if target == "verification"
        else AsyncMock(return_value={"status": "success", "sessionId": "native"})
    )
    if target == "command":
        monkeypatch.setattr(framework_commands, "command", callback)
    else:
        monkeypatch.setattr(
            framework_host, "_host", SimpleNamespace(**{target: callback})
        )
    extracted = registry_instance.find_action_by_name(name)
    result = asyncio.run(
        _atomic_action_internal_async(
            name, extracted["code"], payload, extracted["mode"]
        )
    )
    assert result["status"] == "success", result
    assert callback.call_count == 1


def test_verification_without_a_caller_fails_instead_of_queueing(action_json, monkeypatch):
    from types import SimpleNamespace
    from app.agent_app import framework_host
    from agent_core.core.state.session import StateSession

    workflow = AsyncMock()
    monkeypatch.setattr(framework_host, "_host", SimpleNamespace(workflow=workflow))
    extracted = registry_instance.find_action_by_name("agent_app_framework_workflow")
    with StateSession.bind(""):
        result = asyncio.run(_atomic_action_internal_async(
            "agent_app_framework_workflow", extracted["code"],
            {"activity": "verify", "request": "Check the app", "path": "app", "app_id": "id"},
            extracted["mode"],
        ))
    assert result["status"] == "error"
    assert "calling conversation" in result["message"]
    workflow.assert_not_called()


def test_verification_uses_bound_caller_when_input_has_no_session_id(action_json, monkeypatch):
    from types import SimpleNamespace
    from app.agent_app import framework_host
    from agent_core.core.state.session import StateSession

    workflow = AsyncMock(return_value={"verification": {"verdict": "incomplete"}})
    monkeypatch.setattr(framework_host, "_host", SimpleNamespace(workflow=workflow))
    extracted = registry_instance.find_action_by_name("agent_app_framework_workflow")
    StateSession.start("bound-verification-parent")
    try:
        with StateSession.bind("bound-verification-parent"):
            result = asyncio.run(_atomic_action_internal_async(
                "agent_app_framework_workflow", extracted["code"],
                {"activity": "verify", "request": "Check the app", "path": "app", "app_id": "id"},
                extracted["mode"],
            ))
        assert result["status"] == "success"
        workflow.assert_awaited_once_with(
            "verify", "Check the app", "app", "id", parent_session_id="bound-verification-parent"
        )
    finally:
        StateSession.end("bound-verification-parent")


def test_native_bindings_load_from_code_while_custom_actions_stay_in_state(tmp_path, monkeypatch):
    from app.database_interface import DatabaseInterface

    actions_dir = tmp_path / "state/app/data/action"
    actions_dir.mkdir(parents=True)
    custom = actions_dir / "custom_action.py"
    custom_source = '''from agent_core import action
@action(name="my_custom_action", description="User custom action", input_schema={}, output_schema={})
def my_custom_action(input_data):
    return {"custom": True}
'''
    custom.write_text(custom_source, encoding="utf-8")
    # No framework action in STATE: native capabilities still come from CODE.
    for _ in range(2):
        monkeypatch.setattr(registry_instance, "_registry", {})
        database = DatabaseInterface(data_dir=str(actions_dir.parent))
        assert database.get_action("my_custom_action")["description"] == "User custom action"
        native = registry_instance.get_action_implementation("agent_app_framework_workflow")
        assert Path(native.handler.__code__.co_filename).resolve() == (
            REPO / "app/data/action/agent_app_framework_actions.py"
        ).resolve()
        assert "parent_session_id=parent_session_id" in database.get_action(native.metadata.name)["code"]
    assert custom.read_text(encoding="utf-8") == custom_source
    assert not (actions_dir / "agent_app_framework_actions.py").exists()


def test_extracted_action_calls_only_list_and_preserves_framework_data(
    action_json, tmp_path, monkeypatch
):
    data = {
        "ok": True,
        "registry": str(tmp_path / "framework home/registry.json"),
        "apps": [{"id": "canonical-id", "status": "stopped", "future_field": 42}],
        "connected": [
            {"appId": "remote-id", "principal": "member", "status": "offline"}
        ],
        "future_field": {"preserve": True},
    }
    calls = []

    async def run(cli, surface, args, **kwargs):
        calls.append((cli, surface, args, kwargs))
        return CLIResult(0, json.dumps(data), "upstream diagnostic\n")

    monkeypatch.setattr(AgentAppCLI, "run", run)
    result = execute(action_json)
    assert result == {
        "status": "success",
        "data": data,
        "exit_code": 0,
        "stderr": "upstream diagnostic\n",
    }
    ((cli, surface, args, kwargs),) = calls
    assert surface == "agent-app"
    assert args == ["list", "--json"]  # no prune, lifecycle or agent invocation
    assert cli.package_dir == (tmp_path / "built package").resolve()
    assert cli.home == (tmp_path / "framework home").resolve()
    assert kwargs == {"cwd": cli.package_dir, "timeout": 30}


@pytest.mark.parametrize("override", [None, "", "   ", "relative profile", " profile "])
def test_framework_home_matches_the_cli_default_or_explicit_override(
    override, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user"))
    if override is None:
        monkeypatch.delenv("A2APP_HOME")
    else:
        monkeypatch.setenv("A2APP_HOME", override)
    expected = (
        Path(override) if override and override.strip() else tmp_path / "user/.a2app"
    )
    assert framework.configured_cli().home == expected.resolve()
    assert not expected.exists()  # configuration itself creates no state


@pytest.mark.parametrize("package", [None, "", "   "])
def test_no_override_selects_the_bundled_package(
    action_json, package, monkeypatch, tmp_path
):
    if package is None:
        monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE")
    else:
        monkeypatch.setenv("CRAFTBOT_AGENT_APP_PACKAGE", package)
    selected = []
    caller_thread = threading.get_ident()

    def ensure_package():
        assert threading.get_ident() != caller_thread
        selected.append(True)
        return tmp_path / "bundled CLI"

    monkeypatch.setattr(framework.agent_app_package, "ensure_package", ensure_package)
    run = AsyncMock(
        return_value=CLIResult(0, '{"ok":true,"apps":[],"connected":[]}', "")
    )
    monkeypatch.setattr(AgentAppCLI, "run", run)
    result = execute(action_json)
    assert result["status"] == "success"
    assert selected == [True]
    run.assert_awaited_once()


def test_missing_package_is_reported_through_the_real_executor(action_json):
    result = execute(action_json)
    assert result["status"] == "error"
    assert "entry point is missing" in result["message"]


def test_real_action_automatically_uses_the_shipped_cli(
    action_json, tmp_path, monkeypatch
):
    from app import node_runtime, paths

    if node_runtime.resolve() is None:
        pytest.skip("CraftBot's Node runtime is required")
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE")
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    result = execute(action_json)
    assert result["status"] == "success", result
    assert result["data"]["apps"] == []
    assert Path(result["data"]["registry"]) == tmp_path / "framework home/registry.json"


@pytest.mark.parametrize(
    "outcome,message",
    [
        (CLIResult(2, '{"ok":true,"apps":[],"connected":[]}', "failed"), "exit code 2"),
        (CLIResult(124, "partial", "waiting", timed_out=True), "timed out"),
        (CLIResult(0, "not JSON", "warning"), "invalid registry response"),
        (CLIResult(0, "[]", ""), "invalid registry response"),
        (CLIResult(0, '{"ok":true,"apps":[]}', ""), "invalid registry response"),
        (
            CLIResult(0, '{"ok":false,"apps":[],"connected":[]}', ""),
            "invalid registry response",
        ),
        (
            CLIResult(0, '{"ok":true,"apps":{},"connected":[]}', ""),
            "invalid registry response",
        ),
    ],
)
def test_failed_or_malformed_cli_result_is_not_an_empty_success(
    action_json, monkeypatch, outcome, message
):
    monkeypatch.setattr(AgentAppCLI, "run", AsyncMock(return_value=outcome))
    result = execute(action_json)
    assert result["status"] == "error"
    assert message in result["message"]
    assert result["exit_code"] == outcome.code
    assert result["stdout"] == outcome.stdout
    assert result["stderr"] == outcome.stderr
    assert "data" not in result


def test_executor_cancellation_propagates_to_the_cli(action_json, monkeypatch):
    async def check():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def run(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(AgentAppCLI, "run", run)
        task = asyncio.create_task(
            _atomic_action_internal_async(ACTION, action_json["code"], {}, "CLI")
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(check())


@pytest.mark.skipif(
    not os.environ.get("CRAFTBOT_TEST_AGENT_APP_PACKAGE"),
    reason="set the unchanged built CLI package path to run this smoke test",
)
@pytest.mark.parametrize("populated", [False, True])
def test_real_executor_lists_the_unchanged_framework_registry(
    action_json, tmp_path, monkeypatch, populated
):
    monkeypatch.setenv(
        "CRAFTBOT_AGENT_APP_PACKAGE", os.environ["CRAFTBOT_TEST_AGENT_APP_PACKAGE"]
    )
    home = tmp_path / "framework home"
    registry = home / "registry.json"
    if populated:
        home.mkdir()
        # A registered directory that is absent has a deterministic 'missing'
        # status; no app server or real user's credentials are needed.
        registry.write_text(
            json.dumps(
                {
                    "version": 1,
                    "apps": [
                        {
                            "id": "fixture-id",
                            "name": "Fixture",
                            "path": str(tmp_path / "absent app"),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        before = registry.read_bytes()

    result = execute(action_json)
    assert result["status"] == "success", result
    data = result["data"]
    assert Path(data["registry"]) == registry
    assert data["connected"] == []
    if populated:
        (app,) = data["apps"]
        assert app["id"] == "fixture-id"
        assert app["status"] == "missing"
        assert registry.read_bytes() == before
        assert list(home.iterdir()) == [registry]
    else:
        assert data["apps"] == []
        assert not home.exists()
