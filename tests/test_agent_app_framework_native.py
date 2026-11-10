"""Real pinned CLI → bridge HTTP → native receiver → scoped CLI operation.

Set CRAFTBOT_TEST_ADAPTER_ENTRY to a built, unchanged upstream adapter-core
dist/index.js. Runtime/registry/app state is entirely disposable.
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import aiohttp

from app.agent_app import framework, framework_host
from app.agent_app.framework_bridge import TOKEN_ENV, capability_fingerprint
from app.agent_app.framework_commands import command
from app.agent_app.framework_host import FrameworkHost
from app.agent_app.framework_sharing import ShareGateway
from app.agent_app.framework_store import HostStore
from app import node_runtime
from tests.test_agent_app_framework_host import Sessions


@pytest.mark.skipif(not os.environ.get("CRAFTBOT_TEST_LEGACY_ADAPTER_ENTRY"), reason="Requires an unchanged protocol 0.1 adapter build")
def test_real_protocol01_owner_request_permission_and_completion(tmp_path, monkeypatch):
    home, app_dir = tmp_path / "home", tmp_path / "owner app"
    monkeypatch.setenv("A2APP_HOME", str(home))
    previous = framework_host._host

    async def check():
        process = await asyncio.create_subprocess_exec(
            node_runtime.resolve().node,
            str(Path(__file__).parent / "fixtures/framework-local-task-app.mjs"),
            os.environ["CRAFTBOT_TEST_LEGACY_ADAPTER_ENTRY"], str(app_dir), str(home),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        host = None
        try:
            first = await asyncio.wait_for(process.stdout.readline(), 15)
            assert first, (await process.stderr.read()).decode()
            fixture = json.loads(first)
            async def rpc(op, **values):
                process.stdin.write((json.dumps({"op": op, **values}) + "\n").encode())
                await process.stdin.drain()
                return json.loads(await asyncio.wait_for(process.stdout.readline(), 10))
            agent = SimpleNamespace(session_manager=Sessions(), trigger_service=SimpleNamespace(emit=AsyncMock()), request_run_stop=AsyncMock())
            host = FrameworkHost(agent, AsyncMock(), HostStore(tmp_path / "host.sqlite3"))
            attachment = await host.attach(str(app_dir), fixture["id"])
            task = await rpc("task")
            status = await host.bridge.request_status(str(app_dir), fixture["id"])
            assert status["permissionRequired"] and status["needsReview"]
            agent.trigger_service.emit.assert_not_awaited()
            await host.bridge.consent(str(app_dir), fixture["id"], True, revision=status["revision"], review_id=status["reviewId"])
            for _ in range(80):
                if agent.trigger_service.emit.await_args:
                    break
                await asyncio.sleep(.25)
            assert agent.trigger_service.emit.await_args, host.store.all("attachment")
            spec = agent.trigger_service.emit.await_args.args[0]
            assert spec.session_id == attachment["sessionId"]
            assert len(agent.session_manager.sessions) == 1
            run = host.bridge.runs[spec.payload["framework_task_key"]]
            assert run["localOwner"] and "run_shell" not in run["authority"].allowed_actions
            async def turn(_):
                notes = await command("a2app", [fixture["base"], "data", "notes", "list"])
                assert notes["status"] == "success", notes
                assert notes["data"]["items"][0]["title"] == "Round-trip note"
                result = await command("a2app", [fixture["base"], "tasks", "complete", task["taskId"], "--summary", "Read the note through CraftBot"])
                assert result["status"] == "success", result
                await host.bridge.ended(spec.session_id)
            await host.bridge.run_turn(spec.session_id, spec, turn)
            assert (await rpc("status", id=task["taskId"]))["status"] == "completed"
            assert host.store.all("delivery")[0]["status"] == "completed"
            assert "disposable-local-owner" not in json.dumps(await host.snapshot())
        finally:
            if host:
                await host.close()
            if process.returncode is None:
                process.terminate()
            await process.wait()
    try:
        asyncio.run(check())
    finally:
        framework_host._host = previous


@pytest.mark.skipif(
    not os.environ.get("CRAFTBOT_TEST_ADAPTER_ENTRY"),
    reason="Set CRAFTBOT_TEST_ADAPTER_ENTRY to the unchanged built adapter-core entry point",
)
def test_real_bridge_delegates_member_authority_and_native_cancellation(
    tmp_path, monkeypatch
):
    home, app_dir = tmp_path / "home", tmp_path / "app with spaces"
    monkeypatch.setenv("A2APP_HOME", str(home))
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    old_host = framework_host._host

    async def check():
        runtime = node_runtime.resolve()
        process = await asyncio.create_subprocess_exec(
            runtime.node,
            str(Path(__file__).parent / "fixtures/framework-task-app.mjs"),
            os.environ["CRAFTBOT_TEST_ADAPTER_ENTRY"],
            str(app_dir),
            str(home),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **(
                {"creationflags": subprocess.CREATE_NO_WINDOW}
                if os.name == "nt"
                else {}
            ),
        )
        host = None
        gateway = None
        try:
            first = await asyncio.wait_for(process.stdout.readline(), 15)
            assert first, (await process.stderr.read()).decode()
            fixture = json.loads(first)
            gateway = ShareGateway(fixture["port"], fixture["id"])
            share_port = await gateway.start()
            share_origin = f"http://127.0.0.1:{share_port}"
            gateway.origin = share_origin
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True)
            ) as visitor:
                await visitor.get(share_origin + "/?a2app_share=" + gateway.secret)
                anonymous = await visitor.get(
                    share_origin + "/api/collections/notes/records"
                )
                assert anonymous.status == 401
                login = await visitor.post(
                    share_origin + "/api/_a2app/session",
                    headers={"Origin": share_origin},
                    json={"login": "member", "password": "fixture long password"},
                )
                assert login.status == 200, await login.text()
                notes = await visitor.get(
                    share_origin + "/api/collections/notes/records"
                )
                assert notes.status == 200, await notes.text()
                assert [note["title"] for note in (await notes.json())["items"]] == [
                    "Member note"
                ]

            async def rpc(op, **values):
                process.stdin.write((json.dumps({"op": op, **values}) + "\n").encode())
                await process.stdin.drain()
                return json.loads(await asyncio.wait_for(process.stdout.readline(), 10))

            agent = SimpleNamespace(
                session_manager=Sessions(),
                trigger_service=SimpleNamespace(emit=AsyncMock()),
                request_run_stop=AsyncMock(),
            )
            host = FrameworkHost(
                agent, AsyncMock(), HostStore(tmp_path / "host.sqlite3")
            )
            # Exercise the same account commands exposed by Advanced settings.
            # These links and accounts exist only inside this disposable adapter.
            async with aiohttp.ClientSession() as accounts:
                for verb, role in (("owner", "owner"), ("invite", "member")):
                    issued = await host.request(
                        {
                            "operation": "manage",
                            "path": str(app_dir),
                            "appId": fixture["id"],
                            "verb": verb,
                        }
                    )
                    assert issued["status"] == "success"
                    assert issued["data"]["role"] == role
                    code = issued["data"]["url"].split("#setup/", 1)[1]
                    endpoint = fixture["base"] + "/api/_a2app/invites/" + code
                    signup = {
                        "name": "QA " + role,
                        "login": "qa-" + role,
                        "password": "disposable test password",
                    }
                    response = await accounts.post(
                        endpoint, headers={"Origin": fixture["base"]}, json=signup
                    )
                    assert response.status == 201
                    replay = await accounts.post(
                        endpoint, headers={"Origin": fixture["base"]}, json=signup
                    )
                    assert replay.status != 201
                    assert code not in json.dumps(host.store.all("attachment"))
            attachment = await host.attach(str(app_dir), fixture["id"])
            attachment.update(
                tasksAllowed=True,
                capabilityFingerprint=capability_fingerprint(str(app_dir)),
            )
            host.store.put("attachment", attachment["key"], attachment)
            await host.bridge.start()
            cli = framework.configured_cli()

            async def deliver():
                task = await rpc("task")
                result = await cli.run(
                    "agent-app",
                    [
                        str(app_dir),
                        "bridge",
                        "start",
                        "--once",
                        "--harness",
                        host.bridge.profile_id,
                    ],
                    cwd=cli.package_dir,
                    timeout=35,
                    env_extra={TOKEN_ENV: host.bridge.token},
                )
                assert result.ok, result.stderr
                assert agent.trigger_service.emit.await_args
                spec = agent.trigger_service.emit.await_args.args[0]
                return task["taskId"], spec

            task_id, spec = await deliver()
            assert spec.payload["workflow_skills"] == ["framework-operator"]
            observed = {}

            async def react(_):
                # Execute extracted native action source, as a real model turn does.
                import inspect
                from agent_core.core.impl.action.executor import (
                    _atomic_action_internal_async,
                )
                from app.data.action.agent_app_framework_actions import (
                    agent_app_framework_command,
                )

                source = inspect.getsource(agent_app_framework_command)
                source = source[source.index("async def ") :]
                observed["who"] = await _atomic_action_internal_async(
                    "agent_app_framework_command",
                    source,
                    {"surface": "a2app", "args": [fixture["base"], "whoami"]},
                    "CLI",
                )
                observed["notes"] = await command(
                    "a2app", [fixture["base"], "data", "notes", "list"]
                )
                observed["context"] = await command(
                    "a2app", [fixture["base"], "context"]
                )
                observed["write"] = await command(
                    "a2app",
                    [
                        fixture["base"],
                        "data",
                        "notes",
                        "create",
                        "--title",
                        "Forbidden",
                    ],
                )
                observed["complete"] = await command(
                    "a2app",
                    [
                        fixture["base"],
                        "tasks",
                        "complete",
                        task_id,
                        "--summary",
                        "Read the member's note",
                    ],
                )
                from app.agent_base import AgentBase

                agent.state_manager = SimpleNamespace(bump_event_stream=Mock())
                agent.session_manager.touch_session = Mock()
                agent._check_agent_limits = AsyncMock(return_value=False)
                agent._warn_if_undeployed = AsyncMock()
                agent._on_run_end = AsyncMock()
                await AgentBase._finalize_turn(
                    agent,
                    agent.session_manager.get(spec.session_id),
                    spec,
                    observed["complete"],
                )

            await host.bridge.run_turn(spec.session_id, spec, react)
            assert observed["who"]["data"]["principal"] == fixture["member"]
            assert [r["title"] for r in observed["notes"]["data"]["items"]] == [
                "Member note"
            ]
            assert observed["write"]["status"] == "error"
            assert observed["context"]["status"] == "success"
            assert observed["context"]["data"] == {"a2app": True, "view": None, "selected": []}
            assert observed["complete"]["status"] == "success"
            agent._on_run_end.assert_awaited_once()
            agent._check_agent_limits.assert_not_awaited()
            assert agent.trigger_service.emit.await_count == 1
            assert (await rpc("status", id=task_id))["status"] == "completed"
            assert host.store.all("delivery")[0]["status"] == "completed"
            task_id, spec = await deliver()
            await rpc("cancel", id=task_id)
            never = AsyncMock()
            await host.bridge.run_turn(spec.session_id, spec, never)
            await asyncio.sleep(0)
            never.assert_not_awaited()
            agent.request_run_stop.assert_not_awaited()
            assert (await rpc("status", id=task_id))["status"] == "canceled"
        finally:
            if gateway:
                await gateway.stop()
            if host:
                await host.close()
            if process.returncode is None:
                process.terminate()
            await process.wait()

    try:
        asyncio.run(check())
    finally:
        framework_host._host = old_host
