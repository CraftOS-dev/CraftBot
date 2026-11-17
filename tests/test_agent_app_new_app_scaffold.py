"""New apps never see the bundled Kanban's toolkit."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

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
