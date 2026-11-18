# -*- coding: utf-8 -*-
"""The action list the model reads is compact and lossless (prompt audit T8).

Action lists (the main <actions> block, every action_schemas load, sub-agent
prompts) were pretty-printed JSON, and every integration action repeated the
same ``account`` description (about 55 tokens each, 43 times in one Stripe
load). The list is now one action per line without padding, and a parameter
every action of the list takes with the same text is written once above it.
These tests pin:

* the layout: a JSON array, one action per line, a shared-params line only
  when there is something every action shares;
* nothing is lost: putting the shared params back into each action gives
  exactly what each action renders alone, on the real registry's
  integration loads;
* the same list always renders the same text (it sits in cached prefixes).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_core.core.action_framework.formatting import format_action_candidates

REPO = Path(__file__).resolve().parents[1]
SHARED = "Every action below also takes these params: "


def _action(name, **params):
    return {
        "name": name,
        "description": f"{name} things.",
        "input_schema": {
            p: {"type": "string", "required": req, "description": f"The {p}."}
            for p, req in params.items()
        },
    }


def _parse(block):
    """(shared params, actions) of a rendered list."""
    lines = block.splitlines()
    shared = {}
    if lines[0].startswith(SHARED):
        shared = json.loads(lines[0][len(SHARED) :])
        lines = lines[1:]
    return shared, json.loads("\n".join(lines))


def test_one_action_per_line_without_padding():
    block = format_action_candidates(
        [_action("a", path=True), _action("b", query=True), _action("c")]
    )
    lines = block.splitlines()
    assert lines[0] == "[" and lines[-1] == "]"
    assert len(lines) == 5
    assert all("\n" not in line and ": " not in line.split('"')[0] for line in lines)
    assert [a["name"] for a in json.loads(block)] == ["a", "b", "c"]


def test_a_param_every_action_takes_is_written_once():
    block = format_action_candidates(
        [_action("a", path=True, account=False), _action("b", account=False)]
    )
    shared, actions = _parse(block)
    assert shared == {"account": "string, optional - The account."}
    assert [a["params"] for a in actions] == [
        {"path": "string, required - The path."},
        {},
    ]
    assert block.count("The account.") == 1


def test_a_param_some_actions_lack_or_word_differently_is_kept_in_each():
    lacking = format_action_candidates([_action("a", account=False), _action("b")])
    assert not lacking.startswith(SHARED)
    differing = [_action("a", account=False), _action("b", account=False)]
    differing[1]["input_schema"]["account"]["description"] = "Another account."
    assert not format_action_candidates(differing).startswith(SHARED)


def test_a_single_action_shares_nothing():
    block = format_action_candidates([_action("a", account=False)])
    assert json.loads(block)[0]["params"] == {"account": "string, optional - The account."}


def test_the_same_list_renders_the_same_text():
    cands = [_action("a", account=False), _action("b", account=False)]
    assert format_action_candidates(cands) == format_action_candidates(cands)


# ── the real registry ────────────────────────────────────────────────────────

_LOADS = """
import json, sys
sys.path.insert(0, ".")
from agent_core.core.action_framework.loader import load_actions_from_directories
load_actions_from_directories(paths_to_scan=["app/data/action"])
from app.data.action.integrations.account_bridge import inject_account_schemas
inject_account_schemas()
from agent_core.core.action_framework.formatting import (
    candidate_dict_from_action, format_action_candidates,
)
from app.action.action_set import action_set_manager
out = {}
for set_name in ("stripe", "google_drive", "gmail", "slack", "telegram"):
    metas = action_set_manager.actions_in_sets([set_name], mode="CLI")
    cands = [candidate_dict_from_action(m) for m in metas]
    out[set_name] = {
        "block": format_action_candidates(cands),
        "alone": [format_action_candidates([c]) for c in cands],
    }
print("LOADS-JSON " + json.dumps(out))
"""


@pytest.fixture(scope="module")
def loads():
    """Real integration loads, rendered in a subprocess so loading every
    action does not touch this process's registry."""
    out = subprocess.run(
        [sys.executable, "-B", "-c", _LOADS],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    line = next(
        (ln for ln in out.stdout.splitlines() if ln.startswith("LOADS-JSON ")), None
    )
    assert line, out.stderr[-2000:]
    return json.loads(line[len("LOADS-JSON ") :])


def test_an_integration_load_states_its_account_once(loads):
    for set_name, load in loads.items():
        shared, actions = _parse(load["block"])
        assert len(actions) > 1, set_name
        assert "account" in shared, set_name
        assert "OMIT to use the primary account" in shared["account"]
        assert all("account" not in a["params"] for a in actions), set_name


def test_nothing_is_lost(loads):
    for set_name, load in loads.items():
        shared, actions = _parse(load["block"])
        rebuilt = [{**a, "params": {**a["params"], **shared}} for a in actions]
        assert rebuilt == [json.loads(alone)[0] for alone in load["alone"]], set_name
