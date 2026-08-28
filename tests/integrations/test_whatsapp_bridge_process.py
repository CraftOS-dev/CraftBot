"""WhatsAppBridge lifecycle against a REAL subprocess (Phase 5 of the
session-durability plan): the fake node script in fake_wa_bridge.py echoes
the stdio protocol with controllable exit/hang behavior, so these tests
cover what mocks can't — the stop ladder actually reaching the child, the
force-kill path leaving a verifiably dead process, and exit supervision.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import craftos_integrations.providers.whatsapp_web._bridge_client as bc

SCRIPT = Path(__file__).parent / "fake_wa_bridge.py"


@pytest.fixture
def make_bridge(tmp_path, monkeypatch):
    """Bridge factory running fake_wa_bridge.py in the requested mode."""

    live = []

    def make(mode: str) -> bc.WhatsAppBridge:
        monkeypatch.setattr(
            bc,
            "_BRIDGE_EXEC_OVERRIDE",
            [sys.executable, "-u", str(SCRIPT), mode],
        )
        bridge = bc.WhatsAppBridge(auth_dir=str(tmp_path / "auth"))
        live.append(bridge)
        return bridge

    yield make

    async def cleanup():
        for bridge in live:
            if bridge.is_running:
                await bridge._teardown(cmd="shutdown", send_timeout=1.0, wait_timeout=1.0)

    asyncio.run(cleanup())


def test_clean_shutdown_reaches_child_and_exits_zero(make_bridge):
    """D1 end-to-end: stop() sends the shutdown command to a live child,
    which acks and exits 0 — no force kill involved."""

    async def scenario():
        bridge = make_bridge("ready")
        await bridge.start()
        event, data = await bridge.wait_for_qr_or_ready(timeout=15.0)
        assert event == "ready"
        assert bridge.is_ready
        assert data["owner_phone"] == "14155552671"

        pong = await bridge.ping(timeout=5.0)
        assert pong["success"] is True

        await bridge.stop()
        assert not bridge.is_running
        rc = await asyncio.wait_for(bridge.wait_exited(), timeout=5.0)
        assert rc == 0

    asyncio.run(scenario())


def test_force_kill_after_hang_returns_only_when_dead(make_bridge):
    """D2: a child that acks shutdown but never exits gets force-killed,
    and _teardown does not return while the process may still be dying —
    callers rmtree the auth dir right after."""

    async def scenario():
        bridge = make_bridge("hang-on-shutdown")
        await bridge.start()
        assert (await bridge.wait_for_qr_or_ready(timeout=15.0))[0] == "ready"

        proc = bridge._process
        await bridge._teardown(cmd="shutdown", send_timeout=2.0, wait_timeout=1.0)
        # Returned ⇒ the process must actually be gone.
        assert proc.returncode is not None
        assert not bridge.is_running

    asyncio.run(scenario())


def test_crash_resolves_wait_exited_with_code(make_bridge):
    """D3 plumbing: exit supervision sees the child die and reports the
    real return code — the session actor's supervisor builds on this."""

    async def scenario():
        bridge = make_bridge("crash")
        await bridge.start()
        rc = await asyncio.wait_for(bridge.wait_exited(), timeout=10.0)
        assert rc == 3

    asyncio.run(scenario())


def test_wait_exited_supports_multiple_waiters(make_bridge):
    async def scenario():
        bridge = make_bridge("ready")
        await bridge.start()
        assert (await bridge.wait_for_qr_or_ready(timeout=15.0))[0] == "ready"
        waiters = [asyncio.ensure_future(bridge.wait_exited()) for _ in range(3)]
        # A cancelled waiter must not kill the shared exit future.
        waiters[0].cancel()
        await bridge.stop()
        results = await asyncio.wait_for(
            asyncio.gather(*waiters[1:]), timeout=5.0
        )
        assert results == [0, 0]

    asyncio.run(scenario())


def test_qr_mode_reaches_python_side(make_bridge):
    async def scenario():
        bridge = make_bridge("qr")
        await bridge.start()
        event, data = await bridge.wait_for_qr_or_ready(timeout=15.0)
        assert event == "qr"
        assert data["qr_data_url"].startswith("data:image/")
        await bridge.abandon()
        assert not bridge.is_running

    asyncio.run(scenario())
