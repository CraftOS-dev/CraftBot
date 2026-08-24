"""Telegram Bot bridge provider — conformance + binding wiring.

No network: getMe and the long-poll fetch are stubbed. What's real is
the binding chain bind_credential → _load → _api_url, the identity
extraction from the bot_id captured at verify time, and the legacy
getUpdates loop running end-to-end through LegacyListenerAdapter with
per-instance offset state.
"""

from __future__ import annotations

import asyncio

import craftos_integrations.providers.telegram_bot.provider as telegram_mod
from craftos_integrations.providers._shared import LegacyListenerAdapter
from craftos_integrations.providers.telegram_bot import TelegramBotProvider
from craftos_integrations.providers.telegram_bot.provider import (
    BoundTelegramBotClient,
)

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Realistic post-verify shape, fake values: the legacy dataclass fields
# plus the provider-level bot_id captured from getMe at verify time.
TELEGRAM_CRED = {
    "bot_token": "123456789:AAFakeTokenFakeTokenFakeToken",
    "bot_username": "CraftBotHelperBot",
    "bot_id": "123456789",
}

# Legacy telegram_bot.json shape — saved by the legacy handler, before
# the bridge captured a bot_id → no identity → LEGACY_IDENTITY in core.
LEGACY_CRED = {
    "bot_token": "123456789:AAFakeTokenFakeTokenFakeToken",
    "bot_username": "CraftBotHelperBot",
}


class TestTelegramBotConformance(ProviderConformance):
    provider = TelegramBotProvider()
    credential_fixtures = [
        TELEGRAM_CRED,
        LEGACY_CRED,  # identity-less shape → None
        {},  # junk
    ]


def test_identity_is_bot_id():
    provider = TelegramBotProvider()
    assert provider.identity_of(TELEGRAM_CRED) == "123456789"
    assert provider.identity_of({"bot_id": "  42  "}) == "42"
    assert provider.identity_of({"bot_id": 987654321}) == "987654321"  # int tolerated
    assert provider.identity_of(LEGACY_CRED) is None  # → LEGACY_IDENTITY in core
    assert provider.identity_of({"bot_id": ""}) is None
    assert provider.identity_of({"bot_id": "   "}) is None
    assert provider.identity_of({"bot_id": None}) is None
    assert provider.identity_of({"bot_id": True}) is None  # bool junk never raises
    assert provider.identity_of({}) is None


def test_token_only_no_oauth_no_run_login():
    provider = TelegramBotProvider()
    try:
        provider.oauth_spec()
        raise AssertionError("oauth_spec must raise NotImplementedError")
    except NotImplementedError:
        pass
    assert not hasattr(provider, "run_login")


def test_refresh_is_none_bot_tokens_do_not_rotate():
    assert run(TelegramBotProvider().refresh(dict(TELEGRAM_CRED))) is None


def test_bridge_surface_is_empty():
    provider = TelegramBotProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_binding_injects_credential_no_disk():
    provider = TelegramBotProvider()
    client = provider.build_client(
        {**TELEGRAM_CRED, "stray_key": "ignored"}, lambda c: None
    )
    assert isinstance(client, BoundTelegramBotClient)
    assert client.has_credentials()  # answered from the injection, not disk
    cred = client._load()
    assert cred.bot_token == TELEGRAM_CRED["bot_token"]
    assert cred.bot_username == "CraftBotHelperBot"
    # bot_id is a provider-level key, filtered before the legacy dataclass
    assert not hasattr(cred, "bot_id")
    assert client._api_url("getMe") == (
        f"https://api.telegram.org/bot{TELEGRAM_CRED['bot_token']}/getMe"
    )

    # Unbound: no legacy fallback — the legacy has_credentials would read
    # telegram_bot.json and even auto-save shared-bot env credentials.
    unbound = BoundTelegramBotClient()
    assert not unbound.has_credentials()
    try:
        unbound._load()
        raise AssertionError("_load must raise before bind_credential()")
    except RuntimeError:
        pass


def test_make_listener_wraps_the_legacy_poll_loop():
    provider = TelegramBotProvider()
    client = provider.build_client(dict(TELEGRAM_CRED), lambda c: None)

    async def emit(event):
        pass

    listener = provider.make_listener(client, None, emit)
    assert isinstance(listener, LegacyListenerAdapter)
    assert client.supports_listening


def test_listener_runs_legacy_poll_loop_per_instance(monkeypatch):
    """End-to-end through LegacyListenerAdapter: catch-up drain advances
    the offset without emitting; the next poll batch is emitted in the
    host payload shape. The offset watermark is per bound instance, so a
    second concurrently-bound bot account is unaffected."""
    provider = TelegramBotProvider()
    client = provider.build_client(dict(TELEGRAM_CRED), lambda c: None)
    other = provider.build_client(dict(TELEGRAM_CRED), lambda c: None)

    events = []
    got_event = asyncio.Event()

    async def emit(event):
        events.append(event)
        got_event.set()

    stale = {"update_id": 6, "message": {"text": "old", "chat": {}, "from": {}}}
    update = {
        "update_id": 7,
        "message": {
            "message_id": 55,
            "date": 1755000000,
            "text": "hello bot",
            "chat": {"id": 1111, "type": "private", "first_name": "Ada"},
            "from": {"id": 1111, "first_name": "Ada", "username": "ada"},
        },
    }

    async def fake_get_me(self):
        return {"ok": True, "result": {"id": 123456789, "username": "CraftBotHelperBot"}}

    calls = {"n": 0}

    async def fake_poll(self):
        calls["n"] += 1
        if calls["n"] == 1:  # catch-up drain — consumed, never emitted
            return {"result": [stale]}
        if calls["n"] == 2:
            return {"result": [update]}
        await asyncio.sleep(3600)  # park until stop() cancels the task
        return {"result": []}

    monkeypatch.setattr(BoundTelegramBotClient, "get_me", fake_get_me)
    monkeypatch.setattr(BoundTelegramBotClient, "_poll_updates", fake_poll)

    async def scenario():
        listener = provider.make_listener(client, None, emit)
        await listener.start()
        assert client.is_listening
        # Double-start guard: supervisor re-invokes start() after clean cycles.
        await listener.start()
        await asyncio.wait_for(got_event.wait(), timeout=5)
        assert listener.cursor() is None
        await listener.stop()
        assert not client.is_listening

    run(scenario())

    assert len(events) == 1
    event = events[0]
    assert event["integrationType"] == "telegram_bot"
    assert event["messageBody"] == "hello bot"
    assert event["contactId"] == "1111"
    assert "Ada" in event["contactName"]
    assert event["channelId"] == "1111"
    assert event["messageId"] == "55"

    # Watermark advanced past the processed update — on this instance only.
    assert client._poll_offset == 8
    assert other._poll_offset == 0


def test_attachment_updates_are_emitted_with_descriptor():
    """Bot API media messages carry no 'text' (user text arrives as
    'caption') — they must still reach the agent as normalized
    PlatformMessage.attachments with the file_id the agent feeds to
    download_file (PR #419 / attachment-reception plan). Service messages
    with neither text nor media stay dropped."""
    provider = TelegramBotProvider()
    client = provider.build_client(dict(TELEGRAM_CRED), lambda c: None)

    got = []

    async def cb(msg):
        got.append(msg)

    client._message_callback = cb

    envelope = {
        "message_id": 56,
        "date": 1755000000,
        "chat": {"id": 1111, "type": "private", "first_name": "Ada"},
        "from": {"id": 1111, "first_name": "Ada"},
    }
    photo = {
        "update_id": 9,
        "message": {
            **envelope,
            "caption": "look at this",
            # PhotoSize list is ordered smallest -> largest
            "photo": [{"file_id": "small"}, {"file_id": "big"}],
        },
    }
    document = {
        "update_id": 10,
        "message": {
            **envelope,
            "document": {
                "file_id": "doc1",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
            },
        },
    }
    service = {"update_id": 11, "message": {**envelope, "new_chat_title": "x"}}

    run(client._process_update(photo))
    run(client._process_update(document))
    run(client._process_update(service))

    assert [m.text for m in got] == ["look at this", ""]
    assert [m.attachments for m in got] == [
        [{"kind": "photo", "id": "big"}],
        [
            {
                "kind": "document",
                "id": "doc1",
                "name": "report.pdf",
                "mime": "application/pdf",
            }
        ],
    ]
    # Offset advanced past every update, including the dropped one.
    assert client._poll_offset == 12


def test_verify_token_mirrors_legacy_login(monkeypatch):
    provider = TelegramBotProvider()
    calls = []

    def fake_call(url, **kwargs):
        calls.append(url)
        return {
            "ok": True,
            "result": {"id": 987654321, "username": "AcmeOpsBot", "is_bot": True},
        }

    monkeypatch.setattr(telegram_mod, "_telegram_call_sync", fake_call)
    ok, message, credential = provider.verify_token({"bot_token": " 987:AAtok "})
    assert ok, message
    assert "AcmeOpsBot" in message
    assert calls == ["https://api.telegram.org/bot987:AAtok/getMe"]
    assert credential == {
        "bot_token": "987:AAtok",
        "bot_username": "AcmeOpsBot",
        "bot_id": "987654321",
    }
    assert provider.identity_of(credential) == "987654321"


def test_verify_token_failure_paths(monkeypatch):
    provider = TelegramBotProvider()

    ok, message, credential = provider.verify_token({})
    assert not ok and credential is None
    assert "BotFather" in message

    ok, message, credential = provider.verify_token({"bot_token": "   "})
    assert not ok and credential is None

    monkeypatch.setattr(
        telegram_mod,
        "_telegram_call_sync",
        lambda url, **k: {"error": "Unauthorized", "details": {"ok": False}},
    )
    ok, message, credential = provider.verify_token({"bot_token": "bad:token"})
    assert not ok and credential is None
    assert "Invalid bot token" in message
