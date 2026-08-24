"""Phase 1 of the attachment-reception plan: listeners normalize non-text
payloads into PlatformMessage.attachments, the emit path forwards them,
and the host renders descriptors (docs/plans/attachment-reception-plan.md).

The telegram_bot end-to-end case lives in test_telegram_bot_conformance;
these cover the per-platform normalizers + the shared plumbing.
"""

from __future__ import annotations

from craftos_integrations.base import PlatformMessage
from craftos_integrations.providers._shared import platform_message_payload


def test_payload_carries_attachments():
    msg = PlatformMessage(
        platform="discord",
        sender_id="u1",
        text="",
        attachments=[{"kind": "photo", "id": "a1", "url": "https://cdn/x.png"}],
    )
    payload = platform_message_payload(msg)
    assert payload["attachments"] == [
        {"kind": "photo", "id": "a1", "url": "https://cdn/x.png"}
    ]
    assert payload["messageBody"] == ""


def test_payload_tolerates_legacy_message_without_field():
    class OldMessage:
        platform = "slack"
        sender_id = "u"
        sender_name = ""
        text = "hi"
        channel_id = ""
        channel_name = ""
        message_id = ""
        raw = {}

    assert platform_message_payload(OldMessage())["attachments"] == []


def test_discord_extract_attachments():
    from craftos_integrations.integrations.discord import DiscordClient

    d = {
        "attachments": [
            {
                "id": "111",
                "filename": "cat.png",
                "content_type": "image/png",
                "size": 2048,
                "url": "https://cdn.discordapp.com/attachments/1/111/cat.png",
            },
            {"id": "222", "filename": "notes.pdf", "size": 1},
        ],
        "embeds": [{"title": "A link", "url": "https://x.test"}, {}],
        "sticker_items": [{"id": "s1", "name": "wave"}],
    }
    atts = DiscordClient._extract_attachments(d)
    assert atts[0] == {
        "kind": "photo",
        "id": "111",
        "name": "cat.png",
        "mime": "image/png",
        "size": 2048,
        "url": "https://cdn.discordapp.com/attachments/1/111/cat.png",
    }
    assert atts[1]["kind"] == "document"  # no content_type → document
    assert atts[2] == {"kind": "embed", "extra": {"title": "A link", "url": "https://x.test"}}
    assert atts[3] == {"kind": "sticker", "id": "s1", "name": "wave"}
    assert len(atts) == 4  # empty embed skipped


def test_whatsapp_web_extract_attachments():
    from craftos_integrations.integrations.whatsapp_web import WhatsAppWebClient

    assert WhatsAppWebClient._extract_attachments(
        {"type": "image", "id": "m1", "has_media": True}
    ) == [{"kind": "photo", "id": "m1"}]
    assert WhatsAppWebClient._extract_attachments({"type": "ptt", "id": "m2"}) == [
        {"kind": "voice", "id": "m2"}
    ]
    assert WhatsAppWebClient._extract_attachments({"type": "location"}) == [
        {"kind": "location"}
    ]
    assert WhatsAppWebClient._extract_attachments({"type": "chat", "body": "hi"}) == []


def test_lark_extract_attachments():
    from craftos_integrations.integrations.lark import LarkClient

    assert LarkClient._extract_attachments(
        "file", {"file_key": "fk1", "file_name": "report.pdf"}, "om_1"
    ) == [
        {
            "kind": "document",
            "id": "fk1",
            "name": "report.pdf",
            "extra": {"message_id": "om_1", "resource_type": "file"},
        }
    ]
    # post: image nodes collected from nested rich-text content
    post = {
        "title": "t",
        "content": [[{"tag": "text", "text": "x"}, {"tag": "img", "image_key": "ik1"}]],
    }
    atts = LarkClient._extract_attachments("post", post, "om_2")
    assert atts == [
        {
            "kind": "photo",
            "id": "ik1",
            "extra": {"message_id": "om_2", "resource_type": "image"},
        }
    ]
    assert LarkClient._extract_attachments("text", {"text": "hi"}, "om_3") == []


def test_slack_extract_attachments():
    from craftos_integrations.integrations.slack import SlackClient

    msg = {
        "files": [
            {
                "id": "F1",
                "name": "deck.pdf",
                "mimetype": "application/pdf",
                "size": 4096,
                "permalink": "https://ws.slack.com/files/F1",
            }
        ]
    }
    assert SlackClient._extract_attachments(msg) == [
        {
            "kind": "document",
            "id": "F1",
            "name": "deck.pdf",
            "mime": "application/pdf",
            "size": 4096,
            "url": "https://ws.slack.com/files/F1",
        }
    ]
    assert SlackClient._extract_attachments({"text": "plain"}) == []


def test_telegram_user_extract_attachments():
    from types import SimpleNamespace

    from craftos_integrations.integrations.telegram_user import TelegramUserClient

    MessageMediaDocument = type("MessageMediaDocument", (), {})
    msg = SimpleNamespace(
        id=42,
        media=MessageMediaDocument(),
        photo=None,
        file=SimpleNamespace(name="notes.txt", mime_type="text/plain", size=10),
    )
    assert TelegramUserClient._extract_attachments(msg, 777) == [
        {
            "kind": "document",
            "id": "42",
            "extra": {"chat_id": "777"},
            "name": "notes.txt",
            "mime": "text/plain",
            "size": 10,
        }
    ]

    MessageMediaGeo = type("MessageMediaGeo", (), {})
    geo_media = MessageMediaGeo()
    geo_media.geo = SimpleNamespace(lat=1.0, long=2.0)
    msg2 = SimpleNamespace(id=43, media=geo_media, photo=None, file=None)
    assert TelegramUserClient._extract_attachments(msg2, 777) == [
        {"kind": "location", "extra": {"lat": 1.0, "long": 2.0}}
    ]

    assert TelegramUserClient._extract_attachments(
        SimpleNamespace(id=44, media=None), 777
    ) == []


def test_slack_download_stale_scope_reconnect_error(monkeypatch, tmp_path):
    """A token connected before files:read was added fails files.info with
    missing_scope — download_file must surface a reconnect message, never
    the login-page HTML Slack serves unauthorized url_private fetches."""
    from craftos_integrations.integrations.slack import SlackClient

    client = SlackClient.__new__(SlackClient)
    monkeypatch.setattr(
        SlackClient,
        "get_file_info",
        lambda self, fid: {"error": "missing_scope", "details": {"needed": "files:read"}},
    )
    out = client.download_file("F1", str(tmp_path))
    assert "files:read" in out["error"]
    assert "reconnect" in out["error"].lower()


def test_host_descriptor_formatting():
    from app.integrations import format_attachment_descriptors

    lines = format_attachment_descriptors(
        "telegram_bot",
        [
            {"kind": "photo", "id": "big", "size": 2048},
            {"kind": "location", "extra": {"lat": 1.5, "long": 2.5}},
            "junk",
            {"no_kind": True},
        ],
    )
    assert lines == [
        "[Attachment: photo (2.0KB) — retrieve with download_telegram_file(file_id='big')]",
        "[Attachment: location [lat=1.5, long=2.5]]",
    ]

    # Discord: direct CDN url, no action round-trip
    (line,) = format_attachment_descriptors(
        "discord",
        [{"kind": "photo", "name": "cat.png", "mime": "image/png", "url": "https://cdn/x"}],
    )
    assert line == (
        '[Attachment: photo "cat.png" (image/png) — fetch directly from url https://cdn/x]'
    )

    # Unknown platform falls back to the url when present
    (line,) = format_attachment_descriptors(
        "somethingelse", [{"kind": "document", "url": "https://f"}]
    )
    assert line.endswith("— url: https://f]")

    # lark: message_id rides extra but is not inlined; hint carries it
    (line,) = format_attachment_descriptors(
        "lark",
        [
            {
                "kind": "photo",
                "id": "ik1",
                "extra": {"message_id": "om_1", "resource_type": "image"},
            }
        ],
    )
    assert "download_lark_message_resource(message_id='om_1', file_key='ik1')" in line
    assert "resource_type=image" in line
