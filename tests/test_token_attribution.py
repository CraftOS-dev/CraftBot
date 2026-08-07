# -*- coding: utf-8 -*-
"""
Tests for per-session LLM token attribution.

Verifies that `attribute_usage_to_current_task` correctly bumps the
cumulative token counters on the active Session and emits a
TASK_TOKEN_UPDATE event on the bus so the browser can tick its per-session
token display.
"""

from __future__ import annotations

import pytest

from agent_core.core.hooks.types import UsageEventData
from agent_core.core.session import Session
from app.state.agent_state import STATE
from app.ui_layer.events.event_bus import EventBus
from app.ui_layer.events.event_types import UIEvent, UIEventType
from app.usage.task_attribution import attribute_usage_to_current_task


@pytest.fixture
def fresh_state():
    """Snapshot and restore STATE.current_session / STATE.event_bus per test."""
    prev_session = STATE.current_session
    prev_bus = STATE.event_bus
    yield
    STATE.current_session = prev_session
    STATE.event_bus = prev_bus


def _make_event(input_tokens=100, output_tokens=50, cached_tokens=20):
    return UsageEventData(
        service_type="llm_anthropic",
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )


def test_no_active_session_is_noop(fresh_state):
    """When no session is active, attribution is a silent no-op."""
    STATE.current_session = None
    STATE.event_bus = EventBus()
    # Must not raise
    attribute_usage_to_current_task(_make_event())
    assert STATE.event_bus.get_history() == []


def test_increments_counters_on_active_session(fresh_state):
    """A single call bumps the session's three counters."""
    session = Session(id="s1")
    STATE.current_session = session
    STATE.event_bus = EventBus()

    attribute_usage_to_current_task(_make_event(100, 50, 20))

    assert session.input_tokens == 100
    assert session.output_tokens == 50
    assert session.cache_tokens == 20


def test_accumulates_across_multiple_calls(fresh_state):
    """Counters accumulate, not overwrite."""
    session = Session(id="s2")
    STATE.current_session = session
    STATE.event_bus = EventBus()

    attribute_usage_to_current_task(_make_event(100, 50, 20))
    attribute_usage_to_current_task(_make_event(40, 10, 5))
    attribute_usage_to_current_task(_make_event(7, 3, 0))

    assert session.input_tokens == 147
    assert session.output_tokens == 63
    assert session.cache_tokens == 25


def test_emits_task_token_update_event(fresh_state):
    """Each attribution emits a TASK_TOKEN_UPDATE carrying running totals."""
    session = Session(id="s3")
    STATE.current_session = session
    bus = EventBus()
    STATE.event_bus = bus

    captured: list[UIEvent] = []
    bus.subscribe(UIEventType.TASK_TOKEN_UPDATE, captured.append)

    attribute_usage_to_current_task(_make_event(100, 50, 20))
    attribute_usage_to_current_task(_make_event(40, 10, 5))

    assert len(captured) == 2

    # First event: counters at first call's values
    assert captured[0].type == UIEventType.TASK_TOKEN_UPDATE
    assert captured[0].task_id == "s3"
    assert captured[0].data == {
        "task_id": "s3",
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_tokens": 20,
    }

    # Second event: cumulative running totals
    assert captured[1].data == {
        "task_id": "s3",
        "input_tokens": 140,
        "output_tokens": 60,
        "cache_tokens": 25,
    }


def test_works_without_event_bus(fresh_state):
    """If no bus is registered, counters still update; no crash."""
    session = Session(id="s4")
    STATE.current_session = session
    STATE.event_bus = None  # explicit

    attribute_usage_to_current_task(_make_event(100, 50, 20))

    assert session.input_tokens == 100
    assert session.output_tokens == 50
    assert session.cache_tokens == 20


def test_handles_none_token_fields_as_zero(fresh_state):
    """Sessions restored from older persistence may have None token fields."""
    session = Session(id="s5")
    session.input_tokens = None  # type: ignore[assignment]
    session.output_tokens = None  # type: ignore[assignment]
    session.cache_tokens = None  # type: ignore[assignment]
    STATE.current_session = session
    STATE.event_bus = EventBus()

    attribute_usage_to_current_task(_make_event(10, 5, 1))

    assert session.input_tokens == 10
    assert session.output_tokens == 5
    assert session.cache_tokens == 1
