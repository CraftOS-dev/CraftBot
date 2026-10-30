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


# ── prompt-audit views ───────────────────────────────────────────────────────


def test_split_sections():
    text = "<a>\none\n</a>\n\n---\n\n<b>\ntwo\n</b>\ntail"
    assert profiler.split_sections(text) == [
        ("a", "<a>\none\n</a>"),
        ("(other)", "\n\n---\n\n"),
        ("b", "<b>\ntwo\n</b>"),
        ("(other)", "\ntail"),
    ]
    # An inline mention is not a block; an unclosed block runs to the end.
    assert profiler.split_sections("see <a> here\n<c>\nopen") == [
        ("(other)", "see <a> here\n"),
        ("c", "<c>\nopen"),
    ]


def _decision(storage, *, user, inp, cached, task="s1", response="{}", model="m"):
    storage.insert(
        LLMCallRow(
            provider="p",
            model=model,
            system_prompt="<rules>\nr\n</rules>",
            user_prompt=user,
            response=response,
            status="success",
            input_tokens=inp,
            output_tokens=1,
            cached_tokens=cached,
            prompt_name="SELECT_ACTION",
            task_id=task,
        )
    )


def test_cache_report_splits_full_prompts_from_deltas(tmp_path):
    db = os.path.join(tmp_path, "llm_calls.db")
    s = LLMCallStorage(db_path=db)
    _decision(s, user="<event_stream>\ne\n</event_stream>", inp=1000, cached=100)
    _decision(s, user="10:00:00 [action_end]: ok", inp=2000, cached=1900)
    _decision(s, user="10:00:01 [action_end]: ok", inp=2000, cached=0)

    by_kind = {r["kind"]: r for r in profiler.cache_report(db, since=None)}
    assert by_kind["full"]["calls"] == 1 and by_kind["full"]["uncached_tokens"] == 900
    delta = by_kind["delta"]
    assert delta["calls"] == 2 and delta["uncached_tokens"] == 2100
    assert delta["misses"] == 1 and delta["miss_uncached_tokens"] == 2000


def test_section_report_measures_blocks_per_layout(tmp_path):
    db = os.path.join(tmp_path, "llm_calls.db")
    s = LLMCallStorage(db_path=db)
    _decision(
        s,
        user="<session>\nx\n</session>\n<event_stream>\ne\n</event_stream>",
        inp=9,
        cached=0,
    )
    _decision(s, user="10:00:00 [action_end]: ok", inp=9, cached=0)  # a delta: skipped

    (layout,) = profiler.section_report(db, since=None)
    assert layout["layout"] == "rules in system" and layout["rows"] == 1
    blocks = {(b["part"], b["block"]) for b in layout["blocks"]}
    assert blocks == {
        ("system", "rules"),
        ("user", "session"),
        ("user", "event_stream"),
    }


def test_duplication_report_finds_inputs_sent_again(tmp_path):
    import json

    db = os.path.join(tmp_path, "llm_calls.db")
    s = LLMCallStorage(db_path=db)
    content = "line of content " * 20
    reply = json.dumps(
        {"actions": [{"action_name": "write_file", "parameters": {"content": content}}]}
    )
    _decision(
        s, user="<event_stream>\ne\n</event_stream>", inp=9, cached=0, response=reply
    )
    _decision(
        s,
        user=f"10:00:00 [action_start]: {json.dumps(content)}",
        inp=9,
        cached=0,
        response=reply,
    )
    _decision(s, user="10:00:01 [action_end]: ok", inp=9, cached=0)
    _decision(
        s, user="10:00:02 [action_end]: other session", inp=9, cached=0, task="s2"
    )

    report = profiler.duplication_report(db, since=None)
    assert report["long_values_checked"] == 2
    assert report["resent_in_next_delta"] == 1
