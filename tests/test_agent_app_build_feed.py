"""The construction dock follows a framework build as it happens.

Played through the action hooks, the way the builder's actions reach them:
progress moves with each step and never goes back, counts grow write by
write, and a framework file edited late adds feed rows, not a jump.
"""

import json
from types import SimpleNamespace

import pytest

from app.agent_app.framework_build_feed import BuildFeed
from app.agent_app.framework_store import HostStore

SID = "s1"


@pytest.fixture
def build(tmp_path):
    app = tmp_path / "apps" / "ledger"
    (app / "reference").mkdir(parents=True)
    (app / "src").mkdir()
    (app / "manifest.json").write_text(
        json.dumps({"modules": [{"name": "core"}]}), encoding="utf-8"
    )
    (app / "operations.json").write_text(
        json.dumps({"operations": []}), encoding="utf-8"
    )
    store = HostStore(tmp_path / "host.sqlite3")
    store.put(
        "creation", SID, {"path": str(app), "building": True, "activity": "creator"}
    )
    feed = BuildFeed(SimpleNamespace(store=store))
    runs = iter(range(10_000))

    def act(name, outputs=None, **inputs):
        run = f"r{next(runs)}"
        feed.on_start(
            run, SimpleNamespace(name=name), {"_session_id": SID, **inputs}, None, ""
        )
        feed.on_end(
            run,
            SimpleNamespace(name=name),
            outputs or {"status": "success"},
            "success",
            None,
            "",
        )
        return feed.snapshot(SID)

    def write(rel, content):
        path = app / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return act("write_file", file_path=str(path), content=content)

    return SimpleNamespace(app=app, feed=feed, store=store, act=act, write=write)


def ledger(done, total):
    return "\n".join(
        f"- [{'x' if i < done else ' '}] T-{i + 1} (F-COR-{i + 1}): Task number {i + 1}"
        for i in range(total)
    )


def labels(feed):
    return [e["label"] for e in feed.replay(SID)["events"]]


def test_a_build_moves_step_by_step_and_never_back(build):
    seen = []

    def track(snapshot):
        return seen.append(snapshot["progress"]) or snapshot

    track(
        build.act(
            "agent_app_command",
            args=[str(build.app), "scaffold", "--blueprint", "blueprint-react-node"],
        )
    )
    track(
        build.act("read_file", file_path=str(build.app / "reference" / "blueprint.md"))
    )
    asked = track(
        build.act(
            "agent_app_command",
            args=[str(build.app), "checkpoint", "ask", "--file", "q.json"],
            outputs={
                "status": "success",
                "data": {"checkpoint": {"questions": [{}, {}, {}]}},
            },
        )
    )
    assert asked["stage"] == "questions"
    build.feed.person_replied(SID, {"status": "answered"})
    track(build.write("reference/requirements.md", "## Introduction\nAn app."))
    track(build.write("reference/requirements.md", "## Features\n- F-COR-1: x"))
    build.act("agent_app_command", args=[str(build.app), "checkpoint", "review"])
    build.feed.person_replied(SID, {"status": "approved"})
    planned = track(build.write("reference/tasks.md", ledger(0, 4)))
    assert (planned["stage"], planned["tasksTotal"], planned["task"]) == (
        "building",
        4,
        "T-1 Task number 1",
    )

    # Building: every write moves the bar, components and files count up as they are written.
    board = track(
        build.write(
            "src/Board.tsx", "export function Board() { return <Card><Button/></Card> }"
        )
    )
    assert (board["components"], board["files"]) == (3, 1)
    column = track(build.write("src/Column.tsx", "export const Column = () => <Card/>"))
    assert (column["components"], column["files"]) == (4, 2), (
        "a component used twice counts once"
    )
    ticked = track(build.write("reference/tasks.md", ledger(1, 4)))
    assert (ticked["tasksDone"], ticked["task"]) == (1, "T-2 Task number 2")
    track(build.write("src/api.ts", "export async function load() {}"))
    track(build.write("reference/tasks.md", ledger(3, 4)))

    # A framework file edited late is one write: one row naming what it adds, no jump.
    before, rows_before = build.feed.snapshot(SID), len(labels(build.feed))
    late = track(
        build.write(
            "operations.json",
            json.dumps(
                {"operations": [{"name": "archive_task"}, {"name": "clear_done"}]}
            ),
        )
    )
    assert labels(build.feed)[rows_before:] == [
        "Operations archive_task, clear_done added"
    ]
    assert (late["files"], late["components"], late["tasksDone"]) == (
        before["files"] + 1,
        before["components"],
        before["tasksDone"],
    )

    failed = track(
        build.act(
            "agent_app_command",
            args=[str(build.app), "validate"],
            outputs={"status": "error", "exit_code": 1},
        )
    )
    assert (failed["stage"], failed["fixing"]) == ("checking", True)
    track(build.write("src/Board.tsx", "export function Board() { return <Card/> }"))
    passed = track(
        build.act(
            "agent_app_command",
            args=[str(build.app), "validate"],
            outputs={"status": "success", "exit_code": 0},
        )
    )
    assert passed["fixing"] is False
    verified = track(
        build.act(
            "agent_app_framework_workflow",
            activity="verify",
            outputs={"status": "success", "verification": {"verdict": "pass"}},
        )
    )
    assert verified["stage"] == "verifying"
    launched = track(build.act("agent_app_command", args=[str(build.app), "serve"]))

    assert seen == sorted(seen), f"progress went back: {seen}"
    assert len(set(seen)) == len(seen), f"a step did not move the bar: {seen}"
    assert seen[-1] < 100 and launched["stage"] == "launching"
    rows = labels(build.feed)
    for row in [
        "Project created on blueprint-react-node",
        "Asked you 3 questions",
        "You answered the questions",
        "Requirements: Introduction",
        "Requirements: Features",
        "Requirements ready for your review",
        "You approved the requirements",
        "Planned 4 tasks",
        "Components Board, Button, Card created",
        "Component Column created",
        "✓ T-1 Task number 1",
        "✓ T-2 Task number 2",
        "✓ T-3 Task number 3",
        "Validation gate found problems: fixing",
        "Validation gate passed",
        "Independent verification passed",
        "App launched",
    ]:
        assert row in rows, f"missing row {row!r} in {rows}"


def test_an_unticked_ledger_still_moves_with_the_work(build):
    build.write("reference/tasks.md", ledger(0, 10))
    marks = [
        build.write(f"src/File{i}.tsx", f"export function Part{i}() {{ return null }}")[
            "progress"
        ]
        for i in range(30)
    ]
    assert marks == sorted(marks) and len(set(marks)) == len(marks), (
        "each write moves the bar"
    )
    assert marks[-1] - marks[0] > 20, "thirty writes are real progress"
    assert marks[-1] < 85, "and never claim the build is done"
    ticked = build.write("reference/tasks.md", ledger(10, 10))["progress"]
    assert ticked > marks[-1] and ticked < 85


def test_only_the_build_being_built_is_followed(build):
    other = build.app.parent / "other.tsx"
    other.write_text("export function Elsewhere() {}", encoding="utf-8")
    build.act("write_file", file_path=str(other), content="")
    build.write(".a2app/state.json", "{}")
    build.write("node_modules/x/index.js", "")
    assert build.feed.snapshot(SID)["files"] == 0
    build.store.put("creation", SID, {"path": str(build.app), "building": False})
    build.write("src/Late.tsx", "export function Late() {}")
    assert build.feed.snapshot(SID)["files"] == 0, "a finished build is not followed"


def test_the_picture_survives_a_restart(build):
    build.write("reference/tasks.md", ledger(1, 3))
    build.write("src/Board.tsx", "export function Board() {}")
    again = BuildFeed(SimpleNamespace(store=build.store))
    replay = again.replay(SID)
    assert replay["snapshot"]["files"] == 1 and replay["snapshot"]["tasksDone"] == 1
    assert [e["label"] for e in replay["events"]] == labels(build.feed)


def test_rows_reach_the_page_as_they_happen(build):
    import asyncio

    sent = []

    async def run():
        async def broadcast(message):
            sent.append(message)

        build.feed.broadcast = broadcast
        build.write("src/Board.tsx", "export function Board() {}")
        await asyncio.sleep(0)

    asyncio.run(run())
    assert sent and sent[0]["type"] == "agent_app_build_event"
    assert sent[0]["data"]["projectId"] == f"framework-build:{SID}"
    assert sent[0]["data"]["event"]["snapshot"]["components"] == 1
