"""Every built-in action states what it can do (Settings > Security).

The security gate decides approvals from these declarations, so an action
added without one would be treated as able to run arbitrary code. This test
makes the declaration part of writing an action.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.security.gate import effects_of, result_source_of
from app.security.policy import ContentSource, Effect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def registry():
    from agent_core.core.action_framework.loader import load_actions_from_directories
    from agent_core.core.action_framework.registry import registry_instance

    load_actions_from_directories(
        base_dir=str(ROOT), paths_to_scan=[os.path.join("app", "data", "action")]
    )
    return registry_instance


def _implementations(registry):
    for name, impls in registry._registry.items():
        for impl in impls.values():
            yield name, impl.metadata


def test_every_non_integration_action_declares_its_effects(registry):
    undeclared = sorted(
        {
            name
            for name, meta in _implementations(registry)
            if meta.effects is None and not meta.integration
        }
    )
    assert undeclared == [], (
        "Declare effects=[...] (and result_source='network' for outside content) "
        f"on: {undeclared}"
    )


def test_declared_effects_use_the_known_vocabulary(registry):
    known = {e.value for e in Effect}
    bad = sorted(
        (name, effect)
        for name, meta in _implementations(registry)
        for effect in meta.effects or ()
        if effect not in known
    )
    assert bad == []
    sources = {s.value for s in ContentSource}
    assert all(
        meta.result_source in (None, *sources) for _, meta in _implementations(registry)
    )


def test_declarations_reach_the_runtime_action(registry):
    from agent_core.core.action.action import Action

    data = registry.find_action_by_name("run_shell")
    action = Action.from_dict(data)
    assert effects_of(action) == {Effect.EXECUTE}
    web = Action.from_dict(registry.find_action_by_name("web_fetch"))
    assert effects_of(web) == frozenset()
    assert result_source_of(web) == ContentSource.NETWORK
    reply = Action.from_dict(registry.find_action_by_name("send_message"))
    assert effects_of(reply) == frozenset()  # a reply to the user, not to others
