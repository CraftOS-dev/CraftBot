"""A build stops for the person in CraftBot's build view, not in chat.

The framework's builder opens a checkpoint (its questions, then the
requirements review) and CraftBot ends its turn there; the person's reply is
recorded through the CLI and reaches the builder as their message, which
resumes it with the creator skill it was started with.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_core.core.session import SessionType
from app.agent_app import framework, framework_commands, framework_host
from app.agent_app.framework_cli import CLIResult
from app.agent_app.framework_store import HostStore

PENDING = {
    "id": "c-0000000a",
    "kind": "questions",
    "round": 1,
    "status": "pending",
    "shown": "ui",
    "createdAt": "2026-11-17T00:00:00.000Z",
}


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(framework_host, "_host", None)
    posted = []

    async def submit_message(message, adapter_id="", session_id=None, **_):
        posted.append((session_id, message))

    agent = SimpleNamespace(
        ui_controller=SimpleNamespace(submit_message=submit_message)
    )
    made = framework_host.FrameworkHost(
        agent, store=HostStore(tmp_path / "host.sqlite3")
    )
    made.posted = posted
    made.app = str(tmp_path / "apps" / "craftbot-1")
    made.store.put(
        "creation",
        "s1",
        {
            "path": made.app,
            "name": "Ledger",
            "authMode": "none",
            "building": True,
            "activity": "creator",
            "checkpoints": "ui",
        },
    )
    return made


def test_scaffold_shows_the_builds_checkpoints_in_craftbot(host):
    args = host.scaffold_arguments(
        "s1", [host.app, "scaffold", "--blueprint", "blueprint-base"]
    )
    assert args[-6:] == [
        "--name",
        "Ledger",
        "--auth-mode",
        "none",
        "--checkpoints",
        "ui",
    ]
    # A build started from chat has no form choices, and still shows its checkpoints here.
    host.store.put(
        "creation",
        "s2",
        {
            "path": host.app,
            "building": True,
            "activity": "creator",
            "checkpoints": "ui",
        },
    )
    assert host.scaffold_arguments("s2", [host.app, "scaffold"]) == [
        host.app,
        "scaffold",
        "--checkpoints",
        "ui",
    ]
    with pytest.raises(ValueError, match="--checkpoints"):
        host.scaffold_arguments("s2", [host.app, "scaffold", "--checkpoints", "chat"])
    # Another directory is not this build's.
    assert host.scaffold_arguments("s1", ["/elsewhere", "scaffold"]) == [
        "/elsewhere",
        "scaffold",
    ]


def test_a_reply_resumes_the_build_with_its_own_skill_and_tools(host):
    session = SimpleNamespace(id="s1")
    assert host.build_resume(session) == {
        "workflow_skills": ["framework-creator"],
        "workflow_action_sets": list(framework_host.BUILD_ACTION_SETS),
    }
    host.store.put(
        "creation", "s1", {"path": host.app, "building": False, "activity": "creator"}
    )
    assert host.build_resume(session) is None, "a finished build is operated, not built"
    host.store.put("creation", "s1", {"path": host.app, "building": True})
    assert host.build_resume(session) is None, (
        "a build recorded before this knew its skill keeps the old behavior"
    )


def test_resumed_runs_load_the_creator_not_the_operator(host, monkeypatch):
    from app.agent_base import AgentBase
    from app.internal_action_interface import InternalActionInterface

    added, loaded = [], []
    fake = SimpleNamespace(
        session_manager=SimpleNamespace(add_skill=lambda sid, name: added.append(name)),
        _user_skill_action_sets=lambda skills: [],
    )
    monkeypatch.setattr(
        InternalActionInterface,
        "load_action_sets",
        staticmethod(lambda sets, session_id=None: loaded.append(sets)),
    )
    session = SimpleNamespace(
        id="s1",
        type=SessionType.AGENT_APP,
        agent_app_framework_key="key",
        selected_skills=[],
    )
    payload = {"run_source": "user_message"}
    asyncio.run(AgentBase._apply_workflow_capabilities(fake, session, payload))
    assert added == ["framework-creator"]
    assert loaded == [list(framework_host.BUILD_ACTION_SETS)]
    assert payload["workflow_skills"] == ["framework-creator"], (
        "unloaded again when the run ends"
    )

    host.store.put(
        "creation", "s1", {"path": host.app, "building": False, "activity": "creator"}
    )
    added.clear()
    asyncio.run(AgentBase._apply_workflow_capabilities(fake, session, {}))
    assert added == ["framework-operator"], "a built app's conversation operates it"


def test_an_opened_checkpoint_is_recorded_and_ends_the_builders_turn(host):
    def seen(checkpoint, opened=True, path=None):
        return asyncio.run(
            host.checkpoint_seen("s1", path or host.app, checkpoint, opened=opened)
        )

    assert seen(PENDING) is True
    assert host.store.get("checkpoint", "s1") == PENDING
    assert seen({**PENDING, "status": "answered"}, opened=False) is False, (
        "recording a reply does not end a turn"
    )
    assert host.store.get("checkpoint", "s1")["status"] == "answered"
    assert seen({**PENDING, "shown": "chat"}) is False, (
        "a chat checkpoint is the builder's to send"
    )
    assert seen(PENDING, path="/elsewhere") is False
    assert seen(None) is False


def test_build_info_carries_the_checkpoint_for_a_reload(host):
    host.store.put("checkpoint", "s1", PENDING)
    session = SimpleNamespace(
        id="s1",
        type=SessionType.AGENT_APP,
        agent_app_framework_pending=True,
        agent_app_framework_key=None,
        todos=[],
    )
    assert host.build_info(session)["checkpoint"] == PENDING


def test_the_persons_reply_is_recorded_and_given_to_the_builder(host):
    calls = []
    state = {"checkpoint": PENDING}

    async def cli(args):
        calls.append(list(args))
        if args[2] == "show":
            return CLIResult(0, "", ""), {"checkpoint": state["checkpoint"]}
        if "--part-a" in args:
            # The edit travels as a file; the CLI refuses an incomplete one.
            part_a = Path(args[args.index("--part-a") + 1])
            calls[-1].append(part_a)
            if part_a.read_text(encoding="utf-8") != "# Edited":
                return CLIResult(1, "", ""), {
                    "ok": False,
                    "reason": "part_a_incomplete",
                    "error": "The edited Part A is not complete.",
                    "problems": ["one placeholder"],
                }
        state["checkpoint"] = {
            **state["checkpoint"],
            "status": "approved" if args[2] == "approve" else "answered",
        }
        return CLIResult(0, "", ""), {
            "ok": True,
            "checkpoint": state["checkpoint"],
            "message": f"{args[2]} recorded",
        }

    host._checkpoint_cli = cli

    def reply(**data):
        return asyncio.run(
            host.checkpoint_reply({"sessionId": "s1", "id": "c-0000000a", **data})
        )

    assert reply(id="c-stale", answers=[]) == {
        "ok": False,
        "reason": "moved",
        "error": "The build has moved past this step.",
    }
    assert host.posted == []
    answers = [{"id": "who", "choices": ["Just me"]}]
    assert reply(answers=answers)["ok"] is True
    assert calls[-1] == [
        host.app,
        "checkpoint",
        "answer",
        "--json",
        json.dumps({"answers": answers}),
    ]
    assert host.posted == [("s1", "answer recorded")], (
        "posted once, as the person's message"
    )
    assert host.store.get("checkpoint", "s1")["status"] == "answered"

    state["checkpoint"] = {**PENDING, "kind": "review"}
    refused = reply(approve=True, partA="BAD")
    assert refused == {
        "ok": False,
        "reason": "part_a_incomplete",
        "error": "The edited Part A is not complete.",
        "problems": ["one placeholder"],
    }
    assert len(host.posted) == 1, "nothing is posted for a refusal"
    assert reply(approve=True, partA="# Edited")["ok"] is True
    approve = calls[-1]
    assert approve[:5] == [host.app, "checkpoint", "approve", "--by", "CraftBot"]
    assert not approve[-1].exists(), "the edit's file is gone afterwards"
    assert host.posted[-1] == ("s1", "approve recorded")

    host.store.put("creation", "s1", {"path": host.app, "building": False})
    with pytest.raises(ValueError, match="no longer being built"):
        reply(answers=answers)


def test_the_builders_checkpoint_command_ends_its_turn(host, monkeypatch, tmp_path):
    from agent_core.core.state.session import StateSession

    out = {"ok": True, "checkpoint": PENDING, "next": "End your turn now."}

    class FakeCLI:
        package_dir = tmp_path
        home = tmp_path

        async def run(self, surface, args, **_):
            return CLIResult(0, json.dumps(out), "")

    async def no_apps(cli):
        return {"data": {"apps": []}}

    monkeypatch.setattr(framework, "configured_cli", lambda: FakeCLI())
    monkeypatch.setattr(framework, "_list_apps", no_apps)
    monkeypatch.setattr(
        StateSession, "bound", classmethod(lambda cls: SimpleNamespace(session_id="s1"))
    )
    result = asyncio.run(
        framework_commands.command(
            "agent-app", [host.app, "checkpoint", "ask", "--file", "q.json"]
        )
    )
    assert (result["end_turn"], result["awaiting_answer"]) == (True, True)
    assert "build view" in result["host_note"]
    out["checkpoint"] = {**PENDING, "shown": "chat"}
    result = asyncio.run(
        framework_commands.command(
            "agent-app", [host.app, "checkpoint", "ask", "--file", "q.json"]
        )
    )
    assert "end_turn" not in result, (
        "a chat checkpoint is sent by the builder, which then ends its own turn"
    )
