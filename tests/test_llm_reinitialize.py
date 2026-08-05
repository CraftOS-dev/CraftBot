# -*- coding: utf-8 -*-
"""Unit tests for LLMInterface.reinitialize() provider/model diffing.

Covers the fix for: a model-only (or no-op) Settings save was
unconditionally wiping every active task's session-cache state
(_session_system_prompts + per-provider message histories), even though
those buffers are only invalidated by an actual *provider* change — the
message format they hold is provider-specific, not model-specific.
"""
from unittest.mock import patch

import pytest

from agent_core.core.impl.llm.interface import LLMInterface
from app.models.factory import ModelFactory


def _make_ctx(provider="anthropic", model="claude-a"):
    return {
        "provider": provider,
        "model": model,
        "client": object(),
        "gemini_client": None,
        "remote_url": None,
        "byteplus": None,
        "anthropic_client": object(),
        "bedrock_client": None,
        "initialized": True,
        "auth_mode": "api_key",
    }


@pytest.fixture
def llm_interface():
    with patch.object(ModelFactory, "create", return_value=_make_ctx()):
        interface = LLMInterface(
            provider="anthropic", model="claude-a", api_key="key-a", base_url=""
        )
    # Seed accumulated session state as if a task were mid-flight.
    interface._session_system_prompts["task-1:reasoning"] = "system prompt"
    interface._anthropic_session_messages["task-1:reasoning"] = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    return interface


def test_reinitialize_noop_preserves_everything(llm_interface):
    """A Settings save with no actual change must not touch live state."""
    with patch.object(ModelFactory, "create") as mock_create, patch(
        "app.config.get_llm_model", return_value="claude-a"
    ):
        ok = llm_interface.reinitialize(
            provider="anthropic", api_key="key-a", base_url=""
        )

    assert ok is True
    mock_create.assert_not_called()
    assert llm_interface._anthropic_session_messages["task-1:reasoning"]
    assert llm_interface._session_system_prompts["task-1:reasoning"] == "system prompt"


def test_reinitialize_model_only_preserves_histories(llm_interface):
    """Same provider, different model: histories survive, model updates."""
    with patch.object(
        ModelFactory, "create", return_value=_make_ctx(model="claude-b")
    ), patch("app.config.get_llm_model", return_value="claude-b"):
        ok = llm_interface.reinitialize(
            provider="anthropic", api_key="key-a", base_url=""
        )

    assert ok is True
    assert llm_interface.model == "claude-b"
    assert llm_interface._anthropic_session_messages["task-1:reasoning"]
    assert llm_interface._session_system_prompts["task-1:reasoning"] == "system prompt"


def test_reinitialize_provider_change_clears_histories(llm_interface):
    """An actual provider change still fully resets session state."""
    with patch.object(
        ModelFactory, "create", return_value=_make_ctx(provider="openai", model="gpt-x")
    ), patch("app.config.get_llm_model", return_value="gpt-x"):
        ok = llm_interface.reinitialize(
            provider="openai", api_key="key-b", base_url=""
        )

    assert ok is True
    assert llm_interface.provider == "openai"
    assert llm_interface._anthropic_session_messages == {}
    assert llm_interface._session_system_prompts == {}
