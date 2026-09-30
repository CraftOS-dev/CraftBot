"""Inbound message fidelity (issue #444).

Listeners emit plain, decoded text built from the real message body, cap
it with ``clip`` and declare the cut as ``PlatformMessage.truncated``; the
host marks the cut for the chat and hands the agent the facts to fetch the
rest (docs/plans/inbound-message-fidelity-plan.md).

No pytest-asyncio in this repo — async paths are driven with asyncio.run.
"""

from __future__ import annotations

import asyncio
import base64
import time
from types import SimpleNamespace

import pytest

import craftos_integrations.providers.gmail.client as gmail_mod
import craftos_integrations.providers.outlook.client as outlook_mod
from craftos_integrations.base import PlatformMessage
from craftos_integrations.helpers import clip
from craftos_integrations.providers._shared import platform_message_payload
from craftos_integrations.providers.gmail.client import clean_snippet
from craftos_integrations.providers.gmail.provider import GmailProvider
from craftos_integrations.providers.outlook.provider import OutlookProvider
from craftos_integrations.providers.slack.formatting import to_plain_text


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _collect_callback():
    received = []

    async def callback(msg):
        received.append(msg)

    return received, callback


# ── clip ────────────────────────────────────────────────────────────────


def test_clip_leaves_short_text_alone():
    assert clip("short", 10) == ("short", False)
    assert clip("exactly10!", 10) == ("exactly10!", False)


def test_clip_cuts_on_word_boundary():
    text, cut = clip("the quick brown fox jumps", 18)
    assert cut is True
    assert text == "the quick brown"


def test_clip_hard_cuts_without_nearby_boundary():
    text, cut = clip("a " + "x" * 50, 20)
    assert cut is True
    assert text == ("a " + "x" * 50)[:20]


# ── Gmail ───────────────────────────────────────────────────────────────


def test_gmail_clean_snippet_decodes_entities():
    assert clean_snippet("that&#39;s Tom &amp; Jerry") == "that's Tom & Jerry"


def _gmail_client(monkeypatch, payload):
    message = {"id": "m1", "threadId": "t1", "payload": payload}

    async def fake_arequest(method, url, **kwargs):
        assert "/users/me/messages/m1" in url
        return {"result": message}

    monkeypatch.setattr(gmail_mod, "arequest", fake_arequest)
    monkeypatch.setattr(
        gmail_mod, "load_config", lambda *a, **k: gmail_mod.GmailConfig()
    )
    client = GmailProvider().build_client(
        {
            "access_token": "tok",
            "refresh_token": "ref",
            "token_expiry": time.time() + 3600,
            "client_id": "cid",
            "client_secret": "cs",
            "email": "me@x.com",
        },
        lambda d: None,
    )
    received, client._message_callback = _collect_callback()
    asyncio.run(client._fetch_and_dispatch("m1"))
    assert len(received) == 1
    return received[0]


_GMAIL_HEADERS = [
    {"name": "From", "value": "Joe <joe@posthog.com>"},
    {"name": "Subject", "value": "Top 10 users"},
]


def test_gmail_listener_forwards_real_body_not_snippet(monkeypatch):
    # The #444 email: an apostrophe that the escaped snippet leaked as &#39;.
    body = "Joe here with an email that's automated. You're probably using Stripe."
    msg = _gmail_client(
        monkeypatch,
        {
            "headers": _GMAIL_HEADERS,
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64(body)}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>x</p>")}},
            ],
        },
    )
    assert msg.text == f"Subject: Top 10 users\n{body}"
    assert msg.truncated is False


def test_gmail_listener_converts_html_only_mail(monkeypatch):
    msg = _gmail_client(
        monkeypatch,
        {
            "headers": _GMAIL_HEADERS,
            "mimeType": "text/html",
            "body": {"data": _b64("<p>Tom &amp; Jerry</p>")},
        },
    )
    assert msg.text == "Subject: Top 10 users\nTom & Jerry"


def test_gmail_listener_caps_long_body_and_flags_it(monkeypatch):
    long_body = "word " * 1000  # 5000 chars
    msg = _gmail_client(
        monkeypatch,
        {
            "headers": _GMAIL_HEADERS,
            "parts": [{"mimeType": "text/plain", "body": {"data": _b64(long_body)}}],
        },
    )
    assert msg.truncated is True
    body = msg.text.split("\n", 1)[1]
    assert len(body) <= gmail_mod._INBOUND_BODY_CHARS


# ── Outlook ─────────────────────────────────────────────────────────────


def _outlook_dispatch(content):
    client = OutlookProvider().build_client(
        {
            "access_token": "tok",
            "refresh_token": "ref",
            "token_expiry": time.time() + 3600,
            "client_id": "cid",
            "email": "me@o.com",
        },
        lambda d: None,
    )
    received, client._message_callback = _collect_callback()
    msg = {
        "id": "om1",
        "from": {"emailAddress": {"address": "bob@x.com", "name": "Bob"}},
        "subject": "Yo",
        "body": {"contentType": "text", "content": content},
        "receivedDateTime": "2026-08-12T10:00:00Z",
    }
    asyncio.run(client._dispatch_message(msg))
    assert len(received) == 1
    return received[0]


def test_outlook_forwards_full_text_body():
    msg = _outlook_dispatch("x" * 300)  # past the old 255-char bodyPreview
    assert msg.text == "Subject: Yo\n" + "x" * 300
    assert msg.truncated is False


def test_outlook_caps_long_body_and_flags_it():
    msg = _outlook_dispatch("word " * 1000)
    assert msg.truncated is True
    assert len(msg.text.split("\n", 1)[1]) <= outlook_mod._INBOUND_BODY_CHARS


# ── Slack ───────────────────────────────────────────────────────────────

_NAMES = {"U1": "Ada"}


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("hi <@U1>", "hi @Ada"),
        ("hi <@U9>", "hi @U9"),  # unresolvable → id
        ("hi <@U9|bob>", "hi @bob"),  # unresolvable → label
        ("see <#C1|general>", "see #general"),
        ("see <#C1>", "see #C1"),
        ("<https://x.test|docs>", "docs (https://x.test)"),
        ("<https://x.test>", "https://x.test"),
        ("<mailto:a@b.co|a@b.co>", "a@b.co"),
        ("<!here> <!channel> <!everyone>", "@here @channel @everyone"),
        ("<!here|here>", "@here"),
        ("<!subteam^S1|@devs>", "@devs"),
        ("<!date^1700000000^{date}|Nov 14>", "Nov 14"),
        ("Tom &amp; Jerry &lt;3", "Tom & Jerry <3"),
        # A literal "<@U1>" the user typed arrives escaped and must stay text.
        ("&lt;@U1&gt;", "<@U1>"),
        ("", ""),
    ],
)
def test_slack_to_plain_text(raw, expected):
    assert to_plain_text(raw, lambda uid: _NAMES.get(uid, "")) == expected


def test_slack_to_plain_text_survives_resolver_error():
    def boom(uid):
        raise RuntimeError("api down")

    assert to_plain_text("hi <@U1>", boom) == "hi @U1"


def test_slack_display_name_is_memoized():
    from craftos_integrations.providers.slack.client import SlackClient

    client = SlackClient()
    calls = []

    def fake_user_info(uid):
        calls.append(uid)
        return {"ok": True, "user": {"profile": {"display_name": "Ada"}}}

    client.get_user_info = fake_user_info
    assert client._display_name("U1") == "Ada"
    assert client._display_name("U1") == "Ada"
    assert calls == ["U1"]


def test_slack_display_name_does_not_cache_failures():
    from craftos_integrations.providers.slack.client import SlackClient

    client = SlackClient()
    calls = []

    def flaky(uid):
        calls.append(uid)
        return {"ok": False}

    client.get_user_info = flaky
    assert client._display_name("U1") == ""
    assert client._display_name("U1") == ""
    assert len(calls) == 2


# ── Twitter ─────────────────────────────────────────────────────────────


def test_twitter_decodes_text_before_tag_match():
    from craftos_integrations.providers.twitter.client import (
        TwitterClient,
        TwitterConfig,
    )

    client = TwitterClient()
    client._config = lambda: TwitterConfig(watch_tag="R&D")
    received, client._message_callback = _collect_callback()
    tweet = {"id": "1", "author_id": "a1", "text": "R&amp;D check this &lt;now&gt;"}
    users = {"a1": {"username": "ada", "name": "Ada"}}
    asyncio.run(client._dispatch_mention(tweet, users))

    assert len(received) == 1
    assert "&amp;" not in received[0].text
    assert "<now>" in received[0].text


# ── payload contract ────────────────────────────────────────────────────


def test_payload_forwards_truncated():
    msg = PlatformMessage(platform="gmail", sender_id="a", text="x", truncated=True)
    assert platform_message_payload(msg)["truncated"] is True
    assert platform_message_payload(PlatformMessage("gmail", "a"))["truncated"] is False


def test_payload_tolerates_legacy_message_without_truncated():
    class OldMessage:
        platform = "slack"
        sender_id = "u"
        sender_name = ""
        text = "hi"
        channel_id = ""
        channel_name = ""
        message_id = ""
        raw = {}

    assert platform_message_payload(OldMessage())["truncated"] is False


# ── host: the chat sees the cut, the agent gets the facts ────────────────


def _ingest(payload):
    """Drive AgentBase._handle_external_event; return the chat payload."""
    from app.agent_base import AgentBase

    captured = []

    async def fake_chat(p):
        captured.append(p)

    agent = SimpleNamespace(_handle_chat_message=fake_chat)
    asyncio.run(AgentBase._handle_external_event(agent, payload))
    assert len(captured) == 1
    return captured[0]


_EMAIL_EVENT = {
    "source": "Gmail",
    "integrationType": "gmail",
    "contactId": "joe@posthog.com",
    "contactName": "Joe",
    "messageBody": "Subject: Hi\nYou probably also",
    "messageId": "m1",
}


def test_truncated_body_marks_cut_for_chat_and_gives_agent_facts():
    chat = _ingest({**_EMAIL_EVENT, "truncated": True})
    # Chat details: the text and a visible cut — no agent instructions.
    assert chat["message_body"] == "Subject: Hi\nYou probably also…"
    # Agent prompt: the same text plus the facts to fetch the rest.
    assert "You probably also…" in chat["text"]
    assert "(Body truncated. Message ID: m1)" in chat["text"]


def test_untruncated_body_is_unchanged():
    chat = _ingest(_EMAIL_EVENT)
    assert chat["message_body"] == "Subject: Hi\nYou probably also"
    assert "truncated" not in chat["text"].lower()
