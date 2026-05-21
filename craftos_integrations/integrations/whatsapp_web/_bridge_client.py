# -*- coding: utf-8 -*-
"""Python client for the WhatsApp Node.js bridge process.

Manages the Node.js subprocess lifecycle and provides an async API for
sending commands and receiving events via stdin/stdout JSON lines.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Optional

from ...config import ConfigStore
from ...logger import get_logger

logger = get_logger(__name__)

BRIDGE_DIR = Path(__file__).parent
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"

EventCallback = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]


class WhatsAppBridge:
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
            self._auth_dir = str(ConfigStore.project_root / ".credentials" / "whatsapp_wwebjs_auth")

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

    def set_event_callback(self, callback: Optional[EventCallback]) -> None:
        self._event_callback = callback

    def _clear_stale_session_locks(self) -> None:
        """Best-effort cleanup of orphaned Chromium state in the auth dir.

        wwebjs uses Puppeteer to launch a Chromium pinned to ``auth_dir``.
        If the agent or the Node bridge is killed without going through
        ``client.destroy()``, Chromium leaves singleton lock files behind
        and (on Windows) the ``chrome.exe`` child process can outlive its
        Node parent. The next bridge launch then fails with
        "The browser is already running for ..." because Chromium thinks
        another instance owns the directory.

        We:
          1. Find any orphan Chromium processes whose ``--user-data-dir``
             argument resolves to OUR auth directory, and kill them.
          2. Remove all known singleton/lock files Chromium leaves
             (``SingletonLock``, ``SingletonSocket``, ``SingletonCookie``,
             ``lockfile`` etc.) under the session subdirectory.

        Matched by absolute path, not basename, so we don't kill unrelated
        Chrome processes.
        """
        auth_dir = Path(self._auth_dir).resolve()
        session_dir = auth_dir / "session"
        # Substring used to match the auth dir anywhere in a Chromium
        # process's command line. We deliberately avoid ``Path.resolve()``
        # equality on Windows because puppeteer launches some children
        # with the path quoted, some unquoted, some with a trailing
        # backslash, and ``Path.resolve()`` does not always round-trip
        # — every miss leaks another zombie tree.
        auth_dir_marker = str(auth_dir).lower()

        # 1. Kill orphan Chromium processes pinned to our auth dir
        killed = 0
        try:
            import psutil  # type: ignore[import-untyped]
            for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name not in ("chrome.exe", "chrome", "chromium", "chromium.exe"):
                        continue
                    cmdline = proc.info.get("cmdline") or []
                    if not cmdline:
                        continue
                    joined = " ".join(a for a in cmdline if isinstance(a, str)).lower()
                    if auth_dir_marker not in joined:
                        continue
                    proc.kill()
                    killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except ImportError:
            # No psutil — fall back to taskkill on Windows. Best-effort
            # match on the full path string in command line.
            if os.name == "nt":
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/IM", "chrome.exe",
                         "/FI", f"WINDOWTITLE eq *{session_dir.name}*"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass

        # 2. Delete singleton/lock files. Chromium creates these in the
        # user-data-dir at every launch and uses them to detect
        # already-running instances.
        lock_names = (
            "SingletonLock", "SingletonSocket", "SingletonCookie",
            "lockfile", "Singleton",
        )
        removed = 0
        for name in lock_names:
            f = session_dir / name
            try:
                if f.is_symlink() or f.exists():
                    f.unlink(missing_ok=True)
                    removed += 1
            except Exception as e:
                logger.debug(f"[WA-Bridge] could not remove {f}: {e}")

        if killed or removed:
            logger.info(
                f"[WA-Bridge] cleared stale session state "
                f"(killed {killed} orphan Chromium proc(s), removed {removed} lock file(s))"
            )

    def _wipe_orphan_localauth_if_disconnected(self) -> None:
        """Defense-in-depth: if the user's top-level credential file is gone
        but wwebjs's LocalAuth data still exists, the user has disconnected
        but the logout RPC didn't finish wiping the session before reconnect.
        Force-wipe the auth dir so the next connect demands a fresh QR
        instead of silently restoring the stale session.
        """
        import shutil
        cred_path = Path(ConfigStore.project_root) / ".credentials" / "whatsapp_web.json"
        auth_path = Path(self._auth_dir)
        if cred_path.exists():
            return  # User is still connected; LocalAuth is legitimate.
        if not auth_path.exists():
            return  # Already clean.
        try:
            shutil.rmtree(auth_path, ignore_errors=True)
            logger.info(
                "[WA-Bridge] wiped orphan LocalAuth — credential was removed "
                "but session data remained; forcing fresh QR on this connect"
            )
        except Exception as e:
            logger.warning(f"[WA-Bridge] could not wipe orphan LocalAuth: {e}")

    async def start(self) -> None:
        if self.is_running:
            return

        self._clear_stale_session_locks()
        self._wipe_orphan_localauth_if_disconnected()

        node_modules = BRIDGE_DIR / "node_modules"
        if not node_modules.exists():
            logger.info("[WA-Bridge] Installing npm dependencies...")
            npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
            proc = await asyncio.create_subprocess_exec(
                npm_cmd, "install",
                cwd=str(BRIDGE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read()
                raise RuntimeError(f"npm install failed: {stderr.decode()}")

        logger.info(f"[WA-Bridge] Starting bridge (auth_dir={self._auth_dir})")

        node_cmd = "node.exe" if os.name == "nt" else "node"
        self._process = await asyncio.create_subprocess_exec(
            node_cmd, str(BRIDGE_SCRIPT), self._auth_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._running = True
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def stop(self) -> None:
        await self._teardown(cmd="shutdown")

    async def logout(self) -> None:
        """Full disconnect — fire-and-forget, with a tight timeout.

        wwebjs's ``client.logout()`` can hang for 30+ seconds on a stuck
        session because it tries to flush the WhatsApp server-side
        invalidation through a half-broken connection. Waiting for that
        gives terrible UX (user clicks Disconnect → 2 minutes of silence).

        Trade-off: we give Node ~3s to start the server-side logout, then
        force-kill the process and wipe LocalAuth ourselves. The user's
        local state (no cred, no auth dir) is the source-of-truth for
        "disconnected"; WhatsApp will eventually expire the server session
        on its own. Net effect: disconnect feels instant, fresh QR every
        reconnect.
        """
        await self._teardown(cmd="logout", send_timeout=3.0, wait_timeout=3.0)
        from pathlib import Path
        import shutil
        try:
            shutil.rmtree(Path(self._auth_dir), ignore_errors=True)
        except Exception as e:
            logger.warning(f"[WA-Bridge] could not remove auth dir: {e}")

    async def _teardown(
        self,
        cmd: str = "shutdown",
        send_timeout: float = 10.0,
        wait_timeout: float = 20.0,
    ) -> None:
        """Send ``cmd`` to the bridge, wait for the Node process to exit,
        and clean up reader tasks. Used by both ``stop`` and ``logout``.
        Tighter timeouts give logout a snappy UX; ``stop`` keeps the
        original generous timeouts for graceful agent-shutdown paths."""
        if not self.is_running:
            return
        self._running = False
        self._ready = False

        try:
            await self.send_command(cmd, timeout=send_timeout)
        except Exception:
            pass

        if self._process:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                if os.name == "nt":
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(self._process.pid)],
                            capture_output=True, timeout=5,
                        )
                    except Exception:
                        self._process.kill()
                else:
                    self._process.kill()

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

        for req_id, future in self._pending.items():
            if not future.done():
                future.set_exception(RuntimeError("Bridge stopped"))
        self._pending.clear()

    async def send_command(self, cmd: str, args: Optional[Dict[str, Any]] = None,
                           timeout: float = 30.0) -> Dict[str, Any]:
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
        return await self.send_command("send_message", {"to": to, "text": text})

    async def get_status(self) -> Dict[str, Any]:
        return await self.send_command("get_status")

    async def get_chats(self, limit: int = 50) -> Dict[str, Any]:
        return await self.send_command("get_chats", {"limit": limit})

    async def get_chat_messages(self, chat_id: str, limit: int = 50) -> Dict[str, Any]:
        return await self.send_command("get_chat_messages", {"chat_id": chat_id, "limit": limit})

    async def search_contact(self, name: str) -> Dict[str, Any]:
        return await self.send_command("search_contact", {"name": name})

    async def get_unread_chats(self) -> Dict[str, Any]:
        return await self.send_command("get_unread_chats")

    # ----- Messages: media / location / reply / edit / delete / forward / react / star / download -----

    async def send_media(self, to: str, file_path: str,
                         caption: Optional[str] = None,
                         send_as_sticker: bool = False,
                         send_as_voice: bool = False,
                         send_as_document: bool = False,
                         quoted_message_id: Optional[str] = None,
                         timeout: float = 120.0) -> Dict[str, Any]:
        return await self.send_command("send_media", {
            "to": to, "file_path": file_path, "caption": caption,
            "send_as_sticker": send_as_sticker,
            "send_as_voice": send_as_voice,
            "send_as_document": send_as_document,
            "quoted_message_id": quoted_message_id,
        }, timeout=timeout)

    async def send_location(self, to: str, latitude: float, longitude: float,
                            description: str = "") -> Dict[str, Any]:
        return await self.send_command("send_location", {
            "to": to, "latitude": latitude, "longitude": longitude, "description": description,
        })

    async def send_reply(self, to: str, text: str,
                         quoted_message_id: str) -> Dict[str, Any]:
        return await self.send_command("send_reply", {
            "to": to, "text": text, "quoted_message_id": quoted_message_id,
        })

    async def edit_message(self, message_id: str, new_body: str) -> Dict[str, Any]:
        return await self.send_command("edit_message", {
            "message_id": message_id, "new_body": new_body,
        })

    async def delete_message(self, message_id: str, everyone: bool = False) -> Dict[str, Any]:
        return await self.send_command("delete_message", {
            "message_id": message_id, "everyone": everyone,
        })

    async def forward_message(self, message_id: str, to: str) -> Dict[str, Any]:
        return await self.send_command("forward_message", {
            "message_id": message_id, "to": to,
        })

    async def react_message(self, message_id: str, emoji: str) -> Dict[str, Any]:
        return await self.send_command("react_message", {
            "message_id": message_id, "emoji": emoji,
        })

    async def star_message(self, message_id: str, starred: bool = True) -> Dict[str, Any]:
        return await self.send_command("star_message", {
            "message_id": message_id, "starred": starred,
        })

    async def download_message_media(self, message_id: str,
                                     timeout: float = 120.0) -> Dict[str, Any]:
        return await self.send_command("download_message_media", {
            "message_id": message_id,
        }, timeout=timeout)

    async def get_quoted_message(self, message_id: str) -> Dict[str, Any]:
        return await self.send_command("get_quoted_message", {
            "message_id": message_id,
        })

    # ----- Chat operations -----

    async def mark_chat_read(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("mark_chat_read", {"chat_id": chat_id})

    async def mark_chat_unread(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("mark_chat_unread", {"chat_id": chat_id})

    async def archive_chat(self, chat_id: str, archive: bool = True) -> Dict[str, Any]:
        return await self.send_command("archive_chat", {"chat_id": chat_id, "archive": archive})

    async def pin_chat(self, chat_id: str, pin: bool = True) -> Dict[str, Any]:
        return await self.send_command("pin_chat", {"chat_id": chat_id, "pin": pin})

    async def mute_chat(self, chat_id: str, mute: bool = True,
                        unmute_date: Optional[int] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {"chat_id": chat_id, "mute": mute}
        if unmute_date is not None:
            args["unmute_date"] = unmute_date
        return await self.send_command("mute_chat", args)

    async def clear_chat_messages(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("clear_chat_messages", {"chat_id": chat_id})

    async def delete_chat(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("delete_chat", {"chat_id": chat_id})

    async def send_typing_state(self, chat_id: str,
                                state: str = "typing") -> Dict[str, Any]:
        """state: typing | recording | clear."""
        return await self.send_command("send_typing_state", {"chat_id": chat_id, "state": state})

    # ----- Groups -----

    async def create_group(self, name: str, participants: list) -> Dict[str, Any]:
        return await self.send_command("create_group", {"name": name, "participants": participants})

    async def group_add_participants(self, group_id: str, participants: list) -> Dict[str, Any]:
        return await self.send_command("group_add_participants",
                                       {"group_id": group_id, "participants": participants})

    async def group_remove_participants(self, group_id: str, participants: list) -> Dict[str, Any]:
        return await self.send_command("group_remove_participants",
                                       {"group_id": group_id, "participants": participants})

    async def group_promote_participants(self, group_id: str, participants: list) -> Dict[str, Any]:
        return await self.send_command("group_promote_participants",
                                       {"group_id": group_id, "participants": participants})

    async def group_demote_participants(self, group_id: str, participants: list) -> Dict[str, Any]:
        return await self.send_command("group_demote_participants",
                                       {"group_id": group_id, "participants": participants})

    async def group_set_subject(self, group_id: str, subject: str) -> Dict[str, Any]:
        return await self.send_command("group_set_subject", {"group_id": group_id, "subject": subject})

    async def group_set_description(self, group_id: str, description: str) -> Dict[str, Any]:
        return await self.send_command("group_set_description",
                                       {"group_id": group_id, "description": description})

    async def group_get_info(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_get_info", {"group_id": group_id})

    async def group_leave(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_leave", {"group_id": group_id})

    async def group_invite_code(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_invite_code", {"group_id": group_id})

    async def group_revoke_invite(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_revoke_invite", {"group_id": group_id})

    async def accept_group_invite(self, invite_code: str) -> Dict[str, Any]:
        return await self.send_command("accept_group_invite", {"invite_code": invite_code})

    # ----- Contacts -----

    async def block_contact(self, contact_id: str, block: bool = True) -> Dict[str, Any]:
        return await self.send_command("block_contact",
                                       {"contact_id": contact_id, "block": block})

    async def get_profile_pic_url(self, contact_id: str) -> Dict[str, Any]:
        return await self.send_command("get_profile_pic_url", {"contact_id": contact_id})

    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        return await self.send_command("get_contact", {"contact_id": contact_id})

    async def get_all_contacts(self, my_contacts_only: bool = True,
                               limit: int = 500) -> Dict[str, Any]:
        return await self.send_command("get_all_contacts",
                                       {"my_contacts_only": my_contacts_only, "limit": limit},
                                       timeout=60.0)

    async def check_number_on_whatsapp(self, number: str) -> Dict[str, Any]:
        return await self.send_command("check_number_on_whatsapp", {"number": number})

    async def wait_for_ready(self, timeout: float = 120.0) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._ready:
                return True
            if not self.is_running:
                return False
            await asyncio.sleep(0.5)
        return False

    async def wait_for_qr_or_ready(self, timeout: float = 120.0):
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

    async def _read_stdout(self) -> None:
        try:
            while self._running and self._process and self._process.stdout:
                line = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode().strip())
                except json.JSONDecodeError:
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
                self._ready = False

    async def _read_stderr(self) -> None:
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
        except Exception:
            pass

    def _handle_event(self, event: str, data: Dict[str, Any]) -> None:
        if event == "ready":
            self._ready = True
            self._owner_phone = data.get("owner_phone", "")
            self._owner_name = data.get("owner_name", "")
            self._wid = data.get("wid", "")
        elif event == "disconnected":
            self._ready = False

        if self._event_callback:
            asyncio.ensure_future(self._event_callback(event, data))


_bridge_instance: Optional[WhatsAppBridge] = None


def get_whatsapp_bridge() -> WhatsAppBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = WhatsAppBridge()
    return _bridge_instance
