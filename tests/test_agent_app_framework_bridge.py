"""HTTP handoff responsibility, claim guards and restart isolation."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from app.agent_app.framework_bridge import capability_fingerprint, register_profile
from app.agent_app.framework_commands import task_authority
from app.agent_app.framework_cli import CLIResult
from tests import test_agent_app_framework_host as host_tests

fixture = host_tests.fixture


def delivered(host):
    spec = host.agent.trigger_service.emit.await_args.args[0]
    return host.bridge.runs[spec.payload["framework_task_key"]]


@pytest.mark.parametrize(
    "result",
    [
        CLIResult(1, "", "unavailable"),
        CLIResult(0, "{}", ""),
        CLIResult(0, '{"running":{"harness":"another-host"}}', ""),
    ],
)
def test_unknown_or_foreign_bridge_is_not_stopped(fixture, result):
    host, cli, row = fixture
    host.bridge.start = AsyncMock()
    cli.run.return_value = result

    async def check():
        with pytest.raises((ValueError, RuntimeError)):
            await host.bridge.consent(row["path"], row["id"], True)
        assert cli.run.await_count == 1
        assert cli.run.await_args.args[1][1:3] == ["bridge", "status"]

    asyncio.run(check())


async def prepared(fixture, *, owner=False):
    host, _, row = fixture
    attachment = await host.attach(row["path"], row["id"])
    attachment.update(
        tasksAllowed=True, capabilityFingerprint=capability_fingerprint(row["path"])
    )
    host.store.put("attachment", attachment["key"], attachment)
    task = {
        "id": "task1",
        "app": row["id"],
        "status": "working",
        "claim": {
            "credentialId": "bridge",
            "principal": "owner",
            "claimedAt": "2026-11-09T12:00:00Z",
        },
        "request": {
            "principal": "owner" if owner else "member1",
            "capability": "summarize",
            "payload": {"title": "untrusted content"},
        },
    }

    async def request(target, route, token, method="GET", body=None):
        assert token == ("" if route == "/api/_a2app" else "delegated-secret")
        if route == "/api/_a2app":
            return {"app": {"id": row["id"]}}
        if route.endswith("whoami"):
            return {"principal": "owner" if owner else "member1", "scopes": ["data:notes:read"]}
        if route.endswith("/complete"):
            task["status"] = body["status"]
        return deepcopy(task)

    host.bridge.http_json = AsyncMock(side_effect=request)
    body = {
        "a2app": True,
        "protocol": "0.2",
        "app": {"id": row["id"], "ref": row["path"]},
        "task": deepcopy(task),
        "credential": {"token": "delegated-secret"},
        "prompt": "malicious replacement prompt",
    }
    return host, task, body


def test_owner_request_uses_connected_conversation_and_leaves_normal_chat_usable(fixture):
    from app.agent_app.framework_bridge import FrameworkBridge

    async def check():
        host, _, body = await prepared(fixture, owner=True)
        attached = host.store.all("attachment")[0]
        session = host.agent.session_manager.get(attached["sessionId"])
        session.title = "Existing board conversation"
        result = await host.bridge.accept(body)
        assert result["sessionId"] == session.id
        assert len(host.agent.session_manager.sessions) == 1
        assert session.title == "Existing board conversation"
        assert not session.isolated_app_task
        assert not host.bridge.is_task_session(session.id)
        spec = host.agent.trigger_service.emit.await_args.args[0]
        run = delivered(host)
        normal = SimpleNamespace(source="user_message", payload={})
        assert host.bridge.is_task_turn(session.id, spec)
        assert not host.bridge.is_task_turn(session.id, normal)
        # A normal user turn ending while this request is queued cannot fail it.
        await host.bridge.ended(session.id)
        assert run["authority"].active

        async def turn(_):
            assert task_authority.get() is run["authority"]
            run["authority"].outcome = "completed"
            run["authority"].active = False
            await host.bridge.ended(session.id)
        await host.bridge.run_turn(session.id, spec, turn)
        assert run["status"] == "completed"
        assert not host.bridge.is_task_turn(session.id, normal)
        restarted = FrameworkBridge(host)
        assert not restarted.is_task_turn(session.id, normal)
        assert restarted.is_task_turn(session.id, spec)
        # A replayed task after restart is ignored, never run with owner authority.
        never = AsyncMock()
        await restarted.run_turn(session.id, spec, never)
        never.assert_not_awaited()
        assert task_authority.get() is None
        await host.bridge.close()
    asyncio.run(check())


def test_multiple_owner_requests_keep_separate_authority_in_one_conversation(fixture):
    async def check():
        host, task, body = await prepared(fixture, owner=True)
        tasks = {task["id"]: deepcopy(task)}
        original = host.bridge.http_json.side_effect
        async def request(target, route, token, method="GET", body=None):
            if route.startswith("/api/_a2app/tasks/"):
                return deepcopy(tasks[route.split("/")[4]])
            return await original(target, route, token, method, body)
        host.bridge.http_json.side_effect = request
        first = await host.bridge.accept(body)
        spec1 = host.agent.trigger_service.emit.await_args.args[0]
        body2 = deepcopy(body)
        body2["task"]["id"] = "task2"
        tasks["task2"] = deepcopy(body2["task"])
        second = await host.bridge.accept(body2)
        spec2 = host.agent.trigger_service.emit.await_args.args[0]
        assert first["sessionId"] == second["sessionId"]
        assert len(host.agent.session_manager.sessions) == 1
        assert (await host.bridge.accept(body))["duplicate"]
        seen = []
        async def turn(_):
            seen.append(task_authority.get().task_id)
        await host.bridge.run_turn(first["sessionId"], spec1, turn)
        await host.bridge.run_turn(second["sessionId"], spec2, turn)
        continuation = SimpleNamespace(source="run_continuation", payload=dict(spec1.payload))
        await host.bridge.run_turn(first["sessionId"], continuation, turn)
        assert seen == ["task1", "task2", "task1"]
        # A trigger cannot take its credential to another conversation.
        await host.bridge.run_turn("main", spec1, turn)
        assert len(seen) == 3
        await host.bridge.close()
    asyncio.run(check())


def test_owner_question_resumes_in_same_chat_and_carries_task_identity(fixture):
    async def check():
        host, _, body = await prepared(fixture, owner=True)
        result = await host.bridge.accept(body)
        sid = result["sessionId"]
        spec = host.agent.trigger_service.emit.await_args.args[0]
        run = delivered(host)
        async def ask(_):
            run["ask"] = {"message": "Which board?"}
            await host.bridge.ended(sid, awaiting_answer=True)
        await host.bridge.run_turn(sid, spec, ask)
        reply = SimpleNamespace(source="user_message", payload={})
        assert host.bridge.is_task_turn(sid, reply)
        async def answer(trigger):
            assert task_authority.get().task_id == "task1"
            assert trigger.payload["framework_task_key"] == run["key"]
            assert run["ask"] is None
        await host.bridge.run_turn(sid, reply, answer)
        await host.bridge.close()
    asyncio.run(check())


def test_canceled_queued_request_does_not_stop_the_connected_chat(fixture):
    async def check():
        host, _, body = await prepared(fixture, owner=True)
        await host.bridge.accept(body)
        run = delivered(host)
        await host.bridge.terminate(run, "consent_revoked", settle=False)
        await asyncio.sleep(0)
        host.agent.request_run_stop.assert_not_awaited()
        assert not run["authority"].active
        await host.bridge.close()
    asyncio.run(check())


def test_delivery_is_scoped_deduplicated_and_contains_no_secret(fixture):
    async def check():
        host, _, body = await prepared(fixture)
        result = await host.bridge.accept(body)
        duplicate = await host.bridge.accept(body)
        assert duplicate["duplicate"] is True
        assert result["sessionId"] == duplicate["sessionId"]
        spec = host.agent.trigger_service.emit.await_args.args[0]
        assert "delegated-secret" not in spec.description
        assert "malicious replacement prompt" not in spec.description
        assert spec.source == "framework_task"
        assert host.agent.session_manager.get(result["sessionId"]).isolated_app_task
        assert "delegated-secret" not in json.dumps(host.store.all("delivery"))
        assert host.agent.trigger_service.emit.await_count == 1

        async def react(trigger):
            assert task_authority.get().target == "http://127.0.0.1:8123"
            assert task_authority.get().token == "delegated-secret"

        await host.bridge.run_turn(result["sessionId"], spec, react)
        assert task_authority.get() is None
        await host.bridge.close()

    asyncio.run(check())


@pytest.mark.parametrize("outcome", ["completed", "failed", "canceled"])
def test_terminal_command_finishes_host_turn_without_continuation(fixture, outcome):
    from app.agent_base import AgentBase
    from app.agent_app.framework_commands import command

    async def check():
        host, _, body = await prepared(fixture)
        result = await host.bridge.accept(body)
        sid = result["sessionId"]
        spec = host.agent.trigger_service.emit.await_args.args[0]
        agent = SimpleNamespace(
            state_manager=SimpleNamespace(bump_event_stream=Mock()),
            session_manager=SimpleNamespace(touch_session=Mock()),
            _check_agent_limits=AsyncMock(return_value=False),
            _warn_if_undeployed=AsyncMock(),
            _on_run_end=AsyncMock(),
            trigger_service=SimpleNamespace(emit=AsyncMock()),
        )
        fixture[1].run.return_value = CLIResult(
            0, json.dumps({"id": "task1", "status": outcome}), ""
        )

        async def react(trigger):
            output = await command(
                "a2app",
                ["http://127.0.0.1:8123", "tasks", "complete", "task1"],
            )
            # CLI actions do not normally end a model run. The host must notice
            # the terminal task before checking budgets or queuing another turn.
            assert "run_ends" not in output
            await AgentBase._finalize_turn(
                agent, host.agent.session_manager.get(sid), trigger, output
            )

        await host.bridge.run_turn(sid, spec, react)
        run = delivered(host)
        assert host.store.get("delivery", run["key"])["status"] == outcome
        assert not run["authority"].active
        assert run["authority"].token == ""
        agent._check_agent_limits.assert_not_awaited()
        agent._on_run_end.assert_awaited_once()
        agent.trigger_service.emit.assert_not_awaited()
        assert task_authority.get() is None
        await host.bridge.close()

    asyncio.run(check())


@pytest.mark.parametrize("owner,granted", [(True, False), (True, True), (False, True)])
def test_workspace_tools_require_both_owner_principal_and_explicit_grant(
    fixture, owner, granted
):
    async def check():
        host, task, body = await prepared(fixture)
        attachment = host.store.all("attachment")[0]
        attachment["ownerToolsAllowed"] = granted
        host.store.put("attachment", attachment["key"], attachment)
        if owner:
            task["request"]["principal"] = None
            body["task"]["request"]["principal"] = None
            original = host.bridge.http_json.side_effect

            async def request(target, route, token, method="GET", body=None):
                if route.endswith("whoami"):
                    return {"principal": "owner", "scopes": ["data:notes:read"]}
                return await original(target, route, token, method, body)

            host.bridge.http_json.side_effect = request
        await host.bridge.accept(body)
        authority = delivered(host)["authority"]
        assert ("run_shell" in authority.allowed_actions) is (owner and granted)
        assert "send_message" in authority.allowed_actions
        assert "agent_app_framework_workflow" not in authority.allowed_actions
        attachment["ownerToolsAllowed"] = not granted
        host.store.put("attachment", attachment["key"], attachment)
        with pytest.raises(PermissionError, match="workspace permission"):
            await authority.check()
        await host.bridge.close()

    asyncio.run(check())


def test_claim_change_stops_actual_run_without_settling_the_new_attempt(fixture):
    async def check():
        host, current, body = await prepared(fixture)
        result = await host.bridge.accept(body)
        run = delivered(host)
        current["claim"]["claimedAt"] = "new attempt"
        react = AsyncMock()
        await host.bridge.run_turn(
            result["sessionId"],
            host.agent.trigger_service.emit.await_args.args[0],
            react,
        )
        await asyncio.sleep(0)
        assert not run["authority"].active
        react.assert_not_awaited()
        # The canceled request never started; do not stop other work in the chat.
        host.agent.request_run_stop.assert_not_awaited()
        assert not any(
            call.args[1].endswith("/complete")
            for call in host.bridge.http_json.await_args_list
        )
        await host.bridge.close()

    asyncio.run(check())


def test_question_heartbeat_preserves_input_required(fixture, monkeypatch):
    async def check():
        host, _, body = await prepared(fixture)
        result = await host.bridge.accept(body)
        async def turn(_):
            await host.bridge.ended(result["sessionId"], awaiting_answer=True)
        await host.bridge.run_turn(result["sessionId"], host.agent.trigger_service.emit.await_args.args[0], turn)
        run = delivered(host)
        assert run["status"] == "input-required"
        await asyncio.sleep(0)
        calls = [
            c
            for c in host.bridge.http_json.await_args_list
            if c.args[1].endswith("/progress")
        ]
        first_ask = next(i for i, call in enumerate(calls) if "ask" in call.args[4])
        assert all("ask" in c.args[4] for c in calls[first_ask:])
        await host.bridge.close()

    asyncio.run(check())


def test_restart_never_reuses_or_replays_delegated_authority(fixture):
    from app.agent_app.framework_bridge import FrameworkBridge

    async def check():
        host, _, body = await prepared(fixture)
        result = await host.bridge.accept(body)
        for monitor in host.bridge.monitors.values():
            monitor.cancel()
        await asyncio.gather(*host.bridge.monitors.values(), return_exceptions=True)
        restarted = FrameworkBridge(host)
        restarted.http_json = host.bridge.http_json
        assert restarted.is_task_session(result["sessionId"])
        react = AsyncMock()
        await restarted.run_turn(result["sessionId"], None, react)
        react.assert_not_awaited()
        with pytest.raises(PermissionError):
            await restarted.accept(body)
        assert host.store.all("delivery")[0]["status"] == "interrupted"

    asyncio.run(check())


def test_endpoint_requires_its_private_token(fixture):
    async def check():
        host, _, _ = await prepared(fixture)
        app = web.Application()
        app.router.add_post("/tasks", host.bridge.handle)
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/tasks", json={})
            assert response.status == 401
            response = await client.post(
                "/tasks",
                json={},
                headers={"Authorization": "Bearer " + host.bridge.token},
            )
            assert response.status == 409
        host.agent.trigger_service.emit.assert_not_awaited()

    asyncio.run(check())


@pytest.mark.parametrize("protocol,principal,auth_mode,credential_id,accepted", [
    ("0.1", "owner", "none", "bridge", True),
    ("0.1", "member1", "none", "bridge", False),
    ("0.1", "owner", "users", "bridge", False),
    ("0.1", "owner", "none", "another", False),
    ("0.2", "owner", "none", "bridge", False),
])
def test_credentialless_delivery_is_only_a_verified_local_owner_task(
    fixture, monkeypatch, protocol, principal, auth_mode, credential_id, accepted
):
    from pathlib import Path
    from app.agent_app import framework_bridge

    async def check():
        host, task, body = await prepared(fixture)
        row = fixture[2]
        Path(row["path"], "manifest.json").write_text(json.dumps({"id": row["id"], "authMode": auth_mode}))
        grant = host.store.all("attachment")[0]
        grant["capabilityFingerprint"] = capability_fingerprint(row["path"])
        host.store.put("attachment", grant["key"], grant)
        task["request"]["principal"] = principal
        body["task"] = deepcopy(task)
        del body["credential"]
        original = host.bridge.http_json.side_effect

        async def request(target, route, token, method="GET", body=None):
            if route == "/api/_a2app":
                return {"app": {"id": row["id"]}, "protocol": protocol}
            if route.endswith("whoami"):
                return {"principal": principal, "credentialId": credential_id}
            return await original(target, route, token, method, body)

        host.bridge.http_json.side_effect = request
        credential = AsyncMock(return_value="delegated-secret")
        monkeypatch.setattr(framework_bridge, "local_owner_token", credential)
        if accepted:
            await host.bridge.accept(body)
            assert delivered(host)["localOwner"]
            assert "delegated-secret" not in json.dumps(host.store.all("delivery"))
            assert "run_shell" not in delivered(host)["authority"].allowed_actions
            await host.bridge.close()
        else:
            with pytest.raises(ValueError):
                await host.bridge.accept(body)
            host.agent.trigger_service.emit.assert_not_awaited()
            if protocol != "0.1" or principal != "owner" or auth_mode != "none":
                credential.assert_not_awaited()
    asyncio.run(check())


def test_delivery_failure_is_visible_without_leaking_secrets(fixture):
    async def check():
        host, _, body = await prepared(fixture)
        host.bridge.http_json.side_effect = RuntimeError("secret-credential-in-upstream-error")
        app = web.Application()
        app.router.add_post("/tasks", host.bridge.handle)
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/tasks", json=body, headers={"Authorization": "Bearer " + host.bridge.token})
            assert response.status == 503
        snapshot = await host.snapshot()
        assert "could not accept" in snapshot["attachments"][0]["bridgeError"]
        assert "secret-credential" not in json.dumps(snapshot)
        host.agent.trigger_service.emit.assert_not_awaited()
    asyncio.run(check())


def test_permission_prompt_tracks_pending_requests_and_changed_source(fixture, monkeypatch):
    from pathlib import Path
    from app.agent_app import framework_bridge

    async def check():
        host, _, row = fixture
        grant = await host.attach(row["path"], row["id"])
        pending = [{"id": "first", "capability": "reviews_waiting"}]
        monkeypatch.setattr(framework_bridge, "pending_tasks", AsyncMock(side_effect=lambda *a: deepcopy(pending)))
        state = await host.bridge.request_status(row["path"], row["id"])
        assert state["permissionRequired"] and state["needsReview"]
        grant["reviewedRequest"] = state["reviewId"]
        host.store.put("attachment", grant["key"], grant)
        assert not (await host.bridge.request_status(row["path"], row["id"]))["needsReview"]
        pending[0]["id"] = "second"
        assert (await host.bridge.request_status(row["path"], row["id"]))["needsReview"]
        grant.update(tasksAllowed=True, capabilityFingerprint=state["revision"])
        host.store.put("attachment", grant["key"], grant)
        assert not (await host.bridge.request_status(row["path"], row["id"]))["permissionRequired"]
        Path(row["path"], "changed.js").write_text("// new app code")
        assert (await host.bridge.request_status(row["path"], row["id"]))["permissionRequired"]
        with pytest.raises(ValueError, match="app changed"):
            await host.bridge.consent(row["path"], row["id"], True, revision=state["revision"])
        pending.clear()
        assert not (await host.bridge.request_status(row["path"], row["id"]))["needsReview"]
        await host.bridge.delivery_error(
            {"app": {"id": row["id"], "ref": row["path"]}, "task": {"id": "failed", "request": {"capability": "summarize"}}},
            framework_bridge.DeliveryError("Review app permission", "consent_required"),
        )
        state = await host.bridge.request_status(row["path"], row["id"])
        assert state["needsReview"] and state["retryNeeded"]
        assert state["requests"] == ["summarize"]
    asyncio.run(check())


def test_harness_registration_preserves_default_and_refuses_custom_changes(tmp_path):
    path = tmp_path / "harnesses.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "default": "other",
                "harnesses": [{"id": "other", "routes": []}],
            }
        )
    )
    profile = {
        "id": "craftbot-test",
        "routes": [
            {
                "mode": "inbound",
                "url": "http://127.0.0.1:8000/tasks",
                "tokenEnv": "TOKEN_NAME",
            }
        ],
    }
    register_profile(tmp_path, profile)
    register_profile(tmp_path, profile)
    data = json.loads(path.read_text())
    assert data["default"] == "other" and len(data["harnesses"]) == 2
    with pytest.raises(ValueError):
        register_profile(tmp_path, {**profile, "routes": []})
    assert json.loads(path.read_text()) == data
