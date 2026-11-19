"""Startup must find subscription credentials in the selected runtime profile."""

import json
import time
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import agent_base
from app.data.action.integrations import account_bridge
from agent_core.core.models import factory
from agent_core.core.models.provider_config import PROVIDER_CONFIG
from craftos_integrations.config import ConfigStore
from craftos_integrations.llm_oauth import chatgpt


class _ModelsCreated(Exception):
    """Stop the real constructor before unrelated agent runtime services start."""


def _save_subscription(root, token):
    directory = root / ".credentials"
    directory.mkdir(parents=True, exist_ok=True)
    credential = chatgpt.ChatGPTOAuthCredential(
        access_token=token,
        refresh_token="test-refresh-token",
        expires_at=time.time() + 3600,
        account_id=token,
    )
    (directory / chatgpt.CRED_FILE).write_text(
        json.dumps(asdict(credential)), encoding="utf-8"
    )


@pytest.fixture
def startup(tmp_path, monkeypatch):
    code = tmp_path / "code checkout"
    profile = tmp_path / "selected profile"
    code.mkdir()
    profile.mkdir()
    monkeypatch.chdir(code)
    monkeypatch.setattr(agent_base, "PROJECT_ROOT", profile)
    monkeypatch.setattr(ConfigStore, "project_root", code)
    monkeypatch.setattr(ConfigStore, "logger", None)

    # Keep the real constructor, LLM/VLM factories and credential-file lookup.
    # Stub network clients and unrelated persistence/media/runtime components.
    sdk = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(factory, "_create_openai_client", sdk)
    monkeypatch.setattr(
        chatgpt,
        "http_request",
        Mock(side_effect=AssertionError("Unexpected network call")),
    )
    monkeypatch.setattr(agent_base.AgentBase, "_build_db_interface", Mock())
    monkeypatch.setattr(account_bridge, "inject_account_schemas", Mock())
    monkeypatch.setattr(agent_base, "ImageGenInterface", Mock())
    monkeypatch.setattr(agent_base, "VideoGenInterface", Mock())
    monkeypatch.setattr(
        agent_base, "EventStreamManager", Mock(side_effect=_ModelsCreated)
    )

    def construct(api_key=None):
        # Reset the default location to simulate a fresh backend process.
        ConfigStore.project_root = code
        sdk.reset_mock()
        agent = agent_base.AgentBase.__new__(agent_base.AgentBase)
        with pytest.raises(_ModelsCreated):
            agent_base.AgentBase.__init__(
                agent,
                llm_provider="openai",
                llm_model=PROVIDER_CONFIG["openai"].subscription_default_model,
                llm_api_key=api_key,
                deferred_init=True,
            )
        return agent

    return SimpleNamespace(code=code, profile=profile, sdk=sdk, construct=construct)


@pytest.mark.parametrize("credentials_beside_code", [False, True])
def test_saved_subscription_initializes_on_each_start(startup, credentials_beside_code):
    _save_subscription(startup.profile, "selected-profile-token")
    if credentials_beside_code:
        _save_subscription(startup.code, "other-account-token")

    for _ in range(2):
        agent = startup.construct()
        assert agent.llm.is_initialized
        assert agent.vlm.is_initialized
        assert agent.llm._auth_mode == "subscription"
        assert agent.vlm._auth_mode == "subscription"
        assert [call.kwargs["api_key"] for call in startup.sdk.call_args_list] == [
            "selected-profile-token",
            "selected-profile-token",
        ]


@pytest.mark.parametrize("credentials_beside_code", [False, True])
def test_unsigned_profile_stays_deferred(startup, credentials_beside_code):
    if credentials_beside_code:
        _save_subscription(startup.code, "other-account-token")

    agent = startup.construct()
    assert not agent.llm.is_initialized
    assert not agent.vlm.is_initialized
    assert agent.llm.client is None
    assert agent.vlm.client is None
    startup.sdk.assert_not_called()


def test_api_key_profile_still_initializes(startup):
    _save_subscription(startup.code, "other-account-token")

    agent = startup.construct(api_key="test-api-key")
    assert agent.llm.is_initialized
    assert agent.vlm.is_initialized
    assert agent.llm._auth_mode == "api_key"
    assert agent.vlm._auth_mode == "api_key"
    assert [call.kwargs["api_key"] for call in startup.sdk.call_args_list] == [
        "test-api-key",
        "test-api-key",
    ]
