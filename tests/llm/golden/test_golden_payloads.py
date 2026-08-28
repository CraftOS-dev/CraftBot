# -*- coding: utf-8 -*-
"""Golden payload scenarios per provider (Phase 0, NFR-3).

Each scenario runs the same script against one provider:
  1. one sessionless ``generate_response`` call (no call_type), then
  2. three ``generate_response_with_session`` turns on one task/call_type.

The full recorded payloads + final session buffers are snapshot-compared.
Targeted assertions below additionally pin the caching invariants in
human-readable form so a snapshot regression is diagnosable at a glance.
"""

from __future__ import annotations

from .conftest import (
    GOLDEN_CALL_TYPE,
    GOLDEN_SYSTEM_PROMPT,
    GOLDEN_TASK_ID,
    assert_snapshot,
    collect_buffers,
)


def run_scenario(iface):
    responses = [
        iface.generate_response(
            system_prompt=GOLDEN_SYSTEM_PROMPT,
            user_prompt="sessionless turn",
            prompt_name="golden",
        )
    ]
    # Canonical session flow: register once at task start (stores the system
    # prompt for lazy per-call use), then send session turns.
    iface.create_session_cache(GOLDEN_TASK_ID, GOLDEN_CALL_TYPE, GOLDEN_SYSTEM_PROMPT)
    for i in range(1, 4):
        responses.append(
            iface.generate_response_with_session(
                GOLDEN_TASK_ID,
                GOLDEN_CALL_TYPE,
                f"session turn {i}",
            )
        )
    return responses


def snapshot_scenario(name, iface, recorder):
    assert_snapshot(
        name,
        {"calls": recorder.calls, "session_buffers": collect_buffers(iface)},
    )


# ─────────────────────────── Anthropic ───────────────────────────


def test_anthropic(golden):
    iface, rec = golden("anthropic", "claude-sonnet-4-6")
    run_scenario(iface)

    creates = [c for c in rec.calls if c["method"] == "messages.create"]
    assert len(creates) == 4

    # Sessionless: long system prompt -> cached system block, 5-min TTL
    # (no call_type), single user message.
    sessionless = creates[0]["payload"]
    assert sessionless["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [m["role"] for m in sessionless["messages"]] == ["user"]

    # Session turns: system cache_control gets the 1h TTL (call_type set).
    for call in creates[1:]:
        assert call["payload"]["system"][0]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }

    # Turn 3: history [u1, a1, u2, a2] + new user. cache_control must sit on
    # the LAST assistant message's text block and nowhere else in messages.
    turn3 = creates[3]["payload"]["messages"]
    assert [m["role"] for m in turn3] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    marked = [
        (i, block)
        for i, m in enumerate(turn3)
        if isinstance(m["content"], list)
        for block in m["content"]
        if "cache_control" in block
    ]
    assert len(marked) == 1
    assert marked[0][0] == 3  # index of the last assistant message
    assert marked[0][1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    snapshot_scenario("anthropic", iface, rec)


# ─────────────────────────── Bedrock ───────────────────────────


def test_bedrock(golden):
    iface, rec = golden("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    run_scenario(iface)

    converses = [c for c in rec.calls if c["method"] == "converse"]
    assert len(converses) == 4

    # Sessionless (no call_type): plain system block, no cachePoint anywhere.
    sessionless = converses[0]["payload"]
    assert sessionless["system"] == [{"text": GOLDEN_SYSTEM_PROMPT}]
    assert not any(
        "cachePoint" in b for m in sessionless["messages"] for b in m["content"]
    )

    # Session turn 1: no history yet -> cachePoint lands in the system block.
    turn1 = converses[1]["payload"]
    assert turn1["system"] == [
        {"text": GOLDEN_SYSTEM_PROMPT},
        {"cachePoint": {"type": "default"}},
    ]

    # Session turn 3: exactly one cachePoint, at the end of the LAST assistant
    # message's content; system block back to plain text (no double-up).
    turn3 = converses[3]["payload"]
    assert turn3["system"] == [{"text": GOLDEN_SYSTEM_PROMPT}]
    points = [
        (i, j)
        for i, m in enumerate(turn3["messages"])
        for j, b in enumerate(m["content"])
        if "cachePoint" in b
    ]
    assert len(points) == 1
    i, j = points[0]
    assert turn3["messages"][i]["role"] == "assistant"
    assert i == 3  # last assistant in [u1, a1, u2, a2, new_user]
    assert j == len(turn3["messages"][i]["content"]) - 1

    snapshot_scenario("bedrock", iface, rec)


# ─────────────────────────── OpenAI-compatible ───────────────────────────


def test_openai(golden):
    """OpenAI profile policies: max_completion_tokens + no temperature."""
    iface, rec = golden("openai", "gpt-5.2-2025-12-11")
    run_scenario(iface)

    creates = [c for c in rec.calls if c["method"] == "chat.completions.create"]
    assert len(creates) == 4
    assert all("max_completion_tokens" in c["payload"] for c in creates)
    assert all("max_tokens" not in c["payload"] for c in creates)
    # Reasoning-family models only accept the default temperature — the API
    # 400s on an explicit value ("'temperature' does not support 0.0 with
    # this model"), so the field must be absent.
    assert all("temperature" not in c["payload"] for c in creates)

    # Sessionless (no call_type): now ALSO gets a prompt_cache_key (the bare
    # system-prompt hash, no call_type prefix) so the main reasoning loop
    # gets sticky routing / cache hits. Regression for Mistral 0% cache.
    sessionless_key = creates[0]["payload"]["extra_body"]["prompt_cache_key"]
    assert "_" not in sessionless_key  # bare hash, no call_type prefix

    # Session turns: stable prompt_cache_key across all turns, call_type-prefixed.
    keys = [c["payload"]["extra_body"]["prompt_cache_key"] for c in creates[1:]]
    assert len(set(keys)) == 1
    assert keys[0] == f"{GOLDEN_CALL_TYPE}_{sessionless_key}"

    # History grows: turn N sends [system] + 2*(N-1) history + [new user].
    for n, call in enumerate(creates[1:], start=1):
        msgs = call["payload"]["messages"]
        assert len(msgs) == 1 + 2 * (n - 1) + 1
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"

    snapshot_scenario("openai", iface, rec)


def test_moonshot_omits_temperature(golden):
    """Kimi/Moonshot thinking models reject an explicit temperature — the
    chat_completions transport must NOT send the field (Hermes' OMIT_TEMPERATURE
    policy). Other OpenAI-compat providers still send it (see test_deepseek /
    test_openai). Regression for the live error 'invalid temperature: only 1
    is allowed for this model'."""
    iface, rec = golden("moonshot", "kimi-k2.5")
    iface.generate_response(system_prompt="s" * 600, user_prompt="hi")
    creates = [c for c in rec.calls if c["method"] == "chat.completions.create"]
    assert len(creates) == 1
    assert "temperature" not in creates[0]["payload"]
    # sanity: a normal provider DOES send it
    iface2, rec2 = golden("deepseek", "deepseek-chat")
    iface2.generate_response(system_prompt="s" * 600, user_prompt="hi")
    assert (
        "temperature"
        in [c for c in rec2.calls if c["method"] == "chat.completions.create"][0][
            "payload"
        ]
    )


def test_provider_request_quirks(golden):
    """Per-provider request-shaping verified against provider docs / Hermes
    (docs/PROVIDER_SETTINGS_UX_FIX.md audit). Each of these would 400 on the
    first real request if we sent the field unconditionally."""

    def _payload(provider, model):
        iface, rec = golden(provider, model)
        iface.generate_response(system_prompt="respond in json " * 40, user_prompt="hi")
        return [c for c in rec.calls if c["method"] == "chat.completions.create"][0][
            "payload"
        ]

    # Perplexity: json_object is a hard 400 → must be omitted.
    ppx = _payload("perplexity", "sonar-pro")
    assert "response_format" not in ppx

    # LM Studio: json_object unsupported → omitted.
    lms = _payload("lmstudio", "openai/gpt-oss-20b")
    assert "response_format" not in lms

    # OmniRoute (local OpenAI-compatible router): a routed backend may reject
    # json_object → omitted; and as a proxy it must NOT receive prompt_cache_key
    # (KV-safe — avoids a 400, gains nothing).
    omni = _payload("omniroute", "auto")
    assert "response_format" not in omni
    assert "prompt_cache_key" not in (omni.get("extra_body") or {})

    # Qwen: temperature 0 is rejected → sent as 0.01 (not 0.0, not omitted).
    qwen = _payload("qwen", "qwen-max")
    assert qwen["temperature"] == 0.01
    assert qwen["response_format"] == {"type": "json_object"}  # qwen DOES accept it

    # Groq (control): still sends json_object + temperature, but now uses
    # max_completion_tokens (max_tokens deprecated) capped at 32768.
    groq = _payload("groq", "openai/gpt-oss-120b")
    assert groq["response_format"] == {"type": "json_object"}
    assert "temperature" in groq
    assert "max_tokens" not in groq
    assert groq["max_completion_tokens"] == 32768  # capped from default 50000

    # NVIDIA: legacy max_tokens field, capped to 16384 (would 422 at 50000).
    nvidia = _payload("nvidia", "meta/llama-3.3-70b-instruct")
    assert nvidia["max_tokens"] == 16384
    assert "max_completion_tokens" not in nvidia

    # Cerebras: requires max_completion_tokens, capped to 32000.
    cerebras = _payload("cerebras", "gpt-oss-120b")
    assert cerebras["max_completion_tokens"] == 32000
    assert "max_tokens" not in cerebras

    # MiniMax: OpenAI-compat wire requires max_completion_tokens.
    mm = _payload("minimax", "MiniMax-M2.1")
    assert "max_completion_tokens" in mm
    assert "max_tokens" not in mm


def test_minimax_think_tags_stripped(golden):
    """MiniMax M2.x inlines <think>...</think> reasoning in content; the
    transport must strip it before the JSON-action parser sees it."""
    from types import SimpleNamespace

    class _ThinkClient:
        def __init__(self):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='<think>let me reason about this</think>{"action": "done"}'
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=0),
                    prompt_cache_hit_tokens=0,
                ),
            )

    import agent_core.core.impl.llm.transports.chat_completions as cc

    out = cc._strip_reasoning_tags(
        '<think>let me reason about this</think>{"action": "done"}'
    )
    assert out == '{"action": "done"}'
    # multi-line think block
    assert cc._strip_reasoning_tags("<think>\na\nb\n</think>hello") == "hello"
    # no think tags -> unchanged
    assert cc._strip_reasoning_tags('{"x": 1}') == '{"x": 1}'


def test_deepseek(golden):
    """Representative OpenAI-compat provider -> legacy max_tokens branch."""
    iface, rec = golden("deepseek", "deepseek-chat")
    run_scenario(iface)

    creates = [c for c in rec.calls if c["method"] == "chat.completions.create"]
    assert len(creates) == 4
    assert all("max_tokens" in c["payload"] for c in creates)
    assert all("max_completion_tokens" not in c["payload"] for c in creates)
    assert all(
        c["payload"]["response_format"] == {"type": "json_object"} for c in creates
    )

    snapshot_scenario("deepseek", iface, rec)


def test_openrouter_claude(golden):
    """Claude slug via OpenRouter -> cache_control in extra_body + its own
    session buffer family."""
    iface, rec = golden("openrouter", "anthropic/claude-sonnet-4.5")
    run_scenario(iface)

    creates = [c for c in rec.calls if c["method"] == "chat.completions.create"]
    assert len(creates) == 4

    # Sessionless: cache_control present (long system prompt), 5-min TTL.
    assert creates[0]["payload"]["extra_body"]["cache_control"] == {"type": "ephemeral"}

    # Session turns: cache_control with 1h TTL + prompt_cache_key.
    for call in creates[1:]:
        extra = call["payload"]["extra_body"]
        assert extra["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert extra["prompt_cache_key"].startswith(f"{GOLDEN_CALL_TYPE}_")

    # Accumulation must use the OpenRouter-Anthropic buffer, not openai_compat.
    buffers = collect_buffers(iface)
    key = f"{GOLDEN_TASK_ID}:{GOLDEN_CALL_TYPE}"
    assert len(buffers["openrouter_anthropic"][key]) == 6  # 3 turns x (u, a)
    assert buffers["openai_compat"] == {}

    snapshot_scenario("openrouter_claude", iface, rec)


def test_openrouter_non_claude(golden):
    """Non-Claude slug via OpenRouter -> NO cache_control, openai_compat
    buffer family."""
    iface, rec = golden("openrouter", "deepseek/deepseek-chat")
    run_scenario(iface)

    creates = [c for c in rec.calls if c["method"] == "chat.completions.create"]
    assert len(creates) == 4
    for call in creates:
        extra = call["payload"].get("extra_body", {})
        assert "cache_control" not in extra

    buffers = collect_buffers(iface)
    key = f"{GOLDEN_TASK_ID}:{GOLDEN_CALL_TYPE}"
    assert len(buffers["openai_compat"][key]) == 6
    assert buffers["openrouter_anthropic"] == {}

    snapshot_scenario("openrouter_non_claude", iface, rec)


def test_groq_new_provider(golden):
    """Phase 3 provider on the chat_completions wire: session history
    accumulates (session_accumulation=True) but prompt_cache_key is NOT
    emitted (opt-in flag defaults to False for new providers)."""
    iface, rec = golden("groq", "llama-3.3-70b-versatile")
    run_scenario(iface)

    creates = [c for c in rec.calls if c["method"] == "chat.completions.create"]
    assert len(creates) == 4
    for call in creates:
        extra = call["payload"].get("extra_body", {})
        assert "prompt_cache_key" not in extra
        assert "cache_control" not in extra

    buffers = collect_buffers(iface)
    key = f"{GOLDEN_TASK_ID}:{GOLDEN_CALL_TYPE}"
    assert len(buffers["openai_compat"][key]) == 6  # 3 turns x (u, a)

    snapshot_scenario("groq", iface, rec)


# ─────────────────────────── Gemini ───────────────────────────


def test_gemini(golden):
    iface, rec = golden("gemini", "gemini-2.5-pro")
    run_scenario(iface)

    # Sessionless (no call_type) -> single-turn generate_text.
    assert rec.calls[0]["method"] == "generate_text"

    # Session turns -> multiturn contents array growing by 2 per turn.
    multiturns = [c for c in rec.calls if c["method"] == "generate_text_multiturn"]
    assert len(multiturns) == 3
    for n, call in enumerate(multiturns, start=1):
        contents = call["payload"]["contents"]
        assert len(contents) == 2 * (n - 1) + 1
        assert contents[-1]["role"] == "user"

    snapshot_scenario("gemini", iface, rec)


# ─────────────────────────── BytePlus ───────────────────────────


def test_byteplus(golden):
    iface, rec = golden("byteplus", "seed-2-0-pro-260328")
    run_scenario(iface)

    api_calls = [c for c in rec.calls if c["method"] == "_call_responses_api"]
    assert len(api_calls) == 4

    # Sessionless long-system call goes through the prefix-cache path:
    # first call has no previous_response_id and caching enabled.
    assert api_calls[0]["payload"]["previous_response_id"] is None

    # Session turns chain: turn 1 creates (no previous id), turns 2-3 chain
    # to the response id returned by the PREVIOUS call.
    session_calls = api_calls[1:]
    assert session_calls[0]["payload"]["previous_response_id"] is None
    assert session_calls[1]["payload"]["previous_response_id"] == "resp_2"
    assert session_calls[2]["payload"]["previous_response_id"] == "resp_3"
    assert all(c["payload"]["caching_enabled"] for c in session_calls)

    snapshot_scenario("byteplus", iface, rec)


# ─────────────────────────── Ollama (remote) ───────────────────────────


def test_remote_ollama(golden):
    iface, rec = golden("remote", "llama3.2:3b")
    run_scenario(iface)

    posts = [c for c in rec.calls if c["method"] == "requests.post"]
    assert len(posts) == 4
    assert all(p["payload"]["url"].endswith("/api/generate") for p in posts)
    assert posts[0]["payload"]["json"]["system"] == GOLDEN_SYSTEM_PROMPT

    # Known current behavior (frozen deliberately): remote does not support
    # session caching (create_session_cache returns None) and session turns
    # fall through to a stateless call that does NOT re-send the registered
    # system prompt.
    assert "system" not in posts[1]["payload"]["json"]
    assert "system" not in posts[2]["payload"]["json"]
    assert "system" not in posts[3]["payload"]["json"]

    snapshot_scenario("remote", iface, rec)
