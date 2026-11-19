"""Test Connection must test a connected subscription, not ask for an API key."""

from types import SimpleNamespace

import pytest

from agent_core.core.models import (
    chatgpt_subscription_client,
    connection_tester,
    factory,
)
from agent_core.core.models.provider_config import PROVIDER_CONFIG
from craftos_integrations.llm_oauth import tokens


def signed_in(monkeypatch, provider, bearer=("token", None, {})):
    monkeypatch.setattr(tokens, "has_credential", lambda name: name == provider)

    def get_bearer(name):
        if isinstance(bearer, Exception):
            raise bearer
        return bearer if name == provider else None

    monkeypatch.setattr(tokens, "get_bearer", get_bearer)


@pytest.fixture
def chatgpt_requests(monkeypatch):
    requests = []
    monkeypatch.setattr(
        chatgpt_subscription_client._CompletionsNamespace,
        "create",
        lambda self, **kwargs: requests.append(kwargs),
    )
    return requests


def test_chatgpt_subscription_needs_no_api_key(monkeypatch, chatgpt_requests):
    signed_in(monkeypatch, "openai")
    model = PROVIDER_CONFIG["openai"].subscription_models[0]
    result = connection_tester.test_provider_connection(
        "openai", api_key=None, model=model
    )
    assert result["success"], result
    assert model in result["message"]
    (request,) = chatgpt_requests
    assert request["model"] == model
    # ChatGPT's backend takes the system message as its required instructions.
    assert request["messages"][0]["role"] == "system"


def test_chatgpt_subscription_reports_the_model_it_runs(monkeypatch, chatgpt_requests):
    signed_in(monkeypatch, "openai")
    result = connection_tester.test_provider_connection(
        "openai", model="not-a-subscription-model"
    )
    default = PROVIDER_CONFIG["openai"].subscription_default_model
    assert result["success"] and default in result["message"]
    assert chatgpt_requests[0]["model"] == default


def test_grok_subscription_needs_no_api_key(monkeypatch):
    signed_in(monkeypatch, "grok")
    requests = []
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: requests.append(kwargs))
        )
    )
    monkeypatch.setattr(factory, "_create_openai_client", lambda **kwargs: sdk)
    result = connection_tester.test_provider_connection(
        "grok", api_key=None, model="grok-4.3"
    )
    assert result["success"], result
    assert requests[0]["model"] == "grok-4.3"


def test_expired_subscription_says_to_reconnect(monkeypatch, chatgpt_requests):
    signed_in(
        monkeypatch,
        "openai",
        RuntimeError(
            "openai subscription session expired and refresh failed: 400. "
            "Reconnect from Settings."
        ),
    )
    result = connection_tester.test_provider_connection("openai", model="gpt-6.1-sol")
    assert not result["success"] and "Reconnect" in result["message"]
    assert chatgpt_requests == []


def test_without_a_subscription_the_api_key_is_still_required(monkeypatch):
    monkeypatch.setattr(tokens, "has_credential", lambda name: False)
    result = connection_tester.test_provider_connection(
        "openai", api_key=None, model="gpt-6.1-sol"
    )
    assert not result["success"] and result["error"] == "Missing API key"
