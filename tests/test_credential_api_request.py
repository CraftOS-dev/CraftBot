"""Saved-key agent requests against a real local HTTP server and encrypted vault."""

import asyncio
import base64
import inspect
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest
import requests

from app.credentials import CredentialVault, Secret, VaultError
from app.credentials import api_request as api
from app.logger import logger

KEY = "sk-test-only+api/key&2026="
TEXT = "Café crème"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    vault = CredentialVault(base_dir=tmp_path / ".credentials")
    monkeypatch.setattr(api, "get_vault", lambda: vault)
    return vault


@pytest.fixture
def server():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append({"path": self.path, "headers": dict(self.headers)})
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/must-not-follow")
                self.end_headers()
                return
            if self.path == "/not-modified":
                self.send_response(304)
                self.end_headers()
                return
            if self.path in ("/text", "/latin1"):
                latin1 = self.path == "/latin1"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/plain; charset=ISO-8859-1" if latin1 else "text/plain",
                )
                self.end_headers()
                self.wfile.write(TEXT.encode("latin-1" if latin1 else "utf-8"))
                return
            if self.path == "/large":
                body = ("x" * api._MAX_BODY_BYTES + KEY).encode()
            else:
                value = (
                    self.headers.get("Authorization")
                    or self.headers.get("X-API-Key")
                    or self.headers.get("x-goog-api-key")
                )
                self.send_response(
                    200
                    if self.path != "/unauthorized" and value in (KEY, "Bearer " + KEY)
                    else 401
                )
                body = json.dumps(
                    {
                        "ok": True,
                        "echo": value,
                        "url": self.path,
                        "encoded": quote(KEY, safe=""),
                        "base64": base64.b64encode(KEY.encode()).decode(),
                    }
                ).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header(
                    "X-Echo", KEY
                )  # Response headers must never reach the model.
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            calls.append(
                {"path": self.path, "body": body, "headers": dict(self.headers)}
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"created": json.loads(body)}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def saved(vault, site="api.example.test", *, kind="api_key", key=KEY):
    return vault.add_entry(
        site,
        "account" if kind == "login" else "",
        key,
        "Example key",
        kind=kind,
        group="work",
    )


def run(data):
    return asyncio.run(api.request_with_api_key(data))


def test_list_only_api_metadata_and_filter(vault):
    key = saved(vault)
    saved(vault, kind="login")
    saved(vault, site="", kind="secure_note")
    result = asyncio.run(api.list_api_keys({"query": "example.test"}))
    assert result == {
        "status": "success",
        "credentials": [
            {
                "id": key["id"],
                "site": "api.example.test",
                "label": "Example key",
                "group": "work",
            }
        ],
    }
    assert KEY not in json.dumps(result)
    assert asyncio.run(api.list_api_keys({"query": "absent"}))["credentials"] == []


@pytest.mark.parametrize(
    "auth,header", [("bearer", "Authorization"), ("header", "X-API-Key")]
)
def test_real_request_injects_key_and_sanitizes_echo(vault, server, auth, header):
    url, calls = server
    entry = saved(vault, url)
    result = run(
        {
            "credential_id": entry["id"],
            "url": url + "/echo",
            "auth_type": auth,
            "params": {"page": 2},
        }
    )
    assert result["status"] == "success"
    assert json.loads(result["body"])["ok"] is True
    assert "[redacted]" in result["body"]
    text = json.dumps(result)
    for variant in (KEY, quote(KEY, safe=""), base64.b64encode(KEY.encode()).decode()):
        assert variant not in text
    assert "response_headers" not in result
    assert calls[0]["headers"][header] == ("Bearer " if auth == "bearer" else "") + KEY
    assert calls[0]["path"] == "/echo?page=2"
    assert KEY not in calls[0]["path"]


def test_json_write_request(vault, server):
    url, calls = server
    result = run(
        {
            "credential_id": saved(vault, url)["id"],
            "url": url + "/items",
            "method": "POST",
            "json": {"name": "Widget"},
            "headers": {"Accept": "application/json"},
        }
    )
    assert result["status"] == "success"
    assert json.loads(result["body"]) == {"created": {"name": "Widget"}}
    assert json.loads(calls[0]["body"]) == {"name": "Widget"}


def test_custom_api_key_header(vault, server):
    url, calls = server
    result = run(
        {
            "credential_id": saved(vault, url)["id"],
            "url": url + "/echo",
            "auth_type": "header",
            "header_name": "x-goog-api-key",
        }
    )
    assert result["status"] == "success"
    assert calls[0]["headers"]["x-goog-api-key"] == KEY
    assert KEY not in json.dumps(result)


def test_http_error_response_is_also_sanitized(vault, server):
    url, _ = server
    result = run(
        {"credential_id": saved(vault, url)["id"], "url": url + "/unauthorized"}
    )
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert "[redacted]" in result["body"]
    assert KEY not in json.dumps(result)


def test_redirect_never_follows_or_returns_location(vault, server):
    url, calls = server
    result = run({"credential_id": saved(vault, url)["id"], "url": url + "/redirect"})
    assert result["error_code"] == "CREDENTIAL_REDIRECT_REFUSED"
    assert [call["path"] for call in calls] == ["/redirect"]
    assert "Location" not in json.dumps(result)


def test_not_modified_is_returned_not_refused_as_redirect(vault, server):
    url, _ = server
    result = run(
        {"credential_id": saved(vault, url)["id"], "url": url + "/not-modified"}
    )
    assert result["status"] == "success"
    assert result["status_code"] == 304


@pytest.mark.parametrize("path", ["/text", "/latin1"])
def test_text_response_uses_declared_charset_else_utf8(vault, server, path):
    url, _ = server
    result = run({"credential_id": saved(vault, url)["id"], "url": url + path})
    assert result["body"] == TEXT


def test_oversize_response_returns_no_partial_value(vault, server):
    url, _ = server
    result = run({"credential_id": saved(vault, url)["id"], "url": url + "/large"})
    assert result["error_code"] == "CREDENTIAL_RESPONSE_TOO_LARGE"
    assert "body" not in result


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example.test/",
        "https://sub.api.example.test/",
        "https://www.api.example.test/",
        "https://api.example.test:444/",
        "https://api.example.test:80/",
        "http://api.example.test/",
    ],
)
def test_wrong_destination_refused_before_network(vault, monkeypatch, target):
    entry = saved(vault)
    calls = []
    monkeypatch.setattr(requests.Session, "send", lambda *_a, **_kw: calls.append(True))
    result = run({"credential_id": entry["id"], "url": target})
    assert result["status"] == "error"
    assert not calls


def test_www_api_host_is_kept_and_matched_exactly(vault):
    entry = saved(vault, "https://www.api.example.test/v1")
    assert entry["site"] == "www.api.example.test"
    assert (
        vault.api_key_for_url(entry["id"], "https://www.api.example.test/v1").reveal()
        == KEY
    )
    with pytest.raises(VaultError):
        vault.api_key_for_url(entry["id"], "https://api.example.test/v1")


@pytest.mark.parametrize(
    "kind,site", [("login", "api.example.test"), ("secure_note", ""), ("api_key", "")]
)
def test_wrong_type_or_missing_website_refused(vault, kind, site):
    result = run(
        {
            "credential_id": saved(vault, site, kind=kind)["id"],
            "url": "https://api.example.test/",
        }
    )
    assert result["error_code"] == "CREDENTIAL_UNAVAILABLE"
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "https://user:pass@api.example.test/"},
        {"url": "https://api.example.test/#fragment"},
        {"url": "https://api.example.test/\n"},
        {"url": "https://evil.test\\@api.example.test/"},
        {"url": "file:///tmp/data"},
        {"headers": {"Host": "evil.test"}},
        {"headers": {"authorization": "override"}},
        {"headers": {"X-Thing": "value\r\nX-Other: bad"}},
        {"header_name": "Host"},
        {"header_name": "Proxy-Authorization"},
        {"header_name": "Cookie"},
        {"auth_type": "query"},
        {"verify_tls": False},
        {"allow_redirects": True},
        {"save_to": "leak.txt"},
        {"timeout": float("nan")},
        {"timeout": True},
        {"timeout": 61},
        {"json": {}, "data": "both"},
        {"params": []},
    ],
)
def test_unsafe_request_inputs_never_send(vault, monkeypatch, changes):
    entry = saved(vault)
    calls = []
    monkeypatch.setattr(requests.Session, "send", lambda *_a, **_kw: calls.append(True))
    result = run(
        {"credential_id": entry["id"], "url": "https://api.example.test/", **changes}
    )
    assert result["status"] == "error"
    assert not calls


def test_transport_failures_do_not_echo_key_or_log_tracebacks(vault, monkeypatch):
    entry = saved(vault)
    observed = {}

    def fail(session, prepared, **kwargs):
        observed.update(kwargs)
        observed["trust_env"] = session.trust_env
        assert prepared.headers["Authorization"] == "Bearer " + KEY
        raise requests.ConnectionError("Request failed: " + KEY)

    monkeypatch.setattr(requests.Session, "send", fail)
    logs = []
    sink = logger.add(
        lambda message: logs.append(str(message)), diagnose=True, backtrace=True
    )
    try:
        result = run({"credential_id": entry["id"], "url": "https://api.example.test/"})
    finally:
        logger.remove(sink)
    assert result["error_code"] == "CREDENTIAL_REQUEST_FAILED"
    assert KEY not in json.dumps(result) + "".join(logs)
    assert observed["verify"] is True
    assert observed["allow_redirects"] is False
    assert observed["trust_env"] is False
    assert observed["stream"] is True


def test_redaction_decodes_json_escapes_and_scrubs_nested_keys():
    escaped = "".join("\\u%04x" % ord(c) for c in KEY)
    payload = '{"' + escaped + '": [{"value":"' + escaped + '"}]}'
    assert json.loads(api._redact(payload, Secret(KEY))) == {
        "[redacted]": [{"value": "[redacted]"}]
    }


def test_vault_missing_or_unreadable_fails_without_network(vault, monkeypatch):
    entry = saved(vault)
    vault.key_path.unlink()
    calls = []
    monkeypatch.setattr(requests.Session, "send", lambda *_a, **_kw: calls.append(True))
    assert (
        asyncio.run(api.list_api_keys({}))["error_code"]
        == "CREDENTIAL_VAULT_UNAVAILABLE"
    )
    assert (
        run({"credential_id": entry["id"], "url": "https://api.example.test/"})[
            "status"
        ]
        == "error"
    )
    assert not calls


def test_actions_load_and_executor_stripped_source_uses_real_backend(vault, server):
    from agent_core import load_actions_from_directories, registry_instance

    root = Path(__file__).resolve().parent.parent
    load_actions_from_directories(base_dir=str(root), paths_to_scan=["app/data/action"])
    url, calls = server
    entry = saved(vault, url)

    def execute(name, data):
        impl = registry_instance.get_action_implementation(name)
        assert impl.metadata.action_sets == ["core"]
        assert impl.metadata.mode == "ALL"
        assert impl.metadata.execution_mode == "internal"
        # Irreversible actions replay a stored output for identical calls,
        # which would hand the agent stale API reads.
        assert not impl.metadata.irreversible
        namespace = {"input_data": data, "json": json, "asyncio": asyncio}
        before = set(namespace)
        exec(registry_instance.find_action_by_name(name)["code"], namespace)
        function = next(
            v for k, v in namespace.items() if k not in before and inspect.isfunction(v)
        )
        return asyncio.run(function(data))

    listed = execute("credential_list_api_keys", {})
    assert listed["credentials"][0]["id"] == entry["id"]
    result = execute(
        "credential_api_request",
        {
            "credential_id": entry["id"],
            "url": url + "/echo",
            "_session_id": "test-session",
        },
    )
    assert result["status"] == "success"
    assert KEY not in json.dumps(result)
    assert calls[0]["headers"]["Authorization"] == "Bearer " + KEY
    assert (
        execute("credential_api_request", {"simulated_mode": True})["status"]
        == "success"
    )
    assert len(calls) == 1
