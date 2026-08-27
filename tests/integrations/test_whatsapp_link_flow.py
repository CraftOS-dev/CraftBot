"""LinkFlow behavior (session-durability plan §2.5): state progression
qr_ready → scanned → promoting → connected with idempotent completion,
cancel cleanup, QR-cycle timeout, abandoned-flow self-cancel, the
recent-connect ghost-flow guard, and the boot sweep for orphan pending
dirs. Mocked bridges — no Node, no Chromium.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

import craftos_integrations.providers.whatsapp_web._bridge_client as bc
import craftos_integrations.providers.whatsapp_web._session as sess


class FlowFakeBridge:
    """Pending-bridge double for LinkFlow: emits a QR on start, the test
    flips it to ready (scan) or emits events through the stored callback."""

    def __init__(self, auth_dir: str):
        self.auth_dir = auth_dir
        self.fail_restart = False  # when True, start() raises
        self.start_calls = 0
        self._running = False
        self._ready = False
        self.owner_phone = ""
        self.owner_name = ""
        self.wid = ""
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
        self.start_calls += 1
        if self.fail_restart:
            raise RuntimeError("scripted restart failure")
        self._running = True
        Path(self.auth_dir, "session").mkdir(parents=True, exist_ok=True)

    async def wait_for_qr_or_ready(self, timeout=60.0):
        if self._ready:
            return "ready", {}
        return "qr", {"qr_data_url": "data:image/png;base64,QUFBQQ=="}

    async def wait_exited(self):
        while self._running:
            await asyncio.sleep(0.01)
        return 0

    async def ping(self, timeout=10.0):
        return {"success": True, "ready": self.is_ready}

    async def stop(self):
        self._running = False

    async def abandon(self):
        self._running = False

    async def logout(self):
        self._running = False
        import shutil

        shutil.rmtree(self.auth_dir, ignore_errors=True)

    async def emit(self, event, data=None):
        if self._event_callback is not None:
            await self._event_callback(event, data or {})

    def scanned_by(self, phone: str, name: str = "Ada"):
        self.owner_phone = phone
        self.owner_name = name
        self.wid = f"{phone}:1@c.us"
        self._ready = True


@pytest.fixture
def flow_env(tmp_path, monkeypatch):
    monkeypatch.setattr(bc.ConfigStore, "project_root", tmp_path)
    bc._reset_bridge_registry_for_tests()
    monkeypatch.setattr(bc, "WhatsAppBridge", FlowFakeBridge)
    yield tmp_path
    bc._reset_bridge_registry_for_tests()


def manager():
    return sess.get_session_manager()


def test_full_flow_states_and_idempotent_done(flow_env):
    async def scenario():
        started = await manager().start_link_flow()
        assert started["status"] == "qr_ready"
        assert started["expires_in"] > 0
        sid = started["session_id"]
        flow = manager()._flows[sid]

        # Phone scanned → wwebjs fires authenticated before ready.
        await flow._bridge.emit("authenticated", {})
        polled = await manager().link_flow_status(sid)
        assert polled["status"] == "scanned"

        flow._bridge.scanned_by("14155552671")
        result = await manager().link_flow_status(sid)
        assert result["status"] == "connected" and result["connected"] is True
        assert result["identity"] == "14155552671"
        assert result["credential"]["wid"] == "14155552671:1@c.us"

        # D10: completion is idempotent — a concurrent/late poller gets the
        # same result, never "Session not found".
        for _ in range(3):
            again = await manager().link_flow_status(sid)
            assert again["status"] == "connected"
            assert again["identity"] == "14155552671"

        # Adoption: the live pending bridge IS the account's bridge now —
        # still running, re-keyed by identity, dir rename deferred behind
        # an adoption marker.
        flow = manager()._flows[sid]
        adopted = bc.peek_whatsapp_bridge("14155552671")
        assert adopted is flow._bridge and adopted.is_running
        root = flow_env / ".credentials" / "whatsapp_wwebjs_auth"
        pending_dir = root / f"pending-{sid}"
        assert (pending_dir / ".adopted").read_text() == "14155552671"
        assert not (root / "14155552671").exists()

        # The session actor adopts the running+ready bridge without a
        # relaunch — the user's session simply continues.
        session = sess.get_session_manager().session_for("14155552671")
        state = await session.ensure_started()
        assert state in (sess.LAUNCHING, sess.CONNECTED)
        for _ in range(50):
            if session.state == sess.CONNECTED:
                break
            await asyncio.sleep(0.01)
        assert session.state == sess.CONNECTED
        assert adopted.is_running  # never stopped

        # Clean stop performs the deferred rename; the actor comes back
        # from the renamed conventional dir.
        await session.stop()
        assert not pending_dir.exists()
        assert (root / "14155552671").exists()
        assert not (root / "14155552671" / ".adopted").exists()
        assert adopted.auth_dir == str(root / "14155552671")

    asyncio.run(scenario())


def test_recent_connect_guard_blocks_ghost_flows(flow_env):
    """Log-4 ghost flow: a stale poller restarting a QR right after a
    successful link is refused; an explicit user click (force) is not."""

    async def scenario():
        started = await manager().start_link_flow()
        sid = started["session_id"]
        manager()._flows[sid]._bridge.scanned_by("14155552671")
        assert (await manager().link_flow_status(sid))["status"] == "connected"

        ghost = await manager().start_link_flow()
        assert ghost["success"] is False and ghost["status"] == "error"

        forced = await manager().start_link_flow(force=True)
        assert forced["status"] == "qr_ready"
        await manager().cancel_link_flow(forced["session_id"])

    asyncio.run(scenario())


def test_qr_cycles_then_timeout(flow_env, monkeypatch):
    """Unscanned QR: cycles renew the code (event-driven, never a
    destructive recovery), then the flow parks as TIMEOUT with a
    start-again CTA — no Chromium burns forever."""
    monkeypatch.setattr(sess.LinkFlow, "QR_CYCLE_SECONDS", 0.05)
    monkeypatch.setattr(sess.LinkFlow, "WATCH_INTERVAL", 0.01)
    monkeypatch.setattr(sess.LinkFlow, "MAX_QR_CYCLES", 2)
    monkeypatch.setattr(sess.LinkFlow, "ABANDON_AFTER", 10.0)

    async def scenario():
        started = await manager().start_link_flow()
        sid = started["session_id"]
        deadline = time.time() + 3.0
        status = None
        while time.time() < deadline:
            status = await manager().link_flow_status(sid)
            if status["status"] == "timeout":
                break
            await asyncio.sleep(0.02)
        assert status is not None and status["status"] == "timeout"
        # Pending dir cleaned up on park.
        root = flow_env / ".credentials" / "whatsapp_wwebjs_auth"
        assert not (root / f"pending-{sid}").exists()

    asyncio.run(scenario())


def test_abandoned_flow_cancels_itself(flow_env, monkeypatch):
    """Nobody polling (modal closed without cancel): the flow stops
    burning a browser for an abandoned QR."""
    monkeypatch.setattr(sess.LinkFlow, "ABANDON_AFTER", 0.05)
    monkeypatch.setattr(sess.LinkFlow, "WATCH_INTERVAL", 0.01)

    async def scenario():
        started = await manager().start_link_flow()
        sid = started["session_id"]
        flow = manager()._flows[sid]
        await asyncio.sleep(0.3)
        assert flow.state == sess.FLOW_CANCELLED
        assert not flow._bridge.is_running

    asyncio.run(scenario())


def test_link_reset_clears_relink_marker_and_old_session(flow_env):
    """Re-linking a NEEDS_RELINK account: promotion replaces the dead
    LocalAuth and resets the parked actor — the account comes back."""

    async def scenario():
        identity = "14155552671"
        sess._write_relink_marker(identity)
        parked = manager().session_for(identity)
        assert await parked.ensure_started() == sess.NEEDS_RELINK

        started = await manager().start_link_flow(force=True)
        sid = started["session_id"]
        manager()._flows[sid]._bridge.scanned_by(identity)
        result = await manager().link_flow_status(sid)
        assert result["status"] == "connected"

        assert not sess._has_relink_marker(identity)
        fresh = manager().session_for(identity)
        assert fresh is not parked
        assert fresh.state == sess.STOPPED  # ready for the next reconcile

    asyncio.run(scenario())


def test_boot_sweep_removes_only_old_orphan_pending_dirs(flow_env):
    root = flow_env / ".credentials" / "whatsapp_wwebjs_auth"
    old = root / "pending-deadbeef"
    young = root / "pending-cafebabe"
    keep = root / "14155552671"
    for d in (old, young, keep):
        d.mkdir(parents=True)
    stale = time.time() - 2 * 3600
    os.utime(old, (stale, stale))

    manager().boot_sweep()

    assert not old.exists()  # interrupted promote reclaimed
    assert young.exists()  # too fresh to judge
    assert keep.exists()  # identity dirs are sacred

    asyncio.run(asyncio.sleep(0))  # no lingering tasks


def test_dead_pending_bridge_is_relaunched_and_flow_completes(flow_env, monkeypatch):
    """A pending bridge that dies mid-flow (INJECT watchdog on a slow
    post-scan sync) is relaunched from its scan-time auth — the flow keeps
    going instead of failing with 'bridge stopped unexpectedly' (observed
    live 2026-08-21 15:14)."""
    monkeypatch.setattr(sess.LinkFlow, "WATCH_INTERVAL", 0.01)

    async def scenario():
        started = await manager().start_link_flow()
        sid = started["session_id"]
        flow = manager()._flows[sid]
        fake = flow._bridge
        await fake.emit("authenticated", {})
        assert (await manager().link_flow_status(sid))["status"] == "scanned"

        # Process dies post-scan; the saved auth will restore straight to
        # ready on relaunch.
        fake.scanned_by("14155552671")
        fake._running = False

        # Polls during the outage report the live state, not an error.
        polled = await manager().link_flow_status(sid)
        assert polled["status"] in ("scanned", "promoting")

        for _ in range(200):
            await asyncio.sleep(0.01)
            if flow.state == sess.FLOW_DONE:
                break
        assert flow.state == sess.FLOW_DONE
        assert flow.relaunches == 1
        assert fake.start_calls == 2
        result = await manager().link_flow_status(sid)
        assert result["status"] == "connected"
        assert result["identity"] == "14155552671"

    asyncio.run(scenario())


def test_pending_bridge_relaunch_cap_fails_flow(flow_env, monkeypatch):
    monkeypatch.setattr(sess.LinkFlow, "WATCH_INTERVAL", 0.01)
    monkeypatch.setattr(sess.LinkFlow, "MAX_RELAUNCHES", 2)

    async def scenario():
        started = await manager().start_link_flow()
        sid = started["session_id"]
        flow = manager()._flows[sid]
        fake = flow._bridge
        await fake.emit("authenticated", {})
        fake._running = False
        fake.fail_restart = True  # every relaunch attempt dies again

        for _ in range(200):
            await asyncio.sleep(0.01)
            if flow.state == sess.FLOW_FAILED:
                break
        assert flow.state == sess.FLOW_FAILED
        assert flow.relaunches == sess.LinkFlow.MAX_RELAUNCHES + 1
        result = await manager().link_flow_status(sid)
        assert result["success"] is False
        assert "try again" in result["message"].lower()

    asyncio.run(scenario())


def test_boot_finishes_deferred_adopted_rename(flow_env):
    """An adopted dir left behind by an app exit is renamed to the
    conventional <identity>/ at the next boot, before any bridge starts."""
    root = flow_env / ".credentials" / "whatsapp_wwebjs_auth"
    adopted = root / "pending-deadbeef"
    (adopted / "session").mkdir(parents=True)
    (adopted / "session" / "creds.json").write_text("fresh")
    (adopted / ".adopted").write_text("14155552671")

    # An adopted dir counts as a connected account for the capacity cap.
    assert bc._account_slots_used() == 1

    bridge = bc.get_whatsapp_bridge("14155552671")  # boot-path resolution
    assert not adopted.exists()
    assert (root / "14155552671" / "session" / "creds.json").read_text() == "fresh"
    assert not (root / "14155552671" / ".adopted").exists()
    assert bridge.auth_dir == str(root / "14155552671")


def test_teardown_deletes_not_yet_renamed_adopted_dir(flow_env):
    async def scenario():
        started = await manager().start_link_flow()
        sid = started["session_id"]
        manager()._flows[sid]._bridge.scanned_by("14155552671")
        assert (await manager().link_flow_status(sid))["status"] == "connected"
        root = flow_env / ".credentials" / "whatsapp_wwebjs_auth"
        assert (root / f"pending-{sid}").exists()

        await manager().teardown("14155552671")
        assert not (root / f"pending-{sid}").exists()
        assert not (root / "14155552671").exists()
        assert bc.peek_whatsapp_bridge("14155552671") is None

    asyncio.run(scenario())


def test_capacity_freed_after_timeout_and_cancel(flow_env, monkeypatch):
    monkeypatch.setattr(bc, "max_whatsapp_accounts", lambda: 1)

    async def scenario():
        first = await manager().start_link_flow()
        assert first["status"] == "qr_ready"
        refused = await manager().start_link_flow(force=True)
        assert refused["success"] is False  # cap holds while flow is live

        await manager().cancel_link_flow(first["session_id"])
        second = await manager().start_link_flow(force=True)
        assert second["status"] == "qr_ready"  # slot released
        await manager().cancel_link_flow(second["session_id"])

    asyncio.run(scenario())
