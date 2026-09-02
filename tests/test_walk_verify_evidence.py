# -*- coding: utf-8 -*-
"""How a verdict is WRITTEN is not part of the test.

Regression cover for the 2026-09-02 incident (brainstorm_graph f1eb1c85): the
verifier watched AI Explore work, could not phrase the hook quote the prompt
demanded, and marked the feature FAIL for that reason alone. That produced
kind="defects", which never promotes, so a working feature blocked the deploy
of an unrelated change while the agent reported "Done".

The fix is the DELETION of that demand — nothing replaces it. The verifier
still checks the hooks with grep_files, still judges, and is no longer
rejected over phrasing. Nothing here intercepts a bad verdict either: a FAIL
reaches the builder, which can reproduce the feature and dispute the verdict
on the record (see test_agent_app_dispute.py). A regex vetoing a verdict would
be the same species of rule as the one that caused the bug.
"""

from app.agent_app.walk_verify import parse_check_report
from app.subagent.definitions.walk_verify import _guard_quality

# The verdict line as the verifier actually wrote it, verbatim from the log.
CITATION_FAIL = (
    "- AI Explore \u2014 FAIL \u2014 clicked Start Exploring and the graph updated "
    "from 1 node to 5 nodes with four AI-created ideas, but this is a live/AI "
    "feature and the hooks must be quoted; evidence exists in "
    "pb/pb_hooks/ops.pb.js and pb/pb_hooks/_craftbot_bridge.js: "
    "`bridge.callLLM(` on line 32 and `const res = $http.send({` on line 22. "
    "A passing verdict would need to explicitly quote the hook evidence while "
    "also verifying the rendered result."
)
REAL_FAIL = (
    "- Save note \u2014 FAIL \u2014 clicked Save, reloaded the page, the note was gone."
)
LIVE_PASS = "- Live weather \u2014 PASS \u2014 the card showed 14\u00b0C after I clicked Refresh."


def _report(*feature_lines, verdict="FAIL"):
    return "SCOPE: DELTA\nVERDICT: %s\n\nFEATURES\n%s\n" % (
        verdict,
        "\n".join(feature_lines),
    )


class TestParseCheckReport:
    def test_a_citation_fail_reaches_the_builder_rather_than_being_swallowed(self):
        # Deliberately NOT intercepted. The builder is the only party that can
        # reproduce the feature and find out the verdict is wrong; a regex
        # here would take the finding away from it and hide a real failure.
        out = parse_check_report(_report(CITATION_FAIL))
        assert out["kind"] == "defects"
        assert len(out["defects"]) == 1
        # ...and it arrives intact, so the builder can read the contradiction.
        assert "the graph updated" in out["defects"][0]

    def test_a_real_defect_alongside_it_is_reported_too(self):
        out = parse_check_report(_report(CITATION_FAIL, REAL_FAIL))
        assert out["kind"] == "defects"
        assert len(out["defects"]) == 2

    def test_ordinary_defect_report_is_unaffected(self):
        out = parse_check_report(_report(REAL_FAIL))
        assert out["kind"] == "defects"

    def test_clean_pass_is_unaffected(self):
        report = _report(
            "- Graph \u2014 PASS \u2014 added a node, reloaded, it persisted.",
            verdict="PASS",
        )
        assert parse_check_report(report)["kind"] == "pass"


class TestGuardQuality:
    def test_a_fail_is_never_vetoed_over_how_it_cites_evidence(self):
        # The guard's job is to catch a verdict with NO evidence behind it,
        # not to overrule one it disagrees with. A wrong FAIL goes downstream
        # to be argued with, not silently rewritten here.
        assert _guard_quality(_report(CITATION_FAIL)) is None

    def test_a_live_pass_showing_no_server_side_call_is_still_questioned(self):
        # The guard's real purpose survives: an app that fetches nothing
        # cannot be showing live data (Math.random() as "live weather").
        rejection = _guard_quality(_report(LIVE_PASS, verdict="PASS"))
        assert rejection is not None

    def test_the_rejection_cannot_be_cleared_by_failing_the_feature(self):
        # The 2026-09-02 bug in one assertion. The old message ended "QUOTE
        # the line in your verdict", and the verifier complied by downgrading
        # a working feature to FAIL — which promotes nothing. The message has
        # to name both exits, and rule that one out.
        rejection = _guard_quality(_report(LIVE_PASS, verdict="PASS"))
        assert "KEEP the PASS" in rejection
        assert "Do NOT fail a feature you watched work" in rejection

    def test_a_live_pass_that_shows_the_call_is_accepted(self):
        report = _report(LIVE_PASS, verdict="PASS") + "  ops.pb.js:32 callAction(\n"
        assert _guard_quality(report) is None

    def test_pre_existing_guards_still_fire(self):
        assert _guard_quality(_report("- Nav \u2014 PASS \u2014 nav present"))
        assert _guard_quality(
            _report("- Settings \u2014 PASS \u2014 Gmail send not connected")
        )
