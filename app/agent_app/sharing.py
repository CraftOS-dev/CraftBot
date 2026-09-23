"""Sharing a running Agent App beyond this machine.

Apps only ever bind loopback. Sharing one means opening a CHANNEL: a
transport that relays visitors to 127.0.0.1:<port>, plus a GRANT the app's
guards read (a2app_proxy.guard_request, _a2app_lib.js authorizeCaller):

  lan     private — an in-process relay on this machine's LAN address.
          Reachable by devices on the same network, only while switched on.
  tunnel  public  — a cloudflared quick tunnel (https://*.trycloudflare.com).

Both are shared the same way: by LINK. A grant is two files in the project
dir, `.<name>-origin` (the origin browsers use through the channel) and
`.<name>-secret` (what `?a2app_share=` trades for a session). Every relay
stamps what it forwards, so the guards treat all of it as remote: no
credential, no access, reads included. Closing a channel deletes its grant,
which ends every session opened through it at once.

The grant files are also the channel's state of record: `link()` is derived
from them, so there is nothing to keep in sync on the project object.
"""

import asyncio
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from app.agent_app.a2app_proxy import HOP_HEADERS, SHARE_CHANNELS, SHARE_PARAM

# Host-local, channel-lifetime state: never exported, never trusted on import.
SHARE_STATE_FILES = tuple(
    f".{name}-{kind}" for name in SHARE_CHANNELS for kind in ("origin", "secret")
)


class ShareError(RuntimeError):
    """A channel could not be opened; the message is for the owner."""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


class ShareGrant:
    """One channel's grant files — the only thing the app's guards see."""

    def __init__(self, name: str):
        self.name = name

    def _origin_file(self, project_dir: Path) -> Path:
        return Path(project_dir) / f".{self.name}-origin"

    def _secret_file(self, project_dir: Path) -> Path:
        return Path(project_dir) / f".{self.name}-secret"

    def origin(self, project_dir: Path) -> str:
        return _read(self._origin_file(project_dir))

    def publish(self, project_dir: Path, origin: str) -> None:
        """Trust `origin` and mint the link secret. An existing secret is
        kept, so re-publishing the same channel keeps links already sent."""
        self._origin_file(project_dir).write_text(
            origin.rstrip("/") + "\n", encoding="utf-8"
        )
        secret_file = self._secret_file(project_dir)
        if not _read(secret_file):
            secret_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            try:
                os.chmod(secret_file, 0o600)
            except Exception:
                pass

    def revoke(self, project_dir: Path) -> None:
        """Idempotent: closing runs often."""
        for path in (self._origin_file(project_dir), self._secret_file(project_dir)):
            try:
                path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"[AGENT_APP:SHARE] Could not remove {path.name}: {e}")

    def link(self, project_dir: Path) -> Optional[str]:
        """The link to hand out: origin + secret. The bare origin admits nobody."""
        origin = self.origin(project_dir)
        secret = _read(self._secret_file(project_dir))
        if not (origin and secret):
            return None
        return f"{origin}/?{SHARE_PARAM}={secret}"


class ShareChannel(ABC):
    """A transport + its grant. Subclasses supply only the transport."""

    name: str

    def __init__(self) -> None:
        self.grant = ShareGrant(self.name)

    async def open(self, project: Any, port: int) -> str:
        """Open (or re-open) the channel and return its share link."""
        project_dir = Path(project.path)
        # No agent token = no credential the guards can check. They fail
        # closed remotely anyway, but refuse here so the owner is told why
        # instead of handed a link that only ever answers 503. Checked before
        # touching anything, so a refused open leaves an existing share as is.
        if not _read(project_dir / ".agent-token"):
            raise ShareError(
                "This app has no access token, so it can't be shared safely. "
                "Restart the app and try again."
            )
        await self.close(project)
        origin = await self._connect(project, port)
        self.grant.publish(project_dir, origin)
        logger.info(f"[AGENT_APP:SHARE] {self.name} open for {project.name}: {origin}")
        return self.grant.link(project_dir)  # type: ignore[return-value]

    async def close(self, project: Any) -> None:
        await self._disconnect(project)
        self.grant.revoke(Path(project.path))

    def link(self, project: Any) -> Optional[str]:
        return self.grant.link(Path(project.path))

    def restore(self, project: Any) -> None:
        """At CraftBot start: most transports did not survive the restart,
        so a leftover grant is revoked. Override when one can."""
        self.grant.revoke(Path(project.path))

    @abstractmethod
    async def _connect(self, project: Any, port: int) -> str:
        """Bring the transport up for 127.0.0.1:`port`; return the origin
        visitors will use. Raise ShareError with an owner-facing reason."""

    @abstractmethod
    async def _disconnect(self, project: Any) -> None:
        """Tear the transport down. Must be a no-op when it is not up."""


# ── private: the LAN relay ─────────────────────────────────────────────────


class LanRelay:
    """HTTP + WebSocket relay from <lan-ip>:<port> to 127.0.0.1:<upstream>.

    HTTP-aware on purpose: it stamps X-Forwarded-For on everything it
    forwards, overwriting whatever the visitor sent, so the app's guard sees
    every LAN request as remote. A raw TCP relay could not, and a LAN caller
    sending `Host: 127.0.0.1` would pass for local.

    Runs in its own thread and event loop (a SelectorEventLoop, as the
    external-app proxy does on Windows), so relaying never competes with
    CraftBot's own loop.
    """

    def __init__(self, host: str, port: int, upstream_port: int):
        self.host = host
        self.port = port
        self.upstream = f"http://127.0.0.1:{upstream_port}"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._runner = None
        self._session = None

    async def start(self) -> int:
        """Listen, preferring the app's own port; returns the bound port."""
        self._loop = asyncio.SelectorEventLoop()
        ready = threading.Event()
        result: list = [None]

        def _run() -> None:
            asyncio.set_event_loop(self._loop)
            try:
                result[0] = self._loop.run_until_complete(self._setup())
            except Exception as e:
                result[0] = e
            ready.set()
            if not isinstance(result[0], Exception):
                self._loop.run_forever()

        threading.Thread(target=_run, daemon=True, name=f"lan-relay-{self.port}").start()
        await asyncio.get_running_loop().run_in_executor(None, ready.wait, 10)
        if not isinstance(result[0], int):
            self._loop = None
            raise ShareError(f"Could not listen on {self.host}: {result[0]}")
        return result[0]

    async def _setup(self) -> int:
        import aiohttp
        from aiohttp import web

        self._session = aiohttp.ClientSession(
            auto_decompress=False,
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
        )
        app = web.Application(client_max_size=1024**3)
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        # The app's own port when free on this address (a stable URL);
        # otherwise any port — the link carries it either way.
        for port in (self.port, 0):
            site = web.TCPSite(self._runner, self.host, port)
            try:
                await site.start()
            except OSError:
                if port == 0:
                    raise
                continue
            return site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        raise OSError("unreachable")

    async def stop(self) -> None:
        loop, self._loop = self._loop, None
        if loop is None:
            return

        async def _cleanup() -> None:
            if self._runner is not None:
                await self._runner.cleanup()
            if self._session is not None:
                await self._session.close()

        try:
            fut = asyncio.run_coroutine_threadsafe(_cleanup(), loop)
            await asyncio.wrap_future(fut)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)

    def _forward_headers(self, request, drop=()) -> Dict[str, str]:
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in HOP_HEADERS and k.lower() not in drop
        }
        # The remote marker (see a2app_proxy.REMOTE_MARKER_HEADERS): set, never
        # appended — nothing the visitor sends survives.
        headers["X-Forwarded-For"] = request.remote or "unknown"
        headers["X-Forwarded-Proto"] = "http"
        headers["X-Forwarded-Host"] = request.host
        return headers

    async def _handle(self, request):
        from aiohttp import web

        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._relay_ws(request)
        try:
            async with self._session.request(
                request.method,
                self.upstream + str(request.rel_url),
                headers=self._forward_headers(request),
                data=request.content if request.body_exists else None,
                allow_redirects=False,
            ) as up:
                resp = web.StreamResponse(status=up.status)
                for k, v in up.headers.items():
                    if k.lower() not in HOP_HEADERS:
                        resp.headers.add(k, v)  # add: several Set-Cookie
                await resp.prepare(request)
                async for chunk in up.content.iter_chunked(64 * 1024):
                    await resp.write(chunk)
                await resp.write_eof()
                return resp
        except (ConnectionResetError, ConnectionAbortedError):
            raise
        except Exception:
            return web.Response(status=502, text="The app is not running.")

    async def _relay_ws(self, request):
        import aiohttp
        from aiohttp import web

        protocols = tuple(
            p.strip()
            for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
            if p.strip()
        )
        headers = self._forward_headers(
            request,
            drop=(
                "sec-websocket-key",
                "sec-websocket-version",
                "sec-websocket-extensions",
                "sec-websocket-protocol",
            ),
        )
        # Connect upstream FIRST: if the app's guard refuses the handshake,
        # the visitor gets that refusal, not an open socket that goes nowhere.
        try:
            client_ws = await self._session.ws_connect(
                self.upstream + str(request.rel_url),
                headers=headers,
                protocols=protocols,
            )
        except aiohttp.WSServerHandshakeError as e:
            return web.Response(status=e.status or 502)
        except Exception:
            return web.Response(status=502, text="The app is not running.")
        server_ws = web.WebSocketResponse(protocols=protocols)
        await server_ws.prepare(request)

        async def pump(src, dst):
            async for msg in src:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await dst.send_str(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await dst.send_bytes(msg.data)
                else:
                    break

        try:
            await asyncio.wait(
                [
                    asyncio.ensure_future(pump(server_ws, client_ws)),
                    asyncio.ensure_future(pump(client_ws, server_ws)),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            await client_ws.close()
            await server_ws.close()
        return server_ws


class LanChannel(ShareChannel):
    """Private link: devices on the same network, via LanRelay."""

    name = "lan"

    def __init__(self) -> None:
        super().__init__()
        self._relays: Dict[str, LanRelay] = {}

    @staticmethod
    def lan_ip() -> Optional[str]:
        """This machine's address on the network its default route uses."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 80))  # no packet is sent; picks the interface
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            try:
                ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                return None
        return None if ip.startswith("127.") else ip

    async def _connect(self, project: Any, port: int) -> str:
        ip = self.lan_ip()
        if not ip:
            raise ShareError("This computer isn't connected to a local network.")
        relay = LanRelay(ip, port, port)
        bound = await relay.start()
        self._relays[project.id] = relay
        return f"http://{ip}:{bound}"

    async def _disconnect(self, project: Any) -> None:
        relay = self._relays.pop(project.id, None)
        if relay is not None:
            await relay.stop()


# ── public: the cloudflared tunnel ─────────────────────────────────────────


class TunnelChannel(ShareChannel):
    """Public link: a cloudflared quick tunnel, one process per project."""

    name = "tunnel"

    _CLOUDFLARED_URLS = {
        "win32": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        "darwin": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        "linux": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    }
    _BIN_DIR = Path(__file__).parent.parent / "bin"

    def __init__(self, terminate: Callable[[subprocess.Popen], None]):
        super().__init__()
        self._terminate = terminate
        # project id -> (cloudflared process, its open log file)
        self._running: Dict[str, Tuple[subprocess.Popen, Any]] = {}

    # ── transport ──

    async def _connect(self, project: Any, port: int) -> str:
        if not self._running:
            await self._kill_orphans()

        cloudflared = await self._ensure_cloudflared()
        if not cloudflared:
            raise ShareError("Couldn't install cloudflared, which public links need.")

        # cloudflared writes to stderr for the WHOLE life of the tunnel, not
        # just at startup. Piping that into this process and then not draining
        # it — which is what "find the URL, return from the reader thread"
        # did — fills the OS pipe buffer (4 KB by default on Windows) and
        # cloudflared then BLOCKS forever on its next write. The tunnel stops
        # proxying while the process still looks perfectly alive, so remote
        # visitors hang until their client times out, and every byte that would
        # explain why is stuck unread in that buffer. A file sink has no such
        # backpressure, and doubles as the log this had no way to produce.
        log_handle, log_path, log_offset = self._open_log(project, port)
        if log_handle is None:
            raise ShareError("No writable location for the cloudflared log.")

        # 127.0.0.1, NOT localhost: PocketBase binds --http=127.0.0.1:<port>
        # (runner.start) and the external-app proxy binds the same, so neither
        # ever listens on ::1. cloudflared resolves 'localhost' to ::1 first on
        # Windows and got "connectex: No connection could be made" on every
        # single request — the tunnel came up healthy, announced its URL, and
        # then refused every visitor.
        origin_url = f"http://127.0.0.1:{port}"
        logger.info(
            f"[AGENT_APP:SHARE] Starting cloudflared: {cloudflared} tunnel "
            f"--url {origin_url} (log: {log_path})"
        )
        proc = subprocess.Popen(
            [cloudflared, "tunnel", "--url", origin_url],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        url = await self._parse_url(proc, log_path, log_offset)
        if not url:
            self._terminate(proc)
            self._close_log(log_handle)
            raise ShareError(
                f"cloudflared didn't come up; its own output is in {log_path}"
            )
        self._running[project.id] = (proc, log_handle)
        return url

    async def _disconnect(self, project: Any) -> None:
        proc, log_handle = self._running.pop(project.id, (None, None))
        if proc is not None:
            self._terminate(proc)
        self._close_log(log_handle)

    def restore(self, project: Any) -> None:
        """cloudflared outlives CraftBot: keep a grant whose tunnel still
        answers (401 is the app refusing a visitor with no session — the
        tunnel is up), revoke one that does not."""
        origin = self.grant.origin(Path(project.path))
        if not origin:
            return
        import urllib.error
        import urllib.request

        try:
            try:
                urllib.request.urlopen(
                    urllib.request.Request(origin, method="HEAD"), timeout=3
                )
            except urllib.error.HTTPError as he:
                if he.code != 401:
                    raise
            logger.info(f"[AGENT_APP:SHARE] Tunnel still active for {project.name}")
        except Exception:
            logger.info(f"[AGENT_APP:SHARE] Tunnel expired for {project.name}")
            self.grant.revoke(Path(project.path))

    async def _kill_orphans(self) -> None:
        """Only when no tunnel of ours is running: a cloudflared left over
        from a previous CraftBot would otherwise pile up."""
        try:
            if os.name == "nt":
                subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        "Stop-Process -Name cloudflared -Force -ErrorAction SilentlyContinue",
                    ],
                    capture_output=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
            await asyncio.sleep(1)
        except Exception:
            pass

    # ── cloudflared binary ──

    def _cloudflared_path(self) -> Optional[str]:
        """PATH first, then our local bin directory."""
        system_path = shutil.which("cloudflared")
        if system_path:
            return system_path
        ext = ".exe" if sys.platform == "win32" else ""
        local_bin = self._BIN_DIR / f"cloudflared{ext}"
        return str(local_bin) if local_bin.exists() else None

    async def _ensure_cloudflared(self) -> Optional[str]:
        path = self._cloudflared_path()
        if path:
            return path
        logger.info("[AGENT_APP:SHARE] cloudflared not found, auto-installing...")
        import urllib.request

        platform_key = sys.platform
        if platform_key not in self._CLOUDFLARED_URLS:
            logger.error(f"[AGENT_APP:SHARE] Unsupported platform: {platform_key}")
            return None
        self._BIN_DIR.mkdir(parents=True, exist_ok=True)
        ext = ".exe" if platform_key == "win32" else ""
        target = self._BIN_DIR / f"cloudflared{ext}"
        try:
            req = urllib.request.Request(
                self._CLOUDFLARED_URLS[platform_key], headers={"User-Agent": "CraftBot"}
            )
            resp = urllib.request.urlopen(req, timeout=60)
            if platform_key == "darwin":
                import io
                import tarfile

                with tarfile.open(fileobj=io.BytesIO(resp.read()), mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if "cloudflared" in member.name:
                            f = tar.extractfile(member)
                            if f:
                                target.write_bytes(f.read())
                                break
            else:
                target.write_bytes(resp.read())
            if platform_key != "win32":
                target.chmod(0o755)
            logger.info(f"[AGENT_APP:SHARE] cloudflared installed at {target}")
            return str(target)
        except Exception as e:
            logger.error(f"[AGENT_APP:SHARE] Failed to download cloudflared: {e}")
            if target.exists():
                target.unlink()
            return None

    # ── cloudflared output ──

    @staticmethod
    def log_path(project: Any) -> Path:
        return Path(project.path) / "logs" / "cloudflared.log"

    def _open_log(self, project: Any, port: int) -> Tuple[Optional[Any], Path, int]:
        """Open cloudflared's output sink. Returns (handle, path, offset).

        The sink is not optional — it is both the tunnel's only log and the
        only place the public URL is announced — so an unwritable project
        directory falls back to the temp dir rather than failing the share.
        """
        candidates = [
            self.log_path(project),
            Path(tempfile.gettempdir()) / f"cloudflared-{project.id}.log",
        ]
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Append across restarts, but never grow without bound: this
                # file collects everything cloudflared logs while sharing.
                too_big = path.exists() and path.stat().st_size > 2_000_000
                handle = open(
                    path, "w" if too_big else "a", encoding="utf-8", errors="replace"
                )
                handle.write(
                    f"\n=== cloudflared start "
                    f"{datetime.now().isoformat(timespec='seconds')} "
                    f"port={port} ===\n"
                )
                handle.flush()
                return handle, path, path.stat().st_size
            except Exception as e:
                logger.warning(f"[AGENT_APP:SHARE] Tunnel log unusable at {path}: {e}")
        return None, candidates[-1], 0

    @staticmethod
    def _close_log(handle: Optional[Any]) -> None:
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            pass

    @staticmethod
    async def _parse_url(
        proc: subprocess.Popen, log_path: Path, start_offset: int = 0, timeout: int = 30
    ) -> Optional[str]:
        """Wait for cloudflared to announce its public URL in its log file.
        Tails the file rather than reading the process pipes — see the note
        in _connect about the pipe-buffer deadlock that cost us the tunnel."""
        pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        deadline = time.time() + timeout
        offset = start_offset
        seen = ""
        while True:
            # Sample liveness BEFORE reading, so a process that dies between
            # the two still gets its final bytes examined.
            exited = proc.poll() is not None
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(offset)
                    seen += fh.read()
                    offset = fh.tell()
            except FileNotFoundError:
                pass
            match = pattern.search(seen)
            if match:
                return match.group(0)
            # cloudflared boxes the URL inside an ASCII banner, so it can land
            # split across two reads: keep a tail long enough to re-match.
            if len(seen) > 8192:
                seen = seen[-1024:]
            if exited:
                logger.error(
                    f"[AGENT_APP:SHARE] cloudflared exited (code {proc.returncode}) "
                    f"before announcing a URL; see {log_path}"
                )
                return None
            if time.time() >= deadline:
                logger.error(
                    f"[AGENT_APP:SHARE] No cloudflare URL within {timeout}s; see {log_path}"
                )
                return None
            await asyncio.sleep(0.3)


# ── the service the manager composes ──────────────────────────────────────


class SharingService:
    """Every share channel, behind one interface. The manager decides WHEN
    (project running, which port); the channels decide HOW."""

    def __init__(self, terminate: Callable[[subprocess.Popen], None]):
        self.channels: Dict[str, ShareChannel] = {
            c.name: c for c in (LanChannel(), TunnelChannel(terminate))
        }
        assert set(self.channels) == set(SHARE_CHANNELS), "guards must know every channel"

    def channel(self, name: str) -> ShareChannel:
        try:
            return self.channels[name]
        except KeyError:
            raise ShareError(f"Unknown share channel: {name}") from None

    async def open(self, project: Any, name: str, port: int) -> str:
        return await self.channel(name).open(project, port)

    async def close(self, project: Any, name: str) -> None:
        await self.channel(name).close(project)

    async def close_all(self, project: Any) -> None:
        for channel in self.channels.values():
            await channel.close(project)

    def links(self, project: Any) -> Dict[str, Optional[str]]:
        return {name: c.link(project) for name, c in self.channels.items()}

    def restore(self, project: Any) -> None:
        for channel in self.channels.values():
            channel.restore(project)
