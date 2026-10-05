# -*- coding: utf-8 -*-
"""Phase 5 reliability tests: credential pools (FR-7) and cross-provider
fallback (FR-9).

Fallback assertions include the NFR-3 property from the spec's Phase 5
acceptance: after a fallback turn, the PRIMARY interface's session buffers
are untouched and the fallback interface accumulates its own, so returning
to the primary next turn stays cache-warm.
"""

from __future__ import annotations

import pytest

from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError

from .golden.conftest import (
    GOLDEN_SYSTEM_PROMPT,
    build_interface,
)


# ─────────────────────── credential pool state machine ───────────────────────


@pytest.fixture()
def pool(monkeypatch, tmp_path):
    from agent_core.core.models import credentials

    monkeypatch.setattr(
        credentials, "_state_path", lambda: tmp_path / "pool_state.json"
    )
    credentials.reset_state_for_tests()

    keys = {"primary": "key-A", "extras": ["key-B", "key-C"]}
    import app.config as app_config

    monkeypatch.setattr(app_config, "get_api_key", lambda p: keys["primary"])
    monkeypatch.setattr(
        app_config, "get_extra_api_keys", lambda p: list(keys["extras"])
    )
    return credentials


def test_fill_first_serves_primary(pool):
    assert pool.resolve("anthropic") == "key-A"
    assert pool.has_pool("anthropic") is True


def test_rate_limit_cools_after_second_consecutive(pool):
    pool.resolve("anthropic")
    pool.note_failure("anthropic", "rate_limit")  # 1st: no cooldown yet
    assert pool.resolve("anthropic") == "key-A"
    pool.note_failure("anthropic", "rate_limit")  # 2nd: cool 60s
    assert pool.resolve("anthropic") == "key-B"


def test_billing_rotates_immediately(pool):
    pool.resolve("anthropic")
    pool.note_failure("anthropic", "credit")
    assert pool.resolve("anthropic") == "key-B"
    pool.note_failure("anthropic", "credit")  # B billing-cooled too
    assert pool.resolve("anthropic") == "key-C"


def test_auth_rotates_and_success_clears(pool):
    pool.resolve("anthropic")
    pool.note_failure("anthropic", "auth")
    assert pool.resolve("anthropic") == "key-B"
    pool.note_success("anthropic")  # clears B's (empty) record, keeps A cooling
    assert pool.resolve("anthropic") == "key-B"


def test_all_cooling_fails_open_to_primary(pool):
    for _ in range(3):
        pool.resolve("anthropic")
        pool.note_failure("anthropic", "credit")
    assert pool.resolve("anthropic") == "key-A"


def test_transient_categories_do_not_cool(pool):
    pool.resolve("anthropic")
    pool.note_failure("anthropic", "server")
    pool.note_failure("anthropic", "connection")
    pool.note_failure("anthropic", "unknown")
    assert pool.resolve("anthropic") == "key-A"


def test_single_key_provider_is_untouched(pool, monkeypatch):
    import app.config as app_config

    monkeypatch.setattr(app_config, "get_extra_api_keys", lambda p: [])
    assert pool.has_pool("anthropic") is False
    pool.resolve("anthropic")
    pool.note_failure("anthropic", "credit")
    assert pool.resolve("anthropic") == "key-A"


# ─────────────────────── cross-provider fallback ───────────────────────


def _break_client(iface):
    """Make the fake OpenAI-compat client raise on every call."""

    def failing_create(**kwargs):
        raise RuntimeError("primary provider down")

    iface.client.chat = type(iface.client.chat)(
        completions=type(iface.client.chat.completions)(create=failing_create)
    )


@pytest.fixture()
def fallback_pair(monkeypatch):
    """Primary openai interface (broken) + anthropic fallback (healthy),
    with the chain configured and the fallback interface injected."""
    primary, primary_rec = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    fallback, fallback_rec = build_interface(
        monkeypatch, "anthropic", "claude-sonnet-4-6"
    )
    _break_client(primary)

    import app.config as app_config

    monkeypatch.setattr(
        app_config, "get_fallback_providers", lambda: ["anthropic"]
    )
    monkeypatch.setattr(app_config, "get_api_key", lambda p: "k")
    # Inject the pre-built fallback interface (its factory patch would
    # otherwise have been torn down by build_interface's second call).
    primary._fallback_interfaces["anthropic"] = fallback
    return primary, primary_rec, fallback, fallback_rec


def test_fallback_serves_sessionless_turn(fallback_pair):
    primary, _prec, fallback, frec = fallback_pair

    out = primary.generate_response(
        system_prompt=GOLDEN_SYSTEM_PROMPT, user_prompt="hello"
    )
    assert out  # turn served by the fallback
    assert any(c["method"] == "messages.create" for c in frec.calls)
    # Served turn == success: the primary's counter must not tick.
    assert primary.consecutive_failures == 0


def test_fallback_session_turn_preserves_primary_buffers(fallback_pair):
    primary, _prec, fallback, frec = fallback_pair

    # Prime one successful-looking primary session state by hand: the
    # buffers below must survive the fallback turn untouched.
    primary.create_session_cache("t1", "reasoning", GOLDEN_SYSTEM_PROMPT)
    primary._session_histories["t1:reasoning"] = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    before = [dict(m) for m in primary._session_histories["t1:reasoning"]]

    out = primary.generate_response_with_session("t1", "reasoning", "turn 2")
    assert out  # served by anthropic fallback

    # NFR-3: primary buffers untouched; fallback accumulated its own.
    assert primary._session_histories["t1:reasoning"] == before
    assert fallback._session_histories["t1:reasoning"]
    assert primary.consecutive_failures == 0


def test_fallback_off_preserves_error_contract(monkeypatch):
    """No chain configured -> exact historical failure behavior (NFR-1)."""
    primary, rec = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    _break_client(primary)
    import app.config as app_config

    monkeypatch.setattr(app_config, "get_fallback_providers", lambda: [])

    for _ in range(4):
        with pytest.raises(Exception):
            primary.generate_response(system_prompt="s", user_prompt="u")
    assert primary.consecutive_failures == 4
    with pytest.raises(LLMConsecutiveFailureError):
        primary.generate_response(system_prompt="s", user_prompt="u")


def test_strict_turn_after_reinitialize_skips_fallback(fallback_pair):
    primary, _prec, fallback, frec = fallback_pair

    # Simulate the flag reinitialize() sets on explicit selection.
    primary._suppress_fallback_once = True
    with pytest.raises(Exception):
        primary.generate_response(system_prompt="s", user_prompt="u")
    assert not any(c["method"] == "messages.create" for c in frec.calls)

    # Next turn: fallback active again.
    out = primary.generate_response(system_prompt="s", user_prompt="u")
    assert out
    assert any(c["method"] == "messages.create" for c in frec.calls)


def test_total_outage_terminates_without_recursion(monkeypatch):
    """Multi-provider chain with EVERYTHING down must terminate in one chain
    walk (audit finding 2026-08-17: fallback instances used to walk their
    own chains, nesting primary -> fb -> fb-of-fb without bound)."""
    primary, _ = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    fb1, _ = build_interface(monkeypatch, "anthropic", "claude-sonnet-4-6")
    fb2, _ = build_interface(monkeypatch, "deepseek", "deepseek-chat")
    _break_client(primary)
    fb1.messages_broken = True

    def failing_messages(**kwargs):
        raise RuntimeError("anthropic down")

    fb1._anthropic_client.messages = type(fb1._anthropic_client.messages)(
        create=failing_messages
    )
    _break_client(fb2)

    import app.config as app_config

    monkeypatch.setattr(
        app_config, "get_fallback_providers", lambda: ["anthropic", "deepseek"]
    )
    monkeypatch.setattr(app_config, "get_api_key", lambda p: "k")
    primary._fallback_interfaces = {"anthropic": fb1, "deepseek": fb2}
    fb1._is_fallback_instance = True
    fb2._is_fallback_instance = True

    with pytest.raises(Exception) as exc_info:
        primary.generate_response(system_prompt="s", user_prompt="u")
    # Terminated with a plain failure, not a RecursionError.
    assert not isinstance(exc_info.value, RecursionError)
    assert primary.consecutive_failures == 1

    # Structural guarantee: fallback instances never expose a chain.
    assert fb1._fallback_chain() == []
    assert fb2._fallback_chain() == []


def test_fallback_notice_hook_fires(fallback_pair):
    primary, _prec, fallback, _frec = fallback_pair
    events = []
    primary._on_fallback = lambda frm, to, reason: events.append((frm, to, reason))

    primary.generate_response(system_prompt="s", user_prompt="u")
    assert events == [("openai", "anthropic", events[0][2])]
