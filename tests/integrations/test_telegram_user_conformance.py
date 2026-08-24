"""Telegram User (MTProto) bridge provider — conformance + binding wiring.

No network and no Telethon: the async auth helpers (start_auth /
complete_auth) and the legacy listen loop are stubbed. What's real is
the binding chain bind_credential → _load, the phone-number identity
normalization, the two-phase verify_token state machine over the shared
``_pending_telegram_auth`` dict, and the LegacyListenerAdapter wiring
with per-instance listener state.
"""

from __future__ import annotations

import asyncio

import pytest

import craftos_integrations.integrations.telegram_user._telegram_mtproto as mtproto
from craftos_integrations.config import ConfigStore
from craftos_integrations.integrations.telegram_user import (
    TelegramUserHandler,
    _pending_telegram_auth,
)
from craftos_integrations.providers._shared import LegacyListenerAdapter
from craftos_integrations.providers.telegram_user import TelegramUserProvider
from craftos_integrations.providers.telegram_user.provider import (
    BoundTelegramUserClient,
)

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Realistic post-verify shape, fake values: the legacy dataclass fields
# plus the provider-level telegram_user_id captured at verify time.
TELEGRAM_USER_CRED = {
    "session_string": "1BVtsOKcBu5FAKEfakeFAKEfakeSessionString=",
    "api_id": "12345",
    "api_hash": "0123456789abcdef0123456789abcdef",
    "phone_number": "+923001234567",
    "telegram_user_id": "111222333",
}

# QR-login shape — no phone captured → identity falls back to the user id.
QR_CRED = {
    "session_string": "1BVtsOKcBu5FAKEqrSessionString=",
    "api_id": "12345",
    "api_hash": "0123456789abcdef0123456789abcdef",
    "phone_number": "",
    "telegram_user_id": "111222333",
}


@pytest.fixture(autouse=True)
def _clean_pending():
    _pending_telegram_auth.clear()
    yield
    _pending_telegram_auth.clear()


@pytest.fixture()
def api_config(monkeypatch):
    monkeypatch.setitem(ConfigStore._oauth, "TELEGRAM_API_ID", "12345")
    monkeypatch.setitem(
        ConfigStore._oauth, "TELEGRAM_API_HASH", "0123456789abcdef0123456789abcdef"
    )


class TestTelegramUserConformance(ProviderConformance):
    provider = TelegramUserProvider()
    credential_fixtures = [
        TELEGRAM_USER_CRED,
        QR_CRED,  # phone-less → user-id fallback
        {"session_string": "x"},  # identity-less → None (LEGACY sentinel in core)
        {},  # junk
    ]


def test_identity_is_normalized_phone():
    provider = TelegramUserProvider()
    # digits only, leading zeros stripped — all spellings of one number collapse
    assert provider.identity_of(TELEGRAM_USER_CRED) == "923001234567"
    assert provider.identity_of({"phone_number": "92 300 1234567"}) == "923001234567"
    assert provider.identity_of({"phone_number": "0092-300-1234567"}) == "923001234567"
    assert provider.identity_of({"phone_number": "(92) 300.123.45.67"}) == (
        "923001234567"
    )


def test_identity_falls_back_to_user_id_then_none():
    provider = TelegramUserProvider()
    assert provider.identity_of(QR_CRED) == "111222333"
    assert provider.identity_of({"telegram_user_id": 987654321}) == "987654321"
    assert provider.identity_of({"telegram_user_id": " 42 "}) == "42"
    assert provider.identity_of({"phone_number": "+++"}) is None  # no digits, no id
    assert provider.identity_of({"telegram_user_id": True}) is None  # bool junk
    assert provider.identity_of({"phone_number": None}) is None
    assert provider.identity_of({"session_string": "x"}) is None
    assert provider.identity_of({}) is None


def test_phone_login_no_oauth_no_run_login():
    provider = TelegramUserProvider()
    with pytest.raises(NotImplementedError):
        provider.oauth_spec()
    assert not hasattr(provider, "run_login")


def test_refresh_is_none_sessions_do_not_rotate():
    assert run(TelegramUserProvider().refresh(dict(TELEGRAM_USER_CRED))) is None


def test_bridge_surface_is_empty():
    provider = TelegramUserProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_handler_declares_token_fields():
    """The UI contract the two-phase verify_token rides on: token auth
    with phone required and code/password marked optional (the connect
    flow's missing-field check keys off 'optional' in the label)."""
    assert TelegramUserHandler.auth_type == "token"
    fields = {f["key"]: f for f in TelegramUserHandler.fields}
    assert set(fields) == {"phone_number", "code", "password"}
    assert "optional" not in fields["phone_number"]["label"].lower()
    assert "optional" in fields["code"]["label"].lower()
    assert "optional" in fields["password"]["label"].lower()
    assert fields["password"]["password"] is True
    # CLI flow unchanged — both login subcommands still exposed.
    subs = TelegramUserHandler().subcommands
    assert "login" in subs and "login-qr" in subs


def test_binding_injects_credential_no_disk():
    provider = TelegramUserProvider()
    client = provider.build_client(
        {**TELEGRAM_USER_CRED, "stray_key": "ignored"}, lambda c: None
    )
    assert isinstance(client, BoundTelegramUserClient)
    assert client.has_credentials()  # answered from the injection, not disk
    cred = client._load()
    assert cred.session_string == TELEGRAM_USER_CRED["session_string"]
    assert cred.api_id == "12345"
    assert cred.phone_number == "+923001234567"
    # telegram_user_id is a provider-level key, filtered before the dataclass
    assert not hasattr(cred, "telegram_user_id")

    # Unbound: no legacy fallback — the legacy _load would read
    # telegram_user.json from disk.
    unbound = BoundTelegramUserClient()
    assert not unbound.has_credentials()
    with pytest.raises(RuntimeError):
        unbound._load()


def test_two_bound_clients_are_independent():
    """Per-account isolation: every piece of listener/send state is
    instance-level (no module-global Telethon client or session)."""
    provider = TelegramUserProvider()
    a = provider.build_client(dict(TELEGRAM_USER_CRED), lambda c: None)
    b = provider.build_client(
        {**TELEGRAM_USER_CRED, "phone_number": "+15551234567"}, lambda c: None
    )
    assert a._load() is not b._load()
    assert a._agent_sent_ids is not b._agent_sent_ids
    a._my_user_id = 111
    assert b._my_user_id is None
    assert a._live_client is None and b._live_client is None


# ── verify_token — two-phase phone login ─────────────────────────────


def test_verify_token_requires_phone(api_config):
    ok, message, credential = TelegramUserProvider().verify_token({})
    assert not ok and credential is None
    assert "phone number" in message.lower()


def test_verify_token_requires_api_config(monkeypatch):
    monkeypatch.setitem(ConfigStore._oauth, "TELEGRAM_API_ID", "")
    monkeypatch.setitem(ConfigStore._oauth, "TELEGRAM_API_HASH", "")
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567"}
    )
    assert not ok and credential is None
    assert "TELEGRAM_API_ID" in message

    monkeypatch.setitem(ConfigStore._oauth, "TELEGRAM_API_ID", "not-a-number")
    monkeypatch.setitem(ConfigStore._oauth, "TELEGRAM_API_HASH", "abc")
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567"}
    )
    assert not ok and credential is None
    assert "must be a number" in message


def test_verify_token_phase1_sends_code_and_parks_pending(api_config, monkeypatch):
    calls = {}

    async def fake_start_auth(api_id, api_hash, phone_number):
        calls.update(api_id=api_id, api_hash=api_hash, phone_number=phone_number)
        return {
            "ok": True,
            "result": {
                "phone_code_hash": "hash123",
                "phone_number": phone_number,
                "session_string": "partial-session",
                "status": "code_sent",
            },
        }

    monkeypatch.setattr(mtproto, "start_auth", fake_start_auth)

    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": " +923001234567 ", "code": "", "password": ""}
    )
    assert not ok and credential is None  # False → message surfaces in connect UI
    assert "Verification code sent to +923001234567" in message
    assert "submit again" in message
    assert calls == {
        "api_id": 12345,
        "api_hash": "0123456789abcdef0123456789abcdef",
        "phone_number": "+923001234567",
    }
    # Pending state parked in the SAME dict the CLI flow uses.
    assert _pending_telegram_auth["+923001234567"] == {
        "phone_code_hash": "hash123",
        "session_string": "partial-session",
    }


def test_verify_token_phase1_send_failure(api_config, monkeypatch):
    async def fake_start_auth(**kwargs):
        return {"error": "Too many attempts. Please wait 30 seconds."}

    monkeypatch.setattr(mtproto, "start_auth", fake_start_auth)
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567"}
    )
    assert not ok and credential is None
    assert "Failed to send code" in message
    assert "+923001234567" not in _pending_telegram_auth


def test_verify_token_phase2_success_builds_credential(api_config, monkeypatch):
    _pending_telegram_auth["+923001234567"] = {
        "phone_code_hash": "hash123",
        "session_string": "partial-session",
    }
    seen = {}

    async def fake_complete_auth(**kwargs):
        seen.update(kwargs)
        return {
            "ok": True,
            "result": {
                "session_string": "final-session-string",
                "user_id": 111222333,
                "first_name": "Ahmad",
                "last_name": "A",
                "username": "ahmad",
                "phone": "923001234567",
                "status": "authenticated",
            },
        }

    monkeypatch.setattr(mtproto, "complete_auth", fake_complete_auth)

    provider = TelegramUserProvider()
    ok, message, credential = provider.verify_token(
        {"phone_number": "+923001234567", "code": "54321", "password": ""}
    )
    assert ok, message
    assert "Telegram user connected: Ahmad A (@ahmad)" == message
    assert seen["code"] == "54321"
    assert seen["phone_code_hash"] == "hash123"
    assert seen["pending_session_string"] == "partial-session"
    assert seen["password"] is None  # empty field → no 2FA attempt
    assert credential == {
        "session_string": "final-session-string",
        "api_id": "12345",
        "api_hash": "0123456789abcdef0123456789abcdef",
        "phone_number": "923001234567",
        "telegram_user_id": "111222333",
    }
    assert provider.identity_of(credential) == "923001234567"
    # Pending entry consumed.
    assert "+923001234567" not in _pending_telegram_auth


def test_verify_token_phase2_without_pending(api_config):
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567", "code": "54321"}
    )
    assert not ok and credential is None
    assert "No pending login" in message


def test_verify_token_phase2_invalid_code_keeps_pending(api_config, monkeypatch):
    _pending_telegram_auth["+923001234567"] = {
        "phone_code_hash": "hash123",
        "session_string": "partial-session",
    }

    async def fake_complete_auth(**kwargs):
        return {
            "error": "Invalid verification code.",
            "details": {"status": "invalid_code"},
        }

    monkeypatch.setattr(mtproto, "complete_auth", fake_complete_auth)
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567", "code": "00000"}
    )
    assert not ok and credential is None
    assert "Invalid verification code" in message
    # Retry with a corrected code must still work — pending kept.
    assert "+923001234567" in _pending_telegram_auth


def test_verify_token_phase2_2fa_needed_keeps_pending(api_config, monkeypatch):
    _pending_telegram_auth["+923001234567"] = {
        "phone_code_hash": "hash123",
        "session_string": "partial-session",
    }

    async def fake_complete_auth(**kwargs):
        return {
            "error": "Two-factor authentication is enabled. Please provide password.",
            "details": {"requires_2fa": True, "status": "2fa_required"},
        }

    monkeypatch.setattr(mtproto, "complete_auth", fake_complete_auth)
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567", "code": "54321"}
    )
    assert not ok and credential is None
    assert "2FA" in message and "password" in message.lower()
    assert "+923001234567" in _pending_telegram_auth


def test_verify_token_phase2_expired_clears_pending(api_config, monkeypatch):
    _pending_telegram_auth["+923001234567"] = {
        "phone_code_hash": "hash123",
        "session_string": "partial-session",
    }

    async def fake_complete_auth(**kwargs):
        return {
            "error": "Verification code has expired. Please request a new one.",
            "details": {"status": "code_expired"},
        }

    monkeypatch.setattr(mtproto, "complete_auth", fake_complete_auth)
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567", "code": "54321"}
    )
    assert not ok and credential is None
    assert "Code expired" in message
    assert "+923001234567" not in _pending_telegram_auth  # dead code_hash purged


def test_verify_token_phase2_generic_failure(api_config, monkeypatch):
    _pending_telegram_auth["+923001234567"] = {
        "phone_code_hash": "hash123",
        "session_string": "partial-session",
    }

    async def fake_complete_auth(**kwargs):
        return {
            "error": "Invalid 2FA password.",
            "details": {"status": "invalid_password"},
        }

    monkeypatch.setattr(mtproto, "complete_auth", fake_complete_auth)
    ok, message, credential = TelegramUserProvider().verify_token(
        {"phone_number": "+923001234567", "code": "54321", "password": "wrong"}
    )
    assert not ok and credential is None
    assert "Auth failed" in message and "Invalid 2FA password" in message


# ── listener ─────────────────────────────────────────────────────────


def test_make_listener_wraps_the_legacy_telethon_loop():
    provider = TelegramUserProvider()
    client = provider.build_client(dict(TELEGRAM_USER_CRED), lambda c: None)

    async def emit(event):
        pass

    listener = provider.make_listener(client, None, emit)
    assert isinstance(listener, LegacyListenerAdapter)
    assert client.supports_listening
    assert listener.cursor() is None


def test_listener_start_stop_and_payload_shape(monkeypatch):
    """Adapter drives the bound client's listen loop (stubbed — real one
    needs a live Telethon connection) and the legacy PlatformMessage is
    converted to the host payload shape. Double-start is a no-op."""
    from craftos_integrations import PlatformMessage

    provider = TelegramUserProvider()
    client = provider.build_client(dict(TELEGRAM_USER_CRED), lambda c: None)
    other = provider.build_client(dict(TELEGRAM_USER_CRED), lambda c: None)

    starts = {"n": 0}

    async def fake_start_listening(self, callback):
        starts["n"] += 1
        self._message_callback = callback
        self._listening = True

    async def fake_stop_listening(self):
        self._listening = False
        self._message_callback = None

    monkeypatch.setattr(
        BoundTelegramUserClient, "start_listening", fake_start_listening
    )
    monkeypatch.setattr(BoundTelegramUserClient, "stop_listening", fake_stop_listening)

    events = []

    async def emit(event):
        events.append(event)

    async def scenario():
        listener = provider.make_listener(client, None, emit)
        await listener.start()
        assert client.is_listening
        await listener.start()  # double-start guard: no second spawn
        assert starts["n"] == 1
        # Other account's client is untouched — per-instance state only.
        assert not other.is_listening
        assert other._message_callback is None

        await client._message_callback(
            PlatformMessage(
                platform="telegram_user",
                sender_id="444555",
                sender_name="Ada L",
                text="hello from telegram",
                channel_id="444555",
                channel_name="Ada L",
                message_id="9001",
                raw={"is_self_message": False},
            )
        )
        await listener.stop()
        assert not client.is_listening

    run(scenario())

    assert len(events) == 1
    event = events[0]
    assert event["integrationType"] == "telegram_user"
    assert event["source"] == "Telegram User"
    assert event["messageBody"] == "hello from telegram"
    assert event["contactId"] == "444555"
    assert event["contactName"] == "Ada L"
    assert event["messageId"] == "9001"
    assert event["is_self_message"] is False
