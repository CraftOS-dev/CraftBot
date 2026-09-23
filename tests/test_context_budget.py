# -*- coding: utf-8 -*-
"""Context budget: one decision, on the request, made before it is sent.

The history collapse came from two budgets that could not see each other: a
threshold on the event stream alone and an independent cap on the session
history. There is one decision now, and it is made on the whole request the
way pi and OpenClaw make it -- the provider's own input count for the previous
request plus what is new -- against the window less the headroom the summary
request needs. These tests pin:

* the history cap is gone; a fold resets the history WITHOUT ending the
  session, so the router keeps the session path and its cached prefix;
* the cache markers the providers need are still on the wire;
* the provider's input count is recorded per session and drives fits_context;
* the event stream never folds on its own -- only on request;
* an overflow is surfaced as one typed error, never counted as a provider
  failure, never retried on a fallback provider;
* the settings are configuration with shipped defaults, invalid values error.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_core.core.errors import ErrorCategory
from agent_core.core.impl.llm.interface import LLMContextOverflowError, LLMInterface
from agent_core.utils.token import count_tokens
from app import config as app_config
from app.models.factory import ModelFactory

WINDOW = 128000
RESERVE = 16384
MAX_TOKENS = 8000
FOLD_POINT = WINDOW - RESERVE - MAX_TOKENS  # 103,616 input tokens


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
        return LLMInterface(provider=provider, model=model, api_key="k", base_url="", max_tokens=MAX_TOKENS)


def _settings(context_window=WINDOW, reserve_tokens=RESERVE, keep_recent_tokens=20000):
    return {
        "model": {"context_window": context_window},
        "context": {"reserve_tokens": reserve_tokens, "keep_recent_tokens": keep_recent_tokens},
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


class _CountingLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self):
        self.calls = 0

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        self.calls += 1
        return "SUMMARY"


# ------------------------------------------------------------- one budget


def test_the_independent_history_cap_is_gone():
    from pathlib import Path

    import agent_core.core.impl.llm.interface as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "_trim_openai_compat_history" not in source
    assert "max_history_chars" not in source
    assert "_session_messages" not in source  # one provider-agnostic container


def test_reset_session_history_keeps_the_session_registered():
    iface = _make()
    key = "task:action_selection"
    iface.create_session_cache("task", "action_selection", "SYSTEM")
    iface._session_histories[key] = [{"role": "user", "content": "stale"}]
    iface._last_input_tokens[key] = 90000

    iface.reset_session_history("task", "action_selection")

    assert key not in iface._session_histories
    assert iface.last_input_tokens("task", "action_selection") is None
    assert iface.has_session_cache("task", "action_selection") is True


def test_router_decides_on_the_request_and_restarts_without_ending():
    from pathlib import Path

    import agent_core.core.impl.action.router as router

    src = Path(router.__file__).read_text(encoding="utf-8")
    delta_branch = src.index("if has_synced_before:")
    delta_send = src.index("Sending delta events", delta_branch)
    assert "fits_context" in src[delta_branch:delta_send]
    first_call = src.index("if not has_synced_before:")
    send = src.index("generate_response_with_session_async", first_call)
    assert "reset_session_history" in src[first_call:send]
    assert "end_session_cache" not in src[src.index("No delta events"):send]
    assert "except LLMContextOverflowError" in src


def test_subagent_first_turn_resets_history():
    from pathlib import Path

    import app.subagent.runner as runner

    src = Path(runner.__file__).read_text(encoding="utf-8")
    branch = src.index("if not stream.has_session_sync(_SUBAGENT_CALL_TYPE):")
    build = src.index("make_first_turn_user_prompt", branch)
    assert "_reset_session" in src[branch:build]


# ------------------------------------------------------------ KV caching


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


# --------------------------------------- the decision is made on the request


def test_the_providers_input_count_is_recorded_per_session():
    """Every transport reports it through _report_usage_async; it must land on
    the session that made the call and nowhere else."""
    iface = _make()
    iface.create_session_cache("task", "action_selection", "SYSTEM")

    def fake_generate_openai(self, system_prompt, user_prompt, call_type=None, messages_override=None, **kw):
        self._report_usage_async("llm_openai", "grok", "grok-3", 4321, 10, 0)
        return {"content": '{"ok": 1}', "tokens_used": 4331}

    with patch.object(LLMInterface, "_generate_openai", fake_generate_openai):
        iface.generate_response_with_session("task", "action_selection", "turn 1", log_response=False)
    assert iface.last_input_tokens("task", "action_selection") == 4321

    iface._report_usage_async("llm_openai", "grok", "grok-3", 999, 1, 0)  # outside any session call
    assert iface.last_input_tokens("task", "action_selection") == 4321


def test_fits_context_uses_the_providers_count_plus_only_what_is_new():
    iface = _make()
    pending = "new events " * 300
    pending_tokens = count_tokens(pending)
    with patch.object(app_config, "get_settings", return_value=_settings()):
        iface._last_input_tokens["task:action_selection"] = FOLD_POINT - pending_tokens
        assert iface.fits_context("task", "action_selection", "SYSTEM", pending) is True
        iface._last_input_tokens["task:action_selection"] = FOLD_POINT - pending_tokens + 1
        assert iface.fits_context("task", "action_selection", "SYSTEM", pending) is False


def test_fits_context_counts_the_whole_prompt_on_a_sessions_first_request():
    iface = _make()
    system, prompt = "system " * 100, "prompt " * 100
    with patch.object(app_config, "get_settings", return_value=_settings()):
        assert iface.fits_context("task", "action_selection", system, prompt) is True
        too_big = "word " * (FOLD_POINT + 5000)
        assert iface.fits_context("task", "action_selection", system, too_big) is False


def test_the_shipped_fold_point_for_a_128k_window():
    """window 128,000 - reserve 16,384 - output 8,000: fold when input passes 103,616."""
    iface = _make()
    with patch.object(app_config, "get_settings", return_value=_settings()):
        iface._last_input_tokens["task:action_selection"] = 103_616
        assert iface.fits_context("task", "action_selection", "s", "") is True
        iface._last_input_tokens["task:action_selection"] = 103_617
        assert iface.fits_context("task", "action_selection", "s", "") is False


# ----------------------------------------- the stream folds only on request


def test_the_event_stream_never_folds_on_its_own(event_stream_limits):
    from agent_core.core.impl.event_stream.event_stream import EventStream

    event_stream_limits(100)
    llm = _CountingLLM()
    es = EventStream(llm=llm, temp_dir=None)
    for i in range(400):
        es.log("action_end", f"action {i} produced output " + "x " * 50)
    assert llm.calls == 0 and es.head_summary is None

    es.summarize_by_LLM()
    assert llm.calls == 1 and es.head_summary is not None


# ------------------------------------------------------------- overflow


def test_a_provider_size_rejection_is_a_typed_overflow_not_a_failure():
    iface = _make()
    refusal = {
        "content": "",
        "error": "BadRequestError: context_length_exceeded",
        "error_info_obj": SimpleNamespace(
            category=ErrorCategory.CONTEXT_OVERFLOW, message="request too large"
        ),
    }
    fallback_calls = []
    with patch.dict("agent_core.core.impl.llm.transports.TRANSPORTS",
                    {"chat_completions": lambda *a, **k: refusal}), \
         patch.object(LLMInterface, "_try_fallback", lambda self, *a, **k: fallback_calls.append(1)), \
         patch.object(app_config, "get_settings", return_value=_settings()):
        with pytest.raises(LLMContextOverflowError):
            iface._generate_response_sync(system_prompt="s", user_prompt="u", log_response=False)
    assert iface._consecutive_failures == 0
    assert fallback_calls == []


def test_the_structured_openai_code_maps_to_context_overflow():
    from pathlib import Path

    import agent_core.core.impl.llm.errors as errors

    src = Path(errors.__file__).read_text(encoding="utf-8")
    i = src.index('code == "context_length_exceeded"')
    assert "ErrorCategory.CONTEXT_OVERFLOW" in src[i: i + 120]


def test_preflight_refuses_a_request_that_does_not_fit():
    iface = _make()
    with patch.object(app_config, "get_settings", return_value=_settings()):
        with pytest.raises(LLMContextOverflowError):
            iface._check_context_fits("system", "word " * 200_000)
    assert iface._consecutive_failures == 0


# ------------------------------------------------------------ configuration


def test_shipped_defaults_apply_when_keys_are_absent():
    with patch.object(app_config, "get_settings", return_value={"model": {}, "context": {}}):
        assert app_config.get_context_window() == 128000
        assert app_config.get_reserve_tokens() == 16384
        assert app_config.get_keep_recent_tokens() == 20000


@pytest.mark.parametrize("value", [0, -1, True, "16384", 12.5])
@pytest.mark.parametrize("key", ["reserve_tokens", "keep_recent_tokens"])
def test_an_invalid_context_setting_is_a_configuration_error(key, value):
    settings = _settings()
    settings["context"][key] = value
    with patch.object(app_config, "get_settings", return_value=settings):
        with pytest.raises(app_config.ConfigurationError):
            getattr(app_config, f"get_{key}")()


def test_no_fallback_constants_and_no_fractions_remain():
    from pathlib import Path

    source = Path(app_config.__file__).read_text(encoding="utf-8")
    for token in ("LEGACY", "v1.4.1", "stream_fraction_of_window", "tail_keep_fraction", "get_context_limits"):
        assert token not in source, token
