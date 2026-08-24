"""WhatsAppSession state machine (session-durability plan §2.2/§2.7):
launch→ready, crash→reconnect backoff, LOGOUT→needs-relink, failure cap →
FAILED, heartbeat-hang restart, graceful stop, serialized teardown. Pure
asyncio — a scripted in-process bridge double, no subprocesses.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest

import craftos_integrations.integrations.whatsapp_web._bridge_client as bc
import craftos_integrations.integrations.whatsapp_web._session as sess


class ScriptedBridge:
    """Bridge double the session actor drives; the test scripts events."""

    def __init__(self, auth_dir: str = "", first_event: str = "ready"):
        self.auth_dir = auth_dir
        self.first_event = first_event
        self.fail_starts = False  # when True, start() raises (launch failure)
        self.start_calls = 0
        self.stop_calls = 0
        self.abandon_calls = 0
        self.logged_out = False
        self.ping_error: Optional[Exception] = None
        self._running = False
        self._ready = False
        self._event_callback = None
        self._exit_event: Optional[asyncio.Event] = None
        self.exit_code = 0

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
        if self.fail_starts:
            raise RuntimeError("scripted launch failure")
        self._running = True
        self._exit_event = asyncio.Event()

    async def wait_for_qr_or_ready(self, timeout=180.0):
        if self.first_event == "ready":
            self._ready = True
            return "ready", {"owner_phone": "111", "owner_name": "A"}
        if self.first_event == "qr":
            return "qr", {}
        await asyncio.sleep(timeout)
        return "timeout", None

    async def wait_exited(self):
        await self._exit_event.wait()
        return self.exit_code

    async def ping(self, timeout=10.0):
        if self.ping_error is not None:
            raise self.ping_error
        return {"success": True, "ready": self.is_ready}

    async def stop(self):
        self.stop_calls += 1
        self._running = False
        self._ready = False
        if self._exit_event is not None:
            self._exit_event.set()

    async def abandon(self):
        self.abandon_calls += 1
        self._running = False
        if self._exit_event is not None:
            self._exit_event.set()

    async def logout(self):
        self.logged_out = True
        self._running = False
        if self._exit_event is not None:
            self._exit_event.set()

    # test helpers ---------------------------------------------------------

    def crash(self, code=1):
        self._running = False
        self._ready = False
        self._exit_event.set()
        self.exit_code = code

    async def emit(self, event, data=None):
        if self._event_callback is not None:
            await self._event_callback(event, data or {})


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated auth root + registry, fast state-machine knobs."""
    monkeypatch.setattr(bc.ConfigStore, "project_root", tmp_path)
    bc._reset_bridge_registry_for_tests()
    for knob, value in (
        ("LAUNCH_WAIT", 1.0),
        ("BACKOFF_BASE", 0.02),
        ("BACKOFF_CAP", 0.05),
        ("MAX_FAILURES", 3),
        ("FAILED_RETRY_INTERVAL", 0.1),
        ("HEARTBEAT_INTERVAL", 0.05),
        ("HEARTBEAT_TIMEOUT", 0.05),
    ):
        monkeypatch.setattr(sess.WhatsAppSession, knob, value)
    yield tmp_path
    bc._reset_bridge_registry_for_tests()


def install(identity: str, **kwargs) -> ScriptedBridge:
    bridge = ScriptedBridge(
        auth_dir=str(bc._identity_auth_dir(identity)), **kwargs
    )
    bc._bridges[identity] = bridge
    return bridge


async def until(predicate, timeout=2.0, interval=0.005):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def test_launch_to_connected_and_idempotent_ensure(env):
    async def scenario():
        bridge = install("111")
        manager = sess.get_session_manager()
        session = manager.session_for("111")

        events = []

        async def subscriber(event, data):
            events.append(event)

        await session.ensure_started(subscriber)
        assert await until(lambda: session.state == sess.CONNECTED)
        assert bridge.start_calls == 1

        # ~1Hz supervisor calls: cheap no-ops, nothing respawns.
        for _ in range(5):
            assert await session.ensure_started() == sess.CONNECTED
        assert bridge.start_calls == 1

        # Events flow through to the subscriber.
        await bridge.emit("message", {"body": "hi"})
        assert "message" in events

        await session.stop()
        assert session.state == sess.STOPPED
        assert bridge.stop_calls >= 1

    asyncio.run(scenario())


def test_crash_reconnects_with_backoff(env):
    async def scenario():
        bridge = install("111")
        session = sess.get_session_manager().session_for("111")
        await session.ensure_started()
        assert await until(lambda: session.state == sess.CONNECTED)

        bridge.crash(code=1)
        assert await until(lambda: session.state == sess.RECONNECTING, timeout=1.0)
        # Backoff elapses → relaunched → connected again.
        assert await until(lambda: session.state == sess.CONNECTED, timeout=2.0)
        assert bridge.start_calls == 2

    asyncio.run(scenario())


def test_logout_disconnect_parks_needs_relink(env):
    """User unlinks from their phone: LOGOUT reason → NEEDS_RELINK with a
    persisted marker — never a respawn loop."""

    async def scenario():
        bridge = install("111")
        manager = sess.get_session_manager()
        session = manager.session_for("111")
        await session.ensure_started()
        assert await until(lambda: session.state == sess.CONNECTED)

        await bridge.emit("disconnected", {"reason": "LOGOUT"})
        bridge.crash(code=0)  # bridge.js exits right after the event
        assert await until(lambda: session.state == sess.NEEDS_RELINK, timeout=1.0)
        assert sess._has_relink_marker("111")
        assert manager.state_of("111") == sess.NEEDS_RELINK

        # No respawn: ensure_started is a no-op while parked.
        starts = bridge.start_calls
        for _ in range(3):
            await session.ensure_started()
        assert bridge.start_calls == starts

    asyncio.run(scenario())


def test_failure_cap_parks_in_failed_then_retries(env):
    async def scenario():
        bridge = install("111", first_event="ready")
        session = sess.get_session_manager().session_for("111")
        await session.ensure_started()
        assert await until(lambda: session.state == sess.CONNECTED)

        # First crash + every relaunch failing → consecutive failures
        # accumulate to the cap (a successful relaunch would reset them).
        bridge.fail_starts = True
        bridge.crash(code=1)
        assert await until(lambda: session.state == sess.FAILED, timeout=3.0)

        # FAILED retries after the (shrunken) hourly interval; once the
        # launches succeed again, it reconnects and resets.
        bridge.fail_starts = False
        assert await until(lambda: session.state == sess.CONNECTED, timeout=3.0)

    asyncio.run(scenario())


def test_never_connected_failure_cap_parks_needs_relink(env):
    """Escape hatch: exhausting the failure cap WITHOUT ever reaching
    CONNECTED means the stored session is unusable (torn profile, revoked)
    — park with the re-link CTA instead of hourly FAILED retries that can
    never succeed (observed live 2026-08-21, account 923334055616)."""

    async def scenario():
        bridge = install("111")
        bridge.fail_starts = True  # unusable from the very first launch
        manager = sess.get_session_manager()
        session = manager.session_for("111")
        await session.ensure_started()

        assert await until(lambda: session.state == sess.NEEDS_RELINK, timeout=3.0)
        assert sess._has_relink_marker("111")
        assert manager.state_of("111") == sess.NEEDS_RELINK
        # Parked means parked: no hourly retry, no respawn.
        starts = bridge.start_calls
        await asyncio.sleep(0.3)
        assert bridge.start_calls == starts

    asyncio.run(scenario())


def test_heartbeat_hang_restarts(env):
    """Process alive but unresponsive: two ping misses → restart through
    the reconnect path (the state synthetic-ready used to paper over)."""

    async def scenario():
        bridge = install("111")
        session = sess.get_session_manager().session_for("111")
        await session.ensure_started()
        assert await until(lambda: session.state == sess.CONNECTED)

        bridge.ping_error = TimeoutError("hung")
        assert await until(
            lambda: session.state in (sess.RECONNECTING, sess.LAUNCHING, sess.CONNECTED)
            and bridge.stop_calls >= 1,
            timeout=2.0,
        )
        bridge.ping_error = None
        assert await until(
            lambda: session.state == sess.CONNECTED and bridge.start_calls >= 2,
            timeout=2.0,
        )

    asyncio.run(scenario())


def test_graceful_stop_prevents_reconnect(env):
    async def scenario():
        bridge = install("111")
        session = sess.get_session_manager().session_for("111")
        await session.ensure_started()
        assert await until(lambda: session.state == sess.CONNECTED)

        await session.stop()
        assert session.state == sess.STOPPED
        await asyncio.sleep(0.2)  # backoff windows elapse — nothing respawns
        assert session.state == sess.STOPPED
        assert bridge.start_calls == 1

    asyncio.run(scenario())


def test_manager_teardown_logs_out_and_forgets(env):
    async def scenario():
        bridge = install("111")
        manager = sess.get_session_manager()
        session = manager.session_for("111")
        await session.ensure_started()
        assert await until(lambda: session.state == sess.CONNECTED)

        await manager.teardown("111")
        assert bridge.logged_out  # server-side unlink attempted
        assert manager.peek("111") is None
        assert bc.peek_whatsapp_bridge("111") is None
        assert not sess._has_relink_marker("111")

        await manager.teardown("111")  # idempotent
        await manager.teardown("junk!!")  # junk never raises

    asyncio.run(scenario())


def test_persisted_marker_parks_fresh_actor_without_spawn(env):
    async def scenario():
        install("111")
        sess._write_relink_marker("111")
        manager = sess.get_session_manager()
        # Pre-actor status surfaces the marker (UI relink CTA on boot).
        assert manager.state_of("111") == sess.NEEDS_RELINK

        session = manager.session_for("111")
        state = await session.ensure_started()
        assert state == sess.NEEDS_RELINK
        assert bc._bridges["111"].start_calls == 0

    asyncio.run(scenario())


def test_shutdown_all_stops_every_session(env):
    async def scenario():
        b1, b2 = install("111"), install("222")
        manager = sess.get_session_manager()
        for identity in ("111", "222"):
            await manager.session_for(identity).ensure_started()
        assert await until(
            lambda: manager.session_for("111").state == sess.CONNECTED
            and manager.session_for("222").state == sess.CONNECTED
        )

        await manager.shutdown_all()
        assert b1.stop_calls >= 1 and b2.stop_calls >= 1
        assert manager.session_for("111").state == sess.STOPPED
        assert manager.session_for("222").state == sess.STOPPED

    asyncio.run(scenario())
