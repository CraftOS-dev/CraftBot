"""PR 5 — provider listeners.

Per real listener (gmail / outlook / slack), with the client's HTTP layer
monkeypatched: start → synthetic incoming event → ``emit`` receives the
exact payload shape the legacy ``ExternalCommsManager`` built from
``PlatformMessage``; ``cursor()`` round-trips into a fresh listener that
does NOT re-emit the same event; ``stop()`` terminates cleanly. Plus: all
ten providers accept the 3-arg ``make_listener``.

No pytest-asyncio in this repo — async paths are driven with asyncio.run.
"""

from __future__ import annotations

import asyncio
import time

import craftos_integrations.integrations.gmail as gmail_mod
import craftos_integrations.integrations.outlook as outlook_mod
import craftos_integrations.integrations.slack as slack_mod
import craftos_integrations.providers.slack.listener as slack_listener_mod
from craftos_integrations.providers import default_providers
from craftos_integrations.providers.gmail.provider import GmailProvider
from craftos_integrations.providers.outlook.provider import OutlookProvider
from craftos_integrations.providers.slack.provider import SlackProvider


def run(coro):
    return asyncio.run(coro)


async def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


async def settle():
    """Let in-flight callbacks finish after a fake API call was observed."""
    await asyncio.sleep(0.05)


def collector():
    events = []

    async def emit(event):
        events.append(event)

    return events, emit


# ════════════════════════════════════════════════════════════════════════
# Gmail
# ════════════════════════════════════════════════════════════════════════

GMAIL_CRED = {
    "access_token": "tok",
    "refresh_token": "ref",
    "token_expiry": time.time() + 3600,
    "client_id": "cid",
    "client_secret": "cs",
    "email": "me@x.com",
}

GMAIL_MESSAGE = {
    "id": "m1",
    "threadId": "t1",
    "snippet": "hello there",
    "payload": {
        "headers": [
            {"name": "From", "value": "Alice <alice@x.com>"},
            {"name": "Subject", "value": "Hi"},
            {"name": "Date", "value": "Tue, 11 Aug 2026 10:00:00 +0000"},
        ]
    },
}


class FakeGmailAPI:
    """Serves profile / history.list / messages.get like the Gmail REST API."""

    def __init__(self):
        self.profile_calls = 0
        self.history_calls = 0
        self.history_response = {
            "historyId": "101",
            "history": [
                {"messagesAdded": [{"message": {"id": "m1", "labelIds": ["INBOX"]}}]}
            ],
        }

    async def arequest(self, method, url, **kwargs):
        if url.endswith("/users/me/profile"):
            self.profile_calls += 1
            return {"result": {"emailAddress": "me@x.com", "historyId": "100"}}
        if url.endswith("/users/me/history"):
            self.history_calls += 1
            return {"result": self.history_response}
        if "/users/me/messages/" in url:
            assert url.rsplit("/", 1)[1] == "m1"
            return {"result": GMAIL_MESSAGE}
        raise AssertionError(f"unexpected URL {url}")


def _gmail_setup(monkeypatch):
    fake = FakeGmailAPI()
    monkeypatch.setattr(gmail_mod, "arequest", fake.arequest)
    # Config file may not exist in the test env; serve the default (toggle on).
    monkeypatch.setattr(gmail_mod, "load_config", lambda *a, **k: gmail_mod.GmailConfig())
    provider = GmailProvider()
    client = provider.build_client(dict(GMAIL_CRED), lambda d: None)
    return fake, provider, client


class TestGmailListener:
    def test_start_emits_payload_and_cursor(self, monkeypatch):
        fake, provider, client = _gmail_setup(monkeypatch)
        events, emit = collector()
        listener = provider.make_listener(client, None, emit)
        assert listener.poll_interval == gmail_mod.POLL_INTERVAL

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: events)
            cursor = listener.cursor()
            await listener.stop()
            return cursor

        cursor = run(scenario())

        assert fake.profile_calls == 1  # fresh start baselines from profile
        assert events == [
            {
                "source": "Gmail",
                "integrationType": "gmail",
                "contactId": "alice@x.com",
                "contactName": "Alice",
                "messageBody": "Subject: Hi\nhello there",
                "channelId": "t1",
                "channelName": "",
                "messageId": "m1",
                "is_self_message": False,
                "raw": GMAIL_MESSAGE,
            }
        ]
        assert cursor == {"history_id": "101", "seen_ids": ["m1"]}
        assert client._poll_task is None  # stop() tore the task down

    def test_cursor_resume_does_not_reemit(self, monkeypatch):
        fake, provider, client = _gmail_setup(monkeypatch)
        events, emit = collector()
        cursor = {"history_id": "101", "seen_ids": ["m1"]}
        listener = provider.make_listener(client, dict(cursor), emit)

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: fake.history_calls >= 1)
            await settle()
            await listener.stop()

        run(scenario())

        assert events == []  # m1 replayed by history.list but deduped
        assert fake.profile_calls == 0  # resume never re-baselines
        assert listener.cursor() == cursor  # round-trip stable

    def test_self_messages_are_dropped(self, monkeypatch):
        fake, provider, client = _gmail_setup(monkeypatch)
        monkeypatch.setitem(
            GMAIL_MESSAGE["payload"]["headers"][0], "value", "Me <me@x.com>"
        )
        events, emit = collector()
        listener = provider.make_listener(client, None, emit)

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: fake.history_calls >= 1)
            await settle()
            await listener.stop()

        run(scenario())
        assert events == []


# ════════════════════════════════════════════════════════════════════════
# Outlook
# ════════════════════════════════════════════════════════════════════════

OUTLOOK_CRED = {
    "access_token": "tok",
    "refresh_token": "ref",
    "token_expiry": time.time() + 3600,
    "client_id": "cid",
    "email": "me@o.com",
}

OUTLOOK_MESSAGE = {
    "id": "om1",
    "from": {"emailAddress": {"address": "bob@x.com", "name": "Bob"}},
    "subject": "Yo",
    "bodyPreview": "preview text",
    "receivedDateTime": "2026-08-12T10:00:00Z",
    "conversationId": "conv1",
}


class FakeGraphAPI:
    def __init__(self):
        self.profile_calls = 0
        self.messages_calls = 0
        self.last_filter = None

    async def arequest(self, method, url, **kwargs):
        if url.endswith("/me"):
            self.profile_calls += 1
            return {"result": {"mail": "me@o.com"}}
        if url.endswith("/me/messages"):
            self.messages_calls += 1
            self.last_filter = (kwargs.get("params") or {}).get("$filter")
            return {"result": {"value": [OUTLOOK_MESSAGE]}}
        raise AssertionError(f"unexpected URL {url}")


def _outlook_setup(monkeypatch):
    fake = FakeGraphAPI()
    monkeypatch.setattr(outlook_mod, "arequest", fake.arequest)
    provider = OutlookProvider()
    client = provider.build_client(dict(OUTLOOK_CRED), lambda d: None)
    return fake, provider, client


class TestOutlookListener:
    def test_start_emits_payload_and_cursor(self, monkeypatch):
        fake, provider, client = _outlook_setup(monkeypatch)
        events, emit = collector()
        listener = provider.make_listener(client, None, emit)
        assert listener.poll_interval == outlook_mod.POLL_INTERVAL

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: events)
            cursor = listener.cursor()
            await listener.stop()
            return cursor

        cursor = run(scenario())

        assert fake.profile_calls == 1
        assert events == [
            {
                "source": "Outlook",
                "integrationType": "outlook",
                "contactId": "bob@x.com",
                "contactName": "Bob",
                "messageBody": "Subject: Yo\npreview text",
                "channelId": "conv1",
                "channelName": "",
                "messageId": "om1",
                "is_self_message": False,
                "raw": OUTLOOK_MESSAGE,
            }
        ]
        # Watermark advanced to the newest receivedDateTime; dedup ids kept.
        assert cursor == {
            "last_poll_time": "2026-08-12T10:00:00Z",
            "seen_ids": ["om1"],
        }
        assert client._poll_task is None

    def test_cursor_resume_does_not_reemit(self, monkeypatch):
        fake, provider, client = _outlook_setup(monkeypatch)
        events, emit = collector()
        cursor = {"last_poll_time": "2026-08-12T10:00:00Z", "seen_ids": ["om1"]}
        listener = provider.make_listener(client, dict(cursor), emit)

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: fake.messages_calls >= 1)
            await settle()
            await listener.stop()

        run(scenario())

        assert events == []  # om1 in the overlap window but deduped
        # The Graph query resumed from the persisted watermark, not "now".
        assert fake.last_filter == "receivedDateTime ge 2026-08-12T10:00:00Z"
        assert listener.cursor() == cursor


# ════════════════════════════════════════════════════════════════════════
# Slack
# ════════════════════════════════════════════════════════════════════════

SLACK_CRED = {"bot_token": "xoxb-1", "workspace_id": "T1", "team_name": "Team"}


class FakeSlackAPI:
    """Routes _slack_acall by endpoint; history honors the ``oldest`` ts
    watermark exclusively, like conversations.history does by default."""

    def __init__(self, messages):
        self.messages = messages
        self.auth_calls = 0
        self.list_calls = 0
        self.history_calls = 0

    async def acall(self, method, path, headers, **kw):
        params = kw.get("params") or {}
        if path == "auth.test":
            self.auth_calls += 1
            return {"ok": True, "user_id": "UBOT"}
        if path == "conversations.list":
            self.list_calls += 1
            return {
                "channels": [{"id": "C1", "is_member": True}],
                "response_metadata": {},
            }
        if path == "conversations.history":
            self.history_calls += 1
            oldest = float(params.get("oldest", "0"))
            return {
                "messages": [
                    m for m in self.messages if float(m["ts"]) > oldest
                ]
            }
        raise AssertionError(f"unexpected Slack call {path}")


def _slack_setup(monkeypatch, messages):
    fake = FakeSlackAPI(messages)
    # Both the legacy client module and the listener module bind the name.
    monkeypatch.setattr(slack_mod, "_slack_acall", fake.acall)
    monkeypatch.setattr(slack_listener_mod, "_slack_acall", fake.acall)
    provider = SlackProvider()
    client = provider.build_client(dict(SLACK_CRED), lambda d: None)
    monkeypatch.setattr(
        client,
        "get_user_info",
        lambda user_id: {"ok": True, "user": {"profile": {"display_name": "Zed"}}},
    )
    return fake, provider, client


class TestSlackListener:
    def test_start_emits_payload_and_cursor(self, monkeypatch):
        msg_ts = f"{time.time() + 10:.6f}"  # after the catch-up watermark
        message = {"ts": msg_ts, "user": "U2", "text": "hello"}
        fake, provider, client = _slack_setup(monkeypatch, [message])
        events, emit = collector()
        listener = provider.make_listener(client, None, emit)
        assert listener.poll_interval == slack_mod.POLL_INTERVAL

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: events)
            cursor = listener.cursor()
            await listener.stop()
            return cursor

        cursor = run(scenario())

        assert fake.auth_calls == 1
        assert client._bot_user_id == "UBOT"
        assert events == [
            {
                "source": "Slack",
                "integrationType": "slack",
                "contactId": "U2",
                "contactName": "Zed",
                "messageBody": "hello",
                "channelId": "C1",
                "channelName": "",
                "messageId": msg_ts,
                "is_self_message": False,
                "raw": message,
            }
        ]
        assert cursor == {"last_timestamps": {"C1": msg_ts}}
        assert not client._listening  # stop() flagged the loop off

    def test_cursor_resume_does_not_reemit(self, monkeypatch):
        msg_ts = f"{time.time() + 10:.6f}"
        message = {"ts": msg_ts, "user": "U2", "text": "hello"}
        fake, provider, client = _slack_setup(monkeypatch, [message])
        events, emit = collector()
        cursor = {"last_timestamps": {"C1": msg_ts}}
        listener = provider.make_listener(client, dict(cursor), emit)

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: fake.history_calls >= 1)
            await settle()
            await listener.stop()

        run(scenario())

        assert events == []  # ts watermark excludes the already-seen message
        assert listener.cursor() == cursor

    def test_bot_and_self_messages_are_dropped(self, monkeypatch):
        future = time.time() + 10
        messages = [
            {"ts": f"{future:.6f}", "user": "UBOT", "text": "own message"},
            {"ts": f"{future + 1:.6f}", "bot_id": "B9", "text": "bot message"},
            {"ts": f"{future + 2:.6f}", "user": "U3", "subtype": "channel_join"},
        ]
        fake, provider, client = _slack_setup(monkeypatch, messages)
        events, emit = collector()
        listener = provider.make_listener(client, None, emit)

        async def scenario():
            await listener.start()
            assert await wait_until(lambda: fake.history_calls >= 1)
            await settle()
            await listener.stop()

        run(scenario())
        assert events == []


# ════════════════════════════════════════════════════════════════════════
# All providers: the 3-arg contract
# ════════════════════════════════════════════════════════════════════════


def test_every_provider_accepts_three_arg_make_listener():
    async def emit(event):  # no-op
        pass

    providers = default_providers()
    # 10 full ports + 5 wave-1 + 6 wave-2 + 2 wave-3 bridges
    assert len(providers) == 23
    with_listeners = set()
    for provider in providers:
        listener = provider.make_listener(object(), None, emit)
        if listener is not None:
            with_listeners.add(provider.id)
            assert hasattr(listener, "start")
            assert hasattr(listener, "stop")
            assert hasattr(listener, "cursor")
            # poll_interval is optional (stagger hint): hand-written
            # listeners expose theirs; LegacyListenerAdapter does not.
            interval = getattr(listener, "poll_interval", None)
            if interval is not None:
                assert interval > 0
    # Bridged platforms reuse their legacy listen loops via
    # LegacyListenerAdapter: github/jira/twitter watch-polls, telegram_bot
    # getUpdates long-poll, discord gateway, lark websocket.
    assert with_listeners == {
        "gmail",
        "outlook",
        "slack",
        "github",
        "jira",
        "telegram_bot",
        "discord",
        "twitter",
        "lark",
        "telegram_user",
        "whatsapp_web",
    }
