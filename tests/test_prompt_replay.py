# -*- coding: utf-8 -*-
"""Tests for the decision replay (prompt audit T0): the layout transform and
the decision comparison. No model is called."""

import importlib

from agent_core.core.prompts.action import (
    SELECT_ACTION_INSTRUCTIONS,
    SELECT_ACTION_PROMPT,
    decision_system_prompt,
)

replay = importlib.import_module("scripts.prompt_replay")


def _captured_user(instructions, user):
    """A user message as captured before T1: the instructions opened it."""
    return "\n" + instructions + "\n\n" + user


def test_t1_layout_matches_what_the_router_sends():
    instructions = SELECT_ACTION_INSTRUCTIONS.format(
        action_candidates='[{"name": "x"}]'
    )
    user = SELECT_ACTION_PROMPT.format(
        session_state="<session>\nS\n</session>",
        event_stream="<event_stream>\n</actions> quoted in a read\n</event_stream>",
        query="hi",
    )
    moved = replay.to_t1_layout("BASE", _captured_user(instructions, user))
    assert moved == (decision_system_prompt("BASE", instructions), user)


def test_t1_layout_skips_requests_captured_after_t1():
    assert (
        replay.to_t1_layout("BASE\n\n<rules>\n...", "<session>\nS\n</session>") is None
    )


def test_decision_actions():
    assert replay.decision_actions(
        '{"reasoning": "r", "actions": [{"action_name": "b"}, {"action_name": "a"}]}'
    ) == ("a", "b")
    assert replay.decision_actions('{"action_name": "end_turn", "parameters": {}}') == (
        "end_turn",
    )
    assert replay.decision_actions(
        'text first {"actions": [{"action_name": "a"}]}'
    ) == ("a",)
    assert replay.decision_actions("") is None
    assert replay.decision_actions("not json") is None


def test_summarize_compares_against_self_agreement():
    results = [
        {"id": 1, "captured_1": ("a",), "captured_2": ("a",), "candidate": ("a",)},
        {"id": 2, "captured_1": ("a",), "captured_2": ("b",), "candidate": ("b",)},
        {"id": 3, "captured_1": ("a",), "captured_2": ("a",), "candidate": ("c",)},
        {"id": 4, "captured_1": None, "captured_2": ("a",), "candidate": None},
    ]
    summary = replay.summarize(results)
    assert summary["self_agreement"] == 2 / 3
    assert summary["cross_agreement"] == 3 / 6
    assert summary["unparsed"] == {"captured": 1, "candidate": 1}
    assert [d["id"] for d in summary["disagreements"]] == [3]


# ── folds (T5) ───────────────────────────────────────────────────────────────


def _standalone_prompt(lines):
    from agent_core.core.prompts import EVENT_STREAM_SUMMARIZATION_PROMPT

    return EVENT_STREAM_SUMMARIZATION_PROMPT.format(
        window="w", previous_summary="(none)", compact_lines="\n".join(lines)
    )


def test_the_fold_marker_is_the_last_folded_event():
    prompt = _standalone_prompt(
        [
            "10:00:00 [user message]: hi",
            '10:00:05 [action_start]: Running action write_file with input: {\n  "x": 1\n}.',
        ]
    )
    assert replay.fold_marker(prompt).startswith("10:00:05 [action_start]: Running")
    long_prompt = _standalone_prompt(["10:00:00 [action_end]: " + "y" * 1000])
    assert replay.fold_marker(long_prompt).endswith(" ...")
    assert replay.fold_marker("no events here") is None


def test_fact_recall_counts_the_concrete_facts_a_summary_keeps():
    chunk = (
        "wrote C:\\work\\report.md and fetched https://example.com/a?b=1 "
        "for ops@example.com, order 12,345, run 9f58177eef1b"
    )
    found = replay.facts(chunk)
    assert {
        "c:\\work\\report.md",
        "https://example.com/a?b=1",
        "ops@example.com",
        "12,345",
        "9f58177eef1b",
    } <= found
    summary = "Report saved to C:\\work\\report.md; order 12,345 placed."
    assert replay.fact_recall(found, summary) == 2 / len(found)
    assert replay.fact_recall(found, None) is None
    assert replay.fact_recall(set(), summary) is None
