"""Google provider base + Gmail reference provider.

No network: HTTP is monkeypatched; client API methods are stubbed. What's
real is the full chain execute() → resolve → bind → client method → shaped
result, and refresh-persistence routing.
"""

from __future__ import annotations

import asyncio
import base64
import email

import pytest

import craftos_integrations.providers._google as google_mod
import craftos_integrations.providers.gmail.client as gmail_client_mod
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.gmail import GmailProvider
from craftos_integrations.providers.gmail.provider import BoundGmailClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


GOOGLE_CRED = {
    "access_token": "at-1",
    "refresh_token": "rt-1",
    "token_expiry": 1e12,  # far future: no refresh during normal calls
    "client_id": "cid",
    "client_secret": "csec",
    "email": "a@x.com",
}


class TestGmailConformance(ProviderConformance):
    provider = GmailProvider()
    credential_fixtures = [
        GOOGLE_CRED,
        {"access_token": "at", "email": "  User@X.com "},  # messy legacy shape
        {"access_token": "at"},  # identity-less pre-multi-account shape → None
    ]


def test_oauth_spec_carries_the_chooser_fix():
    spec = GmailProvider().oauth_spec()
    assert spec.extra_authorize_params["prompt"] == "consent select_account"
    assert spec.extra_authorize_params["access_type"] == "offline"
    assert spec.has_chooser


def test_binding_replaces_disk_plumbing():
    client = BoundGmailClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential(GOOGLE_CRED, lambda c: None)
    assert client.has_credentials()
    assert client._load().email == "a@x.com"
    assert client._load().access_token == "at-1"


def test_refresh_persists_through_core_not_disk(monkeypatch):
    persisted = {}

    def fake_http(method, url, **kwargs):
        assert url == google_mod.GOOGLE_TOKEN_URL
        assert kwargs["data"]["refresh_token"] == "rt-1"
        return {"result": {"access_token": "at-2", "expires_in": 3600}}

    monkeypatch.setattr(google_mod, "http_request", fake_http)
    client = BoundGmailClient()
    client.bind_credential(dict(GOOGLE_CRED), persisted.update)
    token = client.refresh_access_token()
    assert token == "at-2"
    assert persisted["access_token"] == "at-2"
    assert persisted["refresh_token"] == "rt-1"  # carried forward
    assert persisted["email"] == "a@x.com"


def test_refresh_failure_returns_none_and_persists_nothing(monkeypatch):
    persisted = {}
    monkeypatch.setattr(
        google_mod, "http_request", lambda *a, **k: {"error": "invalid_grant"}
    )
    client = BoundGmailClient()
    client.bind_credential(dict(GOOGLE_CRED), persisted.update)
    assert client.refresh_access_token() is None
    assert persisted == {}


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[GmailProvider()]
    )
    sys.store_credential("gmail", "a@x.com", dict(GOOGLE_CRED))
    sys.store_credential(
        "gmail", "b@y.com", {**GOOGLE_CRED, "email": "b@y.com", "access_token": "at-b"}
    )
    sys.set_alias("gmail", "b@y.com", "school")
    return sys


def test_execute_runs_operation_against_resolved_accounts_client(system, monkeypatch):
    seen = []

    def fake_list_emails(self, n=5, unread_only=True):
        seen.append((self._cred.email, n, unread_only))
        return {"ok": True, "result": ["mail"]}

    monkeypatch.setattr(BoundGmailClient, "list_emails", fake_list_emails)

    result = run(system.execute("gmail", "list_gmail", {"count": 3}, account="school"))
    assert result == {"status": "success", "result": ["mail"]}
    assert seen == [("b@y.com", 3, True)]  # school account's client, mapped args

    run(system.execute("gmail", "list_gmail", {}))
    assert seen[-1] == ("a@x.com", 5, True)  # primary + client-side defaults


def test_operation_error_shape_is_agent_friendly(system, monkeypatch):
    monkeypatch.setattr(
        BoundGmailClient,
        "send_email",
        lambda self, **k: {"error": "API error: 403", "details": "insufficient scope"},
    )
    result = run(
        system.execute(
            "gmail", "send_gmail", {"subject": "s", "body": "b"}, account="a@x.com"
        )
    )
    assert result["status"] == "error"
    assert "403" in result["message"]


# ----- Outgoing MIME: HTML + inline images -----

PNG = b"\x89PNG\r\n\x1a\nfake-png-bytes"


@pytest.fixture
def sent(monkeypatch):
    """Captures the parsed MIME message of every Gmail send/draft call."""
    captured = []

    def fake_http(method, url, **kwargs):
        payload = kwargs["json"]
        raw = (payload.get("message") or payload)["raw"]
        captured.append(email.message_from_bytes(base64.urlsafe_b64decode(raw)))
        return {"ok": True, "result": {"id": "m1", "threadId": "t1"}}

    monkeypatch.setattr(gmail_client_mod, "http_request", fake_http)
    return captured


def _parts(msg):
    return {p.get_content_type(): p for p in msg.walk()}


def _image(tmp_path, name="chart.png"):
    path = tmp_path / name
    path.write_bytes(PNG)
    return str(path)


def test_plain_send_is_unchanged(system, sent):
    run(system.execute("gmail", "send_gmail", {"subject": "s", "body": "hi"}))
    (msg,) = sent
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain"]
    assert msg.get_payload()[0].get_payload(decode=True) == b"hi"


def test_html_body_with_cid_inline_image(system, sent, tmp_path):
    path = _image(tmp_path)
    result = run(
        system.execute(
            "gmail",
            "send_gmail",
            {
                "subject": "s",
                "body": '<p>Report</p><img src="cid:chart.png">',
                "html": True,
                "inline_images": [path],
            },
        )
    )
    assert result["status"] == "success"
    (msg,) = sent
    parts = _parts(msg)
    assert "multipart/related" in parts and "multipart/alternative" in parts
    html = parts["text/html"].get_payload(decode=True).decode()
    assert html == '<p>Report</p><img src="cid:chart.png">'
    assert parts["text/plain"].get_payload(decode=True).decode() == "Report"
    img = parts["image/png"]
    assert img["Content-ID"] == "<chart.png>"
    assert img.get_content_disposition() == "inline"
    assert img.get_filename() == "chart.png"
    assert img.get_payload(decode=True) == PNG


def test_local_img_src_is_embedded_and_rewritten(system, sent, tmp_path):
    path = _image(tmp_path, "my chart.png")
    run(
        system.execute(
            "gmail",
            "send_gmail",
            {"subject": "s", "body": f'<img src="{path}">', "html": True},
        )
    )
    parts = _parts(sent[0])
    html = parts["text/html"].get_payload(decode=True).decode()
    assert html == '<img src="cid:my_chart.png">'
    assert parts["image/png"]["Content-ID"] == "<my_chart.png>"


def test_unplaced_image_is_appended_to_plain_text_body(system, sent, tmp_path):
    path = _image(tmp_path)
    run(
        system.execute(
            "gmail",
            "send_gmail",
            {"subject": "s", "body": "a < b\nsee below", "inline_images": [path]},
        )
    )
    parts = _parts(sent[0])
    html = parts["text/html"].get_payload(decode=True).decode()
    assert html.startswith("<div>a &lt; b<br>\nsee below</div>")
    assert html.endswith('<img src="cid:chart.png" alt="chart.png"></div>')
    assert parts["text/plain"].get_payload(decode=True).decode() == "a < b\nsee below"


def test_inline_images_and_attachments_together(system, sent, tmp_path):
    img = _image(tmp_path)
    doc = tmp_path / "notes.txt"
    doc.write_text("notes")
    run(
        system.execute(
            "gmail",
            "send_gmail",
            {
                "subject": "s",
                "body": '<img src="cid:chart.png">',
                "html": True,
                "inline_images": [img],
                "attachments": [str(doc)],
            },
        )
    )
    (msg,) = sent
    top = [p.get_content_type() for p in msg.get_payload()]
    assert top == ["multipart/related", "text/plain"]
    assert msg.get_payload()[1].get_content_disposition() == "attachment"


def test_duplicate_file_names_get_distinct_cids(system, sent, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first, second = _image(tmp_path / "a"), _image(tmp_path / "b")
    run(
        system.execute(
            "gmail",
            "send_gmail",
            {"subject": "s", "body": "x", "inline_images": [first, second]},
        )
    )
    cids = [p["Content-ID"] for p in sent[0].walk() if p.get_content_maintype() == "image"]
    assert cids == ["<chart.png>", "<chart-2.png>"]


@pytest.mark.parametrize("name", ["missing.png", "notes.txt"])
def test_bad_inline_image_fails_without_sending(system, sent, tmp_path, name):
    if name == "notes.txt":
        (tmp_path / name).write_text("not an image")
    result = run(
        system.execute(
            "gmail",
            "send_gmail",
            {"subject": "s", "body": "x", "inline_images": [str(tmp_path / name)]},
        )
    )
    assert result["status"] == "error"
    assert name in result["message"]
    assert sent == []


def test_reply_and_draft_support_inline_images(system, sent, tmp_path, monkeypatch):
    path = _image(tmp_path)
    monkeypatch.setattr(
        BoundGmailClient,
        "_fetch_reply_headers",
        lambda self, mid: {"From": "c@z.com", "Subject": "Hi", "_thread_id": "t1"},
    )
    body = {"body": '<img src="cid:chart.png">', "html": True, "inline_images": [path]}
    run(system.execute("gmail", "reply_gmail", {"message_id": "m0", **body}))
    run(
        system.execute(
            "gmail", "create_gmail_draft", {"to": "c@z.com", "subject": "s", **body}
        )
    )
    assert len(sent) == 2
    for msg in sent:
        assert _parts(msg)["image/png"]["Content-ID"] == "<chart.png>"


def test_default_providers_importable():
    from craftos_integrations.providers import default_providers

    providers = default_providers()
    assert any(p.id == "gmail" for p in providers)
