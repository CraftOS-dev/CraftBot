# -*- coding: utf-8 -*-
"""
Proactive tasks and the scheduler (2026-11-11 study fixes).

- Cron schedules fire in local time. croniter's get_next(float) read the
  naive local start as UTC, so in Tokyo the 30-minute heartbeat slept 569
  minutes between fires, and west of UTC it fired every minute.
- "Due" is decided by code: each task has a slot per period, last_run is
  stamped at dispatch, a missed slot runs once (late), and active_since keeps
  a new, re-enabled or rescheduled task from firing a slot it never had.
- PROACTIVE.md is re-read whenever it changed on disk, and saves write over
  the file as it is now (a planner's Goals edit, a hand-added task survive).
- The heartbeat fires exactly when a task is due and hands the run those
  tasks; scheduler work runs in the background session and posts ONE result
  into main.
- The LLM failure latch expires after a cooldown instead of waiting for a
  user chat message.
"""

import asyncio
import json
import shutil
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_core.core.session import (
    BACKGROUND_SESSION_ID,
    MAIN_SESSION_ID,
    SessionType,
)
from app.proactive.manager import ProactiveManager
from app.proactive.types import RecurringTask, validate_schedule_fields
from app.scheduler.background import background_runs
from app.scheduler.manager import BACKGROUND_RESULT_NOTE, SchedulerManager
from app.scheduler.parser import ScheduleParser
from app.scheduler.types import ScheduledTask
from app.triggers.sources import TriggerSource

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "agent_file_system_template"
    / "PROACTIVE.md"
)


def _ts(*args) -> float:
    return datetime(*args).timestamp()


# ─────────────────────────── Cron in local time ───────────────────────────


class TestCronLocalTime:
    def test_half_hourly_cron_fires_at_the_next_local_half_hour(self):
        sched = ScheduleParser.parse("0,30 * * * *")
        nxt = ScheduleParser.calculate_next_fire_time(
            sched, from_time=_ts(2026, 11, 6, 3, 31)
        )
        assert nxt == _ts(2026, 11, 6, 4, 0)

    def test_monthly_planner_cron_fires_at_local_eight(self):
        sched = ScheduleParser.parse("0 8 1 * *")
        nxt = ScheduleParser.calculate_next_fire_time(
            sched, from_time=_ts(2026, 11, 6, 3, 31)
        )
        assert nxt == _ts(2026, 12, 1, 8, 0)

    def test_next_fire_is_never_in_the_past(self):
        sched = ScheduleParser.parse("*/30 * * * *")
        start = _ts(2026, 11, 6, 10, 1)
        assert ScheduleParser.calculate_next_fire_time(sched, from_time=start) > start


class TestMonthlySchedule:
    def test_parses_day_and_time(self):
        sched = ScheduleParser.parse("every month on day 15 at 9:30pm")
        assert (sched.schedule_type, sched.day_of_month, sched.hour, sched.minute) == (
            "monthly",
            15,
            21,
            30,
        )

    def test_day_31_falls_back_to_the_last_day(self):
        sched = ScheduleParser.parse("every month on day 31 at 8am")
        nxt = ScheduleParser.calculate_next_fire_time(sched, from_time=_ts(2027, 2, 10))
        assert nxt == _ts(2027, 2, 28, 8, 0)

    def test_rolls_into_next_year(self):
        sched = ScheduleParser.parse("every month on day 1 at 8am")
        nxt = ScheduleParser.calculate_next_fire_time(sched, from_time=_ts(2026, 12, 5))
        assert nxt == _ts(2027, 1, 1, 8, 0)

    def test_rejects_day_32(self):
        from app.scheduler.parser import ScheduleParseError

        with pytest.raises((ScheduleParseError, ValueError)):
            ScheduleParser.parse("every month on day 32 at 8am")

    def test_shipped_planners_parse(self):
        config = json.loads(
            (TEMPLATE.parents[2] / "config" / "scheduler_config.json").read_text(
                encoding="utf-8"
            )
        )
        types_by_id = {
            s["id"]: ScheduleParser.parse(s["schedule"]).schedule_type
            for s in config["schedules"]
        }
        assert types_by_id["week-planner"] == "weekly"
        assert types_by_id["month-planner"] == "monthly"


# ─────────────────────────── Task slots and due ───────────────────────────


def _task(frequency, time_=None, day=None, **kw) -> RecurringTask:
    return RecurringTask(
        id="t",
        name="T",
        frequency=frequency,
        instruction="i",
        time=time_,
        day=day,
        **kw,
    )


class TestSlots:
    NOW = datetime(2026, 11, 11, 10, 0)  # a Wednesday

    def test_daily(self):
        t = _task("daily", "09:00")
        assert t.latest_slot(self.NOW) == datetime(2026, 11, 11, 9, 0)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 12, 9, 0)

    def test_hourly_uses_the_minute(self):
        t = _task("hourly", "00:15")
        assert t.latest_slot(self.NOW) == datetime(2026, 11, 11, 9, 15)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 11, 10, 15)

    def test_weekly(self):
        t = _task("weekly", "17:00", "sunday")
        assert t.latest_slot(self.NOW) == datetime(2026, 11, 8, 17, 0)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 15, 17, 0)

    def test_monthly_clamps_to_the_last_day(self):
        t = _task("monthly", "08:00", "31")
        assert t.latest_slot(self.NOW) == datetime(2026, 10, 31, 8, 0)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 30, 8, 0)
        assert t.next_slot(datetime(2027, 2, 15)) == datetime(2027, 2, 28, 8, 0)

    def test_defaults_to_midnight(self):
        assert _task("daily").latest_slot(self.NOW) == datetime(2026, 11, 11, 0, 0)


class TestDue:
    NOW = datetime(2026, 11, 11, 10, 0)

    def test_due_after_slot_until_dispatched(self):
        t = _task("daily", "09:00", active_since=datetime(2026, 11, 1))
        assert t.is_due(self.NOW)
        t.mark_dispatched(self.NOW)
        assert not t.is_due(self.NOW)
        assert t.run_count == 1
        assert t.next_due_at(self.NOW) == datetime(2026, 11, 12, 9, 0)

    def test_missed_slots_run_once_not_per_slot(self):
        t = _task(
            "daily",
            "09:00",
            active_since=datetime(2026, 11, 1),
            last_run=datetime(2026, 11, 8, 9, 0),
        )
        assert t.is_due(self.NOW)
        t.mark_dispatched(self.NOW)
        assert not t.is_due(self.NOW)

    def test_slot_before_active_since_never_runs(self):
        t = _task("daily", "09:00", active_since=datetime(2026, 11, 11, 9, 30))
        assert not t.is_due(self.NOW)
        assert t.next_due_at(self.NOW) == datetime(2026, 11, 12, 9, 0)

    def test_hourly_runs_once_an_hour(self):
        t = _task("hourly", "00:00", active_since=datetime(2026, 11, 1))
        t.mark_dispatched(datetime(2026, 11, 11, 10, 0))
        assert not t.is_due(datetime(2026, 11, 11, 10, 30))
        assert t.is_due(datetime(2026, 11, 11, 11, 0))

    def test_disabled_is_never_due(self):
        t = _task("daily", "09:00", enabled=False, active_since=datetime(2026, 11, 1))
        assert not t.is_due(self.NOW)
        assert t.next_due_at(self.NOW) is None

    def test_outcome_does_not_reschedule(self):
        t = _task("daily", "09:00", active_since=datetime(2026, 11, 1))
        t.add_outcome("Scheduled for later")
        assert t.last_run is None and t.run_count == 0
        assert t.is_due(self.NOW)


class TestValidation:
    @pytest.mark.parametrize(
        "frequency,time_,day",
        [
            ("daily", "25:00", None),
            ("daily", "9", None),
            ("weekly", "09:00", "funday"),
            ("monthly", "09:00", "32"),
            ("yearly", None, None),
        ],
    )
    def test_rejects(self, frequency, time_, day):
        with pytest.raises(ValueError):
            validate_schedule_fields(frequency, time_, day)

    def test_unquoted_yaml_time_reads_as_clock(self):
        task = RecurringTask.from_dict({"id": "x", "frequency": "daily", "time": 540})
        assert task.time == "09:00"


# ─────────────────────────── PROACTIVE.md on disk ───────────────────────────


@pytest.fixture
def proactive_file(tmp_path):
    path = tmp_path / "PROACTIVE.md"
    shutil.copy(TEMPLATE, path)
    return path


def _bump_mtime(path: Path) -> None:
    """External edits in the same tick must still look changed."""
    stat = path.stat()
    import os

    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))


class TestProactiveFile:
    def test_add_task_anchors_and_persists(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        task = mgr.add_task(
            name="Brief", frequency="daily", instruction="x", time="09:00"
        )
        assert task.active_since is not None
        reloaded = ProactiveManager(proactive_file)
        reloaded.load()
        assert reloaded.get_task(task.id).active_since is not None

    def test_save_keeps_a_planner_goals_edit(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        text = proactive_file.read_text(encoding="utf-8")
        proactive_file.write_text(
            text.replace("No long-term goals defined yet.", "PLANNER GOAL", 1),
            encoding="utf-8",
        )
        _bump_mtime(proactive_file)
        mgr.add_task(name="Brief", frequency="daily", instruction="x", time="09:00")
        assert "PLANNER GOAL" in proactive_file.read_text(encoding="utf-8")

    def test_hand_added_task_is_seen_anchored_and_kept(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        text = proactive_file.read_text(encoding="utf-8")
        block = (
            "### [DAILY] Hand added\n```yaml\nid: hand_added\nfrequency: daily\n"
            'time: "09:00"\nenabled: true\ninstruction: y\n```\n\n'
        )
        proactive_file.write_text(
            text.replace(
                "<!-- PROACTIVE_TASKS_END -->",
                block + "<!-- PROACTIVE_TASKS_END -->",
                1,
            ),
            encoding="utf-8",
        )
        _bump_mtime(proactive_file)
        task = mgr.get_task("hand_added")
        assert task is not None and task.active_since is not None
        assert "active_since" in proactive_file.read_text(encoding="utf-8")
        mgr.add_task(name="Other", frequency="hourly", instruction="z")
        assert "hand_added" in proactive_file.read_text(encoding="utf-8")

    def test_mark_dispatched_persists(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        task = mgr.add_task(name="Brief", frequency="daily", instruction="x")
        when = datetime(2026, 11, 11, 9, 0, 1)
        mgr.mark_dispatched([task.id], when)
        reloaded = ProactiveManager(proactive_file)
        reloaded.load()
        stored = reloaded.get_task(task.id)
        assert stored.last_run == when and stored.run_count == 1

    def test_re_enabling_restarts_the_schedule(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        task = mgr.add_task(
            name="Brief", frequency="daily", instruction="x", enabled=False
        )
        task.active_since = datetime(2020, 1, 1)
        mgr.save()
        mgr.update_task(task.id, updates={"enabled": True})
        assert mgr.get_task(task.id).active_since > datetime(2026, 1, 1)

    def test_invalid_time_is_rejected(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        with pytest.raises(ValueError):
            mgr.add_task(name="Bad", frequency="daily", instruction="x", time="7am")

    def test_change_listener_fires_on_save(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        calls = []
        mgr.set_change_listener(lambda: calls.append(1))
        mgr.add_task(name="Brief", frequency="daily", instruction="x")
        assert calls


# ─────────────────────────── Scheduler fires ───────────────────────────


class _FakeTriggerService:
    def __init__(self):
        self.specs = []

    async def emit(self, spec):
        self.specs.append(spec)
        return types.SimpleNamespace(trigger_id=len(self.specs), deduped=False)


@pytest.fixture
def proactive_on(monkeypatch):
    import app.ui_layer.settings.proactive_settings as settings

    state = {"enabled": True}
    monkeypatch.setattr(settings, "is_proactive_enabled", lambda: state["enabled"])
    return state


def _scheduler(proactive_file):
    mgr = ProactiveManager(proactive_file)
    mgr.load()
    sm = SchedulerManager()
    sm._trigger_service = _FakeTriggerService()
    sm.set_proactive_manager(mgr)
    heartbeat = ScheduledTask(
        id="heartbeat",
        name="Heartbeat",
        instruction="Run the PROACTIVE.md tasks that are due",
        schedule=ScheduleParser.parse("*/30 * * * *"),
        skills=["heartbeat-processor"],
        payload={"type": "proactive_heartbeat"},
    )
    sm._schedules[heartbeat.id] = heartbeat
    return sm, mgr, heartbeat


def _overdue_task(mgr):
    """A daily task whose slot was an hour ago, active for days."""
    slot = datetime.now() - timedelta(hours=1)
    task = mgr.add_task(
        name="Morning brief",
        frequency="daily",
        instruction="Brief the user",
        time=f"{slot:%H:%M}",
        permission_tier=1,
    )
    stored = mgr.get_task(task.id)
    stored.active_since = datetime.now() - timedelta(days=3)
    mgr.save()
    return task.id


class TestHeartbeatFire:
    def test_due_task_goes_to_background_with_its_id_and_is_stamped(
        self, proactive_file, proactive_on
    ):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        task_id = _overdue_task(mgr)

        asyncio.run(sm._fire_schedule(heartbeat))

        (spec,) = sm._trigger_service.specs
        assert spec.session_id == BACKGROUND_SESSION_ID
        assert spec.source == TriggerSource.PROACTIVE_HEARTBEAT
        assert spec.payload["proactive_task_ids"] == [task_id]
        assert spec.dedup_key.startswith(f"proactive:{task_id}@")
        assert "Brief the user" in spec.description
        assert "Late:" in spec.description
        assert mgr.get_task(task_id).run_count == 1

        asyncio.run(sm._fire_schedule(heartbeat))
        assert len(sm._trigger_service.specs) == 1  # nothing due any more

    def test_failed_stamp_never_refires_the_slot(self, proactive_file, proactive_on):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        _overdue_task(mgr)

        def locked(*_a, **_k):
            raise OSError("file locked")

        mgr.mark_dispatched = locked
        with pytest.raises(OSError):
            asyncio.run(sm._fire_schedule(heartbeat))
        asyncio.run(sm._fire_schedule(heartbeat))
        assert len(sm._trigger_service.specs) == 1

    def test_nothing_due_emits_nothing(self, proactive_file, proactive_on):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        asyncio.run(sm._fire_schedule(heartbeat))
        assert sm._trigger_service.specs == []

    def test_proactive_off_emits_nothing_and_stamps_nothing(
        self, proactive_file, proactive_on
    ):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        task_id = _overdue_task(mgr)
        proactive_on["enabled"] = False
        asyncio.run(sm._fire_schedule(heartbeat))
        assert sm._trigger_service.specs == []
        assert mgr.get_task(task_id).run_count == 0

    def test_heartbeat_wakes_exactly_when_a_task_is_due(
        self, proactive_file, proactive_on
    ):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        now = time.time()
        assert sm._next_fire(heartbeat, now) > now  # only the interval tick
        _overdue_task(mgr)
        assert sm._next_fire(heartbeat, now) == pytest.approx(now, abs=1)

    def test_task_change_rearms_the_heartbeat(self, proactive_file, proactive_on):
        sm, mgr, heartbeat = _scheduler(proactive_file)

        async def scenario():
            sm._loop = asyncio.get_running_loop()
            event = asyncio.Event()
            sm._wake_events[heartbeat.id] = event
            mgr.add_task(name="Brief", frequency="daily", instruction="x")
            return event.is_set()

        assert asyncio.run(scenario())


class TestRouting:
    def test_memory_stays_in_main(self, monkeypatch):
        import app.ui_layer.settings.memory_settings as memory_settings

        monkeypatch.setattr(memory_settings, "memory_scheduled_run_due", lambda: True)
        sm = SchedulerManager()
        sm._trigger_service = _FakeTriggerService()
        task = ScheduledTask(
            id="memory-processing",
            name="Daily Memory Processing",
            instruction="Process",
            schedule=ScheduleParser.parse("every day at 3am"),
            payload={"type": "memory_processing"},
        )
        asyncio.run(sm._fire_schedule(task))
        (spec,) = sm._trigger_service.specs
        assert spec.session_id == MAIN_SESSION_ID
        assert BACKGROUND_RESULT_NOTE not in spec.description

    def test_user_schedule_runs_in_background(self):
        sm = SchedulerManager()
        sm._trigger_service = _FakeTriggerService()
        task = ScheduledTask(
            id="abc",
            name="Call mom",
            instruction="Remind the user to call mom",
            schedule=ScheduleParser.parse("every day at 7am"),
        )
        asyncio.run(sm._fire_schedule(task))
        (spec,) = sm._trigger_service.specs
        assert spec.session_id == BACKGROUND_SESSION_ID
        assert BACKGROUND_RESULT_NOTE in spec.description

    def test_immediate_runs_in_background(self):
        sm = SchedulerManager()
        sm._trigger_service = _FakeTriggerService()
        asyncio.run(sm.queue_immediate_trigger(name="Now", instruction="Do it"))
        (spec,) = sm._trigger_service.specs
        assert spec.session_id == BACKGROUND_SESSION_ID


# ─────────────────────────── LLM failure latch ───────────────────────────


class TestFailureLatch:
    def _fake(self):
        return types.SimpleNamespace(
            _consecutive_failures=5, _max_consecutive_failures=5, _latched_at=None
        )

    def test_blocks_while_fresh_and_probes_after_cooldown(self):
        from agent_core.core.impl.llm import interface
        from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError

        fake = self._fake()
        fake._latched_at = time.monotonic()
        with pytest.raises(LLMConsecutiveFailureError):
            interface.LLMInterface._check_failure_latch(fake)

        fake._latched_at = time.monotonic() - interface.FAILURE_LATCH_COOLDOWN_S - 1
        interface.LLMInterface._check_failure_latch(fake)  # probe allowed
        assert fake._consecutive_failures == 4
        assert fake._latched_at is None

        # One more failure re-arms the latch.
        with pytest.raises(LLMConsecutiveFailureError):
            interface.LLMInterface._register_failure(fake, error_info=None)
        assert fake._latched_at is not None

    def test_no_trip_time_means_still_blocked(self):
        from agent_core.core.impl.llm import interface
        from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError

        with pytest.raises(LLMConsecutiveFailureError):
            interface.LLMInterface._check_failure_latch(self._fake())


# ─────────────────────────── Background results ───────────────────────────


@pytest.fixture
def agent():
    from app.agent_base import AgentBase

    background_runs.finish()
    bare = AgentBase.__new__(AgentBase)
    bare.posted = []
    bare.outcomes = []
    bare.state_manager = types.SimpleNamespace(
        record_agent_message=lambda text, **kw: bare.posted.append((text, kw))
    )
    bare.proactive_manager = types.SimpleNamespace(
        get_task=lambda task_id: types.SimpleNamespace(name="Morning brief"),
        record_outcome=lambda task_id, result, success=True: bare.outcomes.append(
            (task_id, result, success)
        ),
    )
    bare._persist_session_stream = lambda session_id: None
    yield bare
    background_runs.finish()


class TestBackgroundResult:
    def test_final_message_is_posted_to_main_once(self, agent):
        background_runs.start(["Daily Planning"], ["daily_brief"])
        background_runs.note_final_message("Today: ship it", ["Yes", "No"])
        asyncio.run(agent._finish_background_run())

        ((text, kw),) = agent.posted
        assert text == "**Daily Planning · Morning brief**\n\nToday: ship it"
        assert kw["session_id"] == MAIN_SESSION_ID
        assert kw["suggested_responses"] == ["Yes", "No"]
        assert agent.outcomes == [("daily_brief", "Today: ship it", True)]

    def test_end_turn_posts_nothing(self, agent):
        background_runs.start([], ["hourly_scan"])
        asyncio.run(agent._finish_background_run())
        assert agent.posted == []
        assert agent.outcomes == [("hourly_scan", "Finished without a message", True)]

    def test_failure_posts_a_note(self, agent):
        background_runs.start(["Scheduled task: Call mom"], [])
        background_runs.note_final_message("partial")
        asyncio.run(agent._finish_background_run(failure="the AI service failed."))
        ((text, _),) = agent.posted
        assert (
            text
            == "**Scheduled task: Call mom** did not finish: the AI service failed."
        )

    def test_progress_updates_are_not_the_result(self):
        from app.internal_action_interface import InternalActionInterface

        background_runs.finish()
        background_runs.start(["X"], [])
        InternalActionInterface._note_background_result(
            "working...", BACKGROUND_SESSION_ID, continue_work=True
        )
        InternalActionInterface._note_background_result(
            "main chat", MAIN_SESSION_ID, continue_work=False
        )
        assert background_runs.finish().final_message is None

    def test_causes_come_from_typed_trigger_fields(self):
        from agent_core.core.trigger import Trigger
        from app.agent_base import AgentBase

        trig = Trigger(
            fire_at=0,
            priority=50,
            next_action_description="",
            payload={
                "proactive_task_ids": ["a"],
                "aggregated_triggers": [
                    {
                        "source": TriggerSource.PROACTIVE_HEARTBEAT.value,
                        "name": "Heartbeat",
                    },
                    {
                        "source": TriggerSource.PROACTIVE_PLANNER.value,
                        "name": "Daily Planning",
                    },
                    {"source": TriggerSource.SCHEDULED_ONCE.value, "name": "Call mom"},
                ],
            },
            session_id=BACKGROUND_SESSION_ID,
            source=TriggerSource.PROACTIVE_HEARTBEAT.value,
        )
        causes, task_ids = AgentBase._background_causes(trig)
        assert causes == ["Daily Planning", "Scheduled task: Call mom"]
        assert task_ids == ["a"]

    def test_merged_batches_keep_every_task_id(self):
        from agent_core.core.trigger import Trigger
        from app.triggers.runtime import _merge_triggers

        def trig(ids):
            return Trigger(
                fire_at=0,
                priority=50,
                next_action_description="d",
                payload={"proactive_task_ids": ids},
                session_id=BACKGROUND_SESSION_ID,
                source=TriggerSource.PROACTIVE_HEARTBEAT.value,
            )

        merged = _merge_triggers(trig(["a"]), [trig(["b", "a"])])
        assert merged.payload["proactive_task_ids"] == ["a", "b"]


# ─────────────────────────── Background session ───────────────────────────


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    from agent_core.core.impl.session.manager import SessionManager
    from agent_core.core.state.session import StateSession
    from app.action.action_set import action_set_manager

    monkeypatch.setattr(action_set_manager, "actions_in_sets", lambda *a, **k: [])
    monkeypatch.setattr(action_set_manager, "list_all_sets", lambda: {})
    manager = SessionManager(event_stream_manager=None, workspace_root=tmp_path)
    yield manager
    for sid in list(manager.sessions):
        StateSession.end(sid)


class TestBackgroundSession:
    def test_ensure_background_is_idempotent_and_undeletable(self, sessions):
        first = sessions.ensure_background()
        assert first.id == BACKGROUND_SESSION_ID
        assert first.type == SessionType.BACKGROUND
        assert first.title == "Background"
        assert sessions.ensure_background() is first
        assert sessions.delete_session(BACKGROUND_SESSION_ID) is False
        assert BACKGROUND_SESSION_ID in sessions.sessions

    def test_main_still_lists_first(self, sessions):
        sessions.ensure_background()
        sessions.ensure_main()
        assert sessions.list_sessions()[0].id == MAIN_SESSION_ID


# ─────────────────────────── Settings helpers ───────────────────────────


class TestScheduleSettings:
    def test_heartbeat_expressions_round_trip(self):
        from app.ui_layer.settings.proactive_settings import (
            HEARTBEAT_INTERVAL_OPTIONS,
            heartbeat_interval_minutes,
            heartbeat_schedule_expression,
        )

        assert heartbeat_schedule_expression(30) == "*/30 * * * *"
        assert heartbeat_schedule_expression(60) == "0 * * * *"
        assert heartbeat_schedule_expression(120) == "0 */2 * * *"
        for minutes in HEARTBEAT_INTERVAL_OPTIONS:
            expr = heartbeat_schedule_expression(minutes)
            ScheduleParser.parse(expr)
            assert heartbeat_interval_minutes(expr) == minutes
        with pytest.raises(ValueError):
            heartbeat_schedule_expression(7)

    def test_day_planner_expression(self):
        from app.ui_layer.settings.proactive_settings import (
            day_planner_schedule_expression,
        )

        parsed = ScheduleParser.parse(day_planner_schedule_expression(7, 30))
        assert (parsed.schedule_type, parsed.hour, parsed.minute) == ("daily", 7, 30)
        with pytest.raises(ValueError):
            day_planner_schedule_expression(24, 0)

    def test_week_and_month_planner_expressions(self):
        from app.ui_layer.settings.proactive_settings import (
            month_planner_schedule_expression,
            week_planner_schedule_expression,
        )

        week = ScheduleParser.parse(week_planner_schedule_expression("Friday", 18, 0))
        assert (week.schedule_type, week.weekday, week.hour) == ("weekly", 4, 18)
        month = ScheduleParser.parse(month_planner_schedule_expression(31, 9, 15))
        assert (month.schedule_type, month.day_of_month, month.hour, month.minute) == (
            "monthly",
            31,
            9,
            15,
        )
        with pytest.raises(ValueError):
            week_planner_schedule_expression("funday", 9, 0)
        with pytest.raises(ValueError):
            month_planner_schedule_expression(0, 9, 0)

    def test_get_proactive_schedule_reads_the_config(self, tmp_path, monkeypatch):
        import app.ui_layer.settings.proactive_settings as settings

        config = tmp_path / "scheduler_config.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "schedules": [
                        {"id": "heartbeat", "schedule": "*/15 * * * *"},
                        {"id": "day-planner", "schedule": "every day at 8:45am"},
                        {"id": "week-planner", "schedule": "every friday at 6pm"},
                        {
                            "id": "month-planner",
                            "schedule": "every month on day 28 at 7:30am",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "SCHEDULER_CONFIG_PATH", config)
        result = settings.get_proactive_schedule()
        assert result["heartbeat_minutes"] == 15
        assert result["day_planner_time"] == "08:45"
        assert (result["week_planner_day"], result["week_planner_time"]) == (
            "friday",
            "18:00",
        )
        assert (result["month_planner_day"], result["month_planner_time"]) == (
            28,
            "07:30",
        )
