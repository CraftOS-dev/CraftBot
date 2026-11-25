"""The security gate: approvals by declared effect, taint, and fallbacks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.security import audit
from app.security.approvals import ApprovalBroker, Decision
from app.security.content import RunRegistry
from app.security.gate import SecurityGate, effects_of, result_source_of
from app.security.policy import (
    ContentSource,
    Effect,
    SecurityLevel,
    SecurityStore,
    set_store_for_tests,
)
from app.triggers.sources import TriggerSource


def _action(name="act", **kw):
    defaults = dict(
        effects=None,
        result_source=None,
        integration=None,
        irreversible=False,
        parallelizable=True,
    )
    defaults.update(kw)
    return SimpleNamespace(name=name, display_name=name.title(), **defaults)


@pytest.fixture
def store(tmp_path):
    s = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(s)
    audit.set_log_for_tests(audit.AuditLog(tmp_path / "audit.jsonl"))
    yield s
    set_store_for_tests(None)
    audit.set_log_for_tests(None)


def _gate(answer=None):
    """A gate whose UI answers every card with ``answer`` (None: no UI)."""
    approvals = ApprovalBroker()
    runs = RunRegistry()
    asked = []
    if answer is not None:

        async def notify(message):
            if message["type"] == "security_approval_request":
                asked.append(message["data"])
                asyncio.get_running_loop().call_soon(
                    approvals.resolve, message["data"]["id"], answer
                )

        approvals.attach_ui(notify, lambda: True)
    return SecurityGate(approvals, runs), runs, asked


def _owner_run(runs, session="s1"):
    runs.turn_started(
        session,
        source=TriggerSource.USER_MESSAGE.value,
        origin={"platform": "CraftBot Interface"},
        starts_run=True,
    )


# ── declared effects ──


def test_effects_follow_declarations_not_names():
    assert effects_of(_action(effects=[])) == frozenset()
    assert effects_of(_action(effects=["execute"])) == {Effect.EXECUTE}
    assert effects_of(_action(effects=["something_new"])) == {Effect.EXECUTE}
    # Undeclared code can do anything.
    assert effects_of(_action()) == {Effect.EXECUTE}
    # Integration actions: writes are marked irreversible or non-parallelizable.
    assert effects_of(_action(integration="github")) == frozenset()
    assert effects_of(_action(integration="github", parallelizable=False)) == {
        Effect.SEND_EXTERNAL
    }
    assert result_source_of(_action(integration="github")) == ContentSource.NETWORK
    assert result_source_of(_action()) == ContentSource.LOCAL


# ── Auto mode on: nothing changes ──


def test_auto_mode_on_never_asks(store):
    gate, runs, asked = _gate(Decision.DENY)
    _owner_run(runs)
    out = asyncio.run(gate.review(_action(effects=["execute"]), {}, session_id="s1"))
    assert out is None and asked == []


# ── Auto mode off ──


def test_high_risk_action_asks_and_runs_when_allowed(store):
    store.update({"auto_mode": False})
    gate, runs, asked = _gate(Decision.ALLOW_ONCE)
    _owner_run(runs)
    out = asyncio.run(
        gate.review(_action("run_shell", effects=["execute"]), {"command": "ls"}, session_id="s1")
    )
    assert out is None
    assert asked[0]["action_name"] == "run_shell" and asked[0]["reason"] == "high_risk"


def test_denied_action_is_not_run_and_denials_add_up(store):
    store.update({"auto_mode": False})
    gate, runs, _ = _gate(Decision.DENY)
    _owner_run(runs)
    act = _action("run_shell", effects=["execute"])
    for _ in range(3):
        out = asyncio.run(gate.review(act, {}, session_id="s1"))
    assert out["error_code"] == "approval_denied"
    assert "3 actions in a row" in out["error"]


def test_session_grant_covers_the_rest_of_the_session(store):
    store.update({"auto_mode": False})
    gate, runs, asked = _gate(Decision.ALLOW_SESSION)
    _owner_run(runs)
    act = _action("run_shell", effects=["execute"])
    asyncio.run(gate.review(act, {}, session_id="s1"))
    asyncio.run(gate.review(act, {}, session_id="s1"))
    assert len(asked) == 1


def test_low_risk_action_does_not_ask(store):
    store.update({"auto_mode": False})
    gate, runs, asked = _gate(Decision.DENY)
    _owner_run(runs)
    out = asyncio.run(gate.review(_action(effects=["write_files"]), {}, session_id="s1"))
    assert out is None and asked == []


def test_untrusted_content_makes_any_effect_ask(store):
    store.set_level(SecurityLevel.ENHANCED)
    store.update({"auto_mode": False})
    gate, runs, asked = _gate(Decision.ALLOW_ONCE)
    _owner_run(runs)
    gate.after(_action("web_fetch", effects=[], result_source="network"), "{}", session_id="s1")
    asyncio.run(gate.review(_action(effects=["write_files"]), {}, session_id="s1"))
    assert asked and asked[0]["reason"] == "untrusted_content"


def test_unattended_run_is_refused_not_left_waiting(store):
    store.update({"auto_mode": False})
    gate, runs, asked = _gate(Decision.ALLOW_ONCE)
    runs.turn_started(
        "s1", source=TriggerSource.CRON_JOB.value, origin={}, starts_run=True
    )
    out = asyncio.run(gate.review(_action(effects=["execute"]), {}, session_id="s1"))
    assert out["error_code"] == "approval_unavailable" and asked == []


def test_owner_on_a_chat_app_is_refused_with_a_reason(store):
    store.update({"auto_mode": False})
    gate, runs, asked = _gate(Decision.ALLOW_ONCE)
    runs.turn_started(
        "s1",
        source=TriggerSource.USER_MESSAGE.value,
        origin={"platform": "Telegram", "owner_authenticated": True},
        starts_run=True,
    )
    out = asyncio.run(gate.review(_action(effects=["execute"]), {}, session_id="s1"))
    assert out["error_code"] == "approval_unavailable" and "Telegram" in out["error"]


def test_no_window_open_is_refused(store):
    store.update({"auto_mode": False})
    gate, runs, _ = _gate(None)
    _owner_run(runs)
    out = asyncio.run(gate.review(_action(effects=["execute"]), {}, session_id="s1"))
    assert out["error_code"] == "approval_unavailable"


def test_third_party_message_taints_the_run_and_owner_run_clears_it():
    runs = RunRegistry()
    runs.turn_started(
        "s1",
        source=TriggerSource.USER_MESSAGE.value,
        origin={"platform": "Discord"},
        starts_run=True,
    )
    assert runs.get("s1").tainted
    _owner_run(runs)
    assert not runs.get("s1").tainted


def test_network_results_are_always_marked_as_data(store):
    gate, runs, _ = _gate(None)
    wrapped = gate.after(_action("web_fetch", effects=[], result_source="network"), "page", session_id="s1")
    assert "UNTRUSTED_CONTENT" in wrapped and "page" in wrapped
    assert gate.after(_action("read_file", effects=[]), "text", session_id="s1") == "text"


def test_decisions_are_audited_with_an_intact_chain(store):
    store.set_level(SecurityLevel.ENHANCED)
    store.update({"auto_mode": False})
    gate, runs, _ = _gate(Decision.DENY)
    _owner_run(runs)
    asyncio.run(gate.review(_action(effects=["execute"]), {}, session_id="s1"))
    log = audit.get_log()
    ok, count, broken = log.verify()
    assert ok and count == 1 and broken is None
    assert log.entries()[0]["outcome"] == "user_deny"


def test_a_sub_agent_shares_its_parents_run():
    runs = RunRegistry()
    runs.turn_started(
        "parent", source=TriggerSource.CRON_JOB.value, origin={}, starts_run=True
    )
    runs.link_child("sub_1", "parent")
    assert not runs.get("sub_1").interactive
    runs.mark_tainted("sub_1", "a web page")
    assert runs.get("parent").tainted
