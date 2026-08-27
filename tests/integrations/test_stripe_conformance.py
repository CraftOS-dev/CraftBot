"""Stripe bridge-provider conformance + binding/verify tests.

No network: verify_token's HTTP is monkeypatched. What's real is
conformance, the credential binding, identity extraction, and the
token-verification flow mirroring the legacy StripeHandler.login().
"""

from __future__ import annotations

import craftos_integrations.providers.stripe.provider as stripe_mod
from craftos_integrations.providers.stripe import StripeProvider
from craftos_integrations.providers.stripe.provider import BoundStripeClient

from .conformance import ProviderConformance

# Realistic SHAPE, fake values — asdict(StripeCredential) as verify_token
# builds it after a successful /v1/account read.
STRIPE_CRED = {
    "api_key": "rk_test_51FakeKeyFakeKeyFakeKey",
    "account_id": "acct_1AbCdEfGhIjKlMnO",
    "business_name": "Acme LLC",
    "livemode": False,
    "key_kind": "restricted",
}


class TestStripeConformance(ProviderConformance):
    provider = StripeProvider()
    credential_fixtures = [
        STRIPE_CRED,  # real post-verify shape (account id captured)
        # restricted key that couldn't read /v1/account → no identity
        {"api_key": "rk_test_scoped", "account_id": "", "business_name": ""},
        {},  # junk — must not raise
    ]


def test_identity_is_lowercased_account_id():
    provider = StripeProvider()
    assert provider.identity_of(STRIPE_CRED) == "acct_1abcdefghijklmno"
    assert provider.identity_of({"account_id": "  ACCT_X  "}) == "acct_x"
    assert provider.identity_of({"api_key": "sk_test_old"}) is None
    assert provider.identity_of({"account_id": ""}) is None
    assert provider.identity_of({"account_id": "   "}) is None
    assert provider.identity_of({"account_id": 123}) is None  # non-str tolerated


def test_oauth_spec_declares_token_only():
    provider = StripeProvider()
    try:
        provider.oauth_spec()
    except NotImplementedError:
        pass
    else:
        raise AssertionError("stripe must declare token-only via NotImplementedError")
    assert not hasattr(provider, "run_login")  # no OAuth add-account flow


def test_binding_replaces_disk_plumbing():
    client = BoundStripeClient()
    client.bind_credential(dict(STRIPE_CRED, extra_junk_key="ignored"), lambda c: None)
    assert client.has_credentials()
    cred = client._load()
    assert cred.api_key == STRIPE_CRED["api_key"]
    assert cred.account_id == STRIPE_CRED["account_id"]
    assert cred.key_kind == "restricted"


def test_build_client_binds_credential():
    client = StripeProvider().build_client(STRIPE_CRED, lambda c: None)
    assert isinstance(client, BoundStripeClient)
    assert client._load().api_key == STRIPE_CRED["api_key"]


def test_bridge_surface_is_empty():
    provider = StripeProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_make_listener_is_none_for_legacy_client():
    async def emit(event):
        pass

    provider = StripeProvider()
    client = provider.build_client(STRIPE_CRED, lambda c: None)
    assert not client.supports_listening
    assert provider.make_listener(client, None, emit) is None


def test_verify_token_rejects_bad_keys():
    provider = StripeProvider()
    ok, msg, cred = provider.verify_token({})
    assert not ok and cred is None
    ok, msg, cred = provider.verify_token({"api_key": "pk_test_x"})
    assert not ok and "publishable" in msg and cred is None
    ok, msg, cred = provider.verify_token({"api_key": "not_a_key"})
    assert not ok and cred is None


def test_verify_token_success_captures_account_id(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET" and url.endswith("/account")
        assert kwargs["headers"]["Authorization"] == "Bearer sk_test_fake"
        return {
            "ok": True,
            "result": {
                "id": "acct_1XYZ",
                "business_profile": {"name": "Acme LLC"},
            },
        }

    monkeypatch.setattr(stripe_mod, "http_request", fake_request)
    provider = StripeProvider()
    ok, msg, cred = provider.verify_token({"api_key": " sk_test_fake "})
    assert ok, msg
    assert cred["api_key"] == "sk_test_fake"
    assert cred["account_id"] == "acct_1XYZ"
    assert cred["business_name"] == "Acme LLC"
    assert cred["livemode"] is False and cred["key_kind"] == "secret"
    assert provider.identity_of(cred) == "acct_1xyz"


def test_verify_token_restricted_key_falls_back_to_balance(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        if url.endswith("/account"):
            return {"error": "HTTP 401", "details": "scope"}
        assert url.endswith("/balance")
        return {"ok": True, "result": {"available": []}}

    monkeypatch.setattr(stripe_mod, "http_request", fake_request)
    ok, msg, cred = StripeProvider().verify_token({"api_key": "rk_live_scoped"})
    assert ok, msg
    assert len(calls) == 2
    assert cred["account_id"] == ""  # identity unknown → legacy account slot
    assert cred["livemode"] is True and cred["key_kind"] == "restricted"
    assert StripeProvider().identity_of(cred) is None


def test_verify_token_auth_failure(monkeypatch):
    def fake_request(method, url, **kwargs):
        return {"error": "HTTP 401", "details": "bad key"}

    monkeypatch.setattr(stripe_mod, "http_request", fake_request)
    ok, msg, cred = StripeProvider().verify_token({"api_key": "sk_test_bad"})
    assert not ok and cred is None and "auth failed" in msg
