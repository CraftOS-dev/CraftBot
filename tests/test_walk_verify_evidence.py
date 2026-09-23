# -*- coding: utf-8 -*-
"""How a verdict is WORDED is not part of the test — now structurally.

The verdict is a typed JSON object (verdict + per-feature status enums), and
parse_check_report DERIVES the kind from those fields. No prose is inspected,
so a FAIL routes to the builder regardless of how its evidence reads, and a
working feature can never be blocked by a regex over its phrasing (the
2026-09-02 incident: a verifier downgraded an AI feature it had watched work
because it could not phrase a demanded hook quote — that whole class of
blocklist-validation is gone).

A bad verdict is not intercepted here either: a FAIL reaches the builder,
which reproduces the feature and disputes it on the record (see
test_agent_app_dispute.py).
"""

import json

from app.agent_app.walk_verify import parse_check_report


def _feat(name, status, evidence="", unreached_reason=None):
    f = {"name": name, "status": status, "evidence": evidence}
    if unreached_reason is not None:
        f["unreached_reason"] = unreached_reason
    return f


def _verdict(verdict, *features, mode="delta", blocked_reason=None):
    obj = {
        "scope": {"mode": mode, "excluded": []},
        "verdict": verdict,
        "features": list(features),
    }
    if blocked_reason is not None:
        obj["blocked_reason"] = blocked_reason
    return json.dumps(obj)


# Evidence phrasing that used to trip a regex (a FAIL whose text describes the
# feature working) — irrelevant to routing now.
CITATION_FAIL = _feat(
    "AI Explore",
    "fail",
    "clicked Start Exploring and the graph updated from 1 to 5 nodes, but the "
    "hook evidence must be quoted; callLLM is on ops.pb.js:32.",
)
REAL_FAIL = _feat("Save note", "fail", "clicked Save, reloaded, the note was gone.")
LIVE_PASS = _feat("Live weather", "pass", "the card showed 14C after Refresh.")


class TestParseCheckReport:
    def test_a_fail_reaches_the_builder_regardless_of_evidence_wording(self):
        out = parse_check_report(_verdict("fail", CITATION_FAIL))
        assert out["kind"] == "defects"
        assert len(out["defects"]) == 1
        assert "the graph updated" in out["defects"][0]

    def test_multiple_fails_are_all_reported(self):
        out = parse_check_report(_verdict("fail", CITATION_FAIL, REAL_FAIL))
        assert out["kind"] == "defects"
        assert len(out["defects"]) == 2

    def test_clean_pass(self):
        out = parse_check_report(_verdict("pass", LIVE_PASS))
        assert out["kind"] == "pass"
        assert out["passed"] == ["Live weather"]

    def test_not_reached_only_is_incomplete(self):
        out = parse_check_report(
            _verdict(
                "fail",
                _feat("Export", "not_reached", "no download tool", "tooling"),
            )
        )
        assert out["kind"] == "incomplete"

    def test_typed_blocked_is_trusted(self):
        out = parse_check_report(
            _verdict("blocked", mode="full", blocked_reason="browser MCP died")
        )
        assert out["kind"] == "blocked"
        assert out["blocked_reason"] == "browser MCP died"

    def test_absent_or_invalid_json_is_unparseable(self):
        assert parse_check_report("VERDICT: PASS\nnot json")["kind"] == "unparseable"
        assert parse_check_report("")["kind"] == "unparseable"
        # a verdict enum outside the set, or a feature missing a status
        bad = json.dumps({"verdict": "great", "features": []})
        assert parse_check_report(bad)["kind"] == "unparseable"

    def test_a_pass_that_verified_nothing_is_not_promoted(self):
        # verdict "pass" with an empty features list judged no app at all.
        assert parse_check_report(_verdict("pass"))["kind"] == "unparseable"

    def test_scope_and_features_are_structured(self):
        out = parse_check_report(
            json.dumps(
                {
                    "scope": {
                        "mode": "delta",
                        "excluded": [{"feature": "Boards", "reason": "unchanged"}],
                    },
                    "verdict": "pass",
                    "features": [_feat("Header", "pass", "rendered")],
                }
            )
        )
        assert out["scope"]["mode"] == "DELTA"
        assert out["scope"]["excluded"] == [("Boards", "unchanged")]
        assert out["features"] == {"Header": "PASS"}
