"""Figma provider contract, token verification, OAuth and account isolation."""

import asyncio
import inspect
import time

import pytest

from craftos_integrations.config import ConfigStore
from craftos_integrations.contracts import provider_metadata
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.figma import FigmaProvider
from craftos_integrations.providers.figma import provider as provider_mod
from craftos_integrations.providers.figma import client as client_mod
from craftos_integrations.providers.figma.client import FigmaClient, FigmaConfig

from .conformance import ProviderConformance

PAT = {
    "access_token": "fake_pat",
    "user_id": "123456789012345678",
    "user_email": "user@example.com",
    "auth_kind": "pat",
}


def test_figma_ui_metadata_does_not_offer_unsupported_listening():
    assert provider_metadata(FigmaProvider())["supports_listening"] is False


class TestFigmaConformance(ProviderConformance):
    provider = FigmaProvider()
    credential_fixtures = [
        PAT,
        {**PAT, "auth_kind": "oauth", "refresh_token": "fake_refresh"},
        {},
    ]


@pytest.mark.parametrize("value", [None, [], {}, True, " "])
def test_identity_rejects_unusable_ids(value):
    assert FigmaProvider().identity_of({"user_id": value}) is None


def test_identity_does_not_use_mutable_email():
    assert (
        FigmaProvider().identity_of({**PAT, "user_email": "new@example.com"})
        == PAT["user_id"]
    )
    assert FigmaProvider().identity_of({"user_id": 123}) == "123"
    assert FigmaProvider().identity_of([]) is None


def test_verify_pat_uses_correct_header_and_captures_string_id(monkeypatch):
    def request(method, url, **kwargs):
        assert method == "GET" and url.endswith("/v1/me")
        assert kwargs["headers"] == {"X-Figma-Token": "fake_pat"}
        return {
            "ok": True,
            "result": {
                "id": PAT["user_id"],
                "email": "user@example.com",
                "handle": "User",
            },
        }

    monkeypatch.setattr(provider_mod, "http_request", request)
    ok, message, cred = FigmaProvider().verify_token({"access_token": " fake_pat "})
    assert ok and "user@example.com" in message
    assert cred["user_id"] == PAT["user_id"] and cred["auth_kind"] == "pat"


@pytest.mark.parametrize(
    "response", [{"error": "401", "details": "fake_pat"}, {"ok": True, "result": {}}]
)
def test_verification_refuses_bad_credentials_without_leaking_token(
    monkeypatch, response
):
    monkeypatch.setattr(provider_mod, "http_request", lambda *a, **k: response)
    ok, message, cred = FigmaProvider().verify_token({"access_token": "fake_pat"})
    assert not ok and cred is None and "fake_pat" not in message


def test_empty_token_is_rejected_before_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Empty token must not trigger HTTP.")

    monkeypatch.setattr(provider_mod, "http_request", fail)
    assert FigmaProvider().verify_token({})[0] is False


def test_oauth_visibility_depends_on_configuration(monkeypatch):
    monkeypatch.setattr(ConfigStore, "_oauth", {})
    monkeypatch.delenv("FIGMA_CLIENT_ID", raising=False)
    monkeypatch.delenv("FIGMA_CLIENT_SECRET", raising=False)
    provider = FigmaProvider()
    assert provider.auth_type == "token"
    assert "not configured" in asyncio.run(provider.run_login())[2]
    monkeypatch.setattr(
        ConfigStore,
        "_oauth",
        {"FIGMA_CLIENT_ID": "client", "FIGMA_CLIENT_SECRET": "secret"},
    )
    assert provider.auth_type == "both"


def test_oauth_uses_pkce_basic_auth_and_stable_identity(monkeypatch):
    monkeypatch.setattr(
        ConfigStore,
        "_oauth",
        {"FIGMA_CLIENT_ID": "client", "FIGMA_CLIENT_SECRET": "secret"},
    )
    captured = {}

    class FakeFlow:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self):
            return {
                "access_token": "fake_access",
                "refresh_token": "fake_refresh",
                "expires_in": 3600,
                "userinfo": {"id": PAT["user_id"], "email": "user@example.com"},
            }

    monkeypatch.setattr(provider_mod, "OAuthFlow", FakeFlow)
    identity, cred, _ = asyncio.run(FigmaProvider().run_login())
    assert identity == PAT["user_id"] and cred["auth_kind"] == "oauth"
    assert cred["token_expiry"] > time.time()
    assert captured["use_pkce"] and captured["token_auth_basic"]
    assert "folders:read" not in captured["scopes"].split()
    assert "client_secret" not in cred


def test_operations_match_client_signatures_and_lifecycle_flags():
    operations = FigmaProvider().operations()
    assert len(operations) == 43
    from craftos_integrations.providers.figma import operations as ops_mod

    captured = []
    original = ops_mod.client_op

    def capture(name, method, **kwargs):
        captured.append((method, kwargs["input_schema"]))
        return original(name, method, **kwargs)

    from unittest.mock import patch

    with patch.object(ops_mod, "client_op", capture):
        ops_mod.build_operations()
    for method, schema in captured:
        signature = inspect.signature(getattr(FigmaClient, method))
        assert set(schema) <= set(signature.parameters), method
    names = {op.name: op for op in operations}
    assert not names["post_figma_comment"].parallelizable
    assert names["post_figma_comment"].destructive
    assert names["reply_figma_comment"].destructive
    assert names["delete_figma_comment"].destructive
    assert names["delete_figma_comment_reaction"].destructive


def test_two_accounts_route_separately_and_keep_cache_isolated(tmp_path, monkeypatch):
    system = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[FigmaProvider()]
    )
    system.store_credential(
        "figma", "1", {**PAT, "user_id": "1", "access_token": "first"}
    )
    system.store_credential(
        "figma", "2", {**PAT, "user_id": "2", "access_token": "second"}
    )
    system.set_alias("figma", "2", "work")

    monkeypatch.setattr(client_mod, "load_config", lambda *a: FigmaConfig())
    calls = []

    async def current_user(method, url, **kwargs):
        token = kwargs["headers"]["X-Figma-Token"]
        calls.append(token)
        return {"ok": True, "result": {"id": token}}

    monkeypatch.setattr(client_mod, "arequest", current_user)

    async def run():
        primary = await system.execute("figma", "get_figma_current_user", {})
        work = await system.execute(
            "figma", "get_figma_current_user", {}, account="work"
        )
        cached_primary = await system.execute("figma", "get_figma_current_user", {})
        cached_work = await system.execute(
            "figma", "get_figma_current_user", {}, account="work"
        )
        assert primary == cached_primary
        assert work == cached_work
        return primary, work

    primary, work = asyncio.run(run())
    assert primary["result"]["id"] == "first"
    assert work["result"]["id"] == "second"
    assert calls == ["first", "second"]
    assert system.client_for("figma", "1") is not system.client_for("figma", "2")


def test_pat_has_no_refresh_or_listener():
    provider = FigmaProvider()
    assert asyncio.run(provider.refresh(PAT)) is None
    assert (
        provider.make_listener(provider.build_client(PAT, lambda x: None), None, None)
        is None
    )
