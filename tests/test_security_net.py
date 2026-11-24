"""Network guard: public addresses only, every redirect hop checked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.security import net
from app.security.policy import SecurityLevel, SecurityStore, set_store_for_tests


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    store = SecurityStore(tmp_path / "security.json")
    store.set_level(SecurityLevel.ENHANCED)
    set_store_for_tests(store)
    dns = {
        "public.example": ("93.184.216.34",),
        "intranet.example": ("10.1.2.3",),
        "metadata.example": ("169.254.169.254",),
        "mapped.example": ("::ffff:127.0.0.1",),
        "mixed.example": ("93.184.216.34", "192.168.1.5"),
    }
    monkeypatch.setattr(net, "_resolve", lambda host, port: dns[host])
    yield store
    set_store_for_tests(None)


@pytest.mark.parametrize(
    "address,blocked",
    [
        ("8.8.8.8", False),
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("169.254.169.254", True),
        ("100.64.0.1", True),  # carrier-grade NAT
        ("::ffff:127.0.0.1", True),  # IPv4-mapped loopback
        ("fd00::1", True),
        ("0.0.0.0", True),
        ("2606:4700::1111", False),
    ],
)
def test_addresses_are_judged_by_class(address, blocked):
    assert bool(net.address_refusal(address)) is blocked


def test_every_resolved_address_must_be_public(guarded):
    assert net.url_refusal("https://public.example/") is None
    for host in ("intranet", "metadata", "mapped", "mixed"):
        assert net.url_refusal(f"https://{host}.example/")


def test_names_that_do_not_resolve_are_refused(guarded, monkeypatch):
    def fail(host, port):
        raise net.socket.gaierror("no such host")

    monkeypatch.setattr(net, "_resolve", fail)
    assert "could not be resolved" in net.url_refusal("https://nowhere.example/")


def test_allowlist_matches_domains_and_subdomains(guarded):
    guarded.update({"allowed_domains": ["example"]})
    assert net.url_refusal("https://public.example/") is None
    guarded.update({"allowed_domains": ["other.org"]})
    assert "allowed domains" in net.url_refusal("https://public.example/")


class _Session:
    """Replies with a redirect chain; records what was requested."""

    def __init__(self, chain):
        self.chain = list(chain)
        self.calls = []

    def request(self, method, url, allow_redirects, **kwargs):
        self.calls.append((method, url, dict(kwargs.get("headers") or {})))
        status, location = self.chain.pop(0)
        return SimpleNamespace(
            url=url,
            status_code=status,
            is_redirect=location is not None,
            headers={"location": location} if location else {},
            close=lambda: None,
        )


def test_a_redirect_into_the_local_network_is_refused(guarded):
    session = _Session([(302, "https://intranet.example/admin")])
    with pytest.raises(net.NetworkBlocked):
        net.guarded_request("GET", "https://public.example/", session=session)
    assert len(session.calls) == 1


def test_credentials_are_not_carried_to_another_host(guarded, monkeypatch):
    monkeypatch.setattr(
        net, "_resolve", lambda host, port: ("93.184.216.34",)
    )
    session = _Session([(302, "https://elsewhere.example/"), (200, None)])
    net.guarded_request(
        "GET",
        "https://public.example/",
        session=session,
        headers={"Authorization": "Bearer t", "Accept": "*/*"},
    )
    assert session.calls[0][2].get("Authorization") == "Bearer t"
    assert "Authorization" not in session.calls[1][2]
    assert session.calls[1][2].get("Accept") == "*/*"
