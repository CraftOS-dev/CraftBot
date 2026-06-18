# -*- coding: utf-8 -*-
"""Phase 2 tests: TriggerSource taxonomy, dedup-key builders, and react()
classification equivalence (source-first with payload["type"] fallback)."""

import time

import pytest

from agent_core.core.trigger import Trigger

from app.agent_base import AgentBase
from app.triggers import (
    TriggerSource,
    resume_dedup_key,
    scheduled_dedup_key,
    scheduled_once_dedup_key,
)


def trig(source="", payload=None):
    return Trigger(
        fire_at=time.time(),
        priority=50,
        next_action_description="x",
        payload=payload or {},
        session_id="s1",
        source=source,
    )


class TestDedupKeyBuilders:
    @pytest.mark.parametrize(
        "builder, args, expected",
        [
            (scheduled_once_dedup_key, ("abc123",), "scheduled-once:abc123"),
            (resume_dedup_key, ("task42",), "resume:task42"),
            # 120 seconds apart within the same minute bucket → same key
            (scheduled_dedup_key, ("s1", 600.0), "scheduled:s1:10"),
            (scheduled_dedup_key, ("s1", 659.9), "scheduled:s1:10"),
            (scheduled_dedup_key, ("s1", 660.0), "scheduled:s1:11"),
        ],
    )
    def test_builders(self, builder, args, expected):
        assert builder(*args) == expected

    def test_same_fire_retried_dedups_next_occurrence_does_not(self):
        fire = 1_700_000_000.0
        assert scheduled_dedup_key("a", fire) == scheduled_dedup_key("a", fire + 30)
        assert scheduled_dedup_key("a", fire) != scheduled_dedup_key("a", fire + 3600)
        assert scheduled_dedup_key("a", fire) != scheduled_dedup_key("b", fire)


class TestReactClassification:
    """Source-based classification must match the legacy payload["type"]
    behavior exactly — for migrated producers AND for legacy/scheduler-config
    triggers that still carry only a payload type."""

    # Unbound calls (staticmethod so the test class doesn't rebind self):
    # the classifiers don't touch self.
    is_memory = staticmethod(AgentBase._is_memory_trigger)
    is_proactive = staticmethod(AgentBase._is_proactive_trigger)
    is_restart = staticmethod(AgentBase._is_restart_notice_trigger)

    def test_source_based(self):
        assert self.is_memory(None, trig(source=TriggerSource.MEMORY))
        assert self.is_proactive(None, trig(source=TriggerSource.PROACTIVE_HEARTBEAT))
        assert self.is_proactive(None, trig(source=TriggerSource.PROACTIVE_PLANNER))
        assert self.is_restart(None, trig(source=TriggerSource.RESTART_NOTICE))

    def test_legacy_payload_fallback(self):
        assert self.is_memory(None, trig(payload={"type": "memory_processing"}))
        assert self.is_proactive(None, trig(payload={"type": "proactive_heartbeat"}))
        assert self.is_proactive(None, trig(payload={"type": "proactive_planner"}))
        assert self.is_restart(None, trig(payload={"type": "restart_notice"}))

    def test_scheduler_config_payload_overrides_scheduled_source(self):
        # scheduler_config.json entries inject their own payload["type"]
        # (e.g. proactive_heartbeat) on top of a SCHEDULED-source trigger —
        # they must still classify as proactive/memory.
        heartbeat = trig(
            source=TriggerSource.SCHEDULED,
            payload={"type": "proactive_heartbeat"},
        )
        memory = trig(
            source=TriggerSource.SCHEDULED,
            payload={"type": "memory_processing", "scheduled": True},
        )
        assert self.is_proactive(None, heartbeat)
        assert self.is_memory(None, memory)

    def test_task_continuation_never_classified_as_request(self):
        # Triggers that START an already-created task (memory task, heartbeat
        # task, planner task) are TASK_CONTINUATION — routing them into the
        # request branches would create duplicate tasks.
        t = trig(source=TriggerSource.TASK_CONTINUATION)
        assert not self.is_memory(None, t)
        assert not self.is_proactive(None, t)
        assert not self.is_restart(None, t)

    def test_plain_user_trigger_classified_nowhere(self):
        t = trig(source=TriggerSource.USER_MESSAGE)
        assert not self.is_memory(None, t)
        assert not self.is_proactive(None, t)
        assert not self.is_restart(None, t)
        legacy = trig()  # no source, no type — pre-migration shape
        assert not self.is_memory(None, legacy)
        assert not self.is_proactive(None, legacy)
        assert not self.is_restart(None, legacy)
