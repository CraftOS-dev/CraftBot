"""WhatsApp Web bridge provider — conformance + multi-account plumbing.

No Node, no Chromium: the bridge registry is exercised with tmp auth
dirs and a FakeBridge class monkeypatched over ``WhatsAppBridge``; QR
session bookkeeping runs against the same fakes. What's real is the
identity normalization, the registry (register / rekey / drop / cap /
old-layout migration), the QR-session lifecycle (uuid ids, connected
result carrying identity + credential, cancel cleanup), and the binding
chain that gives each bound client its own account's bridge.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import craftos_integrations.integrations.whatsapp_web as wa_mod
import craftos_integrations.integrations.whatsapp_web._bridge_client as bc
from craftos_integrations.integrations.whatsapp_web import (
    WhatsAppWebCredential,
    cancel_qr_session,
    check_qr_session_status,
    start_qr_session,
)
from craftos_integrations.integrations.whatsapp_web._bridge_client import (
    BridgeCapacityError,
    normalize_wa_identity,
)
from craftos_integrations.providers._shared import LegacyListenerAdapter
from craftos_integrations.providers.whatsapp_web import (
    WhatsAppWebProvider,
    teardown_account,
)
from craftos_integrations.providers.whatsapp_web.provider import (
    BoundWhatsAppWebClient,
)

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Realistic post-QR shape, fake values: the legacy dataclass fields plus
# the provider-level ``wid`` captured from the bridge's ready event.
WA_CRED = {
    "session_id": "14155552671",
    "owner_phone": "14155552671",
    "owner_name": "Ada Lovelace",
    "wid": "14155552671:12@c.us",
}

# Legacy whatsapp_web.json shape — saved by the pre-multi-account flow.
# owner_phone still resolves an identity (migration lands on the right
# account, not LEGACY_IDENTITY).
LEGACY_WA_CRED = {
    "session_id": "bridge",
    "owner_phone": "14155552671",
    "owner_name": "Ada",
}


class TestWhatsAppWebConformance(ProviderConformance):
    provider = WhatsAppWebProvider()
    credential_fixtures = [
        WA_CRED,
        LEGACY_WA_CRED,
        {},  # junk
    ]


# ════════════════════════════════════════════════════════════════════════
# Identity normalization — the ONE rule
# ════════════════════════════════════════════════════════════════════════


def test_normalize_wa_identity():
    assert normalize_wa_identity("14155552671") == "14155552671"
    assert normalize_wa_identity("14155552671@c.us") == "14155552671"
    # wid with device suffix
    assert normalize_wa_identity("14155552671:12@c.us") == "14155552671"
    assert normalize_wa_identity("14155552671:3") == "14155552671"
    # +country / punctuation formatting
    assert normalize_wa_identity("+1 (415) 555-2671") == "14155552671"
    # 00-international prefix collapses to the same identity
    assert normalize_wa_identity("0014155552671") == "14155552671"
    assert normalize_wa_identity(14155552671) == "14155552671"
    # junk never raises
    assert normalize_wa_identity(None) is None
    assert normalize_wa_identity("") is None
    assert normalize_wa_identity("   ") is None
    assert normalize_wa_identity("no digits here") is None
    assert normalize_wa_identity("000") is None


def test_identity_of_prefers_wid_falls_back_to_phone():
    provider = WhatsAppWebProvider()
    assert provider.identity_of(WA_CRED) == "14155552671"
    # wid wins when both present (WhatsApp's own id)
    assert (
        provider.identity_of(
            {"wid": "923001234567:2@c.us", "owner_phone": "+1 415 555 2671"}
        )
        == "923001234567"
    )
    # legacy credential: phone only
    assert provider.identity_of(LEGACY_WA_CRED) == "14155552671"
    assert provider.identity_of({"owner_phone": "+92 300 1234567"}) == "923001234567"
    assert provider.identity_of({}) is None
    assert provider.identity_of({"owner_phone": ""}) is None
    assert provider.identity_of({"wid": "junk", "owner_phone": None}) is None


def test_qr_only_no_oauth_no_run_login_no_verify_token():
    provider = WhatsAppWebProvider()
    with pytest.raises(NotImplementedError):
        provider.oauth_spec()
    assert not hasattr(provider, "run_login")
    assert not hasattr(provider, "verify_token")  # QR is the only connect path
    assert provider.operations() == []
    assert provider.guidance() == ""
    assert run(provider.refresh(dict(WA_CRED))) is None


# ════════════════════════════════════════════════════════════════════════
# Bridge registry — tmp dirs, no Node
# ════════════════════════════════════════════════════════════════════════


@pytest.fixture
def bridge_env(tmp_path, monkeypatch):
    """Isolated registry: tmp project root, no legacy credential, clean
    registry (and session manager / link flows) before and after."""
    monkeypatch.setattr(bc.ConfigStore, "project_root", tmp_path)
    bc._reset_bridge_registry_for_tests()
    yield tmp_path
    bc._reset_bridge_registry_for_tests()


class FakeBridge:
    """WhatsAppBridge stand-in: same lifecycle surface, zero processes."""

    def __init__(self, auth_dir: str):
        self.auth_dir = auth_dir
        self._running = False
        self._ready = False
        self.owner_phone = ""
        self.owner_name = ""
        self.wid = ""
        self.logged_out = False
        self._event_callback = None

    @property
    def is_running(self):
        return self._running

    @property
    def is_ready(self):
        return self._ready and self._running

    def set_event_callback(self, cb):
        self._event_callback = cb

    async def start(self):
        self._running = True
        Path(self.auth_dir, "session").mkdir(parents=True, exist_ok=True)

    async def wait_for_qr_or_ready(self, timeout=60.0):
        if self._ready:
            return "ready", {}
        return "qr", {"qr_data_url": "data:image/png;base64,QUFBQQ=="}

    async def wait_exited(self):
        await asyncio.sleep(3600)

    async def ping(self, timeout=10.0):
        return {"success": True, "ready": self.is_ready}

    async def stop(self):
        self._running = False

    async def abandon(self):
        self._running = False

    async def logout(self):
        self._running = False
        self.logged_out = True
        import shutil

        shutil.rmtree(self.auth_dir, ignore_errors=True)


@pytest.fixture
def fake_bridges(bridge_env, monkeypatch):
    """bridge_env plus WhatsAppBridge replaced by FakeBridge."""
    monkeypatch.setattr(bc, "WhatsAppBridge", FakeBridge)
    return bridge_env


def test_registry_keys_by_normalized_identity(bridge_env):
    a = bc.get_whatsapp_bridge("14155552671")
    assert a is bc.get_whatsapp_bridge("14155552671")  # cached
    # Any spelling of the same account resolves to the same bridge.
    assert a is bc.get_whatsapp_bridge("+1 (415) 555-2671")
    assert a is bc.get_whatsapp_bridge("14155552671:12@c.us")
    assert Path(a.auth_dir) == bridge_env / ".credentials" / "whatsapp_wwebjs_auth" / "14155552671"

    b = bc.get_whatsapp_bridge("923001234567")
    assert b is not a
    assert Path(b.auth_dir).name == "923001234567"

    with pytest.raises(ValueError):
        bc.get_whatsapp_bridge("no digits")


def test_registry_peek_and_drop(bridge_env):
    assert bc.peek_whatsapp_bridge("14155552671") is None
    a = bc.get_whatsapp_bridge("14155552671")
    assert bc.peek_whatsapp_bridge("+1 415 555 2671") is a
    assert bc.drop_whatsapp_bridge("14155552671") is a
    assert bc.peek_whatsapp_bridge("14155552671") is None
    assert bc.drop_whatsapp_bridge("14155552671") is None  # idempotent
    assert bc.get_whatsapp_bridge("14155552671") is not a  # fresh after drop


def test_no_identity_and_no_legacy_credential_raises(bridge_env, monkeypatch):
    """Legacy removal (§2.8): the ``default`` slot is gone — an
    identity-less request with nothing to resolve from fails loudly."""
    monkeypatch.setattr(bc, "_legacy_owner_identity", lambda: None)
    with pytest.raises(RuntimeError):
        bc.get_whatsapp_bridge()


def test_legacy_resolution_uses_credential_identity(bridge_env, monkeypatch):
    # One-release straggler path: a surviving whatsapp_web.json still
    # resolves the identity for identity-less callers.
    monkeypatch.setattr(bc, "_legacy_owner_identity", lambda: "14155552671")
    bridge = bc.get_whatsapp_bridge()
    assert Path(bridge.auth_dir).name == "14155552671"
    # Same account requested by identity → same instance.
    assert bc.get_whatsapp_bridge("14155552671") is bridge


def test_legacy_guard_machinery_is_gone(bridge_env):
    """§2.8: the legacy_guard orphan-wipe (one misplaced call away from
    wiping a v2 account's LocalAuth) no longer exists at all."""
    bridge = bc.get_whatsapp_bridge("14155552671")
    assert not hasattr(bridge, "_legacy_guard")
    assert not hasattr(bridge, "_wipe_orphan_localauth_if_disconnected")


# ── pending → promote (rekey) ────────────────────────────────────────────


def test_pending_bridge_lifecycle_and_promote(fake_bridges):
    root = fake_bridges / ".credentials" / "whatsapp_wwebjs_auth"
    pending = bc.create_pending_bridge("sess1")
    assert bc.create_pending_bridge("sess1") is pending  # stable per session
    assert Path(pending.auth_dir) == root / "pending-sess1"

    run(pending.start())
    (Path(pending.auth_dir) / "session" / "creds.json").write_text("fresh")

    promoted = run(bc.promote_pending_bridge("sess1", "+1 415 555 2671"))
    assert Path(promoted.auth_dir) == root / "14155552671"
    assert (root / "14155552671" / "session" / "creds.json").read_text() == "fresh"
    assert not (root / "pending-sess1").exists()
    # Re-keyed: identity registered, session key gone, pending stopped.
    assert bc.peek_whatsapp_bridge("14155552671") is promoted
    assert bc._bridges.get("sess1") is None
    assert not pending.is_running
    assert not promoted.is_running  # host starts it (LocalAuth restores)


def test_promote_same_account_relogin_prefers_fresh_session(fake_bridges):
    root = fake_bridges / ".credentials" / "whatsapp_wwebjs_auth"
    # Existing connected account with an old session on disk + live bridge.
    old = bc.get_whatsapp_bridge("14155552671")
    run(old.start())
    (Path(old.auth_dir) / "session" / "creds.json").write_text("stale")

    pending = bc.create_pending_bridge("sess2")
    run(pending.start())
    (Path(pending.auth_dir) / "session" / "creds.json").write_text("fresh")

    promoted = run(bc.promote_pending_bridge("sess2", "14155552671"))
    assert (root / "14155552671" / "session" / "creds.json").read_text() == "fresh"
    assert not old.is_running  # old bridge stopped and replaced
    assert bc.peek_whatsapp_bridge("14155552671") is promoted


def test_promote_unknown_session_raises(fake_bridges):
    with pytest.raises(KeyError):
        run(bc.promote_pending_bridge("nope", "14155552671"))


def test_discard_pending_bridge_cleans_dir_and_registry(fake_bridges):
    pending = bc.create_pending_bridge("sess3")
    run(pending.start())
    assert Path(pending.auth_dir).exists()
    run(bc.discard_pending_bridge("sess3"))
    assert not Path(pending.auth_dir).exists()
    assert bc._bridges.get("sess3") is None
    assert not pending.is_running
    run(bc.discard_pending_bridge("sess3"))  # idempotent


# ── capacity cap ─────────────────────────────────────────────────────────


def test_capacity_cap_blocks_pending_beyond_max(fake_bridges, monkeypatch):
    monkeypatch.setattr(bc, "max_whatsapp_accounts", lambda: 1)
    bc.create_pending_bridge("sess1")
    with pytest.raises(BridgeCapacityError) as excinfo:
        bc.create_pending_bridge("sess2")
    message = str(excinfo.value)
    assert "RAM" in message and "max_accounts" in message  # names the cost + the knob


def test_capacity_counts_identity_dirs_on_disk(fake_bridges, monkeypatch):
    monkeypatch.setattr(bc, "max_whatsapp_accounts", lambda: 1)
    # A connected account from a previous run: auth dir on disk, nothing
    # registered in this process yet.
    (fake_bridges / ".credentials" / "whatsapp_wwebjs_auth" / "14155552671").mkdir(
        parents=True
    )
    with pytest.raises(BridgeCapacityError):
        bc.create_pending_bridge("sess1")


def test_max_accounts_config_default_and_clamp(bridge_env):
    assert bc.max_whatsapp_accounts() == 2  # no config file → default
    cfg = bridge_env / ".credentials" / "whatsapp_web_config.json"
    cfg.write_text(json.dumps({"self_messages_only": False, "max_accounts": 5}))
    assert bc.max_whatsapp_accounts() == 5
    cfg.write_text(json.dumps({"max_accounts": 0}))
    assert bc.max_whatsapp_accounts() == 1  # clamped — 0 would brick logins


# ── old-layout migration ─────────────────────────────────────────────────


def test_old_layout_migrates_into_identity_dir(bridge_env, monkeypatch):
    root = bridge_env / ".credentials" / "whatsapp_wwebjs_auth"
    (root / "session").mkdir(parents=True)
    (root / "session" / "creds.json").write_text("old-session")
    monkeypatch.setattr(bc, "_legacy_owner_identity", lambda: "14155552671")

    bridge = bc.get_whatsapp_bridge("14155552671")  # triggers migration
    assert (root / "14155552671" / "session" / "creds.json").read_text() == "old-session"
    assert not (root / "session").exists()
    assert Path(bridge.auth_dir) == root / "14155552671"


def test_old_layout_without_legacy_credential_left_in_place(bridge_env, monkeypatch):
    root = bridge_env / ".credentials" / "whatsapp_wwebjs_auth"
    (root / "session").mkdir(parents=True)
    (root / "session" / "creds.json").write_text("orphan")
    monkeypatch.setattr(bc, "_legacy_owner_identity", lambda: None)

    bc.get_whatsapp_bridge("923001234567")
    assert (root / "session" / "creds.json").exists()  # untouched, just logged


def test_migration_runs_once(bridge_env, monkeypatch):
    calls = []
    monkeypatch.setattr(
        bc, "_legacy_owner_identity", lambda: calls.append(1) or "14155552671"
    )
    root = bridge_env / ".credentials" / "whatsapp_wwebjs_auth"
    (root / "session").mkdir(parents=True)
    bc.get_whatsapp_bridge("14155552671")
    bc.get_whatsapp_bridge("923001234567")
    assert len(calls) == 1


# ════════════════════════════════════════════════════════════════════════
# QR link flow — mocked bridges, whole lifecycle per event loop
# ════════════════════════════════════════════════════════════════════════


def _legacy_json(tmp_root: Path) -> Path:
    return tmp_root / ".credentials" / "whatsapp_web.json"


def _flows():
    from craftos_integrations.integrations.whatsapp_web._session import (
        get_session_manager,
    )

    return get_session_manager()._flows


def test_start_qr_session_uses_real_uuid_ids(fake_bridges):
    async def scenario():
        first = await start_qr_session()
        second = await start_qr_session()
        for result in (first, second):
            assert result["success"] and result["status"] == "qr_ready"
            assert result["qr_code"].startswith("data:image/")
            sid = result["session_id"]
            assert sid != "bridge" and len(sid) == 32 and sid in _flows()
        assert first["session_id"] != second["session_id"]
        # Concurrent sessions don't collide: distinct bridges, distinct dirs.
        b1 = _flows()[first["session_id"]]._bridge
        b2 = _flows()[second["session_id"]]._bridge
        assert b1 is not b2 and b1.auth_dir != b2.auth_dir
        for sid in (first["session_id"], second["session_id"]):
            await check_qr_session_status(sid)  # poll shape sanity
            from craftos_integrations.integrations.whatsapp_web._session import (
                get_session_manager,
            )

            await get_session_manager().cancel_link_flow(sid)

    run(scenario())


def test_start_qr_session_refused_beyond_cap(fake_bridges, monkeypatch):
    monkeypatch.setattr(bc, "max_whatsapp_accounts", lambda: 1)

    async def scenario():
        assert (await start_qr_session())["status"] == "qr_ready"
        refused = await start_qr_session()
        assert refused["success"] is False and refused["status"] == "error"
        assert "RAM" in refused["message"]

    run(scenario())


def test_check_qr_session_lifecycle_returns_identity_and_credential(fake_bridges):
    root = fake_bridges / ".credentials" / "whatsapp_wwebjs_auth"

    async def scenario():
        started = await start_qr_session()
        sid = started["session_id"]

        waiting = await check_qr_session_status(sid)
        assert waiting["status"] == "qr_ready" and waiting["connected"] is False

        fake = _flows()[sid]._bridge
        fake.owner_phone = "14155552671"
        fake.owner_name = "Ada Lovelace"
        fake.wid = "14155552671:7@c.us"
        fake._ready = True

        result = await check_qr_session_status(sid)
        assert result["success"] and result["status"] == "connected"
        assert result["connected"] is True
        assert result["identity"] == "14155552671"
        assert result["owner_phone"] == "14155552671"
        assert result["owner_name"] == "Ada Lovelace"
        assert result["credential"] == {
            "session_id": "14155552671",
            "owner_phone": "14155552671",
            "owner_name": "Ada Lovelace",
            "wid": "14155552671:7@c.us",
        }
        # Provider identity agrees with the QR flow — one rule everywhere.
        assert (
            WhatsAppWebProvider().identity_of(result["credential"])
            == result["identity"]
        )

        # Flow bookkeeping: pending dir promoted to the identity dir.
        assert not (root / f"pending-{sid}").exists()
        assert bc.peek_whatsapp_bridge("14155552671") is not None

        # §2.8: the legacy whatsapp_web.json is NEVER written anymore.
        assert not _legacy_json(fake_bridges).exists()

        # A finished flow polls idempotently — same connected result, no
        # "Session not found" error after success (D10).
        again = await check_qr_session_status(sid)
        assert again["status"] == "connected"
        assert again["identity"] == "14155552671"

    run(scenario())


def test_second_account_leaves_existing_legacy_json_untouched(fake_bridges):
    _legacy_json(fake_bridges).parent.mkdir(parents=True, exist_ok=True)
    _legacy_json(fake_bridges).write_text(
        json.dumps(
            {"session_id": "14155552671", "owner_phone": "14155552671", "owner_name": "Ada"}
        )
    )

    async def scenario():
        started = await start_qr_session()
        sid = started["session_id"]
        fake = _flows()[sid]._bridge
        fake.owner_phone = "923001234567"
        fake.owner_name = "Bea"
        fake.wid = "923001234567:1@c.us"
        fake._ready = True

        result = await check_qr_session_status(sid)
        assert result["status"] == "connected" and result["identity"] == "923001234567"
        # A surviving legacy file (pre-migration installs) is never
        # overwritten by new links.
        assert (
            json.loads(_legacy_json(fake_bridges).read_text())["owner_phone"]
            == "14155552671"
        )

    run(scenario())


def test_check_unknown_session(fake_bridges):
    result = run(check_qr_session_status("does-not-exist"))
    assert result["success"] is False and result["connected"] is False


def test_cancel_qr_session_cleans_pending_bridge_and_temp_dir(fake_bridges):
    async def scenario():
        from craftos_integrations.integrations.whatsapp_web._session import (
            get_session_manager,
        )

        started = await start_qr_session()
        sid = started["session_id"]
        fake = _flows()[sid]._bridge
        assert Path(fake.auth_dir).exists()

        cancelled = await get_session_manager().cancel_link_flow(sid)
        assert cancelled["success"]
        assert sid not in _flows()
        assert bc._bridges.get(sid) is None
        assert not fake.is_running
        assert not Path(fake.auth_dir).exists()  # temp dir deleted

        assert (await get_session_manager().cancel_link_flow(sid))["success"]

    run(scenario())


# ════════════════════════════════════════════════════════════════════════
# teardown_account — the host's disconnect hook
# ════════════════════════════════════════════════════════════════════════


def test_teardown_account_stops_bridge_and_deletes_auth_dir(fake_bridges):
    bridge = bc.get_whatsapp_bridge("14155552671")
    run(bridge.start())
    assert Path(bridge.auth_dir).exists()

    run(teardown_account("+1 (415) 555-2671"))  # any spelling
    assert bridge.logged_out  # server-side logout attempted
    assert not bridge.is_running
    assert bc.peek_whatsapp_bridge("14155552671") is None
    assert not Path(bridge.auth_dir).exists()

    run(teardown_account("14155552671"))  # idempotent
    run(teardown_account("not a phone"))  # junk never raises


def test_provider_method_teardown_delegates(fake_bridges):
    bridge = bc.get_whatsapp_bridge("923001234567")
    run(bridge.start())
    run(WhatsAppWebProvider().teardown_account("923001234567"))
    assert bc.peek_whatsapp_bridge("923001234567") is None
    assert not Path(bridge.auth_dir).exists()


# ════════════════════════════════════════════════════════════════════════
# Binding — per-account credential + per-account bridge
# ════════════════════════════════════════════════════════════════════════


def test_binding_injects_credential_no_disk(bridge_env):
    provider = WhatsAppWebProvider()
    client = provider.build_client(dict(WA_CRED), lambda c: None)
    assert isinstance(client, BoundWhatsAppWebClient)
    assert client.has_credentials()
    cred = client._load()
    assert cred.owner_phone == "14155552671"
    assert cred.owner_name == "Ada Lovelace"
    assert not hasattr(cred, "wid")  # provider-level key filtered out
    assert client.owner_phone == "14155552671"  # legacy property path works

    unbound = BoundWhatsAppWebClient()
    assert not unbound.has_credentials()
    with pytest.raises(RuntimeError):
        unbound._load()
    with pytest.raises(RuntimeError):
        unbound._get_bridge()

    with pytest.raises(ValueError):  # identity-less credential can't bind
        provider.build_client({"owner_name": "who?"}, lambda c: None)


def test_bound_clients_get_their_own_accounts_bridge(bridge_env):
    provider = WhatsAppWebProvider()
    ada = provider.build_client(dict(WA_CRED), lambda c: None)
    bea = provider.build_client(
        {"owner_phone": "923001234567", "owner_name": "Bea", "wid": "923001234567:1@c.us"},
        lambda c: None,
    )
    ada_bridge = ada._get_bridge()
    bea_bridge = bea._get_bridge()
    assert ada_bridge is not bea_bridge  # events can never cross accounts
    assert Path(ada_bridge.auth_dir).name == "14155552671"
    assert Path(bea_bridge.auth_dir).name == "923001234567"
    assert ada_bridge is bc.get_whatsapp_bridge("14155552671")  # registry-backed


def test_binding_persists_owner_refresh_to_account_not_legacy_json(bridge_env):
    provider = WhatsAppWebProvider()
    persisted = []
    client = provider.build_client(dict(WA_CRED), persisted.append)
    client._store_updated_credential(
        WhatsAppWebCredential(
            session_id="14155552671",
            owner_phone="14155552671",
            owner_name="Ada L. (renamed)",
        )
    )
    assert persisted and persisted[0]["owner_name"] == "Ada L. (renamed)"
    assert persisted[0]["wid"] == WA_CRED["wid"]  # identity key preserved
    assert client._load().owner_name == "Ada L. (renamed)"
    assert not _legacy_json(bridge_env).exists()  # legacy file untouched


def test_make_listener_wraps_the_legacy_bridge_loop(bridge_env):
    provider = WhatsAppWebProvider()
    client = provider.build_client(dict(WA_CRED), lambda c: None)

    async def emit(event):
        pass

    listener = provider.make_listener(client, None, emit)
    assert isinstance(listener, LegacyListenerAdapter)
    assert client.supports_listening
