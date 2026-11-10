"""Opt-in real default installation and app → CraftBot → app task round-trip.

Downloads declared Node/PocketBase dependencies. No model is called: the normal
native task runner executes a deterministic turn using its delegated credential.
"""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession

from app import paths
from app.agent_app import framework, framework_bridge, framework_host
from app.agent_app.framework_commands import command
from app.agent_app.framework_host import FrameworkHost
from app.agent_app.framework_store import HostStore
from app.provision.default_agent_app import install_bundled_app, prepare_install
from app.provision.types import Context
from tests.test_agent_app_framework_host import Sessions


@pytest.mark.skipif(
    os.environ.get("CRAFTBOT_TEST_BUNDLED_BOARD") != "1",
    reason="Opt in to real dependency downloads with CRAFTBOT_TEST_BUNDLED_BOARD=1",
)
def test_default_install_restart_and_delegated_board_work(tmp_path, monkeypatch):
    state = tmp_path / "fresh state"
    home = tmp_path / "framework home"
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(paths, "STATE_ROOT", state)
    monkeypatch.setattr(framework_bridge, "STATE_ROOT", state)
    monkeypatch.setenv("A2APP_HOME", str(home))
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    previous = framework_host._host

    async def check():
        prepare_install(
            Context(code_root=str(root), state_root=str(state), new_install=True)
        )
        cli = framework.configured_cli()
        destination = state / "agent-apps/kanban-board"
        host = None
        try:
            await install_bundled_app(root, state)
            rows = (await framework.list_apps())["data"]["apps"]
            assert len(rows) == 1 and rows[0]["status"] == "running"
            row = rows[0]
            assert row["id"] != "077f56de99e4"  # publisher's verification instance
            await install_bundled_app(root, state)
            assert len((await framework.list_apps())["data"]["apps"]) == 1
            agent = SimpleNamespace(
                session_manager=Sessions(),
                trigger_service=SimpleNamespace(emit=AsyncMock()),
                request_run_stop=AsyncMock(),
            )
            host = FrameworkHost(
                agent, AsyncMock(), HostStore(state / "agent-app-host.sqlite3")
            )
            stopped = await framework.change_app_state(row["path"], row["id"], "stop")
            assert stopped["status"] == "success", stopped
            await host.startup()
            attachment = host.store.all("attachment")[0]
            assert attachment["sessionId"] and attachment.get("startError") is None
            agent.trigger_service.emit.assert_not_called()
            opened = await framework.open_app_view(row["path"], row["id"])
            assert opened["status"] == "success", opened
            base = opened["data"]["url"]
            # The local owner's View uses the framework's same-origin route;
            # the worker below must use its separately delegated credential.
            async with ClientSession(
                headers={"Origin": base, "Sec-Fetch-Site": "same-origin"}
            ) as http:

                async def op(operation_name, **params):
                    async with http.post(
                        base + "/api/ops/" + operation_name, json=params
                    ) as response:
                        body = await response.json()
                        assert response.status == 200, body
                        return body["result"]

                board = await op(
                    "boards-create",
                    name="Native task round-trip",
                    key="SMOKE",
                    template="simple",
                )
                assert board
                detail = await op("boards-get", board="SMOKE")
                assert not detail["cards"]
                column = next(c for c in detail["columns"] if c["category"] == "doing")
                await host.bridge.consent(row["path"], row["id"], True)
                card = await op(
                    "cards-add",
                    board="SMOKE",
                    title="Bridge integration proof",
                    column=column["id"],
                    assignee="agent",
                )
                assert card
                for _ in range(120):
                    if agent.trigger_service.emit.await_args:
                        break
                    await asyncio.sleep(0.25)
                assert agent.trigger_service.emit.await_args, host.store.all(
                    "attachment"
                )
                spec = agent.trigger_service.emit.await_args.args[0]
                run = host.bridge.runs[spec.payload["framework_task_key"]]
                task_id = run["taskId"]
                observed = {}

                async def turn(_):
                    observed["queue"] = await command(
                        "a2app", [base, "work", "work-queue"]
                    )
                    observed["comment"] = await command(
                        "a2app",
                        [
                            base,
                            "cards",
                            "cards-comment",
                            "--card",
                            "SMOKE-1",
                            "--text",
                            "Round-trip through CraftBot delegated authority",
                        ],
                    )
                    observed["complete"] = await command(
                        "a2app",
                        [
                            base,
                            "tasks",
                            "complete",
                            task_id,
                            "--summary",
                            "Native integration proof",
                        ],
                    )
                    await host.bridge.ended(spec.session_id)

                await host.bridge.run_turn(spec.session_id, spec, turn)
                assert all(
                    value["status"] == "success" for value in observed.values()
                ), observed
                assert len(observed) == 3
                assert host.store.all("delivery")[0]["status"] == "completed"
                card = await op("cards-get", card="SMOKE-1")
                assert "Round-trip through CraftBot delegated authority" in json.dumps(
                    card
                )
                await host.bridge.consent(row["path"], row["id"], False)
            assert not (state / "agent_file_system/workspace/agent-apps").exists()
        finally:
            if host:
                await host.close()
            if destination.exists():
                await cli.run(
                    "agent-app",
                    [str(destination), "stop"],
                    cwd=cli.package_dir,
                    timeout=60,
                )

    try:
        asyncio.run(check())
    finally:
        framework_host._host = previous
