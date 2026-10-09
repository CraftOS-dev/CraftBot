"""Tests for the Mini Browser password vault (app/mini_browser/vault.py).

No network and no Chromium: every vault lives in a pytest temp directory.
"""

from __future__ import annotations

import base64
import errno
import json
import os
import stat
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.logger import logger
from app.mini_browser import vault as vault_mod
from app.mini_browser.errors import MiniBrowserError, ui_error
from app.mini_browser.vault import (
    CODE_INVALID,
    CODE_IO,
    CODE_UNREADABLE,
    CredentialVault,
    Secret,
    VaultError,
    get_vault,
    normalize_site,
    site_matches,
)

# Distinctive values, so a leak is easy to spot anywhere.
PASSWORD = "Tr0ub4dor&3-horse-battery"
NEW_PASSWORD = "N3w-Corr3ct-Staple-Pass"
OTHER_PASSWORD = "0ther-Acc0unt-S3cret!"
LONG_PASSWORD = "L0ng-Pa55word-" * 100  # > MAX_PASSWORD_CHARS
SECRETS = (PASSWORD, NEW_PASSWORD, OTHER_PASSWORD, LONG_PASSWORD)

PUBLIC_KEYS = {
    "id",
    "site",
    "username",
    "label",
    "createdAt",
    "updatedAt",
    "lastUsedAt",
}


# ─── helpers ────────────────────────────────────────────────────────────


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return tmp_path / ".credentials"


@pytest.fixture
def vault(vault_dir: Path) -> CredentialVault:
    return CredentialVault(base_dir=vault_dir)


@pytest.fixture
def clock(monkeypatch):
    """Strictly increasing, deterministic timestamps (one second apart)."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ticks = iter(range(1, 1_000_000))

    def fake_now() -> str:
        moment = start + timedelta(seconds=next(ticks))
        return moment.isoformat(timespec="milliseconds")

    monkeypatch.setattr(vault_mod, "_now", fake_now)


def _swap_file(path: Path, data: bytes) -> None:
    """Replace a file's content the way another program would (new inode)."""
    tmp = path.with_name(path.name + ".swap")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _fernet_for(vault: CredentialVault):
    content = Secret(vault.key_path.read_bytes())
    key, _protection = vault_mod._unwrap_key(content)
    return vault_mod._fernet_api().fernet(key.reveal())


def _assert_no_secret(value) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in text


def _usernames(entries) -> list:
    return [entry["username"] for entry in entries]


# ─── normalize_site ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("example.com", "example.com"),
        ("Example.COM", "example.com"),
        ("  example.com  ", "example.com"),
        ("example.com/", "example.com"),
        ("//example.com/x", "example.com"),
        ("https://example.com", "example.com"),
        ("http://example.com/login?next=/home#top", "example.com"),
        ("HTTPS://WWW.Example.com/path", "example.com"),
        ("www.example.com", "example.com"),
        ("example.com.", "example.com"),
        ("https://www.example.com./", "example.com"),
        ("https://user:pass@example.com/", "example.com"),
        ("user@example.com", "example.com"),
        ("https://example.com:443/", "example.com"),
        ("http://example.com:80", "example.com"),
        ("example.com:443", "example.com"),
        ("example.com:", "example.com"),
        ("example.com:8443", "example.com:8443"),
        ("https://example.com:8443/x", "example.com:8443"),
        ("sub.www.example.com", "sub.www.example.com"),
        ("www2.example.com", "www2.example.com"),
        ("www.com", "www.com"),  # stripping would leave a bare TLD
        ("accounts.google.com", "accounts.google.com"),
        ("localhost", "localhost"),
        ("LOCALHOST:3000", "localhost:3000"),
        ("http://localhost:5173/login", "localhost:5173"),
        ("127.0.0.1", "127.0.0.1"),
        ("http://127.0.0.1:8080/", "127.0.0.1:8080"),
        ("192.168.1.1", "192.168.1.1"),
        ("[::1]", "[::1]"),
        ("::1", "[::1]"),
        ("http://[::1]:8080/", "[::1]:8080"),
        ("[0:0:0:0:0:0:0:1]:8080", "[::1]:8080"),
        ("xn--bcher-kva.de", "xn--bcher-kva.de"),
        ("bücher.de", "xn--bcher-kva.de"),
        ("https://www.BÜCHER.de/", "xn--bcher-kva.de"),
        ("ドメイン.テスト", "xn--eckwd4c7c.xn--zckzah"),
        ("ｅｘａｍｐｌｅ.com", "example.com"),  # fullwidth letters map like browsers
    ],
)
def test_normalize_site_valid(text, expected):
    assert normalize_site(text) == expected
    # Normalising is idempotent.
    assert normalize_site(expected) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        12345,
        "",
        "   ",
        "my bank",
        "exa mple.com",
        "example.com/my page",
        "example.com" + chr(9) + "x",
        "example" + chr(0x3000) + ".com",  # ideographic space
        "ftp://example.com",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "mailto:me@example.com",
        "about:blank",
        "data:text/html,hi",
        "chrome://settings",
        "http:example.com",
        "com",
        "intranet",
        "www",
        "https://ai/",
        "https://",
        "http://:8080",
        "example..com",
        ".example.com",
        "example.com..",
        "example.com:abc",
        "example.com:99999",
        "example.com:0",
        "localhost:-1",
        "ex%61mple.com",
        "exa$mple.com",
        "example.com\\@evil.com",
        "a" * 64 + ".com",
        "a." * 130 + "com",  # longer than 253 characters
        "x" * 3000 + ".com",
        "1.2.3",
        "999.1.1.1",
        "example.123",
        "[::1",
        "[fe80::1%25eth0]",
    ],
)
def test_normalize_site_invalid(text):
    with pytest.raises(VaultError) as info:
        normalize_site(text)
    assert info.value.code == CODE_INVALID
    assert info.value.detail


def test_normalize_site_errors_never_echo_the_input():
    typed = "correct horse battery staple"  # e.g. a password in the wrong field
    with pytest.raises(VaultError) as info:
        normalize_site(typed)
    assert typed not in str(info.value)
    assert "horse" not in info.value.detail


def test_idn_follows_browsers_not_idna2003():
    # IDNA 2003 maps "faß.de" to "fass.de", a different registrable domain.
    # Chromium (UTS #46 non-transitional) opens xn--fa-hia.de. Without the
    # idna package the vault refuses such names instead (tested below).
    pytest.importorskip("idna")
    assert normalize_site("faß.de") == "xn--fa-hia.de"
    assert site_matches("faß.de", "https://xn--fa-hia.de/login")
    assert not site_matches("faß.de", "https://fass.de/login")
    assert not site_matches("fass.de", "https://xn--fa-hia.de/")


def test_idn_fallback_without_idna_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "idna", None)  # "import idna" fails
    assert normalize_site("bücher.de") == "xn--bcher-kva.de"
    with pytest.raises(VaultError) as info:
        normalize_site("faß.de")  # would silently become fass.de
    assert info.value.code == CODE_INVALID


# ─── site_matches ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "saved, url",
    [
        ("paypal.com", "https://secure-paypal.com/login"),
        ("secure-paypal.com", "https://paypal.com/"),
        ("chase.com", "https://notchase.com/"),
        ("notchase.com", "https://chase.com/"),
        ("amazon.com", "https://zon.com/"),
        ("zon.com", "https://amazon.com/"),
        ("example.com", "https://le.com/"),
        ("le.com", "https://example.com/"),
        ("example.com", "http://example.com/"),  # plain http
        ("example.com", "http://www.example.com/login"),
        ("accounts.google.com", "https://google.com/"),  # parent of the saved site
        ("accounts.google.com", "https://mail.google.com/"),  # sibling
        ("perplexity.ai", "https://ai/"),
        ("perplexity.ai", "https://ai./"),
        ("example.com:8443", "https://example.com/"),  # port mismatch
        ("example.com:8443", "https://example.com:9443/"),
        ("localhost:3000", "http://localhost:3001/"),
        ("localhost:3000", "http://localhost/"),
        ("bank.com", "https://bank.com.evil.com/"),
        ("bank.com", "https://evilbank.com/"),
        ("bank.com", "https://evil.com/?next=https://bank.com"),
        ("bank.com", "https://evil.com/bank.com"),
        ("bank.com", "https://bank.com@evil.com/"),
        ("bank.com", "https://evil.com#@bank.com"),
        ("bank.com", "https://evil.com\\@bank.com/"),
        ("bank.com", "https://bank.com\\.evil.com/"),
        ("bank.com", "https://bank.com%2eevil.com/"),
        ("bank.com", "ftp://bank.com/"),
        ("bank.com", "file:///bank.com"),
        ("bank.com", "javascript:alert('bank.com')"),
        ("bank.com", "data:text/html,bank.com"),
        ("bank.com", "about:blank"),
        ("bank.com", "bank.com"),  # not a URL
        ("bank.com", "//bank.com/"),  # no scheme
        ("bank.com", "https://com/"),
        ("192.168.1.1", "http://192.168.1.1/"),  # http only for loopback
        ("127.0.0.1", "http://127.0.0.2/"),
        ("localhost", "http://app.localhost/"),  # http only for exactly localhost
        ("1.2.3.4", "https://5.1.2.3.4/"),
        # Subdomains are other sites (security SEC-3): on hosts of user pages
        # they belong to someone else.
        ("www.tumblr.com", "https://attacker-blog.tumblr.com/"),
        ("https://www.tumblr.com/login", "https://attacker-blog.tumblr.com/"),
        ("tumblr.com", "https://attacker-blog.tumblr.com/login"),
        ("github.io", "https://someone.github.io/"),
        ("neocities.org", "https://evil.neocities.org/signin"),
        ("amazon.com", "https://signin.amazon.com/ap/signin?openid=x"),
        ("bücher.de", "https://shop.bücher.de/"),
        ("example.com", "https://www.www.example.com/"),
        ("example.com", "https://a.www.example.com/"),
        # A saved site without a port matches the default ports only.
        ("example.com", "https://example.com:8443/"),
        ("localhost", "http://localhost:5173/"),
    ],
)
def test_site_matches_rejects_lookalikes_and_unsafe_pages(saved, url):
    assert site_matches(saved, url) is False


@pytest.mark.parametrize(
    "saved, url",
    [
        ("amazon.com", "https://amazon.com/"),
        ("amazon.com", "https://www.amazon.com/gp/cart"),
        ("www.amazon.com", "https://amazon.com/"),  # saved www. is stripped
        ("www.amazon.com", "https://www.amazon.com/"),
        ("https://www.amazon.com/ap/signin", "https://amazon.com/"),
        ("https://www.tumblr.com/login", "https://www.tumblr.com/login"),
        ("https://www.tumblr.com/login", "https://tumblr.com/"),
        ("accounts.google.com", "https://accounts.google.com/v3/signin"),
        ("amazon.com", "https://AMAZON.com./"),
        ("amazon.com", "https://amazon.com:443/"),
        ("amazon.com", "https://user:pw@amazon.com/"),
        ("example.com:8443", "https://example.com:8443/x"),
        ("localhost:3000", "http://localhost:3000/login"),
        ("localhost:3000", "https://localhost:3000/"),
        ("localhost", "http://localhost/"),
        ("127.0.0.1:8080", "http://127.0.0.1:8080/"),
        ("[::1]:8080", "http://[::1]:8080/"),
        ("bücher.de", "https://xn--bcher-kva.de/"),
        ("bücher.de", "https://www.bücher.de/"),
        ("192.168.1.1", "https://192.168.1.1/"),
        ("www.com", "https://www.com/"),
    ],
)
def test_site_matches_accepts_the_same_site_with_or_without_www(saved, url):
    assert site_matches(saved, url) is True


@pytest.mark.parametrize(
    "saved, url",
    [
        (None, None),
        ("", ""),
        (123, "https://example.com/"),
        (["example.com"], "https://example.com/"),
        ("example.com", 42),
        ("example.com", None),
        ("example.com", "https://[::1"),
        ("example.com", "https://example.com:99999/"),
        ("example.com", "https://example.com:0/"),
        ("not a site", "https://example.com/"),
    ],
)
def test_site_matches_never_raises(saved, url):
    assert site_matches(saved, url) is False


def test_site_matches_rejects_oversized_urls():
    # Built here, not in parametrize: pytest exports the test id in an
    # environment variable, and Windows caps those at 32767 characters.
    longest = "https://example.com/" + "x" * (vault_mod.MAX_URL_CHARS - 20)
    assert site_matches("example.com", longest) is True
    assert site_matches("example.com", longest + "x") is False


# ─── CRUD ───────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("clock")
def test_add_list_update_delete_roundtrip(vault, vault_dir):
    added = vault.add_entry(
        "https://www.Example.com/login",
        "  alice@example.com ",
        PASSWORD,
        label=" Work ",
    )
    assert set(added) == PUBLIC_KEYS
    assert added["site"] == "example.com"
    assert added["username"] == "alice@example.com"
    assert added["label"] == "Work"
    assert len(added["id"]) == 12 and int(added["id"], 16) >= 0
    assert added["createdAt"] == added["updatedAt"]
    assert added["lastUsedAt"] is None
    assert datetime.fromisoformat(added["createdAt"]).utcoffset() == timedelta(0)
    assert vault.list_entries() == [added]
    assert vault.status()["count"] == 1

    updated = vault.update_entry(
        added["id"],
        site="login.example.com",
        username="bob",
        password=NEW_PASSWORD,
        label="",
    )
    assert updated["id"] == added["id"]
    assert (updated["site"], updated["username"], updated["label"]) == (
        "login.example.com",
        "bob",
        "",
    )
    assert updated["createdAt"] == added["createdAt"]
    assert updated["updatedAt"] > added["updatedAt"]
    [candidate] = vault.candidates_for_url("https://login.example.com/")
    assert candidate["password"] == NEW_PASSWORD
    assert vault.candidates_for_url("https://example.com/") == []

    # Persisted: a new instance (empty cache) reads the same thing.
    assert CredentialVault(vault_dir).list_entries() == [updated]

    assert vault.delete_entry(added["id"]) is True
    assert vault.delete_entry(added["id"]) is False
    assert vault.delete_entry("") is False
    assert vault.delete_entry(None) is False
    assert vault.list_entries() == []
    assert CredentialVault(vault_dir).list_entries() == []


@pytest.mark.usefixtures("clock")
def test_add_upserts_on_site_and_username(vault):
    first = vault.add_entry(
        "example.com", "Alice@Example.com", PASSWORD, label="Personal"
    )
    second = vault.add_entry(
        "https://www.example.com/signin", "alice@example.com", NEW_PASSWORD
    )
    assert second["id"] == first["id"]
    assert len(vault.list_entries()) == 1
    assert second["label"] == "Personal"  # an empty label keeps the old one
    assert second["username"] == "alice@example.com"  # the latest spelling
    assert second["createdAt"] == first["createdAt"]
    assert second["updatedAt"] > first["updatedAt"]
    passwords = [
        c["password"] for c in vault.candidates_for_url("https://example.com/")
    ]
    assert passwords == [NEW_PASSWORD]

    third = vault.add_entry("example.com", "ALICE@example.com", NEW_PASSWORD, "Renamed")
    assert third["id"] == first["id"]
    assert third["label"] == "Renamed"

    vault.add_entry("example.com", "bob", OTHER_PASSWORD)  # another username
    vault.add_entry("example.org", "alice@example.com", OTHER_PASSWORD)  # another site
    vault.add_entry("example.com:8443", "alice@example.com", OTHER_PASSWORD)  # port
    assert len(vault.list_entries()) == 4


def test_list_entries_is_sorted_by_site_then_username(vault):
    vault.add_entry("zeta.example", "b", "pw-1-aaaa")
    vault.add_entry("alpha.example", "Zed", "pw-2-bbbb")
    vault.add_entry("alpha.example", "adam", "pw-3-cccc")
    listed = [(e["site"], e["username"]) for e in vault.list_entries()]
    assert listed == [
        ("alpha.example", "adam"),
        ("alpha.example", "Zed"),
        ("zeta.example", "b"),
    ]


@pytest.mark.usefixtures("clock")
def test_update_entry_rules(vault):
    alice = vault.add_entry("example.com", "alice", PASSWORD)
    bob = vault.add_entry("example.com", "bob", OTHER_PASSWORD)

    # None and "" keep the current password.
    vault.update_entry(alice["id"], password="")
    labelled = vault.update_entry(alice["id"], password=None, label="Main")
    assert labelled["label"] == "Main"
    by_user = {
        c["username"]: c["password"]
        for c in vault.candidates_for_url("https://example.com/")
    }
    assert by_user == {"alice": PASSWORD, "bob": OTHER_PASSWORD}

    # A no-op update does not bump updatedAt or rewrite the file.
    before = vault.vault_path.read_bytes()
    again = vault.update_entry(alice["id"], label="Main", site="www.example.com")
    assert again["updatedAt"] == labelled["updatedAt"]
    assert vault.vault_path.read_bytes() == before

    # A Secret works as well as a str.
    vault.update_entry(alice["id"], password=Secret(NEW_PASSWORD))
    by_user = {
        c["username"]: c["password"]
        for c in vault.candidates_for_url("https://example.com/")
    }
    assert by_user["alice"] == NEW_PASSWORD

    failing = [
        lambda: vault.update_entry(bob["id"], username="ALICE"),  # collision
        lambda: vault.update_entry(
            bob["id"], site="https://www.example.com/", username="alice"
        ),
        lambda: vault.update_entry("doesnotexist", label="x"),
        lambda: vault.update_entry(None, label="x"),
        lambda: vault.update_entry(alice["id"], site="not a site"),
        lambda: vault.update_entry(alice["id"], username="   "),
        lambda: vault.update_entry(alice["id"], password="p" * 1025),
        lambda: vault.update_entry(alice["id"], label="x" * 101),
    ]
    snapshot = vault.list_entries()
    for call in failing:
        with pytest.raises(VaultError) as info:
            call()
        assert info.value.code == CODE_INVALID
    assert vault.list_entries() == snapshot


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(site="", username="alice", password="pw-secret-1"),
        dict(site="my bank", username="alice", password="pw-secret-1"),
        dict(site=None, username="alice", password="pw-secret-1"),
        dict(site="example.com", username="", password="pw-secret-1"),
        dict(site="example.com", username="   ", password="pw-secret-1"),
        dict(site="example.com", username="a" * 257, password="pw-secret-1"),
        dict(site="example.com", username="ali" + chr(10) + "ce", password="pw-1"),
        dict(site="example.com", username=None, password="pw-secret-1"),
        dict(site="example.com", username=7, password="pw-secret-1"),
        dict(site="example.com", username="alice", password=""),
        dict(site="example.com", username="alice", password=None),
        dict(site="example.com", username="alice", password=12345678),
        dict(site="example.com", username="alice", password=LONG_PASSWORD),
        dict(site="example.com", username="alice", password="line1" + chr(10) + "x"),
        dict(site="example.com", username="alice", password="tab" + chr(9) + "here"),
        dict(site="example.com", username="alice", password="nul" + chr(0) + "byte"),
        dict(site="example.com", username="alice", password="pw-secret-1", label=42),
        dict(site="example.com", username="alice", password="pw-1", label="x" * 101),
        dict(site="example.com", username="alice", password="pw-1", label=chr(7)),
    ],
)
def test_add_entry_validation(vault, vault_dir, kwargs):
    with pytest.raises(VaultError) as info:
        vault.add_entry(**kwargs)
    assert info.value.code == CODE_INVALID
    assert info.value.detail
    password = kwargs.get("password")
    if isinstance(password, str) and len(password) >= 3:
        assert password not in str(info.value)
        assert password not in repr(info.value)
    # Nothing was written (not even a key).
    assert vault.list_entries() == []
    assert not vault_dir.exists()


def test_add_entry_accepts_limits_and_keeps_passwords_verbatim(vault):
    spaced = "  spaced pässwörd 日本  "
    vault.add_entry("example.com", "u" * 256, "p" * 1024, label="l" * 100)
    vault.add_entry("example.org", "alice", spaced)
    [candidate] = vault.candidates_for_url("https://example.org/")
    assert candidate["password"] == spaced  # never stripped or normalised
    [candidate] = vault.candidates_for_url("https://example.com/")
    assert len(candidate["password"]) == 1024


def test_entry_limit(vault, monkeypatch):
    monkeypatch.setattr(vault_mod, "MAX_ENTRIES", 2)
    vault.add_entry("a.example.com", "u", "pw-aaaa")
    vault.add_entry("b.example.com", "u", "pw-bbbb")
    with pytest.raises(VaultError) as info:
        vault.add_entry("c.example.com", "u", "pw-cccc")
    assert info.value.code == CODE_INVALID
    vault.add_entry("a.example.com", "U", "pw-new1")  # an upsert still works
    assert len(vault.list_entries()) == 2


# ─── no passwords out ───────────────────────────────────────────────────


def test_public_results_never_contain_passwords(vault):
    username, label = "alice.distinctive@example.com", "Distinctive label text"
    added = vault.add_entry("example.com", username, PASSWORD, label=label)
    updated = vault.update_entry(added["id"], password=NEW_PASSWORD)
    other = vault.add_entry("bank.example", "bob", Secret(OTHER_PASSWORD))
    for value in (added, updated, other, vault.list_entries(), vault.status()):
        _assert_no_secret(value)
        assert "password" not in json.dumps(value)

    # The files on disk never hold plaintext. (The probes contain characters
    # outside the base64 alphabets, so they cannot appear in the ciphertext.)
    vault.add_entry("example.net", "carol", PASSWORD)  # creates the .enc.bak
    raw = b"".join(
        path.read_bytes()
        for path in (vault.vault_path, vault.key_path, vault.previous_path)
    )
    for plain in (*SECRETS, username, label, "example.com"):
        assert plain.encode() not in raw

    # Only candidates_for_url returns passwords, and their repr is redacted.
    candidates = vault.candidates_for_url("https://example.com/")
    assert [c["password"] for c in candidates] == [NEW_PASSWORD]
    for text in (
        repr(candidates),
        str(candidates),
        f"{candidates[0]}",
        repr(vault),
        repr(Secret(PASSWORD)),
        str(Secret(PASSWORD)),
        f"{Secret(PASSWORD)}",
    ):
        _assert_no_secret(text)


def test_secret_wrapper():
    secret = Secret(PASSWORD)
    assert secret.reveal() == PASSWORD
    assert Secret.wrap(secret) is secret
    assert Secret.wrap(PASSWORD).reveal() == PASSWORD
    assert bool(Secret("")) is False and bool(secret) is True
    with pytest.raises(TypeError):
        json.dumps({"password": secret})
    import pickle

    with pytest.raises(TypeError):
        pickle.dumps(secret)


def _login(site="example.com", username="alice"):
    return site, username, PASSWORD


def _too_long_login():
    return "example.com", "alice", LONG_PASSWORD


def _multiline_login():
    return "example.com", "alice", NEW_PASSWORD + chr(10) + "second-line"


def _new_password():
    return {"password": NEW_PASSWORD}


def _other_login():
    return "example.org", "bob", OTHER_PASSWORD


def _log_failure(call) -> None:
    try:
        call()
    except VaultError:
        logger.exception("vault operation failed")


def test_logged_tracebacks_never_show_passwords(vault, monkeypatch):
    """The app's loguru sinks use diagnose=True, which prints the values of
    the variables on every traceback line. Vault frames must never hold a raw
    password on such a line. (Call lines below take their arguments from
    helpers, so this test's own frames hold no raw password either.)"""
    records = []
    sink = logger.add(
        records.append,
        level="DEBUG",
        format="{message}",
        backtrace=True,
        diagnose=True,
        colorize=False,
    )
    try:
        vault.add_entry(*_login())
        entry_id = vault.list_entries()[0]["id"]

        _log_failure(lambda: vault.add_entry(*_too_long_login()))
        _log_failure(lambda: vault.add_entry(*_multiline_login()))

        real_replace = os.replace

        def failing_replace(src, dst, *args, **kwargs):
            if Path(dst) == vault.vault_path:
                raise OSError(errno.EIO, "Input/output error")
            return real_replace(src, dst, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(vault_mod.os, "replace", failing_replace)
            _log_failure(lambda: vault.update_entry(entry_id, **_new_password()))
            _log_failure(lambda: vault.add_entry(*_other_login()))

        _swap_file(vault.vault_path, b"corrupted")
        _log_failure(lambda: vault.add_entry(*_other_login()))
        _log_failure(lambda: vault.update_entry(entry_id, **_new_password()))
    finally:
        logger.remove(sink)

    text = "\n".join(str(record) for record in records)
    assert text.count("vault operation failed") == 6
    assert "Traceback" in text
    assert "Secret('[redacted]')" in text  # diagnose did annotate the wrapper
    _assert_no_secret(text)
    assert "second-line" not in text


# ─── candidates and usage ───────────────────────────────────────────────


@pytest.mark.usefixtures("clock")
def test_candidates_are_the_page_hosts_own_logins_most_recently_used_first(vault):
    old = vault.add_entry("amazon.com", "old-user", "pw-old-1")
    vault.add_entry("signin.amazon.com", "sub-user", "pw-sub-2")
    recent = vault.add_entry("amazon.com", "recent-user", "pw-recent-3")
    vault.add_entry("amazon.co.jp", "jp-user", "pw-jp-4")
    vault.add_entry("example.com", "x", "pw-x-5")
    vault.mark_used(old["id"])
    vault.mark_used(recent["id"])

    # A sign-in host gets only its own logins, never its parent's.
    on_signin = vault.candidates_for_url("https://signin.amazon.com/ap/signin")
    assert _usernames(on_signin) == ["sub-user"]
    on_www = vault.candidates_for_url("https://www.amazon.com/")
    assert _usernames(on_www) == ["recent-user", "old-user"]

    vault.mark_used(old["id"])
    on_apex = vault.candidates_for_url("https://amazon.com/")
    assert _usernames(on_apex) == ["old-user", "recent-user"]

    # Never-used entries come after used ones, newest change first.
    fresh = vault.add_entry("amazon.com", "fresh-user", "pw-fresh-6")
    assert _usernames(vault.candidates_for_url("https://amazon.com/")) == [
        "old-user",
        "recent-user",
        "fresh-user",
    ]

    candidate = vault.candidates_for_url("https://amazon.com/")[0]
    assert set(candidate) == PUBLIC_KEYS | {"password"}
    assert candidate["password"] == "pw-old-1"
    candidate["password"] = "tampered"  # results are copies
    assert vault.candidates_for_url("https://amazon.com/")[0]["password"] == "pw-old-1"

    assert vault.candidates_for_url("http://amazon.com/") == []
    assert vault.candidates_for_url("not a url") == []
    assert vault.candidates_for_url(None) == []
    assert fresh["id"] in {
        c["id"] for c in vault.candidates_for_url("https://www.amazon.com")
    }
    assert vault.candidates_for_url("https://a.amazon.com") == []


def test_a_main_site_login_is_never_offered_on_someone_elses_subdomain(vault):
    """Security SEC-3: saving the sign-in URL https://www.tumblr.com/login
    stores "tumblr.com"; that must not make the password fill (and submit)
    on attacker-blog.tumblr.com, a page someone else controls."""
    saved = vault.add_entry("https://www.tumblr.com/login", "jo", "tumblr-pw-1")
    assert saved["site"] == "tumblr.com"
    for url in (
        "https://attacker-blog.tumblr.com/",
        "https://attacker-blog.tumblr.com/login",
        "https://www.attacker-blog.tumblr.com/",
        "https://tumblr.com.evil.example/",
    ):
        assert vault.candidates_for_url(url) == [], url
    for url in ("https://www.tumblr.com/login", "https://tumblr.com/"):
        assert _usernames(vault.candidates_for_url(url)) == ["jo"], url


@pytest.mark.usefixtures("clock")
def test_mark_used(vault):
    entry = vault.add_entry("example.com", "alice", PASSWORD)
    vault.mark_used(entry["id"])
    [listed] = vault.list_entries()
    assert listed["lastUsedAt"] is not None
    assert listed["lastUsedAt"] > entry["updatedAt"]
    assert listed["updatedAt"] == entry["updatedAt"]  # using is not editing

    before = vault.vault_path.read_bytes()
    for bogus in ("unknown-id12", None, "", 42):
        vault.mark_used(bogus)  # silently ignored
    assert vault.vault_path.read_bytes() == before


# ─── fresh vault, files and keys ────────────────────────────────────────


def test_reads_on_a_fresh_vault_have_no_side_effects(vault, vault_dir):
    status = vault.status()
    assert status == {
        "ok": True,
        "unreadable": False,
        "count": 0,
        "protection": vault_mod._expected_protection(),
    }
    assert vault.list_entries() == []
    assert vault.candidates_for_url("https://example.com/") == []
    assert vault.delete_entry("abcdef123456") is False
    vault.mark_used("abcdef123456")
    with pytest.raises(VaultError) as info:
        vault.update_entry("abcdef123456", label="x")
    assert info.value.code == CODE_INVALID
    with pytest.raises(VaultError) as info:
        vault.reset_unreadable()
    assert info.value.code == CODE_INVALID
    assert not vault_dir.exists()


def test_previous_version_is_kept(vault):
    vault.add_entry("example.com", "alice", PASSWORD)
    assert not vault.previous_path.exists()
    first = vault.vault_path.read_bytes()
    vault.add_entry("example.org", "bob", OTHER_PASSWORD)
    assert vault.previous_path.read_bytes() == first
    # The backup is a complete vault encrypted with the same key.
    document = json.loads(_fernet_for(vault).decrypt(vault.previous_path.read_bytes()))
    assert _usernames(document["entries"]) == ["alice"]


def test_vault_document_format(vault):
    entry = vault.add_entry("example.com", "alice", PASSWORD, label="Main")
    document = json.loads(_fernet_for(vault).decrypt(vault.vault_path.read_bytes()))
    assert document == {
        "version": 1,
        "entries": [
            {
                "id": entry["id"],
                "site": "example.com",
                "username": "alice",
                "password": PASSWORD,
                "label": "Main",
                "createdAt": entry["createdAt"],
                "updatedAt": entry["updatedAt"],
                "lastUsedAt": None,
            }
        ],
    }


def test_unknown_fields_survive_and_duplicate_ids_are_repaired(vault):
    vault.add_entry("example.com", "alice", PASSWORD)
    fernet = _fernet_for(vault)
    document = json.loads(fernet.decrypt(vault.vault_path.read_bytes()))
    entry = document["entries"][0]
    entry["futureField"] = {"keep": True}
    twin = dict(entry, username="bob", password=OTHER_PASSWORD)
    document["entries"].append(twin)  # same id as the first entry
    _swap_file(vault.vault_path, fernet.encrypt(json.dumps(document).encode()))

    listed = vault.list_entries()
    assert len({e["id"] for e in listed}) == 2
    vault.add_entry("example.org", "carol", NEW_PASSWORD)  # forces a save
    saved = json.loads(fernet.decrypt(vault.vault_path.read_bytes()))["entries"]
    assert saved[0]["futureField"] == {"keep": True}
    assert len({e["id"] for e in saved}) == 3


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_key_is_dpapi_wrapped_on_windows(vault):
    if not vault_mod._dpapi_backends():
        pytest.skip("no DPAPI implementation available")
    vault.add_entry("example.com", "alice", PASSWORD)
    content = vault.key_path.read_bytes()
    assert content.startswith(b"dpapi:")
    blob = base64.b64decode(content[len(b"dpapi:") :], validate=True)
    assert vault.status()["protection"] == "dpapi"
    key = vault_mod._dpapi_backends()[0].unprotect(blob)
    from cryptography.fernet import Fernet

    document = json.loads(Fernet(key).decrypt(vault.vault_path.read_bytes()))
    assert document["entries"][0]["password"] == PASSWORD


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_dpapi_roundtrip_with_both_implementations():
    backends = {backend.name: backend for backend in vault_mod._dpapi_backends()}
    if "win32crypt" not in backends or "ctypes" not in backends:
        pytest.skip("pywin32 (win32crypt) is not available")
    data = os.urandom(44)
    for protector in backends.values():
        blob = protector.protect(data)
        assert data not in blob
        for unprotector in backends.values():
            assert unprotector.unprotect(blob) == data
    tampered = blob[:-1] + bytes([blob[-1] ^ 0x01])
    for backend in backends.values():
        with pytest.raises(Exception):
            backend.unprotect(tampered)


def test_raw_key_when_dpapi_is_unavailable(vault_dir, monkeypatch):
    monkeypatch.setattr(vault_mod, "_dpapi_backends", lambda: ())
    vault = CredentialVault(vault_dir)
    assert vault.status()["protection"] == "file"
    vault.add_entry("example.com", "alice", PASSWORD)
    content = vault.key_path.read_bytes()
    assert content.startswith(b"raw:")
    from cryptography.fernet import Fernet

    Fernet(content[len(b"raw:") :])  # a valid Fernet key
    assert CredentialVault(vault_dir).status() == {
        "ok": True,
        "unreadable": False,
        "count": 1,
        "protection": "file",
    }


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_posix_permissions(vault):
    vault.add_entry("example.com", "alice", PASSWORD)
    vault.add_entry("example.org", "bob", OTHER_PASSWORD)
    assert stat.S_IMODE(os.stat(vault.directory).st_mode) == 0o700
    for path in (vault.vault_path, vault.key_path, vault.previous_path):
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_publish_new_file_never_replaces(tmp_path):
    target = tmp_path / "key"
    vault_mod._publish_new_file(target, b"first")
    with pytest.raises(FileExistsError):
        vault_mod._publish_new_file(target, b"second")
    assert target.read_bytes() == b"first"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["key"]  # no temp left


def test_get_vault_is_a_lazy_singleton_in_project_credentials():
    from app.config import PROJECT_ROOT

    vault = get_vault()
    assert vault is get_vault()
    assert vault.directory == Path(PROJECT_ROOT) / ".credentials"
    assert vault.vault_path.name == "mini_browser_vault.enc"
    assert vault.key_path.name == "mini_browser_vault.key"


def test_vault_error_is_a_mini_browser_error():
    error = VaultError(CODE_INVALID, detail="Enter the password for this login.")
    assert isinstance(error, MiniBrowserError)
    assert error.code == CODE_INVALID
    assert error.detail == "Enter the password for this login."
    rendered = ui_error(error.code, **error.fields)
    assert rendered["code"] == CODE_INVALID
    assert "Enter the password" in rendered["message"]
    assert ui_error(CODE_UNREADABLE)["title"]
    assert VaultError(CODE_IO, detail="Disk full").code == CODE_IO


# ─── unreadable vaults ──────────────────────────────────────────────────


def _assert_unreadable_and_untouched(vault: CredentialVault) -> None:
    files = {
        path: path.read_bytes()
        for path in (vault.vault_path, vault.key_path)
        if path.exists()
    }
    status = vault.status()
    assert status["unreadable"] is True
    assert status["ok"] is False
    assert status["count"] == 0
    assert vault.list_entries() == []
    assert vault.candidates_for_url("https://example.com/") == []
    writes = [
        lambda: vault.add_entry("example.org", "bob", OTHER_PASSWORD),
        lambda: vault.update_entry("abcdef123456", label="x"),
        lambda: vault.delete_entry("abcdef123456"),
    ]
    for write in writes:
        with pytest.raises(VaultError) as info:
            write()
        assert info.value.code == CODE_UNREADABLE
    vault.mark_used("abcdef123456")  # best effort: no exception
    assert {
        path: path.read_bytes()
        for path in (vault.vault_path, vault.key_path)
        if path.exists()
    } == files
    # A fresh instance (no cache) agrees.
    assert CredentialVault(vault.directory).status()["unreadable"] is True


def test_corrupt_vault_is_unreadable_and_preserved(vault):
    vault.add_entry("example.com", "alice", PASSWORD)
    _swap_file(vault.vault_path, b"this is not a fernet token")
    _assert_unreadable_and_untouched(vault)


def test_empty_vault_file_is_unreadable(vault):
    vault.add_entry("example.com", "alice", PASSWORD)
    _swap_file(vault.vault_path, b"")
    _assert_unreadable_and_untouched(vault)


def test_missing_key_is_unreadable_and_never_regenerated(vault):
    vault.add_entry("example.com", "alice", PASSWORD)
    vault.key_path.unlink()
    _assert_unreadable_and_untouched(vault)
    assert not vault.key_path.exists()


def test_swapped_key_is_unreadable_until_the_right_key_returns(tmp_path):
    first = CredentialVault(tmp_path / "first")
    second = CredentialVault(tmp_path / "second")
    first.add_entry("example.com", "alice", PASSWORD)
    second.add_entry("example.org", "bob", OTHER_PASSWORD)
    original_key = first.key_path.read_bytes()

    _swap_file(first.key_path, second.key_path.read_bytes())
    _assert_unreadable_and_untouched(first)

    _swap_file(first.key_path, original_key)  # nothing was lost
    assert first.status()["ok"] is True
    [candidate] = first.candidates_for_url("https://example.com/")
    assert candidate["password"] == PASSWORD


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"hello",
        b"raw:",
        b"raw:not-a-fernet-key",
        b"dpapi:!!!not-base64!!!",
        b"dpapi:" + base64.b64encode(b"not a dpapi blob"),
        b"nonsense:" + base64.b64encode(b"x" * 32),
    ],
)
def test_damaged_key_file_is_unreadable(vault, content):
    vault.add_entry("example.com", "alice", PASSWORD)
    _swap_file(vault.key_path, content)
    _assert_unreadable_and_untouched(vault)


def test_damaged_key_without_a_vault_is_unreadable_until_reset(vault, vault_dir):
    vault_dir.mkdir()
    vault.key_path.write_bytes(b"dpapi:" + base64.b64encode(b"garbage"))
    _assert_unreadable_and_untouched(vault)
    backup = Path(vault.reset_unreadable())
    assert backup.name.endswith(".key.bak")
    assert backup.read_bytes() == b"dpapi:" + base64.b64encode(b"garbage")
    vault.add_entry("example.com", "alice", PASSWORD)
    assert vault.status()["count"] == 1


def test_dpapi_key_on_a_system_without_dpapi_is_unreadable(vault, monkeypatch):
    vault.add_entry("example.com", "alice", PASSWORD)
    if not vault.key_path.read_bytes().startswith(b"dpapi:"):
        _swap_file(vault.key_path, b"dpapi:" + base64.b64encode(b"blob"))
    monkeypatch.setattr(vault_mod, "_dpapi_backends", lambda: ())
    _assert_unreadable_and_untouched(CredentialVault(vault.directory))


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"version": 2, "entries": []}',
        b'{"version": 1}',
        b'{"version": 1, "entries": {}}',
        b'{"version": 1, "entries": ["x"]}',
        b'{"version": 1, "entries": [{"id": "abc"}]}',
        b'{"version": 1, "entries": [{"id": "a", "site": "s.com", "username": "u"}]}',
        bytes([0xFF, 0xFE, 0x00]),
    ],
)
def test_damaged_document_inside_a_valid_token_is_unreadable(vault, payload):
    vault.add_entry("example.com", "alice", PASSWORD)
    _swap_file(vault.vault_path, _fernet_for(vault).encrypt(payload))
    _assert_unreadable_and_untouched(vault)


def test_reset_unreadable_keeps_backups_and_starts_fresh(vault):
    vault.add_entry("example.com", "alice", PASSWORD)
    vault.add_entry("example.org", "bob", OTHER_PASSWORD)  # creates the .enc.bak
    old_key = vault.key_path.read_bytes()
    old_previous = vault.previous_path.read_bytes()
    _swap_file(vault.vault_path, b"garbage")

    backup = Path(vault.reset_unreadable())
    assert backup.parent == vault.directory
    assert backup.name.startswith("mini_browser_vault.unreadable-")
    assert backup.name.endswith(".enc.bak")
    assert backup.read_bytes() == b"garbage"
    stem = backup.name[: -len(".enc.bak")]
    assert (vault.directory / f"{stem}.key.bak").read_bytes() == old_key
    assert (vault.directory / f"{stem}.prev.enc.bak").read_bytes() == old_previous
    for path in (vault.vault_path, vault.key_path, vault.previous_path):
        assert not path.exists()

    assert vault.status()["ok"] is True
    assert vault.list_entries() == []
    vault.add_entry("example.com", "alice", NEW_PASSWORD)
    assert vault.key_path.read_bytes() != old_key  # a brand-new key
    [candidate] = vault.candidates_for_url("https://example.com/")
    assert candidate["password"] == NEW_PASSWORD

    with pytest.raises(VaultError) as info:
        vault.reset_unreadable()  # readable again: nothing to reset
    assert info.value.code == CODE_INVALID

    # A second reset in the same second gets its own backup names.
    _swap_file(vault.vault_path, b"garbage again")
    second = Path(vault.reset_unreadable())
    assert second != backup
    assert backup.read_bytes() == b"garbage"


def test_missing_cryptography_is_reported_not_unreadable(vault, monkeypatch):
    vault.add_entry("example.com", "alice", PASSWORD)

    def no_cryptography():
        raise ImportError("No module named 'cryptography'")

    fresh = CredentialVault(vault.directory)
    with monkeypatch.context() as patch:
        patch.setattr(vault_mod, "_fernet_api", no_cryptography)
        status = fresh.status()
        assert (status["ok"], status["unreadable"], status["count"]) == (
            False,
            False,
            0,
        )
        assert fresh.list_entries() == []
        with pytest.raises(VaultError) as info:
            fresh.add_entry("example.org", "bob", OTHER_PASSWORD)
        assert info.value.code == CODE_IO
        with pytest.raises(VaultError) as info:
            fresh.reset_unreadable()  # the vault itself is fine
        assert info.value.code == CODE_INVALID

    assert fresh.status()["count"] == 1  # back as soon as the dependency is


# ─── atomicity and concurrency ──────────────────────────────────────────


def test_failed_save_keeps_the_original(vault, monkeypatch):
    vault.add_entry("example.com", "alice", PASSWORD)
    before = vault.vault_path.read_bytes()
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst) == vault.vault_path:
            raise OSError(errno.EIO, "Input/output error")
        return real_replace(src, dst, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(vault_mod.os, "replace", failing_replace)
        with pytest.raises(VaultError) as info:
            vault.add_entry("example.org", "bob", OTHER_PASSWORD)
        assert info.value.code == CODE_IO
        assert info.value.detail == "Input/output error"
        assert vault.vault_path.read_bytes() == before
        assert _usernames(vault.list_entries()) == ["alice"]  # memory unchanged too

    assert not [name for name in os.listdir(vault.directory) if name.endswith(".tmp")]
    vault.add_entry("example.org", "bob", OTHER_PASSWORD)  # and it still works
    assert sorted(_usernames(vault.list_entries())) == ["alice", "bob"]


def test_failed_first_save_leaves_a_usable_vault(vault, monkeypatch):
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst) == vault.vault_path:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_replace(src, dst, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(vault_mod.os, "replace", failing_replace)
        with pytest.raises(VaultError) as info:
            vault.add_entry("example.com", "alice", PASSWORD)
        assert info.value.code == CODE_IO

    assert not vault.vault_path.exists()
    assert vault.status()["ok"] is True  # the key alone is a valid empty vault
    vault.add_entry("example.com", "alice", PASSWORD)
    assert vault.status()["count"] == 1


def test_key_is_never_created_while_a_vault_file_exists(vault, monkeypatch):
    assert vault.status()["ok"] is True  # fresh state is now cached
    real_now = vault_mod._now

    def vault_appears_meanwhile() -> str:
        vault.directory.mkdir(parents=True, exist_ok=True)
        vault.vault_path.write_bytes(b"written by another program")
        return real_now()

    monkeypatch.setattr(vault_mod, "_now", vault_appears_meanwhile)
    with pytest.raises(VaultError) as info:
        vault.add_entry("example.com", "alice", PASSWORD)
    assert info.value.code == CODE_IO
    assert not vault.key_path.exists()
    assert vault.vault_path.read_bytes() == b"written by another program"

    monkeypatch.setattr(vault_mod, "_now", real_now)
    assert vault.status()["unreadable"] is True  # a vault without its key


def test_concurrent_writers_are_all_persisted(vault):
    errors = []

    def writer(n: int) -> None:
        try:
            for i in range(5):
                vault.add_entry(f"site{n}.example.com", f"user{i}", f"pw-{n}-{i}-xx")
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(40):
                vault.list_entries()
                vault.status()
                vault.candidates_for_url("https://site1.example.com/")
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    threads += [threading.Thread(target=reader) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert len(vault.list_entries()) == 40
    assert len(CredentialVault(vault.directory).list_entries()) == 40


def test_instances_on_one_directory_share_a_lock_and_see_each_other(vault_dir):
    first, second = CredentialVault(vault_dir), CredentialVault(vault_dir)
    first.add_entry("example.com", "alice", PASSWORD)
    assert _usernames(second.list_entries()) == ["alice"]  # cache follows the file
    second.add_entry("example.org", "bob", OTHER_PASSWORD)
    assert sorted(_usernames(first.list_entries())) == ["alice", "bob"]

    errors = []

    def writer(vault: CredentialVault, tag: str) -> None:
        try:
            for i in range(10):
                vault.add_entry(f"{tag}.example.net", f"user{i}", f"pw-{tag}-{i}")
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(first, "one")),
        threading.Thread(target=writer, args=(second, "two")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not errors
    assert len(CredentialVault(vault_dir).list_entries()) == 22
