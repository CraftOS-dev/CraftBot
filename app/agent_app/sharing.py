"""LAN relay and cloudflared transport for CraftBot framework app sharing."""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from app.process_ledger import ROLE_TUNNEL, get_ledger

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}

class ShareError(RuntimeError):
    """A channel could not be opened; the message is for the owner."""


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

        threading.Thread(
            target=_run, daemon=True, name=f"lan-relay-{self.port}"
        ).start()
        await asyncio.get_running_loop().run_in_executor(None, ready.wait, 10)
        if not isinstance(result[0], int):
            self._loop = None
            raise ShareError(f"Could not listen on {self.host}: {result[0]}")
        return result[0]

    async def _setup(self) -> int:
        import aiohttp
        from aiohttp import web

        self._session = aiohttp.ClientSession(
            cookie_jar=aiohttp.DummyCookieJar(),
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
                for k, v in self._response_headers(up.headers):
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

    def _response_headers(self, headers):
        return headers.items()

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

        pumps = [asyncio.create_task(pump(server_ws, client_ws)), asyncio.create_task(pump(client_ws, server_ws))]
        try:
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            await client_ws.close()
            await server_ws.close()
        return server_ws


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


# ── public: the cloudflared tunnel ─────────────────────────────────────────


class TunnelChannel:
    """Public link: a cloudflared quick tunnel, one process per project."""

    name = "tunnel"

    _CLOUDFLARED_URLS = {
        "win32": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        "darwin": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        "linux": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    }
    _BIN_DIR = Path(__file__).parent.parent / "bin"

    def __init__(self, terminate: Callable[[subprocess.Popen], None]):
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
        log_handle, log_path = self._open_log(project, port)
        if log_handle is None:
            raise ShareError("No writable location for the cloudflared log.")

        # The share gateway binds IPv4 loopback; avoid localhost resolving to ::1.
        origin_url = f"http://127.0.0.1:{port}"
        # Where cloudflared reports on itself (see _await_ready). Chosen here:
        # its default port is picked at runtime and only named in its log.
        metrics = f"127.0.0.1:{self._free_loopback_port()}"
        logger.info(
            f"[AGENT_APP:SHARE] Starting cloudflared: {cloudflared} tunnel "
            f"--metrics {metrics} --url {origin_url} (log: {log_path})"
        )
        proc = subprocess.Popen(
            [cloudflared, "tunnel", "--metrics", metrics, "--url", origin_url],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        # Record the exact identity (pid + start time) so a later run can reap
        # THIS process and nothing else — see _kill_orphans.
        get_ledger().register(
            proc.pid,
            ROLE_TUNNEL,
            owner=str(getattr(project, "id", "")),
            label=origin_url,
        )
        self._running[project.id] = (proc, log_handle)
        try:
            url = await self._await_ready(proc, metrics, log_path)
            if not url:
                raise ShareError(f"cloudflared didn't come up. More info in {log_path}")
            return url
        except BaseException:
            await self._disconnect(project)
            raise

    async def _disconnect(self, project: Any) -> None:
        proc, log_handle = self._running.pop(project.id, (None, None))
        if proc is not None:
            self._terminate(proc)
        self._close_log(log_handle)


    async def _kill_orphans(self) -> None:
        """Reap cloudflared processes a previous CraftBot run left behind.

        By recorded identity (pid + start time), never by process name. This
        used to be `Stop-Process -Name cloudflared` / `pkill -f cloudflared`,
        which took down EVERY cloudflared on the machine — including a tunnel
        the user runs for their own production work, which is not ours to
        kill. Tunnels this run currently holds are skipped."""
        held = {p.pid for p, _ in self._running.values()}
        ledger = get_ledger()
        reaped = 0
        for entry in ledger.entries(ROLE_TUNNEL):
            if entry.pid not in held and ledger.kill_entry(entry):
                reaped += 1
        if reaped:
            logger.info(f"[AGENT_APP:SHARE] Reaped {reaped} leftover tunnel(s)")
            await asyncio.sleep(1)

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

    def _open_log(self, project: Any, port: int) -> Tuple[Optional[Any], Path]:
        """Open cloudflared's output sink. Returns (handle, path).

        The sink is not optional: a pipe nobody drains wedges cloudflared
        (see _connect), and this is the tunnel's only log. So an unwritable
        project directory falls back to the temp dir rather than failing the
        share.
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
                return handle, path
            except Exception as e:
                logger.warning(f"[AGENT_APP:SHARE] Tunnel log unusable at {path}: {e}")
        return None, candidates[-1]

    @staticmethod
    def _close_log(handle: Optional[Any]) -> None:
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            pass

    # ── cloudflared readiness ──

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @staticmethod
    async def _await_ready(
        proc: subprocess.Popen, metrics: str, log_path: Path, timeout: int = 120
    ) -> Optional[str]:
        """Wait until cloudflared holds a live connection to Cloudflare, then
        return the public origin it was assigned. Both come from cloudflared's
        metrics server as structured data: /ready answers 200 once a
        connection is registered, /quicktunnel names the hostname.

        Never from its log text. The URL used to be scraped from there, and
        the pattern also matched the API host in cloudflared's own failure
        line ("failed to request quick Tunnel: Post
        https://api.trycloudflare.com/tunnel ..."), so a tunnel that never
        came up was handed out as a link. The metrics server only starts once
        the tunnel exists; a failed request exits the process instead."""
        import aiohttp

        # Edge registration can take longer than URL allocation while
        # cloudflared retries. Wall-clock adjustments must not cut it short.
        deadline = time.monotonic() + timeout
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=2)
        ) as session:
            while True:
                if proc.poll() is not None:
                    logger.error(
                        f"[AGENT_APP:SHARE] cloudflared exited (code {proc.returncode}) "
                        f"before its tunnel was ready; see {log_path}"
                    )
                    return None
                try:
                    async with session.get(f"http://{metrics}/ready") as resp:
                        ready = resp.status == 200
                    if ready:
                        async with session.get(f"http://{metrics}/quicktunnel") as resp:
                            hostname = (await resp.json(content_type=None)).get(
                                "hostname"
                            )
                        if hostname:
                            return f"https://{hostname}"
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    pass  # not listening yet: it starts once the tunnel exists
                if time.monotonic() >= deadline:
                    logger.error(
                        f"[AGENT_APP:SHARE] cloudflared tunnel not ready within "
                        f"{timeout}s; see {log_path}"
                    )
                    return None
                await asyncio.sleep(0.3)


# ── the service the manager composes ──────────────────────────────────────
