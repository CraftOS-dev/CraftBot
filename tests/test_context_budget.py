# -*- coding: utf-8 -*-
"""Context budget: one decision, on the request, made before it is sent.

The history collapse came from two budgets that could not see each other: a
threshold on the event stream alone and an independent cap on the session
history. There is one decision now, and it is made on the whole request the
way pi and OpenClaw make it -- the provider's own input count for the previous
request plus what is new -- against the serving model's input budget: its
window (from the model catalog; settings.json for a model the catalog does not
list) less the output cap the request sends, never above the provider's input
limit. These tests pin:

* the history cap is gone; a fold resets the history WITHOUT ending the
  session, so the router keeps the session path and its cached prefix;
* the cache markers the providers need are still on the wire;
* the provider's input count is recorded per session and drives fits_context;
* the budget comes from the serving model: catalog window, input cap, and the
  settings window only for an uncatalogued model;
* the event stream never folds on its own -- only on request -- and a fold
  keeps at most half of the room the budget leaves;
* an overflow is surfaced as one typed error, never counted as a provider
  failure, never retried on a fallback provider;
* the settings are configuration with shipped defaults, invalid values error.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import agent_core.core.impl.llm.interface as interface_module
from agent_core.core.errors import ErrorCategory
from agent_core.core.impl.llm.interface import LLMContextOverflowError, LLMInterface
from agent_core.core.models.catalog import ModelLimits, model_limits
from agent_core.utils.token import count_tokens
from app import config as app_config
from app.models.factory import ModelFactory

WINDOW = 128000
MAX_TOKENS = 8000
# grok-3 is not catalogued, so the settings window applies.
FOLD_POINT = WINDOW - MAX_TOKENS  # 120,000 input tokens


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
    with patch.object(
        ModelFactory, "create", return_value=_ctx(provider, model, anthropic_client)
    ):
        return LLMInterface(
            provider=provider,
            model=model,
            api_key="k",
            base_url="",
            max_tokens=MAX_TOKENS,
        )


def _settings(context_window=WINDOW, keep_recent_tokens=20000):
    return {
        "model": {"context_window": context_window},
        "context": {"keep_recent_tokens": keep_recent_tokens},
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
                input_tokens=10,
                output_tokens=2,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
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
    assert "end_session_cache" not in src[src.index("No delta events") : send]
    assert "except LLMContextOverflowError" in src


def test_a_restored_session_takes_the_session_path_like_a_new_one(tmp_path):
    """The LLM keeps session caches in memory, so a session restored at boot
    must register them again. Without them every turn took the stateless
    path, where only the system prompt hit the provider's KV cache (observed
    2026-10-18 in lui_9a07529e: 9% of 1.65M input tokens cached)."""
    from agent_core.core.impl.llm import LLMCallType
    from agent_core.core.impl.session.manager import SessionManager
    from agent_core.core.session import Session
    from agent_core.core.state.session import StateSession

    iface = _make()
    engine = SimpleNamespace(make_prompt=lambda **kw: ("SYSTEM", ""))
    manager = SessionManager(
        event_stream_manager=None,
        llm_interface=iface,
        context_engine=engine,
        workspace_root=tmp_path,
    )
    created = manager.create_session()
    restored = manager.restore_session(Session.from_dict({"id": "s-restored"}))
    try:
        for session in (created, restored):
            assert iface.has_session_cache(session.id, LLMCallType.ACTION_SELECTION)
    finally:
        for session_id in (created.id, restored.id):
            StateSession.end(session_id)


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
        iface._generate_response_with_session_sync(
            "task", "action_selection", turn, log_response=False
        )

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

    def fake_generate_openai(
        self, system_prompt, user_prompt, call_type=None, messages_override=None, **kw
    ):
        sent.append([dict(m) for m in messages_override])
        return {"content": '{"ok": 1}', "tokens_used": 1}

    iface = _make()
    iface.create_session_cache("task", "action_selection", "SYSTEM")
    with patch.object(LLMInterface, "_generate_openai", fake_generate_openai):
        for turn in range(3):
            iface._generate_response_with_session_sync(
                "task", "action_selection", f"turn {turn}", log_response=False
            )

    assert [m["role"] for m in sent[2]] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert sent[1][:3] == sent[2][:3]


# --------------------------------------- the decision is made on the request


def test_the_providers_input_count_is_recorded_per_session():
    """Every transport reports it through _report_usage_async; it must land on
    the session that made the call and nowhere else."""
    iface = _make()
    iface.create_session_cache("task", "action_selection", "SYSTEM")

    def fake_generate_openai(
        self, system_prompt, user_prompt, call_type=None, messages_override=None, **kw
    ):
        self._report_usage_async("llm_openai", "grok", "grok-3", 4321, 10, 0)
        return {"content": '{"ok": 1}', "tokens_used": 4331}

    with patch.object(LLMInterface, "_generate_openai", fake_generate_openai):
        iface.generate_response_with_session(
            "task", "action_selection", "turn 1", log_response=False
        )
    assert iface.last_input_tokens("task", "action_selection") == 4321

    iface._report_usage_async(
        "llm_openai", "grok", "grok-3", 999, 1, 0
    )  # outside any session call
    assert iface.last_input_tokens("task", "action_selection") == 4321


def test_fits_context_uses_the_providers_count_plus_only_what_is_new():
    iface = _make()
    pending = "new events " * 300
    pending_tokens = count_tokens(pending)
    with patch.object(app_config, "get_settings", return_value=_settings()):
        iface._last_input_tokens["task:action_selection"] = FOLD_POINT - pending_tokens
        assert iface.fits_context("task", "action_selection", "SYSTEM", pending) is True
        iface._last_input_tokens["task:action_selection"] = (
            FOLD_POINT - pending_tokens + 1
        )
        assert (
            iface.fits_context("task", "action_selection", "SYSTEM", pending) is False
        )


def test_fits_context_counts_the_whole_prompt_on_a_sessions_first_request():
    iface = _make()
    system, prompt = "system " * 100, "prompt " * 100
    with patch.object(app_config, "get_settings", return_value=_settings()):
        assert iface.fits_context("task", "action_selection", system, prompt) is True
        too_big = "word " * (FOLD_POINT + 5000)
        assert iface.fits_context("task", "action_selection", system, too_big) is False


def _folds_after(iface, last_input_tokens):
    key = "task:action_selection"
    iface._last_input_tokens[key] = last_input_tokens
    fits = iface.fits_context("task", "action_selection", "s", "")
    iface._last_input_tokens[key] = last_input_tokens + 1
    return fits and not iface.fits_context("task", "action_selection", "s", "")


def test_an_uncatalogued_model_folds_at_the_settings_window():
    """window 128,000 - output 8,000: fold when input passes 120,000."""
    iface = _make()
    with patch.object(app_config, "get_settings", return_value=_settings()):
        assert _folds_after(iface, 120_000)


@pytest.mark.parametrize(
    "provider,model,output_cap",
    [
        ("qwen", "qwen-max", 8192),
        ("groq", "unruled-model", 32768),
        ("nvidia", "meta/llama-3.3-70b-instruct", 16384),
        ("cerebras", "unruled-model", 32000),
    ],
)
def test_context_checks_reserve_the_providers_capped_output(
    provider, model, output_cap
):
    iface = _make(provider, model)
    iface.max_tokens = 50000
    decision = iface.reasoning_decision()
    window, max_input = iface._context_limits()
    budget = min(window - output_cap, max_input or window)

    assert iface._output_reservation(decision) == output_cap
    iface._check_context_fits("system", "hi", reasoning=decision)
    assert _folds_after(iface, budget)


def test_a_catalogued_model_folds_at_its_own_window():
    """The settings window is ignored: 200,000 - output 8,000."""
    iface = _make()
    with (
        patch.object(app_config, "get_settings", return_value=_settings()),
        patch.object(interface_module, "model_limits", lambda *a: ModelLimits(200_000)),
    ):
        assert _folds_after(iface, 192_000)


def test_the_providers_input_limit_caps_the_budget():
    """GPT-5's shape: a 400,000 window that takes at most 272,000 of input."""
    iface = _make()
    limits = ModelLimits(400_000, max_input_tokens=272_000)
    with patch.object(interface_module, "model_limits", lambda *a: limits):
        assert _folds_after(iface, 272_000)
        with pytest.raises(LLMContextOverflowError, match="input capped at 272000"):
            iface._check_context_fits(
                "system", "word " * 280_000, reasoning=iface.reasoning_decision()
            )


def test_the_budget_follows_a_model_switch():
    iface = _make()
    windows = {"small-model": ModelLimits(64_000), "big-model": ModelLimits(1_000_000)}
    with patch.object(
        interface_module, "model_limits", lambda provider, model, auth: windows[model]
    ):
        iface.model = "small-model"
        assert iface.input_budget() == 56_000
        iface.model = "big-model"
        assert iface.input_budget() == 992_000


# ------------------------------------------------------------- the catalog


def test_catalog_lookups_are_exact_and_per_surface(monkeypatch):
    import agent_core.core.models.catalog as catalog

    monkeypatch.setattr(
        catalog,
        "_catalog",
        lambda: {
            "surfaces": {},
            "models": {
                "openai/some-model": {
                    "context_window": 400_000,
                    "max_input_tokens": 272_000,
                },
                "openai_subscription/some-model": {"context_window": 272_000},
            },
        },
    )
    api = model_limits("openai", "some-model")
    assert api == ModelLimits(400_000, max_input_tokens=272_000)
    # The ChatGPT-subscription surface has rows of its own.
    assert model_limits("openai", "some-model", "subscription") == ModelLimits(272_000)
    # No prefix or substring matching; an unlisted model is not catalogued.
    assert model_limits("openai", "some") is None
    assert model_limits("openai", "some-model-x") is None
    assert model_limits("lmstudio", "some-model") is None


def test_the_shipped_catalog_is_well_formed():
    import json

    from agent_core.core.models.catalog import CATALOG_PATH, CacheLifetimeKind
    from agent_core.core.models.provider_config import PROVIDER_CONFIG
    from agent_core.core.models.reasoning import (
        SUBSCRIPTION_AUTH_MODE,
        reasoning_surface,
    )

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    surfaces = {
        reasoning_surface(key, auth)
        for key in PROVIDER_CONFIG
        for auth in ("api_key", SUBSCRIPTION_AUTH_MODE)
    }
    assert set(catalog["surfaces"]) <= surfaces
    for facts in catalog["surfaces"].values():
        assert set(facts) == {"reports_cached_tokens"}
    assert catalog["models"]
    for key, row in catalog["models"].items():
        surface, _, model_id = key.partition("/")
        assert surface in surfaces and model_id, key
        assert set(row) <= {"context_window", "max_input_tokens", "cache_lifetime"}, key
        assert isinstance(row["context_window"], int) and row["context_window"] > 0
        if "max_input_tokens" in row:
            assert 0 < row["max_input_tokens"] < row["context_window"], key
        if "cache_lifetime" in row:
            CacheLifetimeKind(row["cache_lifetime"]["kind"])
            assert row["cache_lifetime"]["seconds"] > 0, key


# ------------------------------------------------- how much a fold keeps


class _KeepRecordingStream:
    head_summary = None

    def __init__(self):
        self.keep_tokens = []

    def summarize_by_LLM(self, keep_tokens):
        self.keep_tokens.append(keep_tokens)


def _fold_keep(budget, system, static, stream=None):
    from agent_core.core.impl.action.router import ActionRouter

    stream = stream or _KeepRecordingStream()
    llm = SimpleNamespace(input_budget=lambda: budget)
    with patch.object(app_config, "get_settings", return_value=_settings()):
        ActionRouter(None, llm, None)._fold(stream, system, static)
    return stream.keep_tokens[0]


def test_a_fold_keeps_the_setting_when_the_budget_has_room():
    assert _fold_keep(900_000, "system " * 1000, "prompt " * 5000) == 20000


def test_a_fold_keeps_at_most_half_the_room_the_budget_leaves():
    system, static = "system " * 1000, "prompt " * 5000
    fixed = count_tokens(system) + count_tokens(static)
    assert _fold_keep(fixed + 24_000, system, static) == 12_000
    # Nothing left after the fixed prompt: keep nothing beyond the pinned tail.
    assert _fold_keep(fixed - 1, system, static) == 0


def test_the_running_summary_is_part_of_what_a_fold_does_not_shrink():
    stream = _KeepRecordingStream()
    stream.head_summary = "summary " * 4000
    budget = 10_000 + count_tokens(stream.head_summary)
    assert _fold_keep(budget, "", None, stream=stream) == 5_000


# ----------------------------------------- the stream folds only on request


def test_the_event_stream_never_folds_on_its_own():
    from agent_core.core.impl.event_stream.event_stream import EventStream

    llm = _CountingLLM()
    es = EventStream(llm=llm, temp_dir=None)
    for i in range(400):
        es.log("action_end", f"action {i} produced output " + "x " * 50)
    assert llm.calls == 0 and es.head_summary is None

    es.mark_delivered()
    es.summarize_by_LLM(keep_tokens=100)
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
    with (
        patch.dict(
            "agent_core.core.impl.llm.transports.TRANSPORTS",
            {"chat_completions": lambda *a, **k: refusal},
        ),
        patch.object(
            LLMInterface,
            "_try_fallback",
            lambda self, *a, **k: fallback_calls.append(1),
        ),
        patch.object(app_config, "get_settings", return_value=_settings()),
    ):
        with pytest.raises(LLMContextOverflowError):
            iface._generate_response_sync(
                system_prompt="s", user_prompt="u", log_response=False
            )
    assert iface._consecutive_failures == 0
    assert fallback_calls == []


def test_the_structured_openai_code_maps_to_context_overflow():
    from pathlib import Path

    import agent_core.core.impl.llm.errors as errors

    src = Path(errors.__file__).read_text(encoding="utf-8")
    i = src.index('code == "context_length_exceeded"')
    assert "ErrorCategory.CONTEXT_OVERFLOW" in src[i : i + 120]


def test_preflight_refuses_a_request_that_does_not_fit():
    iface = _make()
    with patch.object(app_config, "get_settings", return_value=_settings()):
        with pytest.raises(LLMContextOverflowError):
            iface._check_context_fits(
                "system", "word " * 200_000, reasoning=iface.reasoning_decision()
            )
    assert iface._consecutive_failures == 0


# ------------------------------------------------------------ configuration


def test_shipped_defaults_apply_when_keys_are_absent():
    with patch.object(
        app_config, "get_settings", return_value={"model": {}, "context": {}}
    ):
        assert app_config.get_context_window() == 128000
        assert app_config.get_keep_recent_tokens() == 20000


@pytest.mark.parametrize("value", [0, -1, True, "16384", 12.5])
def test_an_invalid_keep_recent_tokens_is_a_configuration_error(value):
    settings = _settings()
    settings["context"]["keep_recent_tokens"] = value
    with patch.object(app_config, "get_settings", return_value=settings):
        with pytest.raises(app_config.ConfigurationError):
            app_config.get_keep_recent_tokens()


def test_no_fallback_constants_and_no_fractions_remain():
    from pathlib import Path

    source = Path(app_config.__file__).read_text(encoding="utf-8")
    for token in (
        "LEGACY",
        "v1.4.1",
        "stream_fraction_of_window",
        "tail_keep_fraction",
        "get_context_limits",
        "reserve_tokens",
    ):
        assert token not in source, token
