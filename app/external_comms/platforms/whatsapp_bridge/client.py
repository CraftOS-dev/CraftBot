# -*- coding: utf-8 -*-
"""
Python client for the WhatsApp Node.js bridge process.

Manages the Node.js subprocess lifecycle and provides an async API for
sending commands and receiving events via stdin/stdout JSON lines.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

# Path to the bridge.js script
BRIDGE_DIR = Path(__file__).parent
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"

# Type alias for event callbacks
EventCallback = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]


class WhatsAppBridge:
    """
    Manages a whatsapp-web.js Node.js subprocess.

    Communication:
      - Commands are sent as JSON lines to the subprocess stdin.
      - Events and responses are read as JSON lines from stdout.
      - Logs from the bridge go to stderr (forwarded to Python logger).
    """

    def __init__(self, auth_dir: Optional[str] = None):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._event_callback: Optional[EventCallback] = None
        self._running = False
        self._ready = False
        self._owner_phone = ""
        self._owner_name = ""
        self._wid = ""

        if auth_dir:
            self._auth_dir = auth_dir
        else:
            # Default: .credentials/whatsapp_wwebjs_auth relative to project root
            project_root = Path(__file__).parent.parent.parent.parent.parent
            self._auth_dir = str(project_root / ".credentials" / "whatsapp_wwebjs_auth")

    @property
    def is_running(self) -> bool:
        return self._running and self._process is not None and self._process.returncode is None

    @property
    def is_ready(self) -> bool:
        return self._ready and self.is_running

    @property
    def owner_phone(self) -> str:
        return self._owner_phone

    @property
    def owner_name(self) -> str:
        return self._owner_name

    def set_event_callback(self, callback: EventCallback) -> None:
        """Set the callback for bridge events (message, qr, ready, etc.)."""
        self._event_callback = callback

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Node.js bridge subprocess."""
        if self.is_running:
            logger.warning("[WA-Bridge] Already running")
            return

        # Ensure node_modules are installed
        node_modules = BRIDGE_DIR / "node_modules"
        if not node_modules.exists():
            logger.info("[WA-Bridge] Installing npm dependencies...")
            proc = await asyncio.create_subprocess_exec(
                "npm", "install",
                cwd=str(BRIDGE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read()
                raise RuntimeError(f"npm install failed: {stderr.decode()}")

        logger.info(f"[WA-Bridge] Starting bridge process (auth_dir={self._auth_dir})")

        self._process = await asyncio.create_subprocess_exec(
            "node", str(BRIDGE_SCRIPT), self._auth_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._running = True
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        logger.info(f"[WA-Bridge] Process started (pid={self._process.pid})")

    async def stop(self) -> None:
        """Gracefully stop the bridge subprocess."""
        if not self.is_running:
            return

        logger.info("[WA-Bridge] Stopping bridge...")
        self._running = False
        self._ready = False

        # Send shutdown command
        try:
            await self.send_command("shutdown", timeout=5.0)
        except Exception:
            pass

        # Wait for process to exit
        if self._process:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("[WA-Bridge] Process did not exit, killing")
                self._process.kill()

        # Cancel reader tasks
        for task in [self._reader_task, self._stderr_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._process = None
        self._reader_task = None
        self._stderr_task = None

        # Resolve pending futures with errors
        for req_id, future in self._pending.items():
            if not future.done():
                future.set_exception(RuntimeError("Bridge stopped"))
        self._pending.clear()

        logger.info("[WA-Bridge] Bridge stopped")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def send_command(
        self,
        cmd: str,
        args: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Send a command to the bridge and wait for the response."""
        if not self.is_running:
            raise RuntimeError("Bridge not running")

        req_id = f"req_{uuid.uuid4().hex[:8]}"
        payload = json.dumps({"id": req_id, "cmd": cmd, "args": args or {}})

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            self._process.stdin.write((payload + "\n").encode())
            await self._process.stdin.drain()
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"Command '{cmd}' timed out after {timeout}s")
        except Exception:
            self._pending.pop(req_id, None)
            raise

    async def send_message(self, to: str, text: str) -> Dict[str, Any]:
        """Send a text message."""
        return await self.send_command("send_message", {"to": to, "text": text})

    async def get_status(self) -> Dict[str, Any]:
        """Get bridge/client status."""
        return await self.send_command("get_status")

    async def get_chats(self, limit: int = 50) -> Dict[str, Any]:
        """Get recent chats."""
        return await self.send_command("get_chats", {"limit": limit})

    async def get_chat_messages(self, chat_id: str, limit: int = 50) -> Dict[str, Any]:
        """Get messages from a chat."""
        return await self.send_command("get_chat_messages", {"chat_id": chat_id, "limit": limit})

    async def search_contact(self, name: str) -> Dict[str, Any]:
        """Search contacts by name."""
        return await self.send_command("search_contact", {"name": name})

    async def get_unread_chats(self) -> Dict[str, Any]:
        """Get chats with unread messages."""
        return await self.send_command("get_unread_chats")

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    async def wait_for_ready(self, timeout: float = 120.0) -> bool:
        """Wait until the bridge reports 'ready' (connected to WhatsApp)."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._ready:
                return True
            if not self.is_running:
                return False
            await asyncio.sleep(0.5)
        return False

    async def wait_for_qr_or_ready(self, timeout: float = 120.0):
        """
        Wait until either a QR code is emitted or client becomes ready.
        Returns ("ready", data) or ("qr", data) or ("timeout", None).
        """
        # If already ready, return immediately
        if self._ready:
            return "ready", {
                "owner_phone": self._owner_phone,
                "owner_name": self._owner_name,
                "wid": self._wid,
            }

        event_received = asyncio.Event()
        result = {"type": None, "data": None}

        original_callback = self._event_callback

        async def intercept_callback(event: str, data: dict):
            if event in ("qr", "ready") and result["type"] is None:
                result["type"] = event
                result["data"] = data
                event_received.set()
            if original_callback:
                await original_callback(event, data)

        self._event_callback = intercept_callback
        try:
            await asyncio.wait_for(event_received.wait(), timeout=timeout)
            return result["type"], result["data"]
        except asyncio.TimeoutError:
            return "timeout", None
        finally:
            self._event_callback = original_callback

    # ------------------------------------------------------------------
    # Internal: stdout/stderr readers
    # ------------------------------------------------------------------

    async def _read_stdout(self) -> None:
        """Read JSON lines from the bridge stdout."""
        try:
            while self._running and self._process and self._process.stdout:
                line = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode().strip())
                except json.JSONDecodeError:
                    logger.debug(f"[WA-Bridge] Non-JSON stdout: {line.decode().strip()}")
                    continue

                msg_type = data.get("type")

                if msg_type == "response":
                    req_id = data.get("id")
                    future = self._pending.pop(req_id, None)
                    if future and not future.done():
                        future.set_result(data.get("data", {}))

                elif msg_type == "event":
                    event = data.get("event", "")
                    event_data = data.get("data", {})
                    self._handle_event(event, event_data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[WA-Bridge] stdout reader error: {e}")
        finally:
            if self._running:
                logger.warning("[WA-Bridge] stdout reader exited unexpectedly")
                self._ready = False

    async def _read_stderr(self) -> None:
        """Forward bridge stderr to Python logger."""
        try:
            while self._running and self._process and self._process.stderr:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    logger.info(f"[WA-Bridge:node] {text}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[WA-Bridge] stderr reader error: {e}")

    def _handle_event(self, event: str, data: Dict[str, Any]) -> None:
        """Process an event from the bridge."""
        if event == "ready":
            self._ready = True
            self._owner_phone = data.get("owner_phone", "")
            self._owner_name = data.get("owner_name", "")
            self._wid = data.get("wid", "")
            logger.info(
                f"[WA-Bridge] Ready: phone={self._owner_phone}, "
                f"name={self._owner_name}, wid={self._wid}"
            )

        elif event == "disconnected":
            self._ready = False
            logger.warning(f"[WA-Bridge] Disconnected: {data.get('reason', 'unknown')}")

        elif event == "message":
            logger.info(
                f"[WA-Bridge] Message from {data.get('contact', {}).get('name', 'unknown')} "
                f"in {data.get('chat', {}).get('name', 'unknown')}: "
                f"{(data.get('body', '') or '')[:80]}"
            )

        elif event == "message_sent":
            logger.info(
                f"[WA-Bridge] Message sent to {data.get('chat', {}).get('name', 'unknown')}: "
                f"{(data.get('body', '') or '')[:80]}"
            )

        elif event == "qr":
            logger.info("[WA-Bridge] QR code received (waiting for scan)")

        elif event == "auth_failure":
            logger.error(f"[WA-Bridge] Auth failure: {data.get('message', '')}")

        # Dispatch to callback
        if self._event_callback:
            asyncio.ensure_future(self._event_callback(event, data))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge_instance: Optional[WhatsAppBridge] = None


def get_whatsapp_bridge() -> WhatsAppBridge:
    """Get or create the global WhatsAppBridge singleton."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = WhatsAppBridge()
    return _bridge_instance
