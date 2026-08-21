# -*- coding: utf-8 -*-
"""Python client for the WhatsApp Node.js bridge process.

Manages the Node.js subprocess lifecycle and provides an async API for
sending commands and receiving events via stdin/stdout JSON lines.

Multi-account model (legacy-to-v2 migration plan §5): one
``WhatsAppBridge`` — one Node subprocess driving one headless Chromium —
per connected WhatsApp account. Instances live in a module registry
keyed by the normalized account identity (see ``normalize_wa_identity``)
and each gets its own LocalAuth directory
``.credentials/whatsapp_wwebjs_auth/<identity>/`` so Chromium profile
locks, session data, and logout cleanup are account-scoped. ``bridge.js``
already takes the auth dir as argv — the Node side needs no changes.

Pending logins (QR scan in progress, identity unknown until the
``ready`` event reports the wid) run under a temporary key — the QR
session id — with a fresh ``pending-<session_id>/`` dir, then get
re-keyed to the identity via ``promote_pending_bridge``.
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


# Test hook: when set, ``WhatsAppBridge.start`` execs this argv (list)
# instead of ``node bridge.js <auth_dir>`` — lets lifecycle tests drive the
# full subprocess protocol against a controllable fake script.
_BRIDGE_EXEC_OVERRIDE: Optional[list] = None


class WhatsAppBridge:
    def __init__(self, auth_dir: str):
        """``auth_dir`` is this instance's private LocalAuth directory —
        always account-scoped (``whatsapp_wwebjs_auth/<identity>/`` or a
        ``pending-<session_id>/`` dir), never the shared root."""
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._exit_watcher: Optional[asyncio.Task] = None
        self._exit_future: Optional[asyncio.Future] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._event_callback: Optional[EventCallback] = None
        self._running = False
        self._ready = False
        self._owner_phone = ""
        self._owner_name = ""
        self._wid = ""
        self._auth_dir = auth_dir
        self._teardown_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return (
            self._running
            and self._process is not None
            and self._process.returncode is None
        )

    @property
    def is_ready(self) -> bool:
        return self._ready and self.is_running

    @property
    def owner_phone(self) -> str:
        return self._owner_phone

    @property
    def owner_name(self) -> str:
        return self._owner_name

    @property
    def wid(self) -> str:
        """Full WhatsApp id from the ready event (e.g. ``123...:12@c.us``)."""
        return self._wid

    @property
    def auth_dir(self) -> str:
        return self._auth_dir

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

        def _marker_matches(joined_cmdline: str) -> bool:
            # Boundary-checked: identity dirs are digit strings under one
            # shared root, so plain substring would let account "1"'s
            # cleanup match (and kill) account "1234"'s Chromium. The
            # marker must be followed by a path separator, quote,
            # whitespace, or end-of-string.
            start = 0
            while True:
                idx = joined_cmdline.find(auth_dir_marker, start)
                if idx == -1:
                    return False
                end = idx + len(auth_dir_marker)
                if end >= len(joined_cmdline) or joined_cmdline[end] in "\\/\" '":
                    return True
                start = idx + 1

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
                    if not _marker_matches(joined):
                        continue
                    proc.kill()
                    killed += 1
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    continue
        except ImportError:
            # No psutil — fall back to taskkill on Windows. Best-effort
            # match on the full path string in command line.
            if os.name == "nt":
                try:
                    subprocess.run(
                        [
                            "taskkill",
                            "/F",
                            "/IM",
                            "chrome.exe",
                            "/FI",
                            f"WINDOWTITLE eq *{session_dir.name}*",
                        ],
                        capture_output=True,
                        timeout=5,
                    )
                except Exception:
                    pass

        # 2. Delete singleton/lock files. Chromium creates these in the
        # user-data-dir at every launch and uses them to detect
        # already-running instances.
        lock_names = (
            "SingletonLock",
            "SingletonSocket",
            "SingletonCookie",
            "lockfile",
            "Singleton",
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

    async def start(self) -> None:
        if self.is_running:
            return

        self._clear_stale_session_locks()

        if _BRIDGE_EXEC_OVERRIDE is None:
            node_modules = BRIDGE_DIR / "node_modules"
            if not node_modules.exists():
                logger.info("[WA-Bridge] Installing npm dependencies...")
                npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
                proc = await asyncio.create_subprocess_exec(
                    npm_cmd,
                    "install",
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
        argv = _BRIDGE_EXEC_OVERRIDE or [node_cmd, str(BRIDGE_SCRIPT)]
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            self._auth_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # A download_message_media response carries the media as one
            # base64 JSON line — WhatsApp allows ~16MB media (~21MB b64),
            # far past asyncio's 64KB default readline limit. Exceeding it
            # kills the stdout reader mid-line and takes the whole bridge
            # IPC down (observed live 2026-08-17: "Separator is not found,
            # and chunk exceed the limit" right after a successful photo
            # download).
            limit=64 * 1024 * 1024,
        )

        self._running = True
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

        # Exit supervision hook: the session actor awaits ``wait_exited``
        # to catch crashes/disconnect-exits the moment they happen (D3 —
        # bridge death used to be silent and permanent until app restart).
        loop = asyncio.get_event_loop()
        self._exit_future = loop.create_future()
        proc, fut = self._process, self._exit_future

        async def _watch_exit() -> None:
            rc = await proc.wait()
            if not fut.done():
                fut.set_result(rc)

        self._exit_watcher = asyncio.create_task(_watch_exit())

    async def wait_exited(self) -> Optional[int]:
        """Block until the current Node process exits; returns its return
        code. Returns immediately (None) when no process was ever started.
        Shielded so multiple waiters can share one future and a cancelled
        waiter doesn't kill it for the others."""
        fut = self._exit_future
        if fut is None:
            return None
        return await asyncio.shield(fut)

    async def stop(self) -> None:
        await self._teardown(cmd="shutdown")

    async def abandon(self) -> None:
        # Tight-timeout teardown for the boot-time "stale auth, got a QR
        # instead of ready" path. We've already decided to throw the session
        # away, so there's nothing to flush — waiting the full shutdown
        # timeout (~20s) just delays agent startup. Mirrors logout()'s
        # rationale; see _teardown for the timeout knobs.
        await self._teardown(cmd="shutdown", send_timeout=2.0, wait_timeout=3.0)

    async def logout(self) -> None:
        """Full disconnect: server-side unlink + local LocalAuth wipe.

        The ``logout`` command makes wwebjs run ``client.logout()``, which
        removes the linked device from the user's phone (Desktop-parity:
        disconnect must not leave a ghost entry in Linked Devices).
        bridge.js acks the command immediately and then logs out + exits,
        so send returns fast; we then give the process up to 8s to finish
        the server-side flush before force-killing — ``client.logout()``
        can hang 30+s on a half-broken connection and we won't hold a
        disconnect hostage to that. Local state (no cred, no auth dir) is
        the source of truth either way.
        """
        await self._teardown(cmd="logout", send_timeout=3.0, wait_timeout=8.0)
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
        original generous timeouts for graceful agent-shutdown paths.

        Serialized: reconcile-driven stop() and teardown_account's logout()
        can race on the same bridge; the second caller must see the first
        teardown's completed state, not a half-dead process."""
        async with self._teardown_lock:
            if not self.is_running:
                return

            # Send the command while the bridge still accepts commands —
            # send_command refuses once _running is False, so flipping the
            # flag first meant no shutdown/logout EVER reached Node: wwebjs
            # never ran client.destroy()/logout(), every stop was a hard
            # kill of a live Chromium (locked profiles, phone kept showing
            # the linked device). bridge.js responds before exiting, so
            # this returns quickly on a healthy bridge.
            try:
                await self.send_command(cmd, timeout=send_timeout)
            except Exception:
                pass

            self._running = False
            self._ready = False

            if self._process:
                try:
                    await asyncio.wait_for(
                        self._process.wait(), timeout=wait_timeout
                    )
                except asyncio.TimeoutError:
                    if os.name == "nt":
                        try:
                            subprocess.run(
                                [
                                    "taskkill",
                                    "/F",
                                    "/T",
                                    "/PID",
                                    str(self._process.pid),
                                ],
                                capture_output=True,
                                timeout=5,
                            )
                        except Exception:
                            self._process.kill()
                    else:
                        self._process.kill()
                    # The kill is asynchronous — Chromium's tree holds file
                    # locks until it fully exits. Callers rmtree/move the
                    # auth dir right after us, so never return while the
                    # process may still be dying.
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=10.0)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "[WA-Bridge] process did not exit after force "
                            "kill; auth dir may still be locked"
                        )

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
            # The exit watcher resolved (or will resolve) the exit future
            # when the process died above — drop our handle so a later
            # start() arms a fresh future.
            self._exit_watcher = None

            # Copy: a concurrently-timing-out send_command pops from
            # self._pending while we iterate.
            for req_id, future in list(self._pending.items()):
                if not future.done():
                    future.set_exception(RuntimeError("Bridge stopped"))
            self._pending.clear()

    async def send_command(
        self, cmd: str, args: Optional[Dict[str, Any]] = None, timeout: float = 30.0
    ) -> Dict[str, Any]:
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

    async def ping(self, timeout: float = 10.0) -> Dict[str, Any]:
        """Cheap liveness probe (answered Node-side without touching the
        page). The session supervisor's heartbeat — two consecutive misses
        mean the process is alive but hung."""
        return await self.send_command("ping", timeout=timeout)

    async def get_chats(self, limit: int = 50) -> Dict[str, Any]:
        return await self.send_command("get_chats", {"limit": limit})

    async def get_chat_messages(self, chat_id: str, limit: int = 50) -> Dict[str, Any]:
        return await self.send_command(
            "get_chat_messages", {"chat_id": chat_id, "limit": limit}
        )

    async def search_contact(self, name: str) -> Dict[str, Any]:
        return await self.send_command("search_contact", {"name": name})

    async def get_unread_chats(self) -> Dict[str, Any]:
        return await self.send_command("get_unread_chats")

    # ----- Messages: media / location / reply / edit / delete / forward / react / star / download -----

    async def send_media(
        self,
        to: str,
        file_path: str,
        caption: Optional[str] = None,
        send_as_sticker: bool = False,
        send_as_voice: bool = False,
        send_as_document: bool = False,
        quoted_message_id: Optional[str] = None,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        return await self.send_command(
            "send_media",
            {
                "to": to,
                "file_path": file_path,
                "caption": caption,
                "send_as_sticker": send_as_sticker,
                "send_as_voice": send_as_voice,
                "send_as_document": send_as_document,
                "quoted_message_id": quoted_message_id,
            },
            timeout=timeout,
        )

    async def send_location(
        self, to: str, latitude: float, longitude: float, description: str = ""
    ) -> Dict[str, Any]:
        return await self.send_command(
            "send_location",
            {
                "to": to,
                "latitude": latitude,
                "longitude": longitude,
                "description": description,
            },
        )

    async def send_reply(
        self, to: str, text: str, quoted_message_id: str
    ) -> Dict[str, Any]:
        return await self.send_command(
            "send_reply",
            {
                "to": to,
                "text": text,
                "quoted_message_id": quoted_message_id,
            },
        )

    async def edit_message(self, message_id: str, new_body: str) -> Dict[str, Any]:
        return await self.send_command(
            "edit_message",
            {
                "message_id": message_id,
                "new_body": new_body,
            },
        )

    async def delete_message(
        self, message_id: str, everyone: bool = False
    ) -> Dict[str, Any]:
        return await self.send_command(
            "delete_message",
            {
                "message_id": message_id,
                "everyone": everyone,
            },
        )

    async def forward_message(self, message_id: str, to: str) -> Dict[str, Any]:
        return await self.send_command(
            "forward_message",
            {
                "message_id": message_id,
                "to": to,
            },
        )

    async def react_message(self, message_id: str, emoji: str) -> Dict[str, Any]:
        return await self.send_command(
            "react_message",
            {
                "message_id": message_id,
                "emoji": emoji,
            },
        )

    async def star_message(
        self, message_id: str, starred: bool = True
    ) -> Dict[str, Any]:
        return await self.send_command(
            "star_message",
            {
                "message_id": message_id,
                "starred": starred,
            },
        )

    async def download_message_media(
        self, message_id: str, timeout: float = 120.0
    ) -> Dict[str, Any]:
        return await self.send_command(
            "download_message_media",
            {
                "message_id": message_id,
            },
            timeout=timeout,
        )

    async def get_quoted_message(self, message_id: str) -> Dict[str, Any]:
        return await self.send_command(
            "get_quoted_message",
            {
                "message_id": message_id,
            },
        )

    # ----- Chat operations -----

    async def mark_chat_read(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("mark_chat_read", {"chat_id": chat_id})

    async def mark_chat_unread(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("mark_chat_unread", {"chat_id": chat_id})

    async def archive_chat(self, chat_id: str, archive: bool = True) -> Dict[str, Any]:
        return await self.send_command(
            "archive_chat", {"chat_id": chat_id, "archive": archive}
        )

    async def pin_chat(self, chat_id: str, pin: bool = True) -> Dict[str, Any]:
        return await self.send_command("pin_chat", {"chat_id": chat_id, "pin": pin})

    async def mute_chat(
        self, chat_id: str, mute: bool = True, unmute_date: Optional[int] = None
    ) -> Dict[str, Any]:
        args: Dict[str, Any] = {"chat_id": chat_id, "mute": mute}
        if unmute_date is not None:
            args["unmute_date"] = unmute_date
        return await self.send_command("mute_chat", args)

    async def clear_chat_messages(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("clear_chat_messages", {"chat_id": chat_id})

    async def delete_chat(self, chat_id: str) -> Dict[str, Any]:
        return await self.send_command("delete_chat", {"chat_id": chat_id})

    async def send_typing_state(
        self, chat_id: str, state: str = "typing"
    ) -> Dict[str, Any]:
        """state: typing | recording | clear."""
        return await self.send_command(
            "send_typing_state", {"chat_id": chat_id, "state": state}
        )

    # ----- Groups -----

    async def create_group(self, name: str, participants: list) -> Dict[str, Any]:
        return await self.send_command(
            "create_group", {"name": name, "participants": participants}
        )

    async def group_add_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        return await self.send_command(
            "group_add_participants",
            {"group_id": group_id, "participants": participants},
        )

    async def group_remove_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        return await self.send_command(
            "group_remove_participants",
            {"group_id": group_id, "participants": participants},
        )

    async def group_promote_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        return await self.send_command(
            "group_promote_participants",
            {"group_id": group_id, "participants": participants},
        )

    async def group_demote_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        return await self.send_command(
            "group_demote_participants",
            {"group_id": group_id, "participants": participants},
        )

    async def group_set_subject(self, group_id: str, subject: str) -> Dict[str, Any]:
        return await self.send_command(
            "group_set_subject", {"group_id": group_id, "subject": subject}
        )

    async def group_set_description(
        self, group_id: str, description: str
    ) -> Dict[str, Any]:
        return await self.send_command(
            "group_set_description", {"group_id": group_id, "description": description}
        )

    async def group_get_info(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_get_info", {"group_id": group_id})

    async def group_leave(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_leave", {"group_id": group_id})

    async def group_invite_code(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_invite_code", {"group_id": group_id})

    async def group_revoke_invite(self, group_id: str) -> Dict[str, Any]:
        return await self.send_command("group_revoke_invite", {"group_id": group_id})

    async def accept_group_invite(self, invite_code: str) -> Dict[str, Any]:
        return await self.send_command(
            "accept_group_invite", {"invite_code": invite_code}
        )

    # ----- Contacts -----

    async def block_contact(
        self, contact_id: str, block: bool = True
    ) -> Dict[str, Any]:
        return await self.send_command(
            "block_contact", {"contact_id": contact_id, "block": block}
        )

    async def get_profile_pic_url(self, contact_id: str) -> Dict[str, Any]:
        return await self.send_command(
            "get_profile_pic_url", {"contact_id": contact_id}
        )

    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        return await self.send_command("get_contact", {"contact_id": contact_id})

    async def get_all_contacts(
        self, my_contacts_only: bool = True, limit: int = 500
    ) -> Dict[str, Any]:
        return await self.send_command(
            "get_all_contacts",
            {"my_contacts_only": my_contacts_only, "limit": limit},
            timeout=60.0,
        )

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
            if result["type"] is None:
                if event in ("qr", "ready"):
                    result["type"] = event
                    result["data"] = data
                    event_received.set()
                elif event == "auth_failure" or (
                    event == "error" and (data or {}).get("fatal")
                ):
                    # The bridge already diagnosed its own failure — surface
                    # it instead of burning the full timeout.
                    result["type"] = "error"
                    result["data"] = data
                    event_received.set()
            if original_callback:
                await original_callback(event, data)

        async def watch_exit():
            proc = self._process
            if proc is None:
                return
            await proc.wait()
            if result["type"] is None:
                result["type"] = "error"
                result["data"] = {
                    "message": (
                        f"WhatsApp bridge exited (code {proc.returncode}) "
                        "before producing a QR code — check the "
                        "[WA-Bridge:node] lines in the logs."
                    )
                }
                event_received.set()

        self._event_callback = intercept_callback
        exit_task = asyncio.create_task(watch_exit())
        try:
            await asyncio.wait_for(event_received.wait(), timeout=timeout)
            return result["type"], result["data"]
        except asyncio.TimeoutError:
            return "timeout", None
        finally:
            exit_task.cancel()
            self._event_callback = original_callback

    async def _read_stdout(self) -> None:
        try:
            while self._running and self._process and self._process.stdout:
                try:
                    line = await self._process.stdout.readline()
                except (asyncio.LimitOverrunError, ValueError) as e:
                    # A single line exceeded the stream limit (huge media
                    # response). Drain the oversized line in chunks rather
                    # than letting the reader die and take the bridge IPC
                    # down with it; the response is lost but the pipe
                    # survives.
                    logger.error(
                        f"[WA-Bridge] Oversized stdout line dropped: {e}"
                    )
                    try:
                        while True:
                            chunk = await self._process.stdout.read(1024 * 1024)
                            if not chunk or chunk.endswith(b"\n"):
                                break
                    except Exception:
                        pass
                    continue
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


# ════════════════════════════════════════════════════════════════════════
# Identity normalization — THE one rule, used by the provider, the QR
# flow, and the registry alike
# ════════════════════════════════════════════════════════════════════════


def normalize_wa_identity(value: Any) -> Optional[str]:
    """Normalize a WhatsApp phone/wid to the canonical account identity.

    ``14155552671:12@c.us`` (wid with device suffix), ``14155552671@c.us``,
    ``+1 (415) 555-2671`` and ``14155552671`` all collapse to
    ``14155552671``: strip the ``@c.us`` domain, strip the ``:NN`` device
    suffix, keep digits only, strip leading zeros (the ``00``
    international-prefix ambiguity — same rationale as telegram_user).
    Returns None for anything that yields no digits. Already lowercase by
    construction (digits), satisfying the conformance identity rules.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = text.split("@", 1)[0]  # wid domain: 14155552671@c.us
    text = text.split(":", 1)[0]  # device suffix: 14155552671:12
    digits = "".join(ch for ch in text if ch.isdigit()).lstrip("0")
    return digits or None


# ════════════════════════════════════════════════════════════════════════
# Per-account bridge registry
# ════════════════════════════════════════════════════════════════════════

_PENDING_DIR_PREFIX = "pending-"
# Marker file inside a pending-* dir that was ADOPTED as a live account
# (contains the identity). Adoption keeps the freshly-linked browser
# running instead of restarting it from a half-written profile — the dir
# is renamed to the conventional <identity>/ later, at a clean stop or the
# next boot, when no Chromium holds it (Windows can't rename under a live
# browser; killing the browser to rename was exactly the old
# torn-LocalAuth bug).
_ADOPTED_MARKER = ".adopted"

_bridges: Dict[str, WhatsAppBridge] = {}
_pending_keys: set = set()  # session ids currently registered as pending
_layout_migrated = False


class BridgeCapacityError(RuntimeError):
    """Raised when starting another bridge would exceed ``max_accounts``."""


def _auth_root() -> Path:
    return Path(ConfigStore.project_root) / ".credentials" / "whatsapp_wwebjs_auth"


def _identity_auth_dir(identity: str) -> Path:
    """The CONVENTIONAL dir for an identity. Prefer
    ``_resolve_identity_dir`` for reads — a freshly-adopted account lives
    in its pending-* dir until the deferred rename."""
    return _auth_root() / identity


def _pending_auth_dir(session_id: str) -> Path:
    return _auth_root() / f"{_PENDING_DIR_PREFIX}{session_id}"


def _adopted_dirs_for(identity: str) -> list:
    """Every pending-* dir whose adoption marker names ``identity``
    (normally 0 or 1; >1 only after an interrupted re-link)."""
    root = _auth_root()
    out = []
    try:
        if not root.exists():
            return out
        for child in root.iterdir():
            if not child.is_dir() or not child.name.startswith(_PENDING_DIR_PREFIX):
                continue
            marker = child / _ADOPTED_MARKER
            try:
                if marker.exists() and marker.read_text(encoding="utf-8").strip() == identity:
                    out.append(child)
            except OSError:
                continue
    except OSError:
        pass
    return out


def _resolve_identity_dir(identity: str) -> Path:
    """Where ``identity``'s LocalAuth actually lives right now: the
    conventional dir when present, else an adopted pending dir awaiting
    its deferred rename, else the conventional path (for creation)."""
    conventional = _identity_auth_dir(identity)
    if conventional.exists():
        return conventional
    adopted = _adopted_dirs_for(identity)
    if adopted:
        return adopted[0]
    return conventional


def _legacy_owner_identity() -> Optional[str]:
    """Normalized identity from the legacy single-account
    ``whatsapp_web.json``, or None if it doesn't exist / has no phone."""
    try:
        from ...credentials_store import load_credential
        from . import WHATSAPP_WEB, WhatsAppWebCredential

        cred = load_credential(WHATSAPP_WEB.cred_file, WhatsAppWebCredential)
    except Exception:
        return None
    if cred is None:
        return None
    return normalize_wa_identity(cred.owner_phone)


def max_whatsapp_accounts() -> int:
    """The ``max_accounts`` knob from whatsapp_web_config.json (default 2).

    A RAM guard, not a hard platform limit: every connected account runs
    its own headless Chromium (~300–500 MB)."""
    try:
        from ...credentials_store import load_config
        from . import WhatsAppWebConfig, _whatsapp_web_config_file

        cfg = (
            load_config(_whatsapp_web_config_file(), WhatsAppWebConfig)
            or WhatsAppWebConfig()
        )
        value = int(getattr(cfg, "max_accounts", 2))
    except Exception:
        return 2
    return max(1, value)


def _account_slots_used() -> int:
    """Connected-account count for cap enforcement: identity auth dirs on
    disk (robust across restarts — a connected account always has one)
    unioned with registered non-pending bridges, plus pending logins."""
    identities = {key for key in _bridges if key not in _pending_keys}
    root = _auth_root()
    try:
        if root.exists():
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if child.name.isdigit():
                    identities.add(child.name)
                elif child.name.startswith(_PENDING_DIR_PREFIX):
                    # An adopted pending dir IS a connected account (its
                    # rename is merely deferred) — count it by identity so
                    # it can never double-count with the registry key.
                    marker = child / _ADOPTED_MARKER
                    try:
                        if marker.exists():
                            adopted_identity = marker.read_text(
                                encoding="utf-8"
                            ).strip()
                            if adopted_identity:
                                identities.add(adopted_identity)
                    except OSError:
                        continue
    except OSError:
        pass
    return len(identities) + len(_pending_keys)


def _ensure_layout_migrated() -> None:
    """One-time move of the OLD single-account layout
    (``whatsapp_wwebjs_auth/session/`` directly under the root) into the
    per-identity layout (``whatsapp_wwebjs_auth/<identity>/session/``),
    using the identity from the legacy whatsapp_web.json. If no legacy
    credential exists we can't name the account — leave the old layout in
    place and log (a fresh QR login will simply use a new identity dir).
    """
    global _layout_migrated
    if _layout_migrated:
        return
    _layout_migrated = True

    # Boot is the one moment no bridge is running — finish any deferred
    # adopted-dir renames first.
    _migrate_adopted_dirs()

    root = _auth_root()
    old_session = root / "session"
    if not old_session.exists():
        return

    identity = _legacy_owner_identity()
    if not identity:
        logger.info(
            f"[WA-Bridge] old single-account auth layout found at {root} but "
            "no legacy whatsapp_web.json to derive an identity from — "
            "leaving it in place"
        )
        return

    target = _identity_auth_dir(identity)
    if target.exists():
        logger.warning(
            f"[WA-Bridge] both the old auth layout and {target} exist — "
            "keeping the identity dir, leaving the old layout untouched"
        )
        return

    import shutil

    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for child in list(root.iterdir()):
        name = child.name
        # Only old-layout content: never touch identity dirs (all-digit
        # names), pending dirs, or the target itself.
        if child == target or name.isdigit() or name.startswith(_PENDING_DIR_PREFIX):
            continue
        try:
            shutil.move(str(child), str(target / name))
            moved += 1
        except OSError as e:
            logger.warning(f"[WA-Bridge] migration could not move {child}: {e}")
    logger.info(
        f"[WA-Bridge] migrated old single-account auth layout into {target} "
        f"({moved} entrie(s)) for identity {identity}"
    )


def get_whatsapp_bridge(identity: Optional[str] = None) -> WhatsAppBridge:
    """The per-account bridge for ``identity`` (any phone/wid spelling —
    normalized here), creating it (stopped) on first use.

    ``identity=None`` is tolerated for one release for stragglers of the
    legacy single-account path: the identity is resolved from a surviving
    whatsapp_web.json. With no such file the call fails loudly — the
    ``default`` slot semantics are gone (legacy removal, session-durability
    plan §2.8); every v2 caller passes an identity.
    """
    _ensure_layout_migrated()
    if identity is None:
        resolved = _legacy_owner_identity()
        if resolved is None:
            raise RuntimeError(
                "whatsapp_web bridge requested without an account identity "
                "and no legacy credential exists — connect an account via "
                "the Settings → Integrations QR flow first"
            )
        key = resolved
    else:
        normalized = normalize_wa_identity(identity)
        if normalized is None:
            raise ValueError(f"invalid whatsapp identity: {identity!r}")
        key = normalized

    bridge = _bridges.get(key)
    if bridge is None:
        bridge = WhatsAppBridge(auth_dir=str(_resolve_identity_dir(key)))
        _bridges[key] = bridge
    return bridge


def peek_whatsapp_bridge(identity: str) -> Optional[WhatsAppBridge]:
    """Registry lookup without creating: the bridge for ``identity`` if one
    has been created this process, else None."""
    normalized = normalize_wa_identity(identity)
    if normalized is None:
        return None
    return _bridges.get(normalized)


def drop_whatsapp_bridge(identity: str) -> Optional[WhatsAppBridge]:
    """Remove ``identity``'s bridge from the registry WITHOUT stopping it —
    the caller owns shutdown. Returns the removed bridge (or None). For
    full account removal (stop + server logout + auth-dir delete) use
    ``teardown_account`` instead."""
    normalized = normalize_wa_identity(identity)
    if normalized is None:
        return None
    return _bridges.pop(normalized, None)


def create_pending_bridge(session_id: str) -> WhatsAppBridge:
    """A fresh bridge for a QR login in progress, registered under the QR
    ``session_id`` with its own ``pending-<session_id>/`` auth dir (so
    concurrent QR sessions never share Chromium state). Raises
    ``BridgeCapacityError`` when the ``max_accounts`` cap is reached."""
    _ensure_layout_migrated()
    existing = _bridges.get(session_id)
    if existing is not None:
        return existing
    limit = max_whatsapp_accounts()
    used = _account_slots_used()
    if used >= limit:
        raise BridgeCapacityError(
            f"WhatsApp account limit reached ({used}/{limit}). Every connected "
            "account runs its own headless Chromium browser (~300-500 MB RAM). "
            "Disconnect an account first, or raise 'max_accounts' in the "
            "WhatsApp integration settings if this machine has RAM to spare."
        )
    bridge = WhatsAppBridge(auth_dir=str(_pending_auth_dir(session_id)))
    _bridges[session_id] = bridge
    _pending_keys.add(session_id)
    return bridge


async def discard_pending_bridge(session_id: str) -> None:
    """Cancel/cleanup a pending QR login: stop its bridge (tight-timeout
    abandon — the session is being thrown away) and delete its temp dir."""
    _pending_keys.discard(session_id)
    bridge = _bridges.pop(session_id, None)
    if bridge is not None and bridge.is_running:
        try:
            await bridge.abandon()
        except Exception as e:
            logger.warning(f"[WA-Bridge] pending-bridge abandon failed: {e}")
    await _rmtree_with_retry(_pending_auth_dir(session_id))


async def promote_pending_bridge(session_id: str, identity: str) -> WhatsAppBridge:
    """Re-key a connected pending-login bridge to its account identity.

    The pending Node/Chromium is STOPPED first — Windows cannot rename a
    profile dir under a live browser — then the fresh auth dir is moved to
    ``<identity>/`` and a stopped bridge is registered under the identity.
    The next ``start()`` (host listener wiring) restores the session from
    LocalAuth without a new QR scan.

    Re-login of an already-connected account: the FRESH session wins — the
    old bridge is stopped/dropped and its auth dir replaced. (The fresh
    scan is the one the user just performed; the old LocalAuth may be the
    very stale state that forced the re-login.)
    """
    normalized = normalize_wa_identity(identity)
    if normalized is None:
        raise ValueError(f"invalid whatsapp identity: {identity!r}")

    _pending_keys.discard(session_id)
    pending = _bridges.pop(session_id, None)
    if pending is None:
        raise KeyError(f"no pending whatsapp bridge for session {session_id}")
    if pending.is_running:
        try:
            await pending.stop()
        except Exception as e:
            logger.warning(f"[WA-Bridge] pending-bridge stop before promote: {e}")

    previous = _bridges.pop(normalized, None)
    if previous is not None and previous.is_running:
        try:
            await previous.stop()
        except Exception as e:
            logger.warning(f"[WA-Bridge] old bridge stop during re-login: {e}")

    target = _identity_auth_dir(normalized)
    if target.exists():
        await _rmtree_with_retry(target)

    src = _pending_auth_dir(session_id)
    if src.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        await _move_with_retry(src, target)

    bridge = WhatsAppBridge(auth_dir=str(target))
    _bridges[normalized] = bridge
    return bridge


async def adopt_pending_bridge(session_id: str, identity: str) -> WhatsAppBridge:
    """Adopt a freshly-linked pending bridge as ``identity``'s live bridge —
    WITHOUT stopping it.

    The old promote path killed the pending browser milliseconds after
    ``ready`` so the dir could be renamed; the companion-registration
    handshake wasn't finished, so the moved LocalAuth was torn and the
    restore hung forever (observed live 2026-08-21, account 923334055616).
    Adoption keeps the healthy browser as the session (Desktop parity —
    Desktop never restarts your session right after a scan); the dir keeps
    its ``pending-*`` name with an adoption marker and is renamed later by
    ``_migrate_adopted_dirs`` at a clean stop or the next boot.

    Any previous bridge/dirs for the identity are stopped and deleted —
    the fresh scan the user just performed always wins (its predecessor
    may be the very stale/torn state that forced the re-link).
    """
    normalized = normalize_wa_identity(identity)
    if normalized is None:
        raise ValueError(f"invalid whatsapp identity: {identity!r}")

    _pending_keys.discard(session_id)
    pending = _bridges.pop(session_id, None)
    if pending is None:
        raise KeyError(f"no pending whatsapp bridge for session {session_id}")

    previous = _bridges.pop(normalized, None)
    if previous is not None and previous is not pending and previous.is_running:
        try:
            await previous.stop()
        except Exception as e:
            logger.warning(f"[WA-Bridge] old bridge stop during re-link: {e}")

    # Old on-disk state (conventional dir and/or stale adopted dirs from an
    # interrupted earlier re-link) is superseded by the fresh session.
    old_conventional = _identity_auth_dir(normalized)
    if old_conventional.exists():
        await _rmtree_with_retry(old_conventional)
    for stale in _adopted_dirs_for(normalized):
        if Path(pending.auth_dir).resolve() != stale.resolve():
            await _rmtree_with_retry(stale)

    try:
        marker = Path(pending.auth_dir) / _ADOPTED_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(normalized, encoding="utf-8")
    except OSError as e:
        logger.warning(f"[WA-Bridge] could not write adoption marker: {e}")

    _bridges[normalized] = pending
    logger.info(
        f"[WA-Bridge] adopted live pending bridge as account {normalized} "
        f"(dir rename deferred: {Path(pending.auth_dir).name})"
    )
    return pending


def _migrate_adopted_dirs() -> None:
    """Deferred rename: adopted ``pending-*`` dirs → ``<identity>/``, done
    only when no live browser holds the dir (boot, or after a clean stop).
    Safe to call any time; skips anything in use."""
    root = _auth_root()
    try:
        if not root.exists():
            return
        children = list(root.iterdir())
    except OSError:
        return
    import shutil

    for child in children:
        if not child.is_dir() or not child.name.startswith(_PENDING_DIR_PREFIX):
            continue
        marker = child / _ADOPTED_MARKER
        try:
            if not marker.exists():
                continue
            identity = marker.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not identity:
            continue
        bridge = _bridges.get(identity)
        holds_dir = bridge is not None and Path(bridge.auth_dir) == child
        if holds_dir and bridge.is_running:
            continue  # live Chromium owns it — next clean stop gets it
        target = _identity_auth_dir(identity)
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if target.exists():
                continue  # locked stale dir — retry at the next opportunity
            shutil.move(str(child), str(target))
            (target / _ADOPTED_MARKER).unlink(missing_ok=True)
            if holds_dir:
                bridge._auth_dir = str(target)
                if bridge.auth_dir != str(target):
                    # Test doubles expose auth_dir as a plain attribute.
                    try:
                        bridge.auth_dir = str(target)
                    except AttributeError:
                        pass
            logger.info(
                f"[WA-Bridge] finished adopted-dir rename: {child.name} → {identity}"
            )
        except OSError as e:
            logger.warning(
                f"[WA-Bridge] adopted-dir rename for {identity} failed "
                f"(will retry at next stop/boot): {e}"
            )


async def teardown_account(identity: str) -> None:
    """Host hook for account removal: routed through the per-identity
    session actor so it can never race the actor's own supervision or a
    concurrent reconcile stop (D9 — two unserialized teardowns of one
    bridge). Server-side logout first, then process exit, then auth-dir
    delete. Safe for an identity with no live bridge; idempotent."""
    from ._session import get_session_manager

    await get_session_manager().teardown(identity)


async def _teardown_account_impl(normalized: str) -> None:
    """The raw teardown primitive — only the session manager calls this
    (inside the identity's actor lock)."""
    _ensure_layout_migrated()
    bridge = _bridges.pop(normalized, None)
    if bridge is not None:
        try:
            # logout() invalidates server-side and rmtree's its own dir;
            # on a non-running bridge it degrades to just the dir wipe.
            await bridge.logout()
        except Exception as e:
            logger.warning(f"[WA-Bridge] teardown logout for {normalized}: {e}")
    await _rmtree_with_retry(_identity_auth_dir(normalized))
    # A not-yet-renamed adopted dir is this account's LocalAuth too.
    for adopted in _adopted_dirs_for(normalized):
        await _rmtree_with_retry(adopted)


async def _rmtree_with_retry(path: Path, attempts: int = 5) -> None:
    """Windows: Chromium file locks linger briefly after process exit."""
    import shutil

    for i in range(attempts):
        if not path.exists():
            return
        shutil.rmtree(path, ignore_errors=(i == attempts - 1))
        if not path.exists():
            return
        await asyncio.sleep(0.4)


async def _move_with_retry(src: Path, dst: Path, attempts: int = 5) -> None:
    import shutil

    last_error: Optional[Exception] = None
    for _ in range(attempts):
        try:
            shutil.move(str(src), str(dst))
            return
        except OSError as e:
            last_error = e
            await asyncio.sleep(0.4)
    raise RuntimeError(f"could not move {src} to {dst}: {last_error}")


def _reset_bridge_registry_for_tests() -> None:
    """Test hook: forget all bridges and re-arm the layout migration."""
    global _layout_migrated
    _bridges.clear()
    _pending_keys.clear()
    _layout_migrated = False
    try:
        from ._session import _reset_session_manager_for_tests

        _reset_session_manager_for_tests()
    except Exception:
        pass
