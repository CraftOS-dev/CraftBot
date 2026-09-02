# -*- coding: utf-8 -*-
"""A fix mission must not be eaten by a chat message that happened to be due.

Regression cover for the 2026-09-02 16:12 incident (brainstorm_graph
f1eb1c85). The runtime logged:

    Aggregated 3 queued trigger(s) (user_message, agent_app_crash_fix,
    run_continuation) into one turn

The crash-fix trigger carried a FIX MISSION for a deploy that walk-verify had
just blocked. Merged into the user message's turn it became item 2 of a prose
checklist and lost its payload — the merge keeps the BASE trigger's payload —
so project_id and factory_mission_id vanished. The agent answered the chat,
the mission was never run, and the machine kept it marked active forever.
"""

import asyncio
import time

from agent_core.core.impl.trigger.session_queue import SessionTriggerQueue
from agent_core.core.trigger import Trigger
from app.triggers.runtime import EXCLUSIVE_SOURCES, _merge_triggers
from app.triggers.sources import TriggerSource

CRASH_FIX = TriggerSource.AGENT_APP_CRASH_FIX.value


def trig(desc, source, *, payload=None, fire_at=None):
    return Trigger(
        fire_at=fire_at if fire_at is not None else time.time() - 1,
        priority=50,
        next_action_description=desc,
        session_id="lui_f1eb1c85",
        source=source,
        payload=payload or {},
    )


def user_msg(text="where are the suggestiosn?", fire_at=None):
    return trig(
        text,
        TriggerSource.USER_MESSAGE.value,
        payload={"user_message": text},
        fire_at=fire_at,
    )


def fix_mission():
    return trig(
        "FIX MISSION 2 for Agent App 'Brainstorm Graph' (f1eb1c85).",
        CRASH_FIX,
        payload={
            "project_id": "f1eb1c85",
            "factory_mission_id": "m2",
            "workflow_skills": ["agent-app-creator"],
        },
    )


class TestExclusiveSources:
    def test_a_fix_mission_is_exclusive(self):
        assert CRASH_FIX in EXCLUSIVE_SOURCES

    def test_it_is_not_drained_into_another_trigger_s_turn(self):
        async def scenario():
            q = SessionTriggerQueue("lui_f1eb1c85")
            await q.put(user_msg())
            await q.put(fix_mission())
            await q.put(trig("continue", TriggerSource.RUN_CONTINUATION.value))
            claimed = await asyncio.wait_for(q.get(), timeout=2)
            extras = await q.pop_due_batch(exclude_sources=EXCLUSIVE_SOURCES)
            return claimed, extras, await q.pop_due_batch()

        claimed, extras, left = asyncio.run(scenario())
        assert claimed.source == TriggerSource.USER_MESSAGE.value
        # The continuation still aggregates; the mission does not.
        assert [t.source for t in extras] == [TriggerSource.RUN_CONTINUATION.value]
        assert [t.source for t in left] == [CRASH_FIX]

    def test_held_back_triggers_keep_their_place_in_line(self):
        # Holding a source out of someone else's turn must not reorder it:
        # two missions come back in the order they were queued.
        async def scenario():
            q = SessionTriggerQueue("lui_f1eb1c85")
            base = time.time() - 10
            await q.put(user_msg(fire_at=base))
            await q.put(trig("first mission", CRASH_FIX, fire_at=base + 1))
            await q.put(trig("second mission", CRASH_FIX, fire_at=base + 2))
            claimed = await asyncio.wait_for(q.get(), timeout=2)
            extras = await q.pop_due_batch(exclude_sources=EXCLUSIVE_SOURCES)
            a = await asyncio.wait_for(q.get(), timeout=2)
            b = await asyncio.wait_for(q.get(), timeout=2)
            return claimed, extras, a, b

        claimed, extras, a, b = asyncio.run(scenario())
        assert claimed.source == TriggerSource.USER_MESSAGE.value
        assert extras == []
        assert [t.next_action_description for t in (a, b)] == [
            "first mission",
            "second mission",
        ]

    def test_without_the_exclusion_everything_still_aggregates(self):
        # The default stays "one turn for everything due" — this is opt-in.
        async def scenario():
            q = SessionTriggerQueue("lui_f1eb1c85")
            await q.put(user_msg())
            await q.put(fix_mission())
            await asyncio.wait_for(q.get(), timeout=2)
            return await q.pop_due_batch()

        assert [t.source for t in asyncio.run(scenario())] == [CRASH_FIX]


class TestMergeKeepsWorkIdentity:
    def test_the_mission_id_survives_a_merge(self):
        # Belt and braces: even if a mission is ever merged (a source added
        # to EXCLUSIVE_SOURCES later, an older queued row), the factory must
        # still be able to close it out.
        merged = _merge_triggers(user_msg(), [fix_mission()])
        assert merged.payload["factory_mission_id"] == "m2"
        assert merged.payload["project_id"] == "f1eb1c85"

    def test_the_base_trigger_s_own_identity_is_never_overwritten(self):
        base = trig(
            "resume",
            CRASH_FIX,
            payload={"project_id": "aaa", "factory_mission_id": "m1"},
        )
        merged = _merge_triggers(base, [fix_mission()])
        assert merged.payload["factory_mission_id"] == "m1"
        assert merged.payload["project_id"] == "aaa"

    def test_routing_and_skill_merging_still_work(self):
        merged = _merge_triggers(user_msg(), [fix_mission()])
        assert merged.payload["workflow_skills"] == ["agent-app-creator"]
        assert "2 triggers fired" in merged.next_action_description

    def test_a_merge_with_no_identity_anywhere_adds_nothing(self):
        merged = _merge_triggers(user_msg(), [user_msg("and londong")])
        assert "factory_mission_id" not in merged.payload
