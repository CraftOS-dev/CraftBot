# -*- coding: utf-8 -*-
"""Context budget: one bound, sessions survive folds, nothing truncated silently.

The history collapse came from two budgets that could not see each other: the
event stream's summarization threshold and an independent character cap on
the accumulated session history. There is one budget now, derived from the
configured context window. These tests pin:

* the cap is gone;
* a fold resets the history WITHOUT ending the session, so the router keeps
  the session path -- and with it the cached prefix;
* the history container is provider-agnostic;
* the cache markers the providers need are still on the wire;
* an oversized request is refused before it is sent;
* the window is required configuration and the thresholds derive from it.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_core.core.impl.llm.interface import LLMContextOverflowError, LLMInterface
from app import config as app_config
from app.models.factory import ModelFactory


def _ctx(provider, model, anthropic_client=None):
    return {
        "provider": provider,
        "model": model,
        "client": object(),
        "gemini_client": None,
        "remote_url": None,
        "byteplus": None,
        "anthropic_client": anthropic_client,
        "bedrock_client": None,
        "initialized": True,
        "auth_mode": "api_key",
    }


def _make(provider="grok", model="grok-3", anthropic_client=None):
    with patch.object(ModelFactory, "create", return_value=_ctx(provider, model, anthropic_client)):
        return LLMInterface(provider=provider, model=model, api_key="k", base_url="", max_tokens=8000)


def _settings(context_window, stream_fraction=0.5, tail_keep_fraction=0.4):
    return {
        "model": {"context_window": context_window},
        "context": {
            "stream_fraction_of_window": stream_fraction,
            "tail_keep_fraction": tail_keep_fraction,
        },
    }


class _FakeAnthropic:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"ok": 1}')],
            usage=SimpleNamespace(
                input_tokens=10, output_tokens=2,
                cache_creation_input_tokens=0, cache_read_input_tokens=0,
            ),
        )


# ---------------------------------------------------------------- one budget


def test_the_independent_history_cap_is_gone():
    from pathlib import Path

    import agent_core.core.impl.llm.interface as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "_trim_openai_compat_history" not in source
    assert "max_history_chars" not in source


def test_the_history_container_is_provider_agnostic():
    """One dict keyed by session. Adding a provider must not touch teardown."""
    from pathlib import Path

    import agent_core.core.impl.llm.interface as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "_session_histories" in source
    assert "_session_messages" not in source


def test_reset_session_history_keeps_the_session_registered():
    """The router's gate is has_session_cache. A fold must not close it."""
    iface = _make()
    key = "task:action_selection"
    iface.create_session_cache("task", "action_selection", "SYSTEM")
    iface._session_histories[key] = [{"role": "user", "content": "stale"}]

    iface.reset_session_history("task", "action_selection")

    assert key not in iface._session_histories
    assert iface.has_session_cache("task", "action_selection") is True


def test_router_restarts_a_session_without_ending_it():
    from pathlib import Path

    import agent_core.core.impl.action.router as router

    src = Path(router.__file__).read_text(encoding="utf-8")
    first_call = src.index("if not has_synced_before:")
    send = src.index("generate_response_with_session_async", first_call)
    assert "reset_session_history" in src[first_call:send]
    assert "end_session_cache" not in src[src.index("No delta events"):send]


def test_subagent_first_turn_resets_history():
    from pathlib import Path

    import app.subagent.runner as runner

    src = Path(runner.__file__).read_text(encoding="utf-8")
    branch = src.index("if not stream.has_session_sync(_SUBAGENT_CALL_TYPE):")
    build = src.index("make_first_turn_user_prompt", branch)
    assert "_reset_session" in src[branch:build]
    reset = src.index("def _reset_session")
    assert "reset_session_history" in src[reset: src.index("def ", reset + 10)]


# ------------------------------------------------------------- KV caching


def test_anthropic_session_marks_system_and_last_assistant():
    fake = _FakeAnthropic()
    iface = _make("anthropic", "claude-x", anthropic_client=fake)
    iface._anthropic_client = fake
    iface.create_session_cache("task", "action_selection", "S" * 5000)

    for turn in ("turn 1", "turn 2"):
        iface._generate_response_with_session_sync("task", "action_selection", turn, log_response=False)

    second = fake.calls[1]
    assert second["system"][0].get("cache_control")
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    last_assistant = second["messages"][1]
    content = last_assistant["content"]
    assert ("cache_control" in last_assistant) or (
        isinstance(content, list) and any("cache_control" in block for block in content)
    )


def test_openai_compat_session_sends_a_growing_identical_prefix():
    sent = []

    def fake_generate_openai(self, system_prompt, user_prompt, call_type=None, messages_override=None, **kw):
        sent.append([dict(m) for m in messages_override])
        return {"content": '{"ok": 1}', "tokens_used": 1}

    iface = _make()
    iface.create_session_cache("task", "action_selection", "SYSTEM")
    with patch.object(LLMInterface, "_generate_openai", fake_generate_openai):
        for turn in range(3):
            iface._generate_response_with_session_sync("task", "action_selection", f"turn {turn}", log_response=False)

    assert [m["role"] for m in sent[2]] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert sent[1][:3] == sent[2][:3]


# ---------------------------------------------------------------- pre-flight


def test_preflight_refuses_a_request_that_does_not_fit():
    iface = _make()
    with patch.object(app_config, "get_settings", return_value=_settings(128000)):
        with pytest.raises(LLMContextOverflowError):
            iface._check_context_fits("system", "word " * 200_000)


def test_preflight_counts_the_whole_session_history():
    iface = _make()
    history = [{"role": "user", "content": "word " * 70_000}, {"role": "assistant", "content": "word " * 70_000}]
    with patch.object(app_config, "get_settings", return_value=_settings(128000)):
        with pytest.raises(LLMContextOverflowError):
            iface._check_context_fits("system", messages=history)


def test_preflight_passes_a_request_that_fits():
    iface = _make()
    with patch.object(app_config, "get_settings", return_value=_settings(128000)):
        iface._check_context_fits("system", "a modest prompt")


def test_overflow_is_not_counted_as_a_provider_failure():
    iface = _make()
    iface._consecutive_failures = 0
    with patch.object(app_config, "get_settings", return_value=_settings(128000)):
        with pytest.raises(LLMContextOverflowError):
            iface._generate_response_sync(system_prompt="s", user_prompt="word " * 200_000, log_response=False)
    assert iface._consecutive_failures == 0


# ------------------------------------------------- required window, derived


@pytest.mark.parametrize("window", [64000, 128000, 200000, 1000000])
@pytest.mark.parametrize("stream_fraction,tail_keep_fraction", [(0.4, 0.4), (0.25, 0.5), (0.6, 0.2)])
def test_thresholds_derive_from_the_configured_window_and_fractions(window, stream_fraction, tail_keep_fraction):
    settings = _settings(window, stream_fraction, tail_keep_fraction)
    with patch.object(app_config, "get_settings", return_value=settings):
        summarize_at, tail_keep = app_config.get_context_limits()
    assert summarize_at == int(window * stream_fraction)
    assert tail_keep == int(summarize_at * tail_keep_fraction)
    assert 0 < tail_keep < summarize_at < window


def test_the_shipped_numbers_for_a_128k_window():
    """window 128000 x 0.5 -> summarize at 64,000; keep 64,000 x 0.4 -> 25,600."""
    with patch.object(app_config, "get_settings", return_value=_settings(128000)):
        assert app_config.get_context_limits() == (64000, 25600)


@pytest.mark.parametrize("key,shipped", [("stream_fraction_of_window", 0.5), ("tail_keep_fraction", 0.4)])
def test_an_absent_fraction_takes_the_shipped_default(key, shipped):
    settings = _settings(128000)
    del settings["context"][key]
    with patch.object(app_config, "get_settings", return_value=settings):
        assert app_config._get_context_fraction(key) == shipped


@pytest.mark.parametrize("key", ["stream_fraction_of_window", "tail_keep_fraction"])
@pytest.mark.parametrize("value", [0, 1, 1.5, -0.4, True, "0.4"])
def test_an_invalid_fraction_is_a_configuration_error(key, value):
    settings = _settings(128000)
    settings["context"][key] = value
    with patch.object(app_config, "get_settings", return_value=settings):
        with pytest.raises(app_config.ConfigurationError):
            app_config.get_context_limits()


def test_an_absent_window_takes_the_shipped_default():
    """Works out of the box: an older settings.json without the key gets 128000."""
    settings = _settings(None)
    del settings["model"]["context_window"]
    with patch.object(app_config, "get_settings", return_value=settings):
        assert app_config.get_context_window() == 128000
    with patch.object(app_config, "get_settings", return_value=_settings(None)):
        assert app_config.get_context_window() == 128000


@pytest.mark.parametrize("value", [0, -1, True, "128000", 12.5])
def test_an_invalid_window_is_a_configuration_error(value):
    """Present but wrong is an error, never silently replaced."""
    with patch.object(app_config, "get_settings", return_value=_settings(value)):
        with pytest.raises(app_config.ConfigurationError):
            app_config.get_context_window()
        with pytest.raises(app_config.ConfigurationError):
            app_config.get_context_limits()


def test_no_fallback_thresholds_exist():
    from pathlib import Path

    source = Path(app_config.__file__).read_text(encoding="utf-8")
    assert "LEGACY" not in source
    assert "DEFAULT_SUMMARIZE_AT_TOKENS" not in source
    assert "v1.4.1" not in source
    # the fractions are configuration too -- no constant to fall back on
    assert "STREAM_FRACTION_OF_WINDOW" not in source
    assert "TAIL_KEEP_FRACTION" not in source


def test_no_context_window_is_written_in_provider_config():
    from pathlib import Path

    import agent_core.core.models.provider_config as pc

    assert "context_window=" not in Path(pc.__file__).read_text(encoding="utf-8")
