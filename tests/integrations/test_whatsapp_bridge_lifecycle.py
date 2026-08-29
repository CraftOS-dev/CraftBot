"""Regression tests for the 2026-08-21 WhatsApp session-durability fixes
(docs/plans/whatsapp-session-durability-plan.md, Phase 1).

Each test pins one structural defect that produced the observed failures:
hard-killed Chromium (locked profiles, ghost Linked Devices entries),
session dirs surviving account deletion, and the infinite Chromium
spawn/kill loop on expired sessions.
"""

import asyncio
from typing import Any, Dict, List


from craftos_integrations.providers.whatsapp_web._bridge_client import (
    WhatsAppBridge,
)


# ── D1: shutdown/logout command must reach Node ──────────────────────────────


def test_teardown_sends_command_while_bridge_still_accepts_it(monkeypatch):
    """_teardown must invoke send_command BEFORE flipping _running.

    The original code set ``self._running = False`` first; send_command's
    ``is_running`` guard then raised, so no shutdown/logout EVER reached
    the Node bridge — every stop was a hard kill of a live Chromium.
    """
    bridge = WhatsAppBridge(auth_dir="X:/fake/auth")

    class FakeProcess:
        returncode = None
        pid = 4242

        async def wait(self):
            self.returncode = 0
            return 0

    bridge._process = FakeProcess()
    bridge._running = True

    sent: List[Dict[str, Any]] = []
    real_is_running: List[bool] = []

    async def fake_send(cmd, args=None, timeout=30.0):
        real_is_running.append(bridge.is_running)
        sent.append({"cmd": cmd})
        return {"success": True}

    monkeypatch.setattr(bridge, "send_command", fake_send)

    asyncio.run(bridge.stop())

    assert sent == [{"cmd": "shutdown"}]
    # The command must have been sent while the bridge still reported
    # running — that is the property whose absence caused every hard kill.
    assert real_is_running == [True]
    assert bridge._process is None
    assert not bridge.is_running


def test_teardown_serialized_second_caller_noops(monkeypatch):
    """Concurrent stop()+logout() (reconcile racing teardown_account) must
    not double-teardown: the second caller waits on the lock and sees the
    bridge already stopped."""
    bridge = WhatsAppBridge(auth_dir="X:/fake/auth")

    class FakeProcess:
        returncode = None
        pid = 4242

        async def wait(self):
            self.returncode = 0
            return 0

    bridge._process = FakeProcess()
    bridge._running = True

    sent: List[str] = []

    async def fake_send(cmd, args=None, timeout=30.0):
        sent.append(cmd)
        await asyncio.sleep(0.01)
        return {"success": True}

    monkeypatch.setattr(bridge, "send_command", fake_send)

    async def scenario():
        await asyncio.gather(bridge.stop(), bridge.logout_command_only())

    # logout() also rmtree's the auth dir; use a helper that only runs the
    # teardown half so the test stays filesystem-free.
    async def logout_command_only():
        await bridge._teardown(cmd="logout", send_timeout=3.0, wait_timeout=8.0)

    bridge.logout_command_only = logout_command_only

    asyncio.run(scenario())
    # Exactly one command went out — the loser of the race no-oped.
    assert len(sent) == 1


# ── D4: expired session must park, not hot-loop ──────────────────────────────


class FakeQrBridge:
    """Bridge double whose stored session always demands a fresh QR."""

    def __init__(self, auth_dir="X:/fake/auth/12345"):
        self.start_calls = 0
        self.abandon_calls = 0
        self.auth_dir = auth_dir
        self.is_running = False
        self.is_ready = False

    def set_event_callback(self, cb):
        pass

    async def start(self):
        self.start_calls += 1
        self.is_running = True

    async def stop(self):
        self.is_running = False

    async def abandon(self):
        self.abandon_calls += 1
        self.is_running = False

    async def wait_for_qr_or_ready(self, timeout=180.0):
        return "qr", None

    async def wait_exited(self):
        while self.is_running:
            await asyncio.sleep(0.01)
        return 0


def test_stale_session_parks_instead_of_respawning(tmp_path, monkeypatch):
    """The session actor gets QR-on-restore once → NEEDS_RELINK; the ~1Hz
    ensure_started calls from the listener supervisor spawn nothing more.
    (The original code relaunched Node+Chromium every supervisor cycle.)"""
    import craftos_integrations.providers.whatsapp_web._bridge_client as bc
    import craftos_integrations.providers.whatsapp_web._session as sess

    monkeypatch.setattr(bc.ConfigStore, "project_root", tmp_path)
    bc._reset_bridge_registry_for_tests()

    fake = FakeQrBridge(auth_dir=str(tmp_path / "auth" / "12345"))
    bc._bridges["12345"] = fake

    async def scenario():
        manager = sess.get_session_manager()
        session = manager.session_for("12345")
        state = await session.ensure_started()
        assert state == sess.LAUNCHING
        # Let the launch task run to the QR and park.
        for _ in range(20):
            await asyncio.sleep(0.01)
            if session.state == sess.NEEDS_RELINK:
                break
        assert session.state == sess.NEEDS_RELINK
        assert fake.start_calls == 1
        assert fake.abandon_calls == 1
        # Marker persisted → a fresh actor (post-restart) parks WITHOUT
        # ever spawning Chromium.
        assert manager.state_of("12345") == sess.NEEDS_RELINK
        # Subsequent supervisor cycles (the 1Hz loop): must be no-ops.
        for _ in range(5):
            await session.ensure_started()
        assert fake.start_calls == 1
        assert fake.abandon_calls == 1

    asyncio.run(scenario())
    bc._reset_bridge_registry_for_tests()


# ── D9: teardown before record removal, ordered ──────────────────────────────


class OrderFakeSystem:
    def __init__(self, identities):
        self._accounts = list(identities)
        self.events: List[str] = []

    def resolve(self, provider_id, hint):
        if hint not in self._accounts:
            raise LookupError(f"No account matching '{hint}'")
        return hint

    def remove_account(self, provider_id, hint):
        self.events.append(f"remove:{hint}")
        self._accounts.remove(hint)
        return hint

    def list_accounts(self, provider_id):
        class _Info:
            def __init__(self, identity):
                self.identity = identity
                self.alias = None

        return [_Info(i) for i in list(self._accounts)]


def test_system_disconnect_tears_down_bridge_before_removing_records(monkeypatch):
    from app.data.action.integrations import _helpers

    system = OrderFakeSystem(["923334055616"])

    async def fake_teardown(identity):
        system.events.append(f"teardown:{identity}")

    import craftos_integrations.providers.whatsapp_web as wa_provider

    monkeypatch.setattr(wa_provider, "teardown_account", fake_teardown)

    ok, message = _helpers.system_disconnect(system, "whatsapp_web", "923334055616")

    assert ok is True
    # Server-side logout + session-dir delete need the account to still
    # exist (record removal triggers a reconcile that races the bridge);
    # the old order was remove-then-fire-and-forget-teardown.
    assert system.events == ["teardown:923334055616", "remove:923334055616"]


def test_system_disconnect_all_orders_each_account(monkeypatch):
    from app.data.action.integrations import _helpers

    system = OrderFakeSystem(["111", "222"])

    async def fake_teardown(identity):
        system.events.append(f"teardown:{identity}")

    import craftos_integrations.providers.whatsapp_web as wa_provider

    monkeypatch.setattr(wa_provider, "teardown_account", fake_teardown)

    ok, message = _helpers.system_disconnect(system, "whatsapp_web", None)

    assert ok is True
    assert system.events == [
        "teardown:111",
        "remove:111",
        "teardown:222",
        "remove:222",
    ]
