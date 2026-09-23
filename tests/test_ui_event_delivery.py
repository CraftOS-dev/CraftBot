"""Delivery guarantees for the UI event pump.

The UI mirrors action state by replaying event-stream records, so every way
an `action_end` can go missing shows up as the same symptom: an activity row
that spins "in progress" forever. These cover the three ways it was losing
them.
"""

import asyncio
from types import SimpleNamespace

from agent_core.core.event_stream.event import Event, EventType
from app.ui_layer.controller.event_cursor import EventStreamCursors
from app.ui_layer.controller.ui_controller import UIController
from app.ui_layer.events.event_bus import EventBus
from app.ui_layer.events.event_types import UIEvent, UIEventType
from app.ui_layer.state.store import UIStateStore


# ─────────────────────────────── helpers ───────────────────────────────


def _action_event(kind: str, action_id: str, event_type: EventType) -> Event:
    return Event(
        message=f"Action run_shell {kind} (same text for every parallel call)",
        kind=kind,
        severity="INFO",
        event_type=event_type,
        action_name="run_shell",
        action_display_name="Run shell",
        action_id=action_id,
    )


def _end(action_id: str) -> Event:
    return _action_event("action_end", action_id, EventType.ACTION_END)


def _record(event: Event) -> SimpleNamespace:
    return SimpleNamespace(event=event)


def _controller(agent=None) -> UIController:
    """A controller with only the pieces the delivery path touches.

    `__init__` wires commands, skills and global state; none of that is
    involved in moving an event from a stream to the interface.
    """
    controller = object.__new__(UIController)
    controller._agent = agent
    controller._adapter = None
    controller._running = True
    controller._event_bus = EventBus(max_history=100)
    controller._state_store = UIStateStore()
    controller._cursors = EventStreamCursors()
    controller._removal_listener_registered = False
    return controller


# ────────────────── one bad event must not sink the batch ──────────────────


def test_a_failing_event_does_not_drop_the_rest_of_the_tick():
    """The regression: the cursor advances past the whole batch on read, so
    a raise partway through used to abandon every later event for good."""
    controller = _controller()
    delivered = []
    controller._event_bus.subscribe(
        UIEventType.ACTION_END, lambda e: delivered.append(e.data["action_id"])
    )

    stream = SimpleNamespace(
        tail_events=[_record(_end(f"run-{i}")) for i in range(4)]
    )

    # Second event of the batch blows up inside the delivery path.
    real_update = controller._update_state_from_event

    def exploding_update(event: UIEvent) -> None:
        if event.data.get("action_id") == "run-1":
            raise RuntimeError("boom")
        real_update(event)

    controller._update_state_from_event = exploding_update

    controller._drain_stream("session-1", stream, controller._cursors)

    assert delivered == ["run-0", "run-1", "run-2", "run-3"]


def test_a_stream_that_cannot_be_read_does_not_stop_the_others():
    controller = _controller()
    delivered = []
    controller._event_bus.subscribe(
        UIEventType.ACTION_END, lambda e: delivered.append(e.data["action_id"])
    )

    class Broken:
        @property
        def tail_events(self):
            raise RuntimeError("stream went away")

    controller._drain_stream("broken", Broken(), controller._cursors)
    controller._drain_stream(
        "ok", SimpleNamespace(tail_events=[_record(_end("run-9"))]), controller._cursors
    )

    assert delivered == ["run-9"]


# ─────────────────── draining a stream before it is dropped ───────────────────


def test_removing_a_stream_drains_it_first():
    """A sub-agent's last action_end is logged microseconds before its
    stream is dropped — the 50 ms poll never gets to see it."""
    from agent_core.core.impl.event_stream.manager import EventStreamManager

    manager = EventStreamManager(llm=SimpleNamespace())
    controller = _controller(agent=SimpleNamespace(event_stream_manager=manager))
    delivered = []
    controller._event_bus.subscribe(
        UIEventType.ACTION_END, lambda e: delivered.append(e.data["action_id"])
    )
    manager.add_removal_listener(controller._on_stream_removed)

    stream = manager.create_stream("sub-1")
    stream.log(
        "action_end",
        "Action run_shell completed",
        event_type=EventType.ACTION_END,
        action_name="run_shell",
        action_id="run-late",
    )

    manager.remove_stream("sub-1")

    assert delivered == ["run-late"]
    assert not manager.has_stream("sub-1")


# ───────────────────── end-of-run reconciliation ─────────────────────


class _FakePanel:
    def __init__(self, items):
        self._items = items
        self.forced = []

    def get_items(self):
        return list(self._items)

    async def update_item_by_name(
        self, action_name, session_id, status, action_id="", output=None, error=None
    ):
        self.forced.append((action_id, status))
        for item in self._items:
            if item.id == action_id:
                item.status = status


def _item(item_id, status="running", session_id="s1"):
    return SimpleNamespace(
        id=item_id,
        name="run_shell",
        status=status,
        item_type="action",
        session_id=session_id,
    )


def _reconciling_controller(items, inflight, stream=None):
    manager = SimpleNamespace(
        has_stream=lambda sid: stream is not None,
        get_stream_by_id=lambda sid: stream,
    )
    agent = SimpleNamespace(
        action_manager=SimpleNamespace(inflight_ids=lambda sid=None: inflight),
        event_stream_manager=manager,
    )
    controller = _controller(agent=agent)
    panel = _FakePanel(items)
    controller._adapter = SimpleNamespace(action_panel=panel)
    controller._RECONCILE_DELAY_SECONDS = 0
    return controller, panel


def test_reconcile_replays_the_real_action_end():
    """Preferred recovery: the true status/output, not a guess."""
    end = _end("run-1")
    end.action_output = {"status": "error", "error": "exit code 1"}
    stream = SimpleNamespace(as_list=lambda: [end])

    controller, panel = _reconciling_controller(
        items=[_item("run-1")], inflight=set(), stream=stream
    )
    statuses = []
    controller._event_bus.subscribe(
        UIEventType.ACTION_END, lambda e: statuses.append(e.data["status"])
    )

    asyncio.run(controller._settle_stale_actions("s1"))

    assert statuses == ["error"]
    # The replay settled it, so no blind force-settle was needed.
    assert panel.forced == []


def test_reconcile_force_settles_when_the_end_event_is_gone():
    stream = SimpleNamespace(as_list=lambda: [])
    controller, panel = _reconciling_controller(
        items=[_item("run-1"), _item("run-2")], inflight=set(), stream=stream
    )

    asyncio.run(controller._settle_stale_actions("s1"))

    assert sorted(panel.forced) == [("run-1", "completed"), ("run-2", "completed")]


def test_reconcile_leaves_genuinely_running_actions_alone():
    """A run can settle while another session's action is still executing."""
    stream = SimpleNamespace(as_list=lambda: [])
    controller, panel = _reconciling_controller(
        items=[_item("run-1"), _item("run-2")],
        inflight={"run-1"},
        stream=stream,
    )

    asyncio.run(controller._settle_stale_actions("s1"))

    assert panel.forced == [("run-2", "completed")]


def test_reconcile_ignores_other_sessions_and_settled_rows():
    stream = SimpleNamespace(as_list=lambda: [])
    controller, panel = _reconciling_controller(
        items=[
            _item("other", session_id="s2"),
            _item("done", status="completed"),
        ],
        inflight=set(),
        stream=stream,
    )

    asyncio.run(controller._settle_stale_actions("s1"))

    assert panel.forced == []


def test_reconcile_only_fires_when_a_run_goes_idle():
    controller, _ = _reconciling_controller(items=[], inflight=set())
    scheduled = []

    async def record(session_id):
        scheduled.append(session_id)

    controller._settle_stale_actions = record

    async def drive():
        for state in ("running", "stopping", "idle"):
            controller._on_run_state_changed(
                UIEvent(
                    type=UIEventType.RUN_STATE_CHANGED,
                    data={"session_id": "s1", "state": state},
                )
            )
        # Let the scheduled task run.
        await asyncio.sleep(0)

    asyncio.run(drive())
    assert scheduled == ["s1"]


# ───────────────────────── in-flight bookkeeping ─────────────────────────


def test_inflight_ids_are_scoped_per_session():
    from agent_core.core.impl.action.manager import ActionManager

    manager = object.__new__(ActionManager)
    manager._inflight = {
        "run-1": {"session_id": "s1"},
        "run-2": {"session_id": "s2"},
        "run-3": {"session_id": "s1"},
    }

    assert manager.inflight_ids("s1") == {"run-1", "run-3"}
    assert manager.inflight_ids("s2") == {"run-2"}
    assert manager.inflight_ids() == {"run-1", "run-2", "run-3"}
