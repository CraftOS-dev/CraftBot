"""Lark family bridge-provider conformance + binding/verify tests.

No network: token minting (``validate_and_mint_token``) and the bot-info
HTTP call are monkeypatched. What's real is conformance for all three
siblings, the shared family value, the credential binding (including the
tenant-token refresh routing through ``persist`` instead of the legacy
credential file), identity extraction, and verify_token mirroring the
legacy handlers' login().
"""

from __future__ import annotations

import asyncio
import time

import craftos_integrations.providers._lark as lark_base
import craftos_integrations.providers.lark.provider as lark_mod
from craftos_integrations.providers._shared import ClientListenerAdapter
from craftos_integrations.providers.lark import LarkProvider
from craftos_integrations.providers.lark.provider import BoundLarkClient
from craftos_integrations.providers.lark_calendar import LarkCalendarProvider
from craftos_integrations.providers.lark_calendar.provider import (
    BoundLarkCalendarClient,
)
from craftos_integrations.providers.lark_drive import LarkDriveProvider
from craftos_integrations.providers.lark_drive.provider import BoundLarkDriveClient

from .conformance import ProviderConformance

# Far-future expiry so the binding never tries to re-mint during tests
# that don't monkeypatch the minting call.
FRESH = 4102444800.0  # 2100-01-01

# Realistic SHAPE, fake values — asdict(LarkCredential) as verify_token
# builds it. All three services share the same shape (one Custom App);
# bot fields are populated only by the messaging integration.
LARK_CRED = {
    "app_id": "cli_a1b2c3d4e5f6g7h8",
    "app_secret": "FakeSecretFakeSecretFakeSec",
    "tenant_access_token": "t-fake-cached-token",
    "token_expires_at": FRESH,
    "bot_name": "CraftBot",
    "bot_open_id": "ou_fake_bot_open_id",
}
CAL_CRED = dict(LARK_CRED, bot_name="", bot_open_id="")
DRIVE_CRED = dict(LARK_CRED, bot_name="", bot_open_id="")

JUNK_FIXTURES = [
    {"app_id": "", "app_secret": "orphan-secret"},  # no identity
    {},  # junk — must not raise
]


class TestLarkConformance(ProviderConformance):
    provider = LarkProvider()
    credential_fixtures = [LARK_CRED] + JUNK_FIXTURES


class TestLarkCalendarConformance(ProviderConformance):
    provider = LarkCalendarProvider()
    credential_fixtures = [CAL_CRED] + JUNK_FIXTURES


class TestLarkDriveConformance(ProviderConformance):
    provider = LarkDriveProvider()
    credential_fixtures = [DRIVE_CRED] + JUNK_FIXTURES


ALL_PROVIDERS = (LarkProvider(), LarkCalendarProvider(), LarkDriveProvider())


def test_family_is_lark_across_all_three():
    assert {p.family for p in ALL_PROVIDERS} == {"lark"}
    assert [p.id for p in ALL_PROVIDERS] == ["lark", "lark_calendar", "lark_drive"]


def test_identity_is_lowercased_app_id():
    for provider in ALL_PROVIDERS:
        assert provider.identity_of(LARK_CRED) == "cli_a1b2c3d4e5f6g7h8"
        assert provider.identity_of({"app_id": "  CLI_UpperCase  "}) == "cli_uppercase"
        assert provider.identity_of({"app_secret": "s"}) is None
        assert provider.identity_of({"app_id": ""}) is None
        assert provider.identity_of({"app_id": "   "}) is None
        assert provider.identity_of({"app_id": 123}) is None  # non-str tolerated


def test_oauth_spec_declares_token_only():
    for provider in ALL_PROVIDERS:
        try:
            provider.oauth_spec()
        except NotImplementedError:
            pass
        else:
            raise AssertionError(
                f"{provider.id} must declare token-only via NotImplementedError"
            )
        assert not hasattr(provider, "run_login")  # no OAuth add-account flow


def test_bridge_surface_is_empty():
    for provider in ALL_PROVIDERS:
        assert provider.operations() == []
        assert provider.guidance() == ""


def test_binding_replaces_disk_plumbing():
    for cls in (BoundLarkClient, BoundLarkCalendarClient, BoundLarkDriveClient):
        client = cls()
        client.bind_credential(
            dict(LARK_CRED, extra_junk_key="ignored"), lambda c: None
        )
        assert client.has_credentials()
        cred = client._load()  # fresh token → no mint, no persist
        assert cred.app_id == LARK_CRED["app_id"]
        assert cred.app_secret == LARK_CRED["app_secret"]
        assert cred.tenant_access_token == LARK_CRED["tenant_access_token"]


def test_build_client_binds_credential():
    for provider, cls in zip(
        ALL_PROVIDERS, (BoundLarkClient, BoundLarkCalendarClient, BoundLarkDriveClient)
    ):
        client = provider.build_client(LARK_CRED, lambda c: None)
        assert isinstance(client, cls)
        assert client._load().app_id == LARK_CRED["app_id"]


def test_token_refresh_routes_through_persist_not_legacy_file(monkeypatch):
    """Expired cached token → the binding re-mints and persists through the
    core; the legacy ``ensure_token``'s save_credential (which writes the
    single-account lark*.json) must never fire, even on the legacy
    ``_headers`` path that calls ``ensure_token`` after us."""
    import craftos_integrations.providers._lark_common as legacy_common

    monkeypatch.setattr(
        lark_base,
        "validate_and_mint_token",
        lambda app_id, app_secret: ("t-new-minted", time.time() + 7200, None),
    )

    def no_disk(*args, **kwargs):
        raise AssertionError("legacy save_credential must not fire for bound clients")

    monkeypatch.setattr(legacy_common, "save_credential", no_disk)

    for provider in ALL_PROVIDERS:
        holder = {}
        client = provider.build_client(
            dict(DRIVE_CRED, tenant_access_token="t-stale", token_expires_at=0.0),
            holder.update,
        )
        headers = client._headers()  # legacy make_headers → ensure_token cache-hit
        assert headers["Authorization"] == "Bearer t-new-minted"
        assert holder["tenant_access_token"] == "t-new-minted"
        assert holder["app_id"] == DRIVE_CRED["app_id"]


def test_provider_refresh_out_of_band(monkeypatch):
    monkeypatch.setattr(
        lark_base,
        "validate_and_mint_token",
        lambda app_id, app_secret: ("t-refreshed", time.time() + 7200, None),
    )
    provider = LarkDriveProvider()
    updated = asyncio.run(provider.refresh(dict(DRIVE_CRED, token_expires_at=0.0)))
    assert updated["tenant_access_token"] == "t-refreshed"
    # Still-fresh cached token → nothing persisted → None (no update).
    assert asyncio.run(provider.refresh(DRIVE_CRED)) is None


def test_provider_refresh_failure_returns_none(monkeypatch):
    monkeypatch.setattr(
        lark_base,
        "validate_and_mint_token",
        lambda app_id, app_secret: (None, 0.0, "Invalid Lark credentials: app deleted"),
    )
    updated = asyncio.run(LarkProvider().refresh(dict(LARK_CRED, token_expires_at=0.0)))
    assert updated is None


def test_listener_support_per_platform():
    async def emit(event):
        pass

    # lark (messaging): legacy WS loop is bridged via the generic adapter.
    lark_provider = LarkProvider()
    chat_client = lark_provider.build_client(LARK_CRED, lambda c: None)
    assert chat_client.supports_listening
    listener = lark_provider.make_listener(chat_client, None, emit)
    assert isinstance(listener, ClientListenerAdapter)

    # calendar / drive: request-response only → no listener.
    for provider in (LarkCalendarProvider(), LarkDriveProvider()):
        client = provider.build_client(CAL_CRED, lambda c: None)
        assert not client.supports_listening
        assert provider.make_listener(client, None, emit) is None


def test_verify_token_missing_fields():
    for provider in ALL_PROVIDERS:
        ok, msg, cred = provider.verify_token({})
        assert not ok and cred is None and "App ID" in msg
        ok, msg, cred = provider.verify_token({"app_id": "cli_x"})
        assert not ok and cred is None and "App Secret" in msg


def test_verify_token_rejected_by_api(monkeypatch):
    monkeypatch.setattr(
        lark_base,
        "validate_and_mint_token",
        lambda app_id, app_secret: (
            None,
            0.0,
            "Invalid Lark credentials: app not found",
        ),
    )
    for provider in ALL_PROVIDERS:
        ok, msg, cred = provider.verify_token(
            {"app_id": "cli_bad", "app_secret": "wrong"}
        )
        assert not ok and cred is None
        assert "Invalid Lark credentials" in msg


def test_verify_token_success_calendar_and_drive(monkeypatch):
    expires = time.time() + 7200
    monkeypatch.setattr(
        lark_base,
        "validate_and_mint_token",
        lambda app_id, app_secret: ("t-minted", expires, None),
    )
    for provider in (LarkCalendarProvider(), LarkDriveProvider()):
        ok, msg, cred = provider.verify_token(
            {"app_id": " CLI_AbC123 ", "app_secret": " s3cret "}
        )
        assert ok, msg
        assert provider.display_name in msg and "CLI_AbC123" in msg
        assert cred["app_id"] == "CLI_AbC123"  # stripped, case preserved
        assert cred["app_secret"] == "s3cret"
        assert cred["tenant_access_token"] == "t-minted"
        assert cred["token_expires_at"] == expires
        assert cred["bot_name"] == "" and cred["bot_open_id"] == ""
        assert provider.identity_of(cred) == "cli_abc123"


def test_verify_token_lark_captures_bot_info(monkeypatch):
    monkeypatch.setattr(
        lark_base,
        "validate_and_mint_token",
        lambda app_id, app_secret: ("t-minted", time.time() + 7200, None),
    )

    def fake_request(method, url, **kwargs):
        assert method == "GET" and url.endswith("/bot/v3/info")
        assert kwargs["headers"]["Authorization"] == "Bearer t-minted"
        return {
            "ok": True,
            "result": {"bot": {"app_name": "CraftBot", "open_id": "ou_bot_1"}},
        }

    monkeypatch.setattr(lark_mod, "http_request", fake_request)
    ok, msg, cred = LarkProvider().verify_token(
        {"app_id": "cli_chat", "app_secret": "s"}
    )
    assert ok, msg
    assert "CraftBot" in msg  # label prefers bot name
    assert cred["bot_name"] == "CraftBot"
    assert cred["bot_open_id"] == "ou_bot_1"
    assert LarkProvider().identity_of(cred) == "cli_chat"


def test_verify_token_lark_tolerates_bot_info_failure(monkeypatch):
    monkeypatch.setattr(
        lark_base,
        "validate_and_mint_token",
        lambda app_id, app_secret: ("t-minted", time.time() + 7200, None),
    )
    monkeypatch.setattr(lark_mod, "http_request", lambda *a, **k: {"error": "HTTP 400"})
    ok, msg, cred = LarkProvider().verify_token(
        {"app_id": "cli_nobot", "app_secret": "s"}
    )
    assert ok, msg  # bot capability not enabled yet — still a valid app
    assert "cli_nobot" in msg
    assert cred["bot_name"] == "" and cred["bot_open_id"] == ""
