# -*- coding: utf-8 -*-
"""Tests for the TriggerSource taxonomy and dedup-key builders."""

import pytest

from app.triggers import (
    TriggerSource,
    scheduled_dedup_key,
    scheduled_once_dedup_key,
)


class TestTriggerSourceTaxonomy:
    def test_values_are_strings(self):
        # Sources are stored in the triggers.source column as plain strings.
        for source in TriggerSource:
            assert isinstance(source.value, str)
            assert source == source.value  # str-enum equality

    def test_session_era_sources_exist(self):
        assert TriggerSource.USER_MESSAGE.value == "user_message"
        assert TriggerSource.RUN_CONTINUATION.value == "run_continuation"
        assert TriggerSource.RESTART_NOTICE.value == "restart_notice"


class TestDedupKeyBuilders:
    @pytest.mark.parametrize(
        "builder, args, expected",
        [
            (scheduled_once_dedup_key, ("abc123",), "scheduled-once:abc123"),
            # 60-second buckets: same minute → same key
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
