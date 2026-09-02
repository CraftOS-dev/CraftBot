# -*- coding: utf-8 -*-
"""A builder that reproduces a feature can argue with the verdict.

The 2026-09-02 incident (brainstorm_graph f1eb1c85) ended with a working
feature marked FAIL and a deploy blocked. The system's first instinct was to
detect and discard such verdicts automatically, which would have hidden a real
failure from the only party able to investigate it: the builder can run the
flow repeatedly and read the server log while it does; the verifier saw it
once.

So the verdict now reaches the builder, with the harness's hook evidence
beside it, and the builder has a third move next to ruled_out and
blocked_question — say, on the record and with evidence, that the verdict is
wrong. That reasoning travels to the NEXT verifier, which has to answer it.
"""

import types

import pytest

from app.factory.appfactory import BUILDING, transition
from app.factory.engine import Caps, Machine


@pytest.fixture
def machine(tmp_path):
    return Machine(transition, tmp_path / "state.json", BUILDING, Caps())


DISPUTE = (
    "AI Explore - I ran it against the dev instance, the graph went 1 -> 5 "
    "nodes with AI-written ideas, and the hook evidence confirms callLLM at "
    "ops.pb.js:32. Nothing here is broken."
)


class TestDisputeLedger:
    def test_a_dispute_is_recorded_with_its_reasoning(self, machine):
        assert machine.record_disputed([DISPUTE], mission="m2") == 1
        entry = machine.disputed()[0]
        assert entry["what"] == DISPUTE
        assert entry["mission"] == "m2"

    def test_repeating_a_dispute_does_not_duplicate_it(self, machine):
        machine.record_disputed([DISPUTE])
        assert machine.record_disputed([DISPUTE]) == 0
        assert len(machine.disputed()) == 1

    def test_empty_input_records_nothing(self, machine):
        assert machine.record_disputed([]) == 0
        assert machine.record_disputed(["", "   "]) == 0

    def test_it_survives_a_reload(self, machine, tmp_path):
        machine.record_disputed([DISPUTE])
        reloaded = Machine(transition, tmp_path / "state.json", BUILDING, Caps())
        assert reloaded.disputed()[0]["what"] == DISPUTE

    def test_it_is_scoped_to_one_arc(self, machine):
        # Like ruled_out: a dispute is a claim about code that a later arc has
        # already changed, so it must not be carried forward.
        machine.record_disputed([DISPUTE])
        machine.reopen(BUILDING)
        assert machine.disputed() == []

    def test_ruled_out_and_disputed_are_separate_ledgers(self, machine):
        # They point opposite ways: ruled_out says a CAUSE is innocent,
        # disputed says a VERDICT is wrong.
        machine.record_ruled_out(["not the grant"])
        machine.record_disputed([DISPUTE])
        assert [e["what"] for e in machine.ruled_out()] == ["not the grant"]
        assert [e["what"] for e in machine.disputed()] == [DISPUTE]


class TestDisputeReachesTheNextVerifier:
    def test_the_evidence_block_carries_the_builder_s_reasoning(
        self, monkeypatch, tmp_path
    ):
        from app.agent_app import walk_verify as wv

        project = types.SimpleNamespace(id="f1eb1c85", name="Brainstorm Graph")
        m = Machine(transition, tmp_path / "state.json", BUILDING, Caps())
        m.record_disputed([DISPUTE])
        monkeypatch.setattr(
            "app.factory.host_craftbot.get_factory_host",
            lambda: types.SimpleNamespace(machine_for=lambda _pid: m),
        )
        assert wv._disputed_verdicts(project) == [DISPUTE]

    def test_no_disputes_means_no_block(self, monkeypatch, tmp_path):
        from app.agent_app import walk_verify as wv

        project = types.SimpleNamespace(id="f1eb1c85", name="Brainstorm Graph")
        m = Machine(transition, tmp_path / "state.json", BUILDING, Caps())
        monkeypatch.setattr(
            "app.factory.host_craftbot.get_factory_host",
            lambda: types.SimpleNamespace(machine_for=lambda _pid: m),
        )
        assert wv._disputed_verdicts(project) == []

    def test_a_broken_ledger_never_breaks_a_verify(self, monkeypatch):
        from app.agent_app import walk_verify as wv

        def boom():
            raise RuntimeError("factory unavailable")

        monkeypatch.setattr("app.factory.host_craftbot.get_factory_host", boom)
        assert wv._disputed_verdicts(types.SimpleNamespace(id="x")) == []


class TestTheAction:
    def _host(self, monkeypatch, recorded):
        host = types.SimpleNamespace(
            machine_for=lambda _pid: types.SimpleNamespace(
                state="fixing", active_mission="m2"
            ),
            record_ruled_out=lambda _pid, items: (
                recorded["ruled"].extend(items) or len(items)
            ),
            record_disputed=lambda _pid, items: (
                recorded["disputed"].extend(items) or len(items)
            ),
        )
        monkeypatch.setattr("app.factory.host_craftbot.get_factory_host", lambda: host)
        return host

    def test_a_dispute_is_stored_and_the_agent_is_told_to_re_verify(self, monkeypatch):
        from app.data.action.agent_app_actions import agent_app_report_finding

        recorded = {"ruled": [], "disputed": []}
        self._host(monkeypatch, recorded)
        out = agent_app_report_finding(
            {"project_id": "f1eb1c85", "disputed": [DISPUTE]}
        )
        assert out["status"] == "success"
        assert recorded["disputed"] == [DISPUTE]
        # Recording a dispute is not the end of the job: a fresh verdict is.
        assert "agent_app_walk_verify" in out["message"]
        # ...and it must not read as a way to dodge a real defect.
        assert "treat the feature as broken" in out["message"]

    def test_a_bare_string_is_accepted(self, monkeypatch):
        from app.data.action.agent_app_actions import agent_app_report_finding

        recorded = {"ruled": [], "disputed": []}
        self._host(monkeypatch, recorded)
        agent_app_report_finding({"project_id": "f1eb1c85", "disputed": DISPUTE})
        assert recorded["disputed"] == [DISPUTE]

    def test_ruled_out_alone_still_behaves_as_before(self, monkeypatch):
        from app.data.action.agent_app_actions import agent_app_report_finding

        recorded = {"ruled": [], "disputed": []}
        self._host(monkeypatch, recorded)
        out = agent_app_report_finding(
            {"project_id": "f1eb1c85", "ruled_out": ["not the grant"]}
        )
        assert recorded == {"ruled": ["not the grant"], "disputed": []}
        assert "every later fix round will see them" in out["message"]

    def test_a_dispute_is_not_taken_alongside_a_blocking_question(self, monkeypatch):
        # blocked_question ends the arc as BLOCKED, which is terminal, so the
        # next begin_modify calls reopen() and reopen() clears the dispute
        # ledger. Recording one here would promise the schema's "goes to the
        # next verifier" and quietly not deliver it.
        from app.data.action.agent_app_actions import agent_app_report_finding

        recorded = {"ruled": [], "disputed": []}
        host = types.SimpleNamespace(
            machine_for=lambda _pid: types.SimpleNamespace(
                state="blocked", active_mission="m2"
            ),
            record_ruled_out=lambda _pid, items: recorded["ruled"].extend(items)
            or len(items),
            record_disputed=lambda _pid, items: recorded["disputed"].extend(items)
            or len(items),
            report_blocked=lambda _pid, q, ruled_out=None: types.SimpleNamespace(
                next_state="blocked"
            ),
        )
        monkeypatch.setattr("app.factory.host_craftbot.get_factory_host", lambda: host)
        agent_app_report_finding(
            {
                "project_id": "f1eb1c85",
                "disputed": [DISPUTE],
                "blocked_question": "Which calendar?",
            }
        )
        assert recorded["disputed"] == []

    def test_simulated_mode_counts_a_bare_string_as_one_entry(self):
        # len() on an uncoerced string counted characters.
        from app.data.action.agent_app_actions import agent_app_report_finding

        out = agent_app_report_finding(
            {"project_id": "x", "disputed": DISPUTE, "simulated_mode": True}
        )
        assert out["recorded"] == 1

    def test_project_id_is_still_required(self):
        from app.data.action.agent_app_actions import agent_app_report_finding

        out = agent_app_report_finding({"disputed": [DISPUTE]})
        assert out["status"] == "error"


class TestTheFixBrief:
    """What the builder is handed when a verdict comes back FAIL."""

    @pytest.fixture
    def brief(self, tmp_path, monkeypatch):
        hooks = tmp_path / "pb" / "pb_hooks"
        hooks.mkdir(parents=True)
        from app.factory.host_craftbot import get_factory_host

        project = types.SimpleNamespace(
            id="f1eb1c85", name="Brainstorm Graph", path=str(tmp_path)
        )
        machine = Machine(transition, tmp_path / "state.json", BUILDING, Caps())
        machine.record_ruled_out(["the collection exists - lui data list shows it"])
        machine.record_disputed([DISPUTE])

        host = get_factory_host()
        monkeypatch.setattr(host, "get_staging_record", lambda _pid: None)
        monkeypatch.setattr(host, "_select_cookbooks", lambda _text: [])
        card = types.SimpleNamespace(
            render=lambda: (
                "DEFECT verify.ai-explore\n  observed: ... the hooks must be quoted"
            )
        )
        decision = types.SimpleNamespace(
            next_state="fixing", escalate_level=1, payload={}
        )
        return host._compose_fix_brief(project, machine, decision, [card])

    def test_earlier_disputes_and_rulings_are_both_carried_forward(self, brief):
        assert "VERDICTS EARLIER ROUNDS DISPUTED" in brief
        assert DISPUTE in brief
        assert "RULED OUT BY EARLIER ROUNDS" in brief

    def test_the_third_move_is_offered_with_its_limits(self, brief):
        assert "Three things you can write into the record" in brief
        assert "disputed=[" in brief
        assert "never to skip a defect you have not reproduced" in brief

    def test_the_round_is_still_the_agent_s_to_use(self, brief):
        # The brief must keep trusting the builder to choose an approach.
        assert "How you use the round is yours" in brief
