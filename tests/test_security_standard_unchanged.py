"""At the default settings (Standard, Auto mode on) nothing gets in the way.

No prompts, no refused files or URLs, no changed environment and no
changed outputs, apart from the always-on protections: outside content
marked as data, secrets hidden in logs, the audit log and the
destructive-command floor. Each setting is checked at its default here, and
the cost of the gate on every action and of redaction on every log line is
measured.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from app.security.policy import SecurityPolicy, SecurityStore, set_store_for_tests

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def default_store(tmp_path):
    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    yield store
    set_store_for_tests(None)


def test_default_policy_is_the_standard_preset(default_store):
    policy = default_store.policy
    assert policy == SecurityPolicy()
    assert policy.auto_mode and not policy.gate_active and not policy.customized


def test_no_action_is_reviewed_and_no_output_changes(default_store):
    from agent_core.core.action.action import Action
    from agent_core.core.action_framework.loader import load_actions_from_directories
    from agent_core.core.action_framework.registry import registry_instance
    from app.security.content import RunRegistry
    from app.security.gate import SecurityGate, result_source_of
    from app.security.policy import ContentSource

    load_actions_from_directories(
        base_dir=str(ROOT), paths_to_scan=[os.path.join("app", "data", "action")]
    )
    gate = SecurityGate(run_registry=RunRegistry())
    names = list(registry_instance._registry)
    assert len(names) > 100

    async def review_all():
        for name in names:
            data = registry_instance.find_action_by_name(name)
            if data is None:
                continue
            action = Action.from_dict(data)
            assert await gate.review(action, {"x": 1}, session_id="s") is None
            output = gate.after(action, '{"ok": true}', session_id="s")
            if result_source_of(action) == ContentSource.NETWORK:
                assert "UNTRUSTED_CONTENT" in output  # always marked as data
            else:
                assert output == '{"ok": true}'

    asyncio.run(review_all())


def test_tools_files_network_and_env_are_untouched(default_store, tmp_path):
    from app.security.env import child_environment
    from app.security.net import guard_active
    from app.security.paths import check_file_access
    from agent_core.core.impl.llm.interface import _prompts_logged

    assert check_file_access(tmp_path / "anything", write=True) is None
    assert not guard_active()
    assert default_store.policy.third_party_reader
    env = {"PATH": "/bin", "AWS_SECRET_ACCESS_KEY": "kept"}
    assert child_environment({"A": "1"}, env) == {**env, "A": "1"}
    assert _prompts_logged()


def test_hiding_secrets_costs_microseconds_per_log_line():
    """Redaction runs on every log line; it must stay far below the cost of
    writing the line."""
    from app.security.redact import Redactor

    redactor = Redactor()
    redactor._secrets = tuple(f"sk-test-{i:04d}-abcdefghijklmnop" for i in range(20))
    redactor._checked = 1e18  # skip the file scan
    line = "[AGENT] step finished: " + "x" * 400
    rounds = 20_000
    start = time.perf_counter()
    for _ in range(rounds):
        redactor(line)
    per_line = (time.perf_counter() - start) / rounds
    print(f"\nredaction: {per_line * 1e6:.2f} µs per log line")
    assert per_line < 50e-6


def test_the_gate_costs_microseconds_per_action(default_store):
    """Performance budget: the gate on every action at the default settings.

    One action already costs milliseconds (an exec, an event-stream write);
    the gate's review and after() together must stay far below that.
    """
    from types import SimpleNamespace

    from app.security.content import RunRegistry
    from app.security.gate import SecurityGate

    gate = SecurityGate(run_registry=RunRegistry())
    action = SimpleNamespace(
        name="run_shell",
        display_name="Run Shell",
        effects=["execute"],
        result_source=None,
        integration=None,
        irreversible=False,
        parallelizable=True,
    )
    rounds = 20_000

    async def loop():
        start = time.perf_counter()
        for _ in range(rounds):
            await gate.review(action, {}, session_id="s")
            gate.after(action, "{}", session_id="s")
        return (time.perf_counter() - start) / rounds

    per_action = asyncio.run(loop())
    print(f"\nsecurity gate at default settings: {per_action * 1e6:.2f} µs per action")
    assert per_action < 50e-6
