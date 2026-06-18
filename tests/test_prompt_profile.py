# -*- coding: utf-8 -*-
"""
Tests for the prompt profiler (issue #322, P2).

Covers the cost-aware pricing single-source and the profiler's aggregation over
the captured llm_calls table.
"""

import importlib
import os
import tempfile

from app.usage.llm_call_storage import LLMCallStorage, LLMCallRow
from app.usage.pricing import get_model_pricing, estimate_cost

profiler = importlib.import_module("scripts.prompt_profile")


# ── pricing ──────────────────────────────────────────────────────────────────


def test_pricing_longest_match_avoids_shadowing():
    # "gpt-4o" must NOT shadow "gpt-4o-mini"
    assert get_model_pricing("gpt-4o-mini")["input"] == 0.15
    assert get_model_pricing("gpt-4o-2024-08")["input"] == 2.50
    assert get_model_pricing("gemini-2.5-pro")["cached"] == 0.125
    assert get_model_pricing("claude-opus-4-8")["input"] == 15.00
    assert get_model_pricing("totally-unknown")["input"] == 1.00  # default


def test_estimate_cost_accounts_for_cache():
    c = estimate_cost(
        "gemini-2.5-pro", input_tokens=10_000, output_tokens=500, cached_tokens=8_000
    )
    # uncached 2000 @1.25 + cached 8000 @0.125 = 0.0035; output 500 @10 = 0.005
    assert round(c["input_cost"], 6) == 0.0035
    assert round(c["output_cost"], 6) == 0.005
    assert round(c["total_cost"], 6) == 0.0085
    # saved = 8000 * (1.25 - 0.125) / 1e6
    assert round(c["saved"], 6) == 0.009


def test_estimate_cost_clamps_cached_to_input():
    # cached can't exceed input; must not produce negative uncached cost
    c = estimate_cost(
        "gemini-2.5-pro", input_tokens=100, output_tokens=0, cached_tokens=999
    )
    assert c["input_cost"] >= 0
    assert round(c["input_cost"], 8) == round(100 * 0.125 / 1e6, 8)


# ── percentile ───────────────────────────────────────────────────────────────


def test_percentile():
    assert profiler._percentile([], 0.5) == 0.0
    assert profiler._percentile([42], 0.95) == 42
    assert profiler._percentile([1, 2, 3, 4], 0.5) == 2.5
    assert profiler._percentile([10, 20, 30], 0.0) == 10
    assert profiler._percentile([10, 20, 30], 1.0) == 30


# ── aggregation ──────────────────────────────────────────────────────────────


def _seed():
    db = os.path.join(tempfile.mkdtemp(), "llm_calls.db")
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


def test_aggregate_groups_and_metrics():
    db = _seed()
    rows = profiler.load_rows(db, since=None)
    agg = profiler.aggregate(rows)

    by_name = {r["prompt_name"]: r for r in agg}
    assert set(by_name) == {"SELECT_ACTION_IN_TASK", "EVENT_STREAM_SUMMARIZATION"}

    task = by_name["SELECT_ACTION_IN_TASK"]
    assert task["calls"] == 2
    assert task["avg_input_tokens"] == 1900  # (1800+2000)/2
    # cache hit ratio = (1200+1500)/(1800+2000) = 2700/3800
    assert round(task["cache_hit_ratio"], 4) == round(2700 / 3800, 4)
    assert task["saved_usd"] > 0

    # sorted by cost desc → summarization (4000 in/400 out) is the priciest
    assert agg[0]["prompt_name"] == "EVENT_STREAM_SUMMARIZATION"


def test_load_rows_missing_db_is_empty():
    assert profiler.load_rows("/no/such/file.db", since=None) == []


def test_parse_since():
    from datetime import datetime

    assert profiler._parse_since(None) is None
    dt = profiler._parse_since("24h")
    assert isinstance(dt, datetime)
