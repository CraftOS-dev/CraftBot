# -*- coding: utf-8 -*-
"""
Tests for the prompt profiler (issue #322, P2).

Covers the token-volume profiler's aggregation over
the captured llm_calls table.
"""

import importlib
import os

from app.usage.llm_call_storage import LLMCallStorage, LLMCallRow

profiler = importlib.import_module("scripts.prompt_profile")


# ── percentile ───────────────────────────────────────────────────────────────


def test_percentile():
    assert profiler._percentile([], 0.5) == 0.0
    assert profiler._percentile([42], 0.95) == 42
    assert profiler._percentile([1, 2, 3, 4], 0.5) == 2.5
    assert profiler._percentile([10, 20, 30], 0.0) == 10
    assert profiler._percentile([10, 20, 30], 1.0) == 30


# ── aggregation ──────────────────────────────────────────────────────────────


def _seed(tmp_path):
    db = os.path.join(tmp_path, "llm_calls.db")
    s = LLMCallStorage(db_path=db)
    seed = [
        ("SELECT_ACTION_IN_TASK", 2500, 1800, 40, 1200),
        ("SELECT_ACTION_IN_TASK", 3100, 2000, 55, 1500),
        ("EVENT_STREAM_SUMMARIZATION", 5000, 4000, 400, 0),
    ]
    for name, lat, inp, out, cached in seed:
        s.insert(
            LLMCallRow(
                provider="gemini",
                model="gemini-2.5-pro",
                system_prompt="s",
                user_prompt="u",
                response="r",
                status="success",
                input_tokens=inp,
                output_tokens=out,
                cached_tokens=cached,
                latency_ms=lat,
                prompt_name=name,
            )
        )
    return db


def test_aggregate_groups_and_metrics(tmp_path):
    db = _seed(tmp_path)
    rows = profiler.load_rows(db, since=None)
    agg = profiler.aggregate(rows)

    by_name = {r["prompt_name"]: r for r in agg}
    assert set(by_name) == {"SELECT_ACTION_IN_TASK", "EVENT_STREAM_SUMMARIZATION"}

    task = by_name["SELECT_ACTION_IN_TASK"]
    assert task["calls"] == 2
    assert task["avg_input_tokens"] == 1900  # (1800+2000)/2
    # cache hit ratio = (1200+1500)/(1800+2000) = 2700/3800
    assert round(task["cache_hit_ratio"], 4) == round(2700 / 3800, 4)
    assert task["total_input_tokens"] == 3800
    assert task["total_output_tokens"] == 95
    assert task["errors"] == 0

    # Ranked by total input volume: summarization has 4000 input tokens.
    assert agg[0]["prompt_name"] == "EVENT_STREAM_SUMMARIZATION"


def test_load_rows_missing_db_is_empty():
    assert profiler.load_rows("/no/such/file.db", since=None) == []


def test_parse_since():
    from datetime import datetime

    assert profiler._parse_since(None) is None
    dt = profiler._parse_since("24h")
    assert isinstance(dt, datetime)
