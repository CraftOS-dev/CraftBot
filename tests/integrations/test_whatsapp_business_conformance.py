"""WhatsApp Business bridge-provider conformance + binding/verify tests.

No network: verify_token's HTTP is monkeypatched. What's real is
conformance, the credential binding, identity extraction, and the
token-verification flow mirroring the legacy
WhatsAppBusinessHandler.login().
"""

from __future__ import annotations

import craftos_integrations.providers.whatsapp_business.provider as wab_mod
from craftos_integrations.providers.whatsapp_business import WhatsAppBusinessProvider
from craftos_integrations.providers.whatsapp_business.provider import (
    BoundWhatsAppBusinessClient,
)

from .conformance import ProviderConformance

# Realistic SHAPE, fake values — asdict(WhatsAppBusinessCredential) as
# verify_token builds it after a successful Graph GET /{phone_number_id}.
WAB_CRED = {
    "access_token": "EAAFakeMetaGraphToken1234567890",
    "phone_number_id": "106540352242922",
    "app_secret": "",
    "verify_token": "",
}


class TestWhatsAppBusinessConformance(ProviderConformance):
    provider = WhatsAppBusinessProvider()
    credential_fixtures = [
        WAB_CRED,  # real post-verify shape
        {"access_token": "EAAOldToken", "phone_number_id": ""},  # no identity
        {},  # junk — must not raise
    ]


def test_identity_is_lowercased_phone_number_id():
    provider = WhatsAppBusinessProvider()
    assert provider.identity_of(WAB_CRED) == "106540352242922"
    assert provider.identity_of({"phone_number_id": "  106540352242922  "}) == (
        "106540352242922"
    )
    assert provider.identity_of({"access_token": "EAAX"}) is None
    assert provider.identity_of({"phone_number_id": ""}) is None
    assert provider.identity_of({"phone_number_id": "   "}) is None
    assert provider.identity_of({"phone_number_id": 123}) is None  # non-str tolerated


def test_oauth_spec_declares_token_only():
    provider = WhatsAppBusinessProvider()
    try:
        provider.oauth_spec()
    except NotImplementedError:
        pass
    else:
        raise AssertionError(
            "whatsapp_business must declare token-only via NotImplementedError"
        )
    assert not hasattr(provider, "run_login")  # no OAuth add-account flow


def test_binding_replaces_disk_plumbing():
    client = BoundWhatsAppBusinessClient()
    client.bind_credential(dict(WAB_CRED, extra_junk_key="ignored"), lambda c: None)
    assert client.has_credentials()
    cred = client._load()
    assert cred.access_token == WAB_CRED["access_token"]
    assert cred.phone_number_id == WAB_CRED["phone_number_id"]


def test_build_client_binds_credential():
    client = WhatsAppBusinessProvider().build_client(WAB_CRED, lambda c: None)
    assert isinstance(client, BoundWhatsAppBusinessClient)
    assert client._load().access_token == WAB_CRED["access_token"]
    # The messages URL must route to THIS account's phone number id, not disk.
    assert WAB_CRED["phone_number_id"] in client._messages_url()


def test_bridge_surface_is_empty():
    provider = WhatsAppBusinessProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_make_listener_is_none_for_legacy_client():
    async def emit(event):
        pass

    provider = WhatsAppBusinessProvider()
    client = provider.build_client(WAB_CRED, lambda c: None)
    assert not client.supports_listening  # Cloud API is webhook-push, no poll loop
    assert provider.make_listener(client, None, emit) is None


def test_verify_token_rejects_missing_fields():
    provider = WhatsAppBusinessProvider()
    ok, msg, cred = provider.verify_token({})
    assert not ok and cred is None and "access token" in msg.lower()
    ok, msg, cred = provider.verify_token({"access_token": "EAAX"})
    assert not ok and cred is None and "phone number id" in msg.lower()
    ok, msg, cred = provider.verify_token({"phone_number_id": "123"})
    assert not ok and cred is None and "access token" in msg.lower()


def test_verify_token_success_validates_phone_id(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET" and url.endswith("/106540352242922")
        assert kwargs["headers"]["Authorization"] == "Bearer EAAFakeToken"
        return {
            "ok": True,
            "result": {
                "id": "106540352242922",
                "display_phone_number": "+1 555-0100",
                "verified_name": "Acme LLC",
            },
        }

    monkeypatch.setattr(wab_mod, "http_request", fake_request)
    provider = WhatsAppBusinessProvider()
    ok, msg, cred = provider.verify_token(
        {"access_token": " EAAFakeToken ", "phone_number_id": " 106540352242922 "}
    )
    assert ok, msg
    assert cred["access_token"] == "EAAFakeToken"
    assert cred["phone_number_id"] == "106540352242922"
    assert "Acme LLC" in msg
    assert provider.identity_of(cred) == "106540352242922"


def test_verify_token_rejects_mismatched_phone_id(monkeypatch):
    def fake_request(method, url, **kwargs):
        return {"ok": True, "result": {"id": "999999999999999"}}

    monkeypatch.setattr(wab_mod, "http_request", fake_request)
    ok, msg, cred = WhatsAppBusinessProvider().verify_token(
        {"access_token": "EAAX", "phone_number_id": "106540352242922"}
    )
    assert not ok and cred is None and "mismatch" in msg.lower()


def test_verify_token_auth_failure(monkeypatch):
    def fake_request(method, url, **kwargs):
        return {"error": "HTTP 401", "details": "bad token"}

    monkeypatch.setattr(wab_mod, "http_request", fake_request)
    ok, msg, cred = WhatsAppBusinessProvider().verify_token(
        {"access_token": "EAAbad", "phone_number_id": "106540352242922"}
    )
    assert not ok and cred is None and "Invalid credentials" in msg
