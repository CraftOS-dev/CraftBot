# -*- coding: utf-8 -*-
"""Checks for /tokens: cumulative counters and the display math."""

import asyncio
from types import SimpleNamespace

from agent_core.core.session import Session
from app.ui_layer.commands.builtin.tokens import TokensCommand


def _run(session):
    """Execute /tokens against a stub controller holding `session`."""
    controller = SimpleNamespace(
        agent=SimpleNamespace(
            session_manager=SimpleNamespace(get=lambda _id: session)
        )
    )
    return asyncio.run(TokensCommand(controller).execute([], session_id="s1"))


def test_totals_survive_run_reset():
    """reset_run_counters() clears per-run counters but not the totals."""
    s = Session(id="s1")
    s.input_tokens, s.output_tokens, s.cache_tokens = 100, 20, 80
    s.total_input_tokens, s.total_output_tokens, s.total_cache_tokens = 100, 20, 80

    s.reset_run_counters()

    assert s.input_tokens == 0
    assert (s.total_input_tokens, s.total_output_tokens, s.total_cache_tokens) == (
        100,
        20,
        80,
    )


def test_totals_round_trip_through_dict():
    """Persistence goes through session_json, so to_dict/from_dict must carry them."""
    s = Session(id="s1")
    s.total_input_tokens, s.total_output_tokens, s.total_cache_tokens = 100, 20, 80

    restored = Session.from_dict(s.to_dict())

    assert restored.total_input_tokens == 100
    assert restored.total_output_tokens == 20
    assert restored.total_cache_tokens == 80


def test_old_sessions_load_as_zero():
    """Sessions persisted before this feature have no totals key."""
    restored = Session.from_dict({"id": "s1"})

    assert restored.total_input_tokens == 0


def test_input_excludes_cached_and_total_excludes_both():
    """cached is a subset of input; total counts new tokens only."""
    s = Session(id="s1")
    s.total_input_tokens, s.total_output_tokens, s.total_cache_tokens = 100, 20, 80

    d = _run(s).data

    assert d["input"] == 20  # 100 - 80
    assert d["raw_input"] == 100  # full prompt, cache reads included
    assert d["cached"] == 80
    assert d["output"] == 20
    assert d["total"] == 40  # 20 + 20, cached excluded


def test_input_clamps_when_cached_exceeds_input():
    """A provider over-reporting cache reads must not yield a negative count."""
    s = Session(id="s1")
    s.total_input_tokens, s.total_cache_tokens = 50, 80

    d = _run(s).data

    assert d["input"] == 0
    assert d["total"] == 0


def test_unsaved_session_reads_as_zero():
    """A brand-new chat has no session yet (id is "new") — report zeros."""
    result = _run(None)

    assert result.success is True
    assert result.data["input"] == 0
    assert result.data["cached"] == 0
    assert result.data["output"] == 0
    assert result.data["total"] == 0
