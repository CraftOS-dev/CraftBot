# -*- coding: utf-8 -*-
"""Per-identity WhatsApp session actors + the QR link flow.

Session-durability redesign (docs/plans/whatsapp-session-durability-plan.md
§2): ALL bridge lifecycle goes through a single per-identity
``WhatsAppSession`` actor. Nobody else calls ``WhatsAppBridge.start/stop/
logout`` or touches the auth dirs — every external request (start
listening, link, teardown, app shutdown, UI status) is an operation on the
actor, and conflicting operations are serialized by construction.

State machine::

     STOPPED ──start──► LAUNCHING ──ready──► CONNECTED
        ▲                  │  │                  │
        │            fatal/│  │qr (stale creds)  │disconnected / proc exit
        │           retries│  ▼                  ▼
        │         exhausted│ NEEDS_RELINK   RECONNECTING ──backoff──► LAUNCHING
        │                  │      │              │
        └──stop / teardown─┴──────┴──────────────┘   (max backoff reached →
                                                      FAILED, hourly retry)

- ``NEEDS_RELINK`` is terminal-until-user-acts: stale LocalAuth stops the
  bridge once, records a marker file in the identity's auth dir (so the
  state survives restarts), and never respawns — the relaunch hot loop is
  structurally impossible. Cleared by a fresh QR link (promote replaces
  the auth dir) or teardown.
- ``RECONNECTING`` covers both bridge ``disconnected`` events and
  unexpected process exit: exponential backoff 5s → 10min with jitter.
  A ``LOGOUT`` disconnect reason (user unlinked from their phone) maps to
  ``NEEDS_RELINK`` instead — respawning would loop.
- After ``MAX_FAILURES`` consecutive failed cycles the session parks in
  ``FAILED`` and retries hourly. Counters are runtime-only: every app
  launch retries immediately with fresh counters.
- Heartbeat: a ``ping`` every 60s; two consecutive misses = process alive
  but hung → restart through the reconnect path (catches the state the
  old synthetic-ready used to paper over).

``LinkFlow`` is the short-lived actor for one QR login
(STARTING → QR_READY → SCANNED → PROMOTING → DONE | FAILED | TIMEOUT |
CANCELLED). Promotion runs inside the flow, single-flight, and the flow
entry stays registered until it completes — a second poller gets the same
DONE result instead of a "Session not found" error after success.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Optional

from ...logger import get_logger

logger = get_logger(__name__)

# ── session states ───────────────────────────────────────────────────────

STOPPED = "stopped"
LAUNCHING = "launching"
CONNECTED = "connected"
RECONNECTING = "reconnecting"
NEEDS_RELINK = "needs_relink"
FAILED = "failed"

# ── link-flow states ─────────────────────────────────────────────────────

FLOW_STARTING = "starting"
FLOW_QR_READY = "qr_ready"
FLOW_SCANNED = "scanned"
FLOW_PROMOTING = "promoting"
FLOW_DONE = "connected"
FLOW_FAILED = "error"
FLOW_TIMEOUT = "timeout"
FLOW_CANCELLED = "cancelled"

_FLOW_TERMINAL = {FLOW_DONE, FLOW_FAILED, FLOW_TIMEOUT, FLOW_CANCELLED}

_RELINK_MARKER = ".needs_relink"

# Strong refs to fire-and-forget tasks (a bare create_task result nobody
# holds can be GC'd mid-flight — same hazard class as the teardown tasks).
_bg_tasks: set = set()


def _spawn(coro: Coroutine) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


def _relink_marker_path(identity: str) -> Path:
    from ._bridge_client import _resolve_identity_dir

    return _resolve_identity_dir(identity) / _RELINK_MARKER


def _write_relink_marker(identity: str) -> None:
    try:
        path = _relink_marker_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError as e:
        logger.warning(f"[WA-Session] could not write relink marker: {e}")


def _clear_relink_marker(identity: str) -> None:
    try:
        _relink_marker_path(identity).unlink(missing_ok=True)
    except OSError:
        pass


def _has_relink_marker(identity: str) -> bool:
    try:
        return _relink_marker_path(identity).exists()
    except OSError:
        return False


# ════════════════════════════════════════════════════════════════════════
# WhatsAppSession — the per-identity actor
# ════════════════════════════════════════════════════════════════════════


class WhatsAppSession:
    """Owns exactly one identity's bridge lifecycle. See module docstring
    for the state machine. Class attributes are knobs so tests can run the
    machine in milliseconds; production uses the defaults."""

    LAUNCH_WAIT = 180.0  # start → qr|ready (post-auth chat sync can lag)
    BACKOFF_BASE = 5.0
    BACKOFF_CAP = 600.0
    MAX_FAILURES = 6  # consecutive failures before parking in FAILED
    FAILED_RETRY_INTERVAL = 3600.0
    HEARTBEAT_INTERVAL = 60.0
    HEARTBEAT_TIMEOUT = 10.0
    HEARTBEAT_MISSES = 2

    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.state = STOPPED
        self.state_since = time.time()
        self.last_error = ""
        self._failures = 0
        self._stopping = False
        self._relink_flagged = False
        # Has this actor EVER reached CONNECTED this process? A session
        # that exhausts the failure cap without ever connecting is not a
        # transient outage — its LocalAuth is unusable (torn profile,
        # revoked session) and no amount of hourly retries will fix it.
        self._ever_connected = False
        self._subscriber: Optional[Callable[[str, Dict[str, Any]], Any]] = None
        self._spawn_lock = asyncio.Lock()
        self._launch_task: Optional[asyncio.Task] = None
        self._supervisor: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None

    # ── public surface ───────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "since": self.state_since,
            "last_error": self.last_error,
            "failures": self._failures,
        }

    async def ensure_started(self, subscriber=None) -> str:
        """Idempotent 'be running' request — THE call sites are the
        listener adapter (invoked ~1Hz by its supervisor, so everything on
        the hot path is a cheap state check) and post-link wiring. Returns
        the state after the request."""
        if subscriber is not None:
            self._subscriber = subscriber
        if self.state != STOPPED:
            return self.state
        async with self._spawn_lock:
            if self.state != STOPPED:
                return self.state
            if _has_relink_marker(self.identity):
                self._set_state(
                    NEEDS_RELINK,
                    "stored session needs re-linking via QR (persisted marker)",
                )
                return self.state
            self._stopping = False
            self._relink_flagged = False
            self._set_state(LAUNCHING)
            self._launch_task = _spawn(self._launch())
        return self.state

    async def stop(self) -> None:
        """Graceful stop (reconcile removal, app shutdown): clean
        ``shutdown`` to Node so LocalAuth flushes and WhatsApp sees a
        proper disconnect — never a hard kill. NEEDS_RELINK's persisted
        marker survives (state re-derives on next start)."""
        self._stopping = True
        self._cancel_tasks()
        from ._bridge_client import peek_whatsapp_bridge

        bridge = peek_whatsapp_bridge(self.identity)
        if bridge is not None:
            bridge.set_event_callback(None)
            if bridge.is_running:
                try:
                    await bridge.stop()
                except Exception as e:
                    logger.warning(
                        f"[WA-Session] {self.identity}: stop error: {e}"
                    )
        # The browser is down — a good moment to finish any deferred
        # adopted-dir rename (cheap no-op otherwise).
        try:
            from ._bridge_client import _migrate_adopted_dirs

            _migrate_adopted_dirs()
        except Exception:
            pass
        self._set_state(STOPPED)

    def halt_nowait(self) -> None:
        """Synchronous task cancellation only — used when the bridge is
        already being handled elsewhere (teardown primitive, promote)."""
        self._stopping = True
        self._cancel_tasks()
        self._set_state(STOPPED)

    # ── internals ────────────────────────────────────────────────────────

    def _set_state(self, state: str, error: str = "") -> None:
        if state != self.state:
            logger.info(
                f"[WA-Session] {self.identity}: {self.state} → {state}"
                + (f" ({error})" if error else "")
            )
        if state == CONNECTED:
            self._ever_connected = True
        self.state = state
        self.state_since = time.time()
        self.last_error = error

    def _cancel_tasks(self) -> None:
        for attr in ("_launch_task", "_supervisor", "_reconnect_task"):
            task = getattr(self, attr)
            if task is not None and not task.done():
                task.cancel()
            setattr(self, attr, None)

    def _start_supervisor(self, bridge) -> None:
        if self._supervisor is not None and not self._supervisor.done():
            self._supervisor.cancel()
        self._supervisor = _spawn(self._supervise(bridge))

    async def _launch(self) -> None:
        from ._bridge_client import get_whatsapp_bridge

        try:
            bridge = get_whatsapp_bridge(self.identity)
            bridge.set_event_callback(self._on_bridge_event)
            if bridge.is_running and bridge.is_ready:
                self._start_supervisor(bridge)
                self._failures = 0
                self._set_state(CONNECTED)
                return
            if bridge.is_running:
                # Half-started leftover (e.g. rewire between tests) — clean
                # restart under our supervision.
                await bridge.stop()
            await bridge.start()
            self._start_supervisor(bridge)
            event_type, _ = await bridge.wait_for_qr_or_ready(
                timeout=self.LAUNCH_WAIT
            )
            if self._stopping:
                return
            if event_type == "ready":
                self._failures = 0
                _clear_relink_marker(self.identity)
                self._set_state(CONNECTED)
            elif event_type == "qr":
                await self._park_needs_relink(bridge)
            elif event_type == "error":
                # Fatal bridge error — the process exits on its own; the
                # supervisor classifies the exit and applies backoff.
                self.last_error = "bridge reported a fatal error during launch"
            else:  # timeout — 'ready' may still arrive; the event handler
                # flips CONNECTED, and exit supervision covers a dead hang.
                logger.warning(
                    f"[WA-Session] {self.identity}: no qr/ready within "
                    f"{self.LAUNCH_WAIT:.0f}s — staying in LAUNCHING under "
                    "supervision"
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._stopping:
                logger.warning(f"[WA-Session] {self.identity}: launch failed: {e}")
                self._register_failure(f"launch failed: {e}")

    async def _park_needs_relink(self, bridge) -> None:
        """Stale LocalAuth (QR instead of ready): one attempt, one clear
        notice, then parked — never a respawn loop (D4)."""
        if self.state == NEEDS_RELINK:
            return
        self._stopping = True  # the abandon-exit below is expected
        if self._supervisor is not None and not self._supervisor.done():
            self._supervisor.cancel()
        self._supervisor = None
        bridge.set_event_callback(None)
        try:
            await bridge.abandon()
        except Exception as e:
            logger.warning(f"[WA-Session] {self.identity}: abandon error: {e}")
        _write_relink_marker(self.identity)
        self._set_state(
            NEEDS_RELINK,
            "stored session is no longer restorable — re-link via QR",
        )
        self._stopping = False
        logger.warning(
            f"[WA-Session] WhatsApp account {self.identity} needs re-linking "
            "via QR from the integrations settings page. Listening is parked "
            "until then."
        )

    async def _supervise(self, bridge) -> None:
        """Watch the Node process: exit → classify (crash vs expected),
        plus the ping heartbeat while it lives."""
        misses = 0
        exit_wait = None
        try:
            while True:
                exit_wait = asyncio.ensure_future(bridge.wait_exited())
                done, _ = await asyncio.wait(
                    {exit_wait}, timeout=self.HEARTBEAT_INTERVAL
                )
                if exit_wait in done:
                    rc = exit_wait.result()
                    if self._stopping:
                        return
                    self._on_bridge_exit(rc)
                    return
                exit_wait.cancel()
                if self._stopping or not bridge.is_running:
                    return
                try:
                    await bridge.ping(timeout=self.HEARTBEAT_TIMEOUT)
                    misses = 0
                except Exception as e:
                    misses += 1
                    logger.warning(
                        f"[WA-Session] {self.identity}: heartbeat miss "
                        f"{misses}/{self.HEARTBEAT_MISSES}: {e}"
                    )
                    if misses >= self.HEARTBEAT_MISSES:
                        logger.warning(
                            f"[WA-Session] {self.identity}: process alive but "
                            "unresponsive — restarting"
                        )
                        try:
                            await bridge.stop()
                        except Exception:
                            pass
                        if not self._stopping:
                            self._register_failure(
                                "heartbeat: bridge process hung"
                            )
                        return
        except asyncio.CancelledError:
            pass
        finally:
            # asyncio.wait never cancels its awaitables — without this, a
            # cancelled supervisor leaks its exit-watch task into the loop
            # forever (the shielded exit future itself is unaffected).
            if exit_wait is not None and not exit_wait.done():
                exit_wait.cancel()

    def _on_bridge_exit(self, rc) -> None:
        if self._relink_flagged:
            self._relink_flagged = False
            _write_relink_marker(self.identity)
            self._set_state(
                NEEDS_RELINK,
                "device was unlinked from the phone — re-link via QR",
            )
            logger.warning(
                f"[WA-Session] WhatsApp account {self.identity} was unlinked "
                "from the phone (LOGOUT) — parked until re-linked via QR."
            )
            return
        self._register_failure(f"bridge process exited (code {rc})")

    def _register_failure(self, reason: str) -> None:
        self._failures += 1
        if self._failures >= self.MAX_FAILURES and not self._ever_connected:
            # Escape hatch: the failure cap was reached without EVER
            # reaching CONNECTED since the session started — the stored
            # LocalAuth is unusable (torn profile, revoked session) and
            # hourly FAILED retries would strand the account forever. Park
            # with the re-link CTA instead. (Cost if it was actually a
            # very long outage: one QR re-scan.)
            _write_relink_marker(self.identity)
            self._set_state(
                NEEDS_RELINK,
                f"session never became ready ({reason}) — the stored "
                "session appears unusable; re-link via QR",
            )
            logger.warning(
                f"[WA-Session] WhatsApp account {self.identity} failed "
                f"{self._failures}x without ever connecting — the stored "
                "session appears unusable (or the network was down "
                "throughout). Parked; re-link via QR from the integrations "
                "settings page."
            )
            return
        if self._failures >= self.MAX_FAILURES:
            delay = self.FAILED_RETRY_INTERVAL
            self._set_state(FAILED, reason)
            logger.warning(
                f"[WA-Session] {self.identity}: {self._failures} consecutive "
                f"failures ({reason}) — parked in FAILED, retrying in "
                f"{delay / 60:.0f}min"
            )
        else:
            delay = min(
                self.BACKOFF_BASE * (2 ** (self._failures - 1)),
                self.BACKOFF_CAP,
            ) * random.uniform(0.8, 1.2)
            self._set_state(RECONNECTING, reason)
            logger.info(
                f"[WA-Session] {self.identity}: {reason} — reconnecting in "
                f"{delay:.1f}s (failure {self._failures}/{self.MAX_FAILURES})"
            )
        self._reconnect_task = _spawn(self._reconnect_after(delay))

    async def _reconnect_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._stopping or self.state not in (RECONNECTING, FAILED):
            return
        self._set_state(LAUNCHING)
        self._launch_task = _spawn(self._launch())

    async def _on_bridge_event(self, event: str, data: Dict[str, Any]) -> None:
        """The session sees every bridge event first (state machine), then
        forwards to the subscriber (the bound client's _on_bridge_event)."""
        try:
            if event == "ready" and not self._stopping:
                self._failures = 0
                _clear_relink_marker(self.identity)
                if self.state != CONNECTED:
                    self._set_state(CONNECTED)
            elif event == "disconnected":
                reason = str((data or {}).get("reason", ""))
                if "logout" in reason.lower():
                    # User unlinked from the phone: flag it — the process
                    # exits right after this event, and exit classification
                    # turns the flag into NEEDS_RELINK instead of a
                    # respawn loop.
                    self._relink_flagged = True
            elif event == "qr" and self.state in (LAUNCHING, CONNECTED):
                # A session never expects a QR — stale LocalAuth. Park.
                from ._bridge_client import peek_whatsapp_bridge

                bridge = peek_whatsapp_bridge(self.identity)
                if bridge is not None:
                    _spawn(self._park_needs_relink(bridge))
        except Exception as e:
            logger.warning(
                f"[WA-Session] {self.identity}: event state handling error: {e}"
            )

        subscriber = self._subscriber
        if subscriber is not None:
            try:
                await subscriber(event, data)
            except Exception as e:
                logger.warning(
                    f"[WA-Session] {self.identity}: subscriber error on "
                    f"'{event}': {e}"
                )


# ════════════════════════════════════════════════════════════════════════
# LinkFlow — one QR login, event-driven, single-flight promotion
# ════════════════════════════════════════════════════════════════════════


def _qr_to_data_url(event_data: Optional[Dict[str, Any]]) -> str:
    """QR data URL from a bridge qr event, generating the PNG locally when
    the bridge could not."""
    qr_data = (event_data or {}).get("qr_data_url") or ""
    if not qr_data:
        qr_string = (event_data or {}).get("qr_string", "")
        if qr_string:
            try:
                import base64
                import io

                import qrcode

                qr = qrcode.QRCode(border=1)
                qr.add_data(qr_string)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                qr_data = (
                    "data:image/png;base64,"
                    + base64.b64encode(buf.getvalue()).decode()
                )
            except Exception as e:
                logger.warning(f"[WA-Link] QR image generation failed: {e}")
    if qr_data and not qr_data.startswith("data:"):
        qr_data = f"data:image/png;base64,{qr_data}"
    return qr_data


class LinkFlow:
    """One pending QR login: own bridge, own temp auth dir, states the UI
    can render verbatim. The flow stays registered through promotion so a
    concurrent poller can never hit 'Session not found' after success —
    ``DONE`` is idempotent."""

    QR_CYCLE_SECONDS = 300.0  # fresh QR window; the bridge refreshes within it
    MAX_QR_CYCLES = 3
    # No poll for this long while a QR is pending = the modal was abandoned
    # — stop holding a connection open for it. Generous enough for the agent
    # action path, which polls at LLM speed.
    ABANDON_AFTER = 120.0
    WATCH_INTERVAL = 5.0
    # A pending bridge that dies mid-flow (e.g. the INJECT watchdog fired
    # because the post-scan sync outran its budget) gets relaunched from
    # its own pending dir — the auth saved at scan time restores without a
    # new QR. The session actor supervises its bridges; the flow must
    # supervise its own (observed live 2026-08-21 15:14: a successful scan
    # turned into "bridge stopped unexpectedly" because nobody restarted
    # the pending bridge).
    MAX_RELAUNCHES = 2

    def __init__(self, manager: "WhatsAppSessionManager", session_id: str) -> None:
        self._manager = manager
        self.session_id = session_id
        self.state = FLOW_STARTING
        self.qr_code = ""
        self.result: Optional[Dict[str, Any]] = None
        self.error = ""
        self.cycles = 1
        self.relaunches = 0
        self.created = time.time()
        self.last_poll = time.time()
        self.cycle_started = time.time()
        self._bridge = None
        self._completing = False
        self._relaunching = False
        self._watch_task: Optional[asyncio.Task] = None

    # ── lifecycle ────────────────────────────────────────────────────────

    async def begin(self) -> Dict[str, Any]:
        from ._bridge_client import BridgeCapacityError, create_pending_bridge

        try:
            self._bridge = create_pending_bridge(self.session_id)
        except BridgeCapacityError as e:
            self.state = FLOW_FAILED
            self.error = str(e)
            return {"success": False, "status": "error", "message": str(e)}

        try:
            self._bridge.set_event_callback(self._on_bridge_event)
            await self._bridge.start()
            event_type, event_data = await self._bridge.wait_for_qr_or_ready(
                timeout=60.0
            )

            if event_type == "ready":
                # Fresh pending dirs shouldn't be pre-authed, but if it
                # happens, finish the login properly.
                return await self._complete()

            if event_type == "qr":
                qr = _qr_to_data_url(event_data)
                if not qr:
                    await self._dispose()
                    self.state = FLOW_FAILED
                    self.error = "Failed to generate QR code."
                    return {
                        "success": False,
                        "status": "error",
                        "message": self.error,
                    }
                self.qr_code = qr
                self.state = FLOW_QR_READY
                self.cycle_started = time.time()
                self._watch_task = _spawn(self._watch())
                return {
                    "success": True,
                    "session_id": self.session_id,
                    "qr_code": self.qr_code,
                    "status": "qr_ready",
                    "expires_in": int(self.QR_CYCLE_SECONDS),
                    "message": "Scan the QR code with your WhatsApp mobile app",
                }

            await self._dispose()
            self.state = FLOW_FAILED
            if event_type == "error":
                detail = (event_data or {}).get("message") or "unknown bridge error"
                self.error = f"WhatsApp bridge failed to start: {detail}"
            else:
                self.error = "Timed out waiting for WhatsApp bridge."
            return {"success": False, "status": "error", "message": self.error}
        except Exception as e:
            logger.error(f"[WA-Link] failed to start QR session: {e}")
            await self._dispose()
            self.state = FLOW_FAILED
            self.error = f"Failed to start session: {e}"
            return {"success": False, "status": "error", "message": self.error}

    async def status(self) -> Dict[str, Any]:
        self.last_poll = time.time()
        if self.state == FLOW_DONE:
            return dict(self.result or {})
        if self.state in (FLOW_FAILED, FLOW_TIMEOUT, FLOW_CANCELLED):
            return self._terminal_dict()
        if self.state == FLOW_PROMOTING or self._completing:
            return {
                "success": True,
                "status": "promoting",
                "connected": False,
                "message": "QR scanned — finishing connection...",
            }
        bridge = self._bridge
        if bridge is not None and bridge.is_ready:
            return await self._complete()
        # A dead pending bridge is NOT an instant failure — the watcher
        # relaunches it (bounded); until then keep reporting the live state
        # so the UI shows "connecting…" instead of an error flash.
        if self.state == FLOW_SCANNED:
            return {
                "success": True,
                "status": "scanned",
                "connected": False,
                "message": "QR scanned — connecting...",
            }
        remaining = max(
            0, int(self.cycle_started + self.QR_CYCLE_SECONDS - time.time())
        )
        return {
            "success": True,
            "status": "qr_ready",
            "connected": False,
            "qr_code": self.qr_code,
            "expires_in": remaining,
            "cycle": self.cycles,
            "message": "Waiting for QR code scan...",
        }

    async def cancel(self, reason: str = "Session cancelled.") -> Dict[str, Any]:
        if self.state in _FLOW_TERMINAL:
            return {"success": True, "message": reason}
        self.state = FLOW_CANCELLED
        self.error = reason
        await self._dispose()
        return {"success": True, "message": reason}

    # ── internals ────────────────────────────────────────────────────────

    def _terminal_dict(self) -> Dict[str, Any]:
        return {
            "success": False,
            "status": self.state,
            "connected": False,
            "message": self.error
            or {
                FLOW_TIMEOUT: "QR code expired — start a new connection attempt.",
                FLOW_CANCELLED: "Session cancelled.",
            }.get(self.state, "Session failed."),
        }

    async def _on_bridge_event(self, event: str, data: Dict[str, Any]) -> None:
        if self.state in _FLOW_TERMINAL:
            return
        if event == "qr":
            # The bridge refreshes the code periodically — always show the
            # newest one.
            fresh = _qr_to_data_url(data)
            if fresh:
                self.qr_code = fresh
            if self.state == FLOW_STARTING:
                self.state = FLOW_QR_READY
        elif event == "authenticated":
            if self.state in (FLOW_QR_READY, FLOW_STARTING):
                self.state = FLOW_SCANNED
        elif event == "ready":
            _spawn(self._complete())

    async def _complete(self) -> Dict[str, Any]:
        """Single-flight promotion; idempotent result."""
        if self.state == FLOW_DONE and self.result:
            return dict(self.result)
        if self._completing:
            return {
                "success": True,
                "status": "promoting",
                "connected": False,
                "message": "QR scanned — finishing connection...",
            }
        self._completing = True
        self.state = FLOW_PROMOTING
        try:
            from ._bridge_client import (
                adopt_pending_bridge,
                discard_pending_bridge,
                normalize_wa_identity,
            )

            bridge = self._bridge
            owner_phone = getattr(bridge, "owner_phone", "") or ""
            owner_name = getattr(bridge, "owner_name", "") or ""
            wid = getattr(bridge, "wid", "") or ""
            identity = normalize_wa_identity(wid or owner_phone)

            if identity is None:
                # Connected but no usable identity — don't leave a
                # nameless bridge running.
                await discard_pending_bridge(self.session_id)
                self.state = FLOW_FAILED
                self.error = (
                    "WhatsApp connected but did not report a phone number/wid. "
                    "Please try again."
                )
                return self._terminal_dict()

            if self._watch_task is not None:
                self._watch_task.cancel()
                self._watch_task = None

            # Halt any old session actor for this identity BEFORE its bridge
            # is stopped/replaced, so its supervisor can't misread the
            # replacement as a crash.
            self._manager.on_link_completed(identity)
            # Adopt the LIVE bridge — the freshly-linked browser keeps
            # running as the account's session. Never a stop-move-restart:
            # restarting seconds after `ready` restored a half-written
            # LocalAuth and bricked the account (torn-profile bug,
            # 2026-08-21). The listener reconcile that follows the host's
            # store_credential finds it running+ready and goes straight to
            # CONNECTED.
            await adopt_pending_bridge(self.session_id, identity)

            display = owner_phone or owner_name or identity
            self.result = {
                "success": True,
                "status": "connected",
                "connected": True,
                "session_id": self.session_id,
                "identity": identity,
                "owner_phone": owner_phone,
                "owner_name": owner_name,
                "credential": {
                    "session_id": identity,
                    "owner_phone": owner_phone,
                    "owner_name": owner_name,
                    "wid": wid,
                },
                "message": f"WhatsApp connected: +{display}",
            }
            self.state = FLOW_DONE
            return dict(self.result)
        except Exception as e:
            logger.error(f"[WA-Link] promotion failed: {e}")
            self.state = FLOW_FAILED
            self.error = f"Failed to finish connection: {e}"
            await self._dispose()
            return self._terminal_dict()
        finally:
            self._completing = False

    async def _watch(self) -> None:
        """Flow supervision: dead-bridge relaunch, abandon detection, and
        QR-cycle recycling. Event-driven transitions happen elsewhere; this
        enforces time/liveness policy."""
        try:
            while self.state in (FLOW_QR_READY, FLOW_SCANNED):
                await asyncio.sleep(self.WATCH_INTERVAL)
                now = time.time()
                if self.state not in (FLOW_QR_READY, FLOW_SCANNED):
                    return
                bridge = self._bridge
                if (
                    bridge is not None
                    and not bridge.is_running
                    and not self._completing
                    and not self._relaunching
                ):
                    await self._relaunch_bridge()
                    continue
                if now - self.last_poll > self.ABANDON_AFTER:
                    logger.info(
                        f"[WA-Link] flow {self.session_id[:8]} abandoned "
                        "(nobody polling) — cancelling"
                    )
                    await self.cancel(
                        reason="QR session abandoned (no polling)."
                    )
                    return
                if (
                    self.state == FLOW_QR_READY
                    and now - self.cycle_started > self.QR_CYCLE_SECONDS
                ):
                    await self._recycle()
        except asyncio.CancelledError:
            pass

    async def _relaunch_bridge(self) -> None:
        """The pending bridge's process died mid-flow (INJECT watchdog on a
        slow post-scan sync, crash). Relaunch it from its own pending dir:
        the auth saved at scan time restores WITHOUT a new QR, so from the
        user's side the flow just keeps 'connecting…'. Bounded — after
        MAX_RELAUNCHES the flow fails honestly."""
        self.relaunches += 1
        if self.relaunches > self.MAX_RELAUNCHES:
            logger.warning(
                f"[WA-Link] flow {self.session_id[:8]}: bridge died "
                f"{self.relaunches}x — giving up"
            )
            self.state = FLOW_FAILED
            self.error = (
                "WhatsApp kept disconnecting while finishing the link. "
                "Please try again."
            )
            await self._dispose()
            return
        self._relaunching = True
        logger.info(
            f"[WA-Link] flow {self.session_id[:8]}: pending bridge died — "
            f"relaunching from saved auth "
            f"({self.relaunches}/{self.MAX_RELAUNCHES})"
        )
        try:
            bridge = self._bridge
            bridge.set_event_callback(self._on_bridge_event)
            await bridge.start()
            event_type, event_data = await bridge.wait_for_qr_or_ready(
                timeout=60.0
            )
            if self.state in _FLOW_TERMINAL:
                return
            if event_type == "ready":
                await self._complete()
            elif event_type == "qr":
                # The scan-time auth didn't survive — back to a fresh QR;
                # the user has to re-scan (the UI shows the new code).
                fresh = _qr_to_data_url(event_data)
                if fresh:
                    self.qr_code = fresh
                self.state = FLOW_QR_READY
                self.cycle_started = time.time()
            # timeout / error: the process either lives (ready may still
            # arrive via the event handler) or died again — the next watch
            # tick re-enters here and the relaunch counter caps it.
        except Exception as e:
            logger.warning(
                f"[WA-Link] flow {self.session_id[:8]}: relaunch failed: {e}"
            )
        finally:
            self._relaunching = False

    async def _recycle(self) -> None:
        """Fresh QR for a new window — event-driven renewal, never a
        destroy-and-respawn 'recovery'. After MAX_QR_CYCLES: park as
        TIMEOUT with a start-again CTA."""
        from ._bridge_client import create_pending_bridge, discard_pending_bridge

        if self.cycles >= self.MAX_QR_CYCLES:
            logger.info(
                f"[WA-Link] flow {self.session_id[:8]}: QR unscanned after "
                f"{self.cycles} cycle(s) — timing out"
            )
            self.state = FLOW_TIMEOUT
            self.error = (
                "QR code expired after "
                f"{int(self.cycles * self.QR_CYCLE_SECONDS / 60)} minutes — "
                "start a new connection attempt."
            )
            await self._dispose()
            return
        self.cycles += 1
        logger.info(
            f"[WA-Link] flow {self.session_id[:8]}: recycling for a fresh QR "
            f"(cycle {self.cycles}/{self.MAX_QR_CYCLES})"
        )
        try:
            await discard_pending_bridge(self.session_id)
            self._bridge = create_pending_bridge(self.session_id)
            self._bridge.set_event_callback(self._on_bridge_event)
            await self._bridge.start()
            event_type, event_data = await self._bridge.wait_for_qr_or_ready(
                timeout=60.0
            )
            if event_type == "ready":
                await self._complete()
                return
            if event_type != "qr":
                raise RuntimeError(f"no fresh QR (got {event_type})")
            fresh = _qr_to_data_url(event_data)
            if fresh:
                self.qr_code = fresh
            self.state = FLOW_QR_READY
            self.cycle_started = time.time()
        except Exception as e:
            logger.warning(f"[WA-Link] recycle failed: {e}")
            self.state = FLOW_FAILED
            self.error = f"Could not refresh the QR code: {e}"
            await self._dispose()

    async def _dispose(self) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None
        try:
            from ._bridge_client import discard_pending_bridge

            await discard_pending_bridge(self.session_id)
        except Exception as e:
            logger.warning(f"[WA-Link] dispose cleanup failed: {e}")


# ════════════════════════════════════════════════════════════════════════
# WhatsAppSessionManager — module singleton
# ════════════════════════════════════════════════════════════════════════


class WhatsAppSessionManager:
    RECENT_LINK_GUARD_SECONDS = 30.0
    FLOW_GC_AFTER = 600.0  # forget terminal flows this long after last poll
    ORPHAN_PENDING_MAX_AGE = 3600.0

    def __init__(self) -> None:
        self._sessions: Dict[str, WhatsAppSession] = {}
        self._flows: Dict[str, LinkFlow] = {}
        self._last_link_ts = 0.0
        self._boot_swept = False

    # ── sessions ─────────────────────────────────────────────────────────

    def session_for(self, identity: str) -> WhatsAppSession:
        from ._bridge_client import normalize_wa_identity

        normalized = normalize_wa_identity(identity)
        if normalized is None:
            raise ValueError(f"invalid whatsapp identity: {identity!r}")
        session = self._sessions.get(normalized)
        if session is None:
            self.boot_sweep()
            session = WhatsAppSession(normalized)
            self._sessions[normalized] = session
        return session

    def peek(self, identity: str) -> Optional[WhatsAppSession]:
        from ._bridge_client import normalize_wa_identity

        normalized = normalize_wa_identity(identity)
        if normalized is None:
            return None
        return self._sessions.get(normalized)

    def state_of(self, identity: str) -> Optional[str]:
        """Session state for UI/status surfaces — NEEDS_RELINK is read
        from the persisted marker even before any session object exists."""
        from ._bridge_client import normalize_wa_identity

        normalized = normalize_wa_identity(identity)
        if normalized is None:
            return None
        session = self._sessions.get(normalized)
        if session is not None and session.state != STOPPED:
            return session.state
        if _has_relink_marker(normalized):
            return NEEDS_RELINK
        return session.state if session is not None else None

    async def teardown(self, identity: str) -> None:
        """Full account removal, serialized with the actor: server-side
        logout while the session still exists → verified process death →
        auth-dir delete (§2.6). Idempotent."""
        from ._bridge_client import _teardown_account_impl, normalize_wa_identity

        normalized = normalize_wa_identity(identity)
        if normalized is None:
            return
        session = self._sessions.pop(normalized, None)
        if session is not None:
            session.halt_nowait()
        await _teardown_account_impl(normalized)
        _clear_relink_marker(normalized)

    async def shutdown_all(self) -> None:
        """App-shutdown hook: graceful ``shutdown`` to every live bridge so
        WhatsApp sees a clean disconnect instead of a crash — this directly
        extends how long the server trusts the stored session."""
        sessions = list(self._sessions.values())
        flows = [f for f in self._flows.values() if f.state not in _FLOW_TERMINAL]
        if sessions or flows:
            logger.info(
                f"[WA-Session] shutting down {len(sessions)} session(s) and "
                f"{len(flows)} pending link flow(s)"
            )
        await asyncio.gather(
            *(s.stop() for s in sessions),
            *(f.cancel(reason="Agent shutting down.") for f in flows),
            return_exceptions=True,
        )

    def on_link_completed(self, identity: str) -> None:
        """Called by LinkFlow right after promotion: the fresh LocalAuth
        replaces whatever the old session knew — reset the actor so the
        next listener reconcile starts clean."""
        from ._bridge_client import normalize_wa_identity

        self._last_link_ts = time.time()
        normalized = normalize_wa_identity(identity)
        if normalized is None:
            return
        old = self._sessions.pop(normalized, None)
        if old is not None:
            old.halt_nowait()
        _clear_relink_marker(normalized)

    def boot_sweep(self) -> None:
        """Once per process: delete orphan ``pending-*`` dirs (interrupted
        promotes / crashes mid-link) older than an hour. Fixes the
        slot-accounting leak — a stale pending dir must never count against
        max_accounts forever."""
        if self._boot_swept:
            return
        self._boot_swept = True
        try:
            from ._bridge_client import (
                _ADOPTED_MARKER,
                _PENDING_DIR_PREFIX,
                _auth_root,
                _pending_keys,
            )

            root = _auth_root()
            if not root.exists():
                return
            import shutil

            now = time.time()
            for child in root.iterdir():
                if not child.is_dir() or not child.name.startswith(
                    _PENDING_DIR_PREFIX
                ):
                    continue
                if (child / _ADOPTED_MARKER).exists():
                    continue  # a live account awaiting its deferred rename
                sid = child.name[len(_PENDING_DIR_PREFIX):]
                if sid in _pending_keys:
                    continue  # live link flow
                try:
                    age = now - child.stat().st_mtime
                except OSError:
                    continue
                if age < self.ORPHAN_PENDING_MAX_AGE:
                    continue
                shutil.rmtree(child, ignore_errors=True)
                logger.info(
                    f"[WA-Session] boot sweep removed orphan pending dir "
                    f"{child.name} (age {age / 60:.0f}min)"
                )
        except Exception as e:
            logger.warning(f"[WA-Session] boot sweep failed: {e}")

    # ── link flows ───────────────────────────────────────────────────────

    async def start_link_flow(self, force: bool = False) -> Dict[str, Any]:
        self.boot_sweep()
        self._gc_flows()
        if (
            not force
            and self._last_link_ts
            and time.time() - self._last_link_ts < self.RECENT_LINK_GUARD_SECONDS
        ):
            # Belt-and-braces against ghost flows (a stale poller starting
            # a fresh QR right after a successful link — log 4). Explicit
            # user clicks pass force=True.
            return {
                "success": False,
                "status": "error",
                "message": (
                    "A WhatsApp account was connected moments ago. If you "
                    "want to link another account, try again in a few "
                    "seconds."
                ),
            }
        flow = LinkFlow(self, uuid.uuid4().hex)
        result = await flow.begin()
        if flow.state != FLOW_FAILED:
            self._flows[flow.session_id] = flow
        return result

    async def link_flow_status(self, session_id: str) -> Dict[str, Any]:
        flow = self._flows.get(session_id)
        if flow is None:
            return {
                "success": False,
                "status": "error",
                "connected": False,
                "message": "Session not found. Please start a new session.",
            }
        return await flow.status()

    async def cancel_link_flow(self, session_id: str) -> Dict[str, Any]:
        flow = self._flows.pop(session_id, None)
        if flow is None:
            return {
                "success": True,
                "message": "Session not found or already cancelled.",
            }
        return await flow.cancel()

    def _gc_flows(self) -> None:
        now = time.time()
        for sid, flow in list(self._flows.items()):
            if (
                flow.state in _FLOW_TERMINAL
                and now - flow.last_poll > self.FLOW_GC_AFTER
            ):
                del self._flows[sid]


_manager: Optional[WhatsAppSessionManager] = None


def get_session_manager() -> WhatsAppSessionManager:
    global _manager
    if _manager is None:
        _manager = WhatsAppSessionManager()
    return _manager


def _reset_session_manager_for_tests() -> None:
    global _manager
    if _manager is not None:
        for session in _manager._sessions.values():
            session.halt_nowait()
        for flow in _manager._flows.values():
            flow.state = FLOW_CANCELLED
            if flow._watch_task is not None:
                flow._watch_task.cancel()
                flow._watch_task = None
    # Environments where asyncio.run shares one loop (nest_asyncio) keep
    # background tasks alive across tests — cancel them all.
    for task in list(_bg_tasks):
        task.cancel()
    _bg_tasks.clear()
    _manager = None
