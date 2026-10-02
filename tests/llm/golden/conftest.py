# -*- coding: utf-8 -*-
"""Golden payload harness (Phase 0 of docs/PROVIDER_LAYER_CATCHUP.md).

Freezes the EXACT request payloads LLMInterface sends per provider so the
Phase 1/2 refactors (registry consolidation, transport extraction) are
provably behavior-preserving. This is the enforcement mechanism for NFR-3
(KV caching): cache_control placement, cachePoint position, prompt_cache_key
stability, previous_response_id chaining, and session-buffer growth are all
captured in committed JSON snapshots under tests/llm/golden/snapshots/.

Mocking strategy:
- ``ModelFactory.create`` is patched to return a context dict with recording
  fake clients, so LLMInterface's own logic (message building, cache markers,
  session buffers) runs unmodified.
- BytePlus uses the REAL BytePlusCacheManager with only its network
  chokepoint (``_call_responses_api``) patched, so the previous_response_id
  chaining and caching-flag semantics are exercised and frozen too.
- Ollama patches the ``requests`` module reference inside interface.py.

Snapshot policy: a missing snapshot is created and the test passes (commit
the file). An existing snapshot MUST match; drift fails the test. To
intentionally regenerate after a reviewed behavior change, run with
``GOLDEN_UPDATE=1``.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"

# ≥ 500 chars (CacheConfig.min_cache_tokens) so every caching branch fires.
GOLDEN_SYSTEM_PROMPT = (
    "You are CraftBot, a personal always-online agent. "
    "You reason step by step, act through a JSON action protocol, and reply "
    "with a single JSON object. "
) * 8

GOLDEN_TASK_ID = "task-golden"
GOLDEN_CALL_TYPE = "reasoning"
GOLDEN_SESSION_KEY = f"{GOLDEN_TASK_ID}:{GOLDEN_CALL_TYPE}"


class CallRecorder:
    """Records every provider-bound call (client label, method, payload)."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._turn = 0

    def next_content(self) -> str:
        self._turn += 1
        return json.dumps({"turn": self._turn})

    def record(self, client: str, method: str, payload: Dict[str, Any]) -> None:
        self.calls.append(
            {"client": client, "method": method, "payload": copy.deepcopy(payload)}
        )


# ─────────────────────────── fake clients ───────────────────────────


class FakeOpenAIClient:
    """Stands in for openai.OpenAI — records chat.completions.create kwargs."""

    def __init__(self, recorder: CallRecorder) -> None:
        self._recorder = recorder
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self._recorder.record("openai_compat", "chat.completions.create", kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._recorder.next_content())
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=10,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
                prompt_cache_hit_tokens=0,
            ),
        )


class FakeAnthropicClient:
    def __init__(self, recorder: CallRecorder) -> None:
        self._recorder = recorder
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self._recorder.record("anthropic", "messages.create", kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._recorder.next_content())],
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=10,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
        )


class FakeBedrockClient:
    def __init__(self, recorder: CallRecorder) -> None:
        self._recorder = recorder

    def converse(self, **kwargs):
        self._recorder.record("bedrock", "converse", kwargs)
        return {
            "output": {
                "message": {
                    "content": [{"text": self._recorder.next_content()}]
                }
            },
            "usage": {"inputTokens": 100, "outputTokens": 10},
        }


def make_recording_gemini_client(recorder: CallRecorder):
    """A REAL GeminiClient whose single HTTP chokepoint is a recorder.

    Recording the JSON body the client would POST (rather than the Python
    kwargs the transport passes it) freezes exactly what reaches the Gemini
    API, including the generationConfig the client assembles.
    """
    from agent_core.core.llm.google_gemini_client import GeminiClient

    client = GeminiClient(api_key="test-gemini-key")

    def _post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        recorder.record("gemini", "generateContent", {"path": path, "body": payload})
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": recorder.next_content()}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "totalTokenCount": 110,
                "promptTokenCount": 100,
                "candidatesTokenCount": 10,
                "cachedContentTokenCount": 0,
            },
        }

    client._post_json = _post_json
    return client


def make_fake_requests(recorder: CallRecorder):
    """Fake for the module-level ``requests`` used by _generate_ollama."""

    def post(url, json=None, timeout=None):  # noqa: A002 - mirrors requests API
        recorder.record("ollama", "requests.post", {"url": url, "json": json})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "response": recorder.next_content(),
                "prompt_eval_count": 100,
                "eval_count": 10,
            },
        )

    return SimpleNamespace(post=post)


def make_fake_byteplus_transport(recorder: CallRecorder):
    """Replacement for BytePlusCacheManager._call_responses_api.

    The REAL manager logic (session registry, previous_response_id chaining,
    caching flags) runs; only the HTTP hop is faked. Payload keys mirror the
    method's signature so the chaining semantics land in the snapshot.
    """
    counter = {"n": 0}

    def _call_responses_api(
        self,
        input_messages,
        temperature,
        max_tokens,
        previous_response_id=None,
        caching_enabled=True,
        caching_prefix=False,
    ):
        recorder.record(
            "byteplus",
            "_call_responses_api",
            {
                "input_messages": input_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "previous_response_id": previous_response_id,
                "caching_enabled": caching_enabled,
                "caching_prefix": caching_prefix,
            },
        )
        counter["n"] += 1
        return {
            "id": f"resp_{counter['n']}",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": recorder.next_content()}
                    ],
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "input_tokens_details": {"cached_tokens": 0},
            },
        }

    return _call_responses_api


# ─────────────────────────── fixture ───────────────────────────


def build_interface(monkeypatch, provider: str, model: str):
    """Construct an LLMInterface for ``provider`` with recording fakes."""
    from agent_core.core.models.factory import ModelFactory
    import agent_core.core.impl.llm.interface as interface_mod
    from agent_core.core.impl.llm.cache.byteplus import BytePlusCacheManager

    recorder = CallRecorder()

    ctx: Dict[str, Any] = {
        "provider": provider,
        "model": model,
        "client": None,
        "gemini_client": None,
        "anthropic_client": None,
        "bedrock_client": None,
        "remote_url": None,
        "byteplus": None,
        "initialized": True,
        "auth_mode": "api_key",
    }

    if provider == "anthropic":
        ctx["anthropic_client"] = FakeAnthropicClient(recorder)
    elif provider == "bedrock":
        ctx["bedrock_client"] = FakeBedrockClient(recorder)
    elif provider == "gemini":
        ctx["gemini_client"] = make_recording_gemini_client(recorder)
    elif provider == "byteplus":
        ctx["byteplus"] = {
            "api_key": "test-byteplus-key",
            "base_url": "https://fake.byteplus.test/api/v3",
        }
        monkeypatch.setattr(
            BytePlusCacheManager,
            "_call_responses_api",
            make_fake_byteplus_transport(recorder),
        )
    elif provider == "remote":
        ctx["remote_url"] = "http://localhost:11434"
        # Ollama's HTTP hop lives in the chat_completions transport since
        # Phase 2; patch the module reference the live code actually uses.
        from agent_core.core.impl.llm.transports import chat_completions

        monkeypatch.setattr(
            chat_completions, "requests", make_fake_requests(recorder)
        )
    else:
        # openai / deepseek / grok / openrouter / glm / fugu / minimax / moonshot
        ctx["client"] = FakeOpenAIClient(recorder)

    def fake_create(**kwargs):
        return dict(ctx)

    monkeypatch.setattr(ModelFactory, "create", staticmethod(fake_create))

    iface = interface_mod.LLMInterface(provider=provider, model=model)
    return iface, recorder


def collect_buffers(iface) -> Dict[str, Any]:
    """Deep-copy the accumulated session histories (NFR-3 state).

    One interface serves one provider, so its single ``_session_histories``
    map holds whatever message shape that provider's session branch builds.
    """
    return {"session_histories": copy.deepcopy(iface._session_histories)}


# ─────────────────────────── snapshots ───────────────────────────


def assert_snapshot(name: str, data: Dict[str, Any]) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAP_DIR / f"{name}.json"
    canonical = json.loads(json.dumps(data))  # normalize tuples etc.

    if os.environ.get("GOLDEN_UPDATE") == "1" or not path.exists():
        path.write_text(
            json.dumps(canonical, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        return

    expected = json.loads(path.read_text(encoding="utf-8"))
    assert canonical == expected, (
        f"Golden payload drift for {name!r}.\n"
        f"A request payload, cache marker, or session buffer changed. This is a "
        f"behavior change by definition (see docs/PROVIDER_LAYER_CATCHUP.md "
        f"section 12.3). If intentional and reviewed, regenerate with "
        f"GOLDEN_UPDATE=1 and commit the diff."
    )


@pytest.fixture()
def golden(monkeypatch):
    """Factory fixture: golden(provider, model) -> (iface, recorder)."""

    def _build(provider: str, model: str):
        return build_interface(monkeypatch, provider, model)

    return _build
