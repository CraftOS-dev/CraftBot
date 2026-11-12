# -*- coding: utf-8 -*-
"""
Proactive tasks and the scheduler (2026-11-11 study fixes).

- Cron schedules fire in local time. croniter's get_next(float) read the
  naive local start as UTC, so in Tokyo the 30-minute heartbeat slept 569
  minutes between fires, and west of UTC it fired every minute.
- Cron jobs (PROACTIVE.md "Cron Jobs"): "due" is decided by code. Each job
  has a slot per period, last_run is stamped at dispatch, a missed slot runs
  once (late), and active_since keeps a new, re-enabled or rescheduled job
  from firing a slot it never had. The cron-job runner fires them at their
  exact slot.
- Heartbeat: every tick, a non-empty PROACTIVE.md "Heartbeat" checklist is
  handed to one run; an empty one costs nothing.
- PROACTIVE.md is re-read whenever it changed on disk, and saves write over
  the file as it is now (a planner's Goals edit, a hand-added job survive).
- Cron jobs and schedule_task jobs fire in the session that created them;
  memory, the heartbeat and the planners in main. A task whose session was
  deleted is kept but skipped, never stamped.
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

from agent_core.core.session import MAIN_SESSION_ID
from app.proactive.manager import ProactiveManager
from app.proactive.types import CronJob, validate_schedule_fields
from app.scheduler.manager import SchedulerManager
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


def _job(frequency, time_=None, day=None, **kw) -> CronJob:
    return CronJob(
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
        t = _job("daily", "09:00")
        assert t.latest_slot(self.NOW) == datetime(2026, 11, 11, 9, 0)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 12, 9, 0)

    def test_hourly_uses_the_minute(self):
        t = _job("hourly", "00:15")
        assert t.latest_slot(self.NOW) == datetime(2026, 11, 11, 9, 15)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 11, 10, 15)

    def test_weekly(self):
        t = _job("weekly", "17:00", "sunday")
        assert t.latest_slot(self.NOW) == datetime(2026, 11, 8, 17, 0)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 15, 17, 0)

    def test_monthly_clamps_to_the_last_day(self):
        t = _job("monthly", "08:00", "31")
        assert t.latest_slot(self.NOW) == datetime(2026, 10, 31, 8, 0)
        assert t.next_slot(self.NOW) == datetime(2026, 11, 30, 8, 0)
        assert t.next_slot(datetime(2027, 2, 15)) == datetime(2027, 2, 28, 8, 0)

    def test_defaults_to_midnight(self):
        assert _job("daily").latest_slot(self.NOW) == datetime(2026, 11, 11, 0, 0)


class TestDue:
    NOW = datetime(2026, 11, 11, 10, 0)

    def test_due_after_slot_until_dispatched(self):
        t = _job("daily", "09:00", active_since=datetime(2026, 11, 1))
        assert t.is_due(self.NOW)
        t.mark_dispatched(self.NOW)
        assert not t.is_due(self.NOW)
        assert t.run_count == 1
        assert t.next_due_at(self.NOW) == datetime(2026, 11, 12, 9, 0)

    def test_missed_slots_run_once_not_per_slot(self):
        t = _job(
            "daily",
            "09:00",
            active_since=datetime(2026, 11, 1),
            last_run=datetime(2026, 11, 8, 9, 0),
        )
        assert t.is_due(self.NOW)
        t.mark_dispatched(self.NOW)
        assert not t.is_due(self.NOW)

    def test_slot_before_active_since_never_runs(self):
        t = _job("daily", "09:00", active_since=datetime(2026, 11, 11, 9, 30))
        assert not t.is_due(self.NOW)
        assert t.next_due_at(self.NOW) == datetime(2026, 11, 12, 9, 0)

    def test_hourly_runs_once_an_hour(self):
        t = _job("hourly", "00:00", active_since=datetime(2026, 11, 1))
        t.mark_dispatched(datetime(2026, 11, 11, 10, 0))
        assert not t.is_due(datetime(2026, 11, 11, 10, 30))
        assert t.is_due(datetime(2026, 11, 11, 11, 0))

    def test_disabled_is_never_due(self):
        t = _job("daily", "09:00", enabled=False, active_since=datetime(2026, 11, 1))
        assert not t.is_due(self.NOW)
        assert t.next_due_at(self.NOW) is None

    def test_outcome_does_not_reschedule(self):
        t = _job("daily", "09:00", active_since=datetime(2026, 11, 1))
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
        job = CronJob.from_dict({"id": "x", "frequency": "daily", "time": 540})
        assert job.time == "09:00"


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
    def test_add_job_anchors_and_persists(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        job = mgr.add_job(
            name="Brief", frequency="daily", instruction="x", time="09:00"
        )
        assert job.active_since is not None
        reloaded = ProactiveManager(proactive_file)
        reloaded.load()
        assert reloaded.get_job(job.id).active_since is not None

    def test_save_keeps_a_planner_goals_edit(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        text = proactive_file.read_text(encoding="utf-8")
        proactive_file.write_text(
            text.replace("No long-term goals defined yet.", "PLANNER GOAL", 1),
            encoding="utf-8",
        )
        _bump_mtime(proactive_file)
        mgr.add_job(name="Brief", frequency="daily", instruction="x", time="09:00")
        assert "PLANNER GOAL" in proactive_file.read_text(encoding="utf-8")

    def test_hand_added_job_is_seen_kept_and_anchored_at_the_edit(self, proactive_file):
        import os

        mgr = ProactiveManager(proactive_file)
        mgr.load()
        slot = datetime.now() - timedelta(minutes=30)
        text = proactive_file.read_text(encoding="utf-8")
        block = (
            "### [DAILY] Hand added\n```yaml\nid: hand_added\nfrequency: daily\n"
            f'time: "{slot:%H:%M}"\nenabled: true\ninstruction: y\n```\n\n'
        )
        proactive_file.write_text(
            text.replace("<!-- CRON_JOBS_END -->", block + "<!-- CRON_JOBS_END -->", 1),
            encoding="utf-8",
        )
        # Written an hour ago, read only now: the 30-minutes-ago slot is
        # after the edit, so it is owed a run (not skipped for the day).
        written = (datetime.now() - timedelta(hours=1)).timestamp()
        os.utime(proactive_file, (written, written))
        job = mgr.get_job("hand_added")
        assert job is not None
        assert abs(job.active_since.timestamp() - written) < 2
        assert job.is_due()
        mgr.add_job(name="Other", frequency="hourly", instruction="z")
        assert "hand_added" in proactive_file.read_text(encoding="utf-8")

    def test_mark_dispatched_persists(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        job = mgr.add_job(name="Brief", frequency="daily", instruction="x")
        when = datetime(2026, 11, 11, 9, 0, 1)
        mgr.mark_dispatched([job.id], when)
        reloaded = ProactiveManager(proactive_file)
        reloaded.load()
        stored = reloaded.get_job(job.id)
        assert stored.last_run == when and stored.run_count == 1

    def test_re_enabling_restarts_the_schedule(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        job = mgr.add_job(
            name="Brief", frequency="daily", instruction="x", enabled=False
        )
        job.active_since = datetime(2020, 1, 1)
        mgr.save()
        mgr.update_job(job.id, updates={"enabled": True})
        assert mgr.get_job(job.id).active_since > datetime(2026, 1, 1)

    def test_invalid_time_is_rejected(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        with pytest.raises(ValueError):
            mgr.add_job(name="Bad", frequency="daily", instruction="x", time="7am")

    def test_change_listener_fires_on_save(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        calls = []
        mgr.set_change_listener(lambda: calls.append(1))
        mgr.add_job(name="Brief", frequency="daily", instruction="x")
        assert calls


class TestHeartbeatChecklist:
    def test_template_checklist_is_empty(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        assert mgr.get_heartbeat_checklist() == ""

    def test_set_and_read_back_between_the_markers(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        mgr.set_heartbeat_checklist("- Check my inbox\n- Watch the deploy\n")
        text = proactive_file.read_text(encoding="utf-8")
        section = text[
            text.index("<!-- HEARTBEAT_START -->") : text.index(
                "<!-- HEARTBEAT_END -->"
            )
        ]
        assert "- Check my inbox\n- Watch the deploy" in section
        assert "No long-term goals defined yet." in text  # Goals untouched
        reloaded = ProactiveManager(proactive_file)
        reloaded.load()
        assert (
            reloaded.get_heartbeat_checklist() == "- Check my inbox\n- Watch the deploy"
        )

    def test_clearing_brings_back_the_placeholder(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        mgr.set_heartbeat_checklist("- Check my inbox")
        mgr.set_heartbeat_checklist("")
        assert mgr.get_heartbeat_checklist() == ""
        assert "Add what the heartbeat should check" in proactive_file.read_text(
            encoding="utf-8"
        )

    def test_cron_job_saves_keep_the_checklist(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        mgr.set_heartbeat_checklist("- Check my inbox")
        mgr.add_job(name="Brief", frequency="daily", instruction="x")
        reloaded = ProactiveManager(proactive_file)
        reloaded.load()
        assert reloaded.get_heartbeat_checklist() == "- Check my inbox"


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
        instruction="Go through the Heartbeat checklist in PROACTIVE.md",
        schedule=ScheduleParser.parse("*/30 * * * *"),
        skills=["heartbeat-processor"],
        payload={"type": "proactive_heartbeat"},
    )
    sm._schedules[heartbeat.id] = heartbeat
    return sm, mgr, heartbeat


def _overdue_job(mgr):
    """A daily cron job whose slot was an hour ago, active for days."""
    slot = datetime.now() - timedelta(hours=1)
    job = mgr.add_job(
        name="Morning brief",
        frequency="daily",
        instruction="Brief the user",
        time=f"{slot:%H:%M}",
        permission_tier=1,
    )
    stored = mgr.get_job(job.id)
    stored.active_since = datetime.now() - timedelta(days=3)
    mgr.save()
    return job.id


class TestCronJobRunner:
    def test_due_job_goes_to_main_with_its_id_and_is_stamped(
        self, proactive_file, proactive_on
    ):
        sm, mgr, _ = _scheduler(proactive_file)
        job_id = _overdue_job(mgr)

        asyncio.run(sm._fire_cron_jobs())

        (spec,) = sm._trigger_service.specs
        assert spec.session_id == MAIN_SESSION_ID
        assert spec.source == TriggerSource.CRON_JOB
        assert spec.payload["cron_job_ids"] == [job_id]
        assert spec.payload["workflow_skills"] == ["cron-job-runner"]
        assert spec.dedup_key.startswith(f"cron:{job_id}@")
        assert "Brief the user" in spec.description
        assert "Late:" in spec.description
        assert "cron_job_update(job_id, add_outcome=" in spec.description
        assert mgr.get_job(job_id).run_count == 1

        asyncio.run(sm._fire_cron_jobs())
        assert len(sm._trigger_service.specs) == 1  # nothing due any more

    def test_failed_stamp_never_refires_the_slot(self, proactive_file, proactive_on):
        sm, mgr, _ = _scheduler(proactive_file)
        _overdue_job(mgr)

        def locked(*_a, **_k):
            raise OSError("file locked")

        mgr.mark_dispatched = locked
        with pytest.raises(OSError):
            asyncio.run(sm._fire_cron_jobs())
        asyncio.run(sm._fire_cron_jobs())
        assert len(sm._trigger_service.specs) == 1

    def test_nothing_due_emits_nothing(self, proactive_file, proactive_on):
        sm, mgr, _ = _scheduler(proactive_file)
        asyncio.run(sm._fire_cron_jobs())
        assert sm._trigger_service.specs == []

    def test_proactive_off_emits_nothing_and_stamps_nothing(
        self, proactive_file, proactive_on
    ):
        sm, mgr, _ = _scheduler(proactive_file)
        job_id = _overdue_job(mgr)
        proactive_on["enabled"] = False
        asyncio.run(sm._fire_cron_jobs())
        assert sm._trigger_service.specs == []
        assert mgr.get_job(job_id).run_count == 0

    def test_runner_fires_a_due_job_and_sleeps_until_the_next(
        self, proactive_file, proactive_on
    ):
        sm, mgr, _ = _scheduler(proactive_file)
        _overdue_job(mgr)

        async def scenario():
            sm._is_running = True
            sm._loop = asyncio.get_running_loop()
            sm._cron_wake = asyncio.Event()
            task = asyncio.create_task(sm._cron_jobs_loop())
            for _ in range(50):
                if sm._trigger_service.specs:
                    break
                await asyncio.sleep(0.02)
            sm._is_running = False
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        asyncio.run(scenario())
        assert len(sm._trigger_service.specs) == 1

    def test_job_change_rearms_the_runner(self, proactive_file, proactive_on):
        sm, mgr, _ = _scheduler(proactive_file)

        async def scenario():
            sm._loop = asyncio.get_running_loop()
            sm._cron_wake = asyncio.Event()
            mgr.add_job(name="Brief", frequency="daily", instruction="x")
            return sm._cron_wake.is_set()

        assert asyncio.run(scenario())


class TestHeartbeat:
    def test_empty_checklist_never_fires(self, proactive_file, proactive_on):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        assert sm._should_fire(heartbeat) is False
        asyncio.run(sm._fire_schedule(heartbeat))
        assert sm._trigger_service.specs == []

    def test_checklist_goes_to_main_in_the_instruction(
        self, proactive_file, proactive_on
    ):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        mgr.set_heartbeat_checklist("- Check my inbox for urgent client email")
        asyncio.run(sm._fire_schedule(heartbeat))
        (spec,) = sm._trigger_service.specs
        assert spec.source == TriggerSource.PROACTIVE_HEARTBEAT
        assert spec.session_id == MAIN_SESSION_ID
        assert "- Check my inbox for urgent client email" in spec.description
        assert "end_turn" in spec.description

    def test_proactive_off_stops_the_heartbeat(self, proactive_file, proactive_on):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        mgr.set_heartbeat_checklist("- Check my inbox")
        proactive_on["enabled"] = False
        assert sm._should_fire(heartbeat) is False

    def test_heartbeat_keeps_its_own_interval(self, proactive_file, proactive_on):
        sm, mgr, heartbeat = _scheduler(proactive_file)
        _overdue_job(mgr)  # a due cron job does not pull the heartbeat in
        start = _ts(2026, 11, 6, 10, 1)
        nxt = ScheduleParser.calculate_next_fire_time(
            heartbeat.schedule, from_time=start
        )
        assert nxt == _ts(2026, 11, 6, 10, 30)


class TestRouting:
    def test_memory_runs_in_main(self, monkeypatch):
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

    def test_user_schedule_runs_in_main(self):
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
        assert spec.session_id == MAIN_SESSION_ID

    def test_immediate_runs_in_main(self):
        sm = SchedulerManager()
        sm._trigger_service = _FakeTriggerService()
        asyncio.run(sm.queue_immediate_trigger(name="Now", instruction="Do it"))
        (spec,) = sm._trigger_service.specs
        assert spec.session_id == MAIN_SESSION_ID


# ─────────────────────────── Task sessions ───────────────────────────


def _sessions(*alive):
    """A session manager that knows only the given (non-main) sessions."""
    return types.SimpleNamespace(get=lambda sid: object() if sid in alive else None)


def _overdue_in(mgr, name, session_id):
    slot = datetime.now() - timedelta(hours=1)
    job = mgr.add_job(
        name=name,
        frequency="daily",
        instruction=f"Do {name}",
        time=f"{slot:%H:%M}",
        session_id=session_id,
    )
    stored = mgr.get_job(job.id)
    stored.active_since = datetime.now() - timedelta(days=3)
    mgr.save()
    return job.id


class TestTaskSessions:
    def test_cron_jobs_fire_as_one_run_per_session(self, proactive_file, proactive_on):
        sm, mgr, _ = _scheduler(proactive_file)
        sm._session_manager = _sessions("chat1")
        main_job = _overdue_in(mgr, "Main brief", MAIN_SESSION_ID)
        chat_job = _overdue_in(mgr, "Chat brief", "chat1")

        asyncio.run(sm._fire_cron_jobs())

        by_session = {s.session_id: s for s in sm._trigger_service.specs}
        assert set(by_session) == {MAIN_SESSION_ID, "chat1"}
        assert by_session[MAIN_SESSION_ID].payload["cron_job_ids"] == [main_job]
        assert by_session["chat1"].payload["cron_job_ids"] == [chat_job]
        assert "Chat brief" in by_session["chat1"].description
        assert "Chat brief" not in by_session[MAIN_SESSION_ID].description

    def test_deleted_session_job_is_kept_skipped_and_not_stamped(
        self, proactive_file, proactive_on
    ):
        sm, mgr, _ = _scheduler(proactive_file)
        sm._session_manager = _sessions()
        job_id = _overdue_in(mgr, "Orphan", "deleted_chat")

        asyncio.run(sm._fire_cron_jobs())

        assert sm._trigger_service.specs == []
        assert mgr.get_job(job_id).run_count == 0
        # It never counts as due, so it cannot hold the runner awake.
        now = datetime.now()
        due_at = mgr.next_due_at(now, runnable=sm._job_runnable)
        assert due_at is None or due_at > now

    def test_moving_a_job_restarts_its_schedule(self, proactive_file, proactive_on):
        sm, mgr, _ = _scheduler(proactive_file)
        job_id = _overdue_in(mgr, "Orphan", "deleted_chat")
        mgr.update_job(job_id, updates={"session_id": MAIN_SESSION_ID})
        job = mgr.get_job(job_id)
        assert job.session_id == MAIN_SESSION_ID
        assert not job.is_due(datetime.now())  # no late run of a missed slot

    def test_session_round_trips_in_proactive_md(self, proactive_file):
        mgr = ProactiveManager(proactive_file)
        mgr.load()
        job = mgr.add_job(
            name="Chat brief", frequency="daily", instruction="x", session_id="abc123"
        )
        again = ProactiveManager(proactive_file)
        again.load()
        assert again.get_job(job.id).session_id == "abc123"
        assert CronJob.from_dict({"id": "x"}).session_id == MAIN_SESSION_ID

    def test_scheduled_task_fires_in_its_session(self):
        sm = SchedulerManager()
        sm._trigger_service = _FakeTriggerService()
        task = ScheduledTask(
            id="abc",
            name="Call mom",
            instruction="Remind the user to call mom",
            schedule=ScheduleParser.parse("every day at 7am"),
            session_id="chat1",
        )
        asyncio.run(sm._fire_schedule(task))
        (spec,) = sm._trigger_service.specs
        assert spec.session_id == "chat1"

    def test_immediate_runs_in_the_calling_session(self):
        sm = SchedulerManager()
        sm._trigger_service = _FakeTriggerService()
        asyncio.run(
            sm.queue_immediate_trigger(
                name="Now", instruction="Do it", session_id="chat1"
            )
        )
        (spec,) = sm._trigger_service.specs
        assert spec.session_id == "chat1"

    def test_scheduled_task_session_is_saved_only_when_not_main(self):
        expr = ScheduleParser.parse("every day at 7am")
        mine = ScheduledTask(
            id="a", name="A", instruction="x", schedule=expr, session_id="chat1"
        )
        builtin = ScheduledTask(id="b", name="B", instruction="x", schedule=expr)
        assert mine.to_dict()["session_id"] == "chat1"
        assert "session_id" not in builtin.to_dict()
        assert ScheduledTask.from_dict(mine.to_dict(), expr).session_id == "chat1"
        assert (
            ScheduledTask.from_dict(builtin.to_dict(), expr).session_id
            == MAIN_SESSION_ID
        )

    def test_deleted_session_schedule_stops_without_firing(self):
        sm = SchedulerManager()
        sm._trigger_service = _FakeTriggerService()
        sm._session_manager = _sessions()
        task = ScheduledTask(
            id="abc",
            name="Call mom",
            instruction="Remind the user",
            schedule=ScheduleParser.parse("every 1 minutes"),
            session_id="deleted_chat",
        )
        sm._schedules[task.id] = task

        async def scenario():
            sm._is_running = True
            await asyncio.wait_for(sm._schedule_loop(task.id), timeout=5)

        asyncio.run(scenario())
        assert sm._trigger_service.specs == []
        assert sm.get_schedule(task.id) is task  # kept, just unavailable
        assert sm.is_session_available("deleted_chat") is False
        assert sm.is_session_available(MAIN_SESSION_ID) is True


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
