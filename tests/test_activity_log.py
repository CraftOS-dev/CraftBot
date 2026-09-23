# -*- coding: utf-8 -*-
"""Phase 4 tests: activity ledger + idempotency guard for irreversible
actions (, Primitive C)."""

from agent_core.core.action.action import Action

from app.triggers.activity_log import (
    ActivityLog,
    ActivityLogGuard,
    make_idem_key,
)


def make_guard(tmp_path):
    log = ActivityLog(db_path=str(tmp_path / "sessions.db"))
    return log, ActivityLogGuard(log)


INPUTS = {"to": "bob@example.com", "subject": "Q3 report", "body": "attached"}


class TestIdemKey:
    def test_deterministic_and_content_sensitive(self):
        k1 = make_idem_key("send_gmail", INPUTS, "task1")
        k2 = make_idem_key("send_gmail", dict(INPUTS), "task1")
        assert k1 == k2
        assert k1 != make_idem_key("send_gmail", {**INPUTS, "subject": "Q4"}, "task1")
        assert k1 != make_idem_key("send_gmail", INPUTS, "task2")
        assert k1 != make_idem_key("send_outlook_email", INPUTS, "task1")

    def test_internal_keys_excluded(self):
        # Executor-injected keys (_session_id etc.) must not change identity.
        k1 = make_idem_key("send_gmail", INPUTS, "task1")
        k2 = make_idem_key(
            "send_gmail", {**INPUTS, "_session_id": "task1", "_extra": "x"}, "task1"
        )
        assert k1 == k2


class TestGuardLifecycle:
    def test_fresh_attempt_records_intent_and_proceeds(self, tmp_path):
        log, guard = make_guard(tmp_path)
        decision = guard.begin("send_gmail", INPUTS, "task1")
        assert decision.proceed
        row = log.get(decision.idem_key)
        assert row["status"] == "INTENT"

    def test_completed_run_is_never_reexecuted(self, tmp_path):
        log, guard = make_guard(tmp_path)
        d1 = guard.begin("send_gmail", INPUTS, "task1")
        guard.complete(
            d1.idem_key, "success", {"status": "success", "message_id": "msg-42"}
        )

        # The crash-redelivery case: the same step re-runs with the same inputs.
        d2 = guard.begin("send_gmail", INPUTS, "task1")
        assert not d2.proceed
        assert d2.stored_output["_idempotent_replay"] is True
        assert d2.stored_output["message_id"] == "msg-42"
        assert log.get(d1.idem_key)["provider_ref"] == "msg-42"

    def test_crash_window_surfaces_uncertainty_once_then_allows_retry(self, tmp_path):
        log, guard = make_guard(tmp_path)
        d1 = guard.begin("send_gmail", INPUTS, "task1")
        # crash between the send and complete(): row stays INTENT

        log2 = ActivityLog(db_path=str(tmp_path / "sessions.db"))  # restart
        guard2 = ActivityLogGuard(log2)

        # First re-attempt: blocked with a warning, NOT executed.
        d2 = guard2.begin("send_gmail", INPUTS, "task1")
        assert not d2.proceed
        assert d2.stored_output is None
        assert "MAY" in d2.note

        # The agent/user verified and decided to retry: now allowed through.
        d3 = guard2.begin("send_gmail", INPUTS, "task1")
        assert d3.proceed
        assert log2.get(d1.idem_key)["status"] == "INTENT"

    def test_parallel_duplicate_in_same_process_is_not_flagged_as_crashed(
        self, tmp_path
    ):
        log, guard = make_guard(tmp_path)
        d1 = guard.begin("send_gmail", INPUTS, "task1")
        assert d1.proceed
        # A batch mate with identical inputs, dispatched by execute_parallel
        # before d1's complete() is reached: not a crash, still running.
        d2 = guard.begin("send_gmail", INPUTS, "task1")
        assert not d2.proceed
        assert d2.stored_output is None
        assert "MAY" not in d2.note
        assert "already running" in d2.note
        assert log.get(d1.idem_key)["status"] == "INTENT"

        guard.complete(
            d1.idem_key, "success", {"status": "success", "message_id": "msg-1"}
        )

        # Once complete()'d, a later identical call follows the ordinary
        # DONE-dedup path, not the in-flight one.
        d3 = guard.begin("send_gmail", INPUTS, "task1")
        assert not d3.proceed
        assert d3.stored_output["_idempotent_replay"] is True

    def test_failed_run_can_be_retried(self, tmp_path):
        log, guard = make_guard(tmp_path)
        d1 = guard.begin("send_gmail", INPUTS, "task1")
        guard.complete(d1.idem_key, "error", {"status": "error", "error": "timeout"})

        d2 = guard.begin("send_gmail", INPUTS, "task1")
        assert d2.proceed  # failure is retryable; only DONE blocks

    def test_different_content_is_independent(self, tmp_path):
        log, guard = make_guard(tmp_path)
        d1 = guard.begin("send_gmail", INPUTS, "task1")
        guard.complete(d1.idem_key, "success", {"status": "success"})

        # A genuinely different email must not be blocked.
        d2 = guard.begin("send_gmail", {**INPUTS, "to": "carol@example.com"}, "task1")
        assert d2.proceed

    def test_oversized_output_is_stubbed(self, tmp_path):
        log, guard = make_guard(tmp_path)
        d1 = guard.begin("send_gmail", INPUTS, "task1")
        guard.complete(
            d1.idem_key, "success", {"status": "success", "blob": "x" * 100_000}
        )
        row = log.get(d1.idem_key)
        assert len(row["output_json"]) < 1000
        assert "too large" in row["output_json"]


class TestFlagPlumbing:
    def test_irreversible_round_trips_through_action_dict(self):
        action = Action(
            name="send_gmail",
            description="send an email",
            action_type="atomic",
            irreversible=True,
        )
        restored = Action.from_dict(action.to_dict())
        assert restored.irreversible is True

    def test_irreversible_defaults_false(self):
        action = Action.from_dict(
            {"name": "read_file", "description": "", "type": "atomic"}
        )
        assert action.irreversible is False

    def test_flagged_actions_registered(self):
        # Import a couple of flagged modules and confirm the registry
        # carries the flag (decorator → metadata path).
        import app.data.action.send_message  # noqa: F401
        from agent_core.core.action_framework.registry import registry_instance

        impls = registry_instance._registry.get("send_message")
        assert impls, "send_message not registered"
        meta = next(iter(impls.values())).metadata
        assert meta.irreversible is True
