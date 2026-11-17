# -*- coding: utf-8 -*-
"""ChatGPT subscription cache routing (agent_core/core/models/chatgpt_subscription_client.py).

The Codex backend derives prompt-cache affinity from the ``session-id``
request header. Without it every request lands on a random shard and gets
0 cached tokens, however stable the prompt is, so every request must carry
the header, equal to the body's ``prompt_cache_key`` and stable across turns.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

from agent_core.core.models.chatgpt_subscription_client import (
    ChatGPTSubscriptionClient,
)


class _FakeResponses:
    """Records each responses.create call and streams back a short reply."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def create(self, **kwargs: Any) -> List[SimpleNamespace]:
        self.calls.append(kwargs)
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=5,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        response = SimpleNamespace(id="resp_1", model=kwargs["model"], usage=usage)
        return [
            SimpleNamespace(type="response.output_text.delta", delta='{"ok": true}'),
            SimpleNamespace(type="response.completed", response=response),
        ]


def _client() -> tuple[ChatGPTSubscriptionClient, _FakeResponses]:
    responses = _FakeResponses()
    return ChatGPTSubscriptionClient(SimpleNamespace(responses=responses)), responses


def _messages(turn: int) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": f"turn {turn}"},
    ]


def test_every_request_sends_the_cache_key_as_the_session_id_header():
    client, responses = _client()
    for turn in (1, 2):
        client.chat.completions.create(
            model="gpt-6.1-sol",
            messages=_messages(turn),
            extra_body={"prompt_cache_key": "action_selection_abc123"},
        )

    for call in responses.calls:
        assert call["prompt_cache_key"] == "action_selection_abc123"
        assert call["extra_headers"] == {"session-id": "action_selection_abc123"}


def test_without_a_caller_key_the_header_is_the_stable_client_key():
    client, responses = _client()
    for turn in (1, 2):
        client.chat.completions.create(model="gpt-6.1-sol", messages=_messages(turn))

    headers = [call["extra_headers"]["session-id"] for call in responses.calls]
    keys = [call["prompt_cache_key"] for call in responses.calls]
    assert headers == keys
    assert headers[0] == headers[1]
