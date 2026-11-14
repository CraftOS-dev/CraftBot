"""New apps start from one upstream blueprint, never the bundled Kanban's toolkit."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.agent_app import framework_host
from app.agent_app.framework_store import HostStore
from app.provision import default_agent_app as default


def _cli(tmp_path, monkeypatch):
    from app import node_runtime, paths
    from app.agent_app.framework_cli import AgentAppCLI

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/agent-app.js").touch()
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(
        node_runtime,
        "resolve",
        lambda: SimpleNamespace(node=sys.executable, version="v24.0.0"),
    )
    monkeypatch.setattr(node_runtime, "child_env", lambda: {})
    monkeypatch.setattr("app.config.get_framework_toolkits_dir", lambda: None)
    return AgentAppCLI(tmp_path, home=tmp_path / "registry")


def test_listing_and_scaffolding_never_see_the_bundled_kanban_toolkit(
    tmp_path, monkeypatch
):
    cli = _cli(tmp_path, monkeypatch)

    def unexpected(*args, **kwargs):
        pytest.fail("A new app must not be offered the bundled Kanban toolkit")

    monkeypatch.setattr(default, "bundled_toolkits", unexpected)
    assert "A2APP_TOOLKITS_DIR" not in cli._prepare("agent-app", {}, True)[1]
    # A toolkit folder the user configured is still offered.
    monkeypatch.setattr("app.config.get_framework_toolkits_dir", lambda: "configured")
    assert cli._prepare("agent-app", {}, True)[1]["A2APP_TOOLKITS_DIR"] == "configured"

    seen = []

    class Stop(Exception):
        pass

    def prepare(surface, extra, new_app=False):
        seen.append(new_app)
        raise Stop

    monkeypatch.setattr(cli, "_prepare", prepare)
    app = str(tmp_path / "app")
    for args in (
        ["blueprints"],
        [app, "scaffold", "--blueprint", "blueprint-pocketbase-react"],
        # Apps already built on the toolkit still resolve it.
        [app, "validate"],
        [app, "promote"],
        ["install", "kanban-board"],
    ):
        with pytest.raises(Stop):
            asyncio.run(cli.run("agent-app", args, cwd=tmp_path))
    assert seen == [True, True, False, False, False]


class _Agent:
    def __init__(self):
        self.calls = []
        self.deleted = []
        self.session_manager = SimpleNamespace(create_session=self._create)
        self.trigger_service = SimpleNamespace(emit=self._emit)

    def _create(self, **kwargs):
        self.calls.append(("session", kwargs))
        return SimpleNamespace(id="build-session")

    async def _emit(self, spec):
        self.calls.append(("trigger", spec.description))

    async def delete_session(self, session_id):
        self.deleted.append(session_id)
        return True


def _host(tmp_path, monkeypatch, result):
    monkeypatch.setattr(framework_host, "_host", None)
    monkeypatch.setattr(
        framework_host.framework,
        "configured_cli",
        lambda: SimpleNamespace(home=tmp_path / "home"),
    )
    agent = _Agent()

    async def command(surface, args):
        agent.calls.append(("command", surface, args))
        return result

    monkeypatch.setattr(framework_host, "command", command)
    host = framework_host.FrameworkHost(agent, store=HostStore(tmp_path / "host.sqlite3"))
    return host, agent


def test_create_scaffolds_the_starter_before_the_builder_runs(tmp_path, monkeypatch):
    host, agent = _host(
        tmp_path,
        monkeypatch,
        {"status": "success", "data": {"id": "1e60ba80f83f"}, "stderr": ""},
    )
    result = asyncio.run(
        host.workflow(
            "create",
            "Build a clock",
            creation={"name": "Clock app", "authMode": "multi-user"},
        )
    )

    kinds = [call[0] for call in agent.calls]
    assert kinds == ["session", "command", "trigger"]
    _, surface, args = agent.calls[1]
    assert surface == "agent-app"
    assert args == [
        result["path"],
        "scaffold",
        "--blueprint",
        "blueprint-pocketbase-react",
        "--name",
        "Clock app",
        "--auth-mode",
        "multi-user",
    ]
    prompt = agent.calls[2][1]
    assert "already scaffolded this app from blueprint-pocketbase-react" in prompt
    assert "Do not scaffold again or choose another blueprint" in prompt
    assert "1e60ba80f83f" in prompt
    assert "Discover the blueprints" not in prompt
    assert host.store.get("creation", "build-session")["building"] is True


def test_failed_scaffold_removes_the_empty_build_conversation(tmp_path, monkeypatch):
    host, agent = _host(
        tmp_path,
        monkeypatch,
        {"status": "error", "data": None, "stderr": "scaffold refused\n"},
    )
    with pytest.raises(RuntimeError, match="scaffold refused"):
        asyncio.run(
            host.workflow(
                "create",
                "Build a clock",
                creation={"name": "Clock app", "authMode": "none"},
            )
        )

    assert "trigger" not in [call[0] for call in agent.calls]
    assert agent.deleted == ["build-session"]
    assert host.store.get("creation", "build-session") is None
    assert host.store.get("conversation", "build-session") is None
