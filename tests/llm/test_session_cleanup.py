# -*- coding: utf-8 -*-
"""Deleting a session frees what the LLM interface holds for it
(prompt audit T12).

SessionManager.delete_session called a ``remove_session_caches`` that did
not exist; the AttributeError was swallowed, so a deleted session's
histories stayed in memory for good. These tests pin, through the real
interface code with recording fakes:

* every per-session record of the deleted session is gone, for every call
  type, and BytePlus's server-side chain is ended;
* other sessions keep everything, and caches sessions share stay: Gemini's
  explicit cache is keyed by the system prompt, which sessions of one type
  all send, so deleting it would cost every other session its prefix;
* SessionManager.delete_session calls it.
"""

from __future__ import annotations

import pytest

from agent_core.core.impl.llm import LLMCallType

from .golden.conftest import GOLDEN_SYSTEM_PROMPT, build_interface

ACTION = LLMCallType.ACTION_SELECTION

PROVIDERS = [
    ("anthropic", "claude-sonnet-4-6"),
    ("openai", "gpt-5.2-2025-12-11"),
    ("gemini", "gemini-2.5-pro"),
    ("byteplus", "seed-2-0-pro-260328"),
]

_PER_SESSION = (
    "_session_system_prompts",
    "_session_histories",
    "_last_input_tokens",
    "_last_requests",
    "_checkpoints",
    "_turn_recorded",
)


def _keys(iface, task_id):
    return {
        name: [k for k in getattr(iface, name) if k.startswith(f"{task_id}:")]
        for name in _PER_SESSION
    }


@pytest.mark.parametrize("provider, model", PROVIDERS)
def test_a_deleted_session_leaves_nothing_behind(monkeypatch, provider, model):
    iface, _ = build_interface(monkeypatch, provider, model)
    for task_id in ("gone", "kept"):
        for call_type in (ACTION, LLMCallType.REASONING):
            iface.create_session_cache(task_id, call_type, GOLDEN_SYSTEM_PROMPT)
        iface.generate_response_with_session(
            task_id, ACTION, "turn", log_response=False
        )
        iface.checkpoint_session(task_id, ACTION, {"point": 1})
    kept_before = _keys(iface, "kept")
    shared = []
    if iface._gemini_cache_manager is not None:
        monkeypatch.setattr(
            iface._gemini_cache_manager,
            "invalidate_cache",
            lambda *args, **kwargs: shared.append(args),
        )

    iface.remove_session_caches("gone")

    assert all(keys == [] for keys in _keys(iface, "gone").values())
    assert _keys(iface, "kept") == kept_before
    assert shared == []  # the explicit cache other sessions read stays
    manager = iface._byteplus_cache_manager
    if manager is not None:
        assert manager.get_session_cache("gone", ACTION) is None
        assert manager.get_session_cache("kept", ACTION) is not None


def test_deleting_a_session_frees_its_llm_state(tmp_path):
    from types import SimpleNamespace

    from agent_core.core.impl.session.manager import SessionManager

    removed = []
    llm = SimpleNamespace(
        create_session_cache=lambda *args: None,
        remove_session_caches=removed.append,
    )
    manager = SessionManager(
        event_stream_manager=None,
        llm_interface=llm,
        context_engine=SimpleNamespace(
            make_decision_system_prompt=lambda sid=None: "S"
        ),
        workspace_root=tmp_path,
    )
    session = manager.create_session()
    assert manager.delete_session(session.id) is True
    assert removed == [session.id]
