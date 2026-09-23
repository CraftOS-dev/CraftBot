"""The A2App caller guard, at the boundary that matters: a share channel.

These live under tests/ on purpose. pytest.ini sets `testpaths = tests`, so
the suites in app/agent_app/test_*.py are never collected by a plain `pytest`
run — the assertions that guard this surface have to sit where CI will run
them.

Everything here drives `guard_request` directly: it is the single decision
point every route funnels through, so a pure-function test covers the
passthrough, the declared ops and the WebSocket upgrade at once.
"""

import pytest

from app.agent_app.a2app_proxy import (
    guard_request,
    local_session_value,
    session_cookie_name,
    share_session_value,
)

TOKEN = "agent-token-for-tests"
TUNNEL_SECRET = "tunnel-secret"

LOCAL = {"Host": "127.0.0.1:3100", "Origin": "http://127.0.0.1:3100"}
# Cloudflare stamps cf-ray on everything it forwards and a remote caller
# cannot strip it; the LAN relay stamps X-Forwarded-For for the same reason.
TUNNEL = {
    "Host": "demo.trycloudflare.com",
    "Origin": "https://demo.trycloudflare.com",
    "cf-ray": "test-ray",
}
LAN = {
    "Host": "192.168.1.20:3100",
    "Origin": "http://192.168.1.20:3100",
    "x-forwarded-for": "192.168.1.55",
}


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".agent-token").write_text(TOKEN, encoding="utf-8")
    (tmp_path / ".tunnel-origin").write_text(TUNNEL["Origin"], encoding="utf-8")
    (tmp_path / ".tunnel-secret").write_text(TUNNEL_SECRET, encoding="utf-8")
    return tmp_path


def allowed(project, method, headers, cookies=None):
    return guard_request(project, method, headers, cookies or {}) is None


def code(project, method, headers, cookies=None):
    verdict = guard_request(project, method, headers, cookies or {})
    return None if verdict is None else verdict[1]["code"]


# -- the original bypass -----------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost",
        "http://127.0.0.1:3100",
        "http://[::1]:3100",
    ],
)
def test_a_loopback_origin_is_not_a_credential(project, origin):
    """The bug this guard replaced: the token check sat in an `elif not
    origin` branch, so naming any loopback Origin skipped it entirely."""
    assert not allowed(project, "POST", {"Host": "127.0.0.1:3100", "Origin": origin})


def test_the_agent_token_still_authorises_a_write(project):
    assert allowed(project, "POST", dict(LOCAL, **{"X-A2App-Token": TOKEN}))


def test_a_wrong_token_does_not(project):
    assert not allowed(project, "POST", dict(LOCAL, **{"X-A2App-Token": "nope"}))


# -- share channels: no credential, no access, reads included ----------------


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_every_method_needs_a_credential_through_a_share_channel(project, method):
    """Including OPTIONS. An unguarded preflight is forwarded upstream with
    its body and its response returned, which makes every native route of an
    adopted app readable and drivable by anyone holding the bare share URL —
    any framework that answers OPTIONS with a real handler is affected
    (aiohttp add_route("*"), Express app.all, FastAPI methods=["*"], ...)."""
    assert not allowed(project, method, TUNNEL)


def test_a_valid_share_session_gets_in(project):
    cookies = {session_cookie_name(TOKEN): share_session_value(TOKEN, TUNNEL_SECRET)}
    assert allowed(project, "GET", TUNNEL, cookies)
    assert allowed(project, "POST", TUNNEL, cookies)


def test_a_local_cookie_is_not_a_remote_credential(project):
    cookies = {session_cookie_name(TOKEN): local_session_value(TOKEN)}
    assert not allowed(project, "POST", TUNNEL, cookies)


def test_a_remote_caller_claiming_a_loopback_origin_is_still_remote(project):
    assert not allowed(project, "POST", dict(TUNNEL, Origin="http://localhost"))


# -- local traffic keeps working --------------------------------------------


def test_local_preflight_is_not_refused(project):
    """A browser strips credentials from a preflight by spec, so demanding one
    locally would break every cross-origin call the app's own UI makes."""
    assert allowed(project, "OPTIONS", LOCAL)


def test_local_reads_stay_open(project):
    assert allowed(project, "GET", LOCAL)


def test_a_foreign_origin_cannot_write_locally(project):
    assert code(project, "POST", dict(LOCAL, Origin="https://evil.example")) == (
        "forbidden_origin"
    )


# -- failure modes -----------------------------------------------------------


def test_sharing_fails_closed_without_an_agent_token(tmp_path):
    """No token means nothing can be checked. Locally that must not lock the
    owner out (it is minted at launch); remotely it must refuse, or a shared
    app is publicly writable."""
    (tmp_path / ".agent-token").write_text("", encoding="utf-8")
    (tmp_path / ".tunnel-origin").write_text(TUNNEL["Origin"], encoding="utf-8")
    (tmp_path / ".tunnel-secret").write_text(TUNNEL_SECRET, encoding="utf-8")

    assert code(tmp_path, "POST", TUNNEL) == "share_unavailable"
    assert code(tmp_path, "DELETE", TUNNEL) == "share_unavailable"
    assert allowed(tmp_path, "POST", LOCAL)


def test_lan_is_reachable_with_its_own_link(tmp_path):
    """LAN is a share channel like the tunnel: remote, so it needs a
    credential, but it must HAVE one to offer — being unreachable with no way
    in is the regression this replaced."""
    (tmp_path / ".agent-token").write_text(TOKEN, encoding="utf-8")
    (tmp_path / ".lan-origin").write_text(LAN["Origin"], encoding="utf-8")
    (tmp_path / ".lan-secret").write_text("lan-secret", encoding="utf-8")

    assert not allowed(tmp_path, "GET", LAN)
    cookies = {session_cookie_name(TOKEN): share_session_value(TOKEN, "lan-secret")}
    assert allowed(tmp_path, "GET", LAN, cookies)
    assert allowed(tmp_path, "POST", LAN, cookies)
