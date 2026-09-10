"""ProbePool — warm headless-browser sessions for Agent App probing.

Every browser check used to pay a full Chromium cold start: `browser_probe`
spawned `lui probe` (launch → steps → close, ~15-20s of which ~3s was the
actual checking), the boot smoke did the same, and the walk verifier's
probes went through the same action. Measured live (2026-09-09, abce2616):
nine probes ≈ 2.5 minutes, almost all of it launch overhead.

The pool keeps ONE `lui probe-server` process per target PORT: first probe
pays the cold start, every later probe against that app reuses the warm
page (which also preserves page state, so multi-step flows can be probed
incrementally). Line-delimited JSON over stdio; requests are serialized per
session — the page is a single stateful resource and interleaving two
probes on it would corrupt both.

Lifecycle is owned by the app lifecycle, not by timers: the moments that
invalidate a rendered page are exactly the moments an environment changes,
so ShadowProvisioner.prepare/destroy and the live launch/stop paths call
`drop(port)`. A dropped or crashed session simply makes the next probe pay
the cold start again.

Fail-open contract: when playwright/browser is unavailable the pool raises
ProbeUnavailable with the server's own reason. Callers degrade exactly like
the boot smoke always has (skipped, never a build failure) — and the walk
action's probe mandate must not block on an environment that cannot probe.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

_MAX_SESSIONS = 4
_READY_TIMEOUT_S = 45.0
_REQUEST_TIMEOUT_S = 150.0


class ProbeUnavailable(RuntimeError):
    """The probe browser cannot run here (playwright/chromium missing)."""


class _Session:
    def __init__(self, port: int, process: asyncio.subprocess.Process) -> None:
        self.port = port
        self.process = process
        self.created_at = time.time()
        self.last_used_at = time.time()
        self.lock = asyncio.Lock()  # one in-flight request per warm page
        self._seq = 0

    def next_id(self) -> str:
        self._seq += 1
        return f"r{self._seq}"

    @property
    def alive(self) -> bool:
        return self.process.returncode is None


class ProbePool:
    def __init__(self) -> None:
        self._sessions: Dict[int, _Session] = {}
        self._spawn_lock = asyncio.Lock()
        # Set the first time the server reports a fatal (playwright missing):
        # a per-machine fact, so later callers skip the spawn attempt.
        self.unavailable_reason: Optional[str] = None

    # ── public API ─────────────────────────────────────────────────────────
    async def probe(
        self,
        url: str,
        steps: List[Dict[str, Any]],
        out_dir: str,
        timeout: float = _REQUEST_TIMEOUT_S,
    ) -> Dict[str, Any]:
        """Run `steps` against `url` on the warm session for its port.

        Returns {"steps": [...], "consoleErrors": [...]}. Raises
        ProbeUnavailable when no browser can run here, RuntimeError on a
        request that failed after the session was healthy."""
        if self.unavailable_reason is not None:
            raise ProbeUnavailable(self.unavailable_reason)
        port = self._port_of(url)
        session = await self._session_for(port)
        request = {
            "id": session.next_id(),
            "url": url,
            "steps": steps,
            "outDir": out_dir,
        }
        async with session.lock:
            try:
                response = await asyncio.wait_for(
                    self._roundtrip(session, request), timeout=timeout
                )
            except (asyncio.TimeoutError, ConnectionError, BrokenPipeError) as e:
                # The page (or the whole browser) wedged mid-request. The
                # session is unusable — kill it so the NEXT probe pays a
                # clean cold start instead of inheriting the wedge.
                self.drop(port)
                raise RuntimeError(
                    f"probe against :{port} did not complete ({e.__class__.__name__})"
                )
        session.last_used_at = time.time()
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        return {
            "steps": response.get("steps", []),
            "consoleErrors": response.get("consoleErrors", []),
        }

    def drop(self, port: int) -> None:
        """Kill the session for `port`. Called whenever the environment on
        that port changes (shadow boot/teardown, live launch/stop) — a page
        must never outlive the build it rendered."""
        session = self._sessions.pop(port, None)
        if session is not None:
            self._kill(session)
            logger.info(f"[PROBE_POOL] dropped session for :{port}")

    def drop_all(self) -> None:
        for port in list(self._sessions):
            self.drop(port)

    # ── internals ──────────────────────────────────────────────────────────
    @staticmethod
    def _port_of(url: str) -> int:
        parts = urlsplit(url)
        if parts.port is None:
            raise ValueError(f"probe URL must carry an explicit port: {url!r}")
        return int(parts.port)

    async def _session_for(self, port: int) -> _Session:
        existing = self._sessions.get(port)
        if existing is not None and existing.alive:
            return existing
        if existing is not None:
            self.drop(port)
        async with self._spawn_lock:
            # Re-check under the lock: a concurrent caller may have spawned.
            existing = self._sessions.get(port)
            if existing is not None and existing.alive:
                return existing
            session = await self._spawn(port)
            self._sessions[port] = session
            self._evict_lru()
            return session

    async def _spawn(self, port: int) -> _Session:
        from app.config import PROJECT_ROOT
        from app import node_runtime

        cli = Path(PROJECT_ROOT) / "agent-app" / "tools" / "src" / "cli.ts"
        process = await asyncio.create_subprocess_exec(
            node_runtime.node_cmd() or "node",
            str(cli),
            "probe-server",
            env=node_runtime.child_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        session = _Session(port, process)
        try:
            first = await asyncio.wait_for(
                process.stdout.readline(), timeout=_READY_TIMEOUT_S
            )
            payload = json.loads(first.decode(errors="replace").strip() or "{}")
        except (asyncio.TimeoutError, json.JSONDecodeError) as e:
            self._kill(session)
            raise RuntimeError(f"probe server did not become ready: {e}")
        if payload.get("fatal"):
            self._kill(session)
            self.unavailable_reason = str(payload["fatal"])
            raise ProbeUnavailable(self.unavailable_reason)
        if not payload.get("ready"):
            self._kill(session)
            raise RuntimeError(f"probe server sent an unexpected greeting: {payload}")
        logger.info(f"[PROBE_POOL] warm browser up for :{port} (pid {process.pid})")
        return session

    async def _roundtrip(
        self, session: _Session, request: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not session.alive:
            raise ConnectionError("probe server process is dead")
        session.process.stdin.write((json.dumps(request) + "\n").encode())
        await session.process.stdin.drain()
        while True:
            line = await session.process.stdout.readline()
            if not line:
                raise ConnectionError("probe server closed its pipe")
            payload = json.loads(line.decode(errors="replace").strip())
            # Correlate strictly by id; anything else on the pipe (a stray
            # error line) is not this request's answer.
            if payload.get("id") == request["id"]:
                return payload
            if "fatal" in payload:
                raise ConnectionError(str(payload["fatal"]))

    def _evict_lru(self) -> None:
        while len(self._sessions) > _MAX_SESSIONS:
            oldest_port = min(
                self._sessions, key=lambda p: self._sessions[p].last_used_at
            )
            self.drop(oldest_port)

    @staticmethod
    def _kill(session: _Session) -> None:
        if not session.alive:
            return
        try:
            if sys.platform == "win32":
                # Chromium is a grandchild; a bare terminate strands its tree.
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(session.process.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                session.process.terminate()
        except Exception as e:
            logger.warning(f"[PROBE_POOL] kill failed: {e}")


_POOL: Optional[ProbePool] = None


def get_probe_pool() -> ProbePool:
    global _POOL
    if _POOL is None:
        _POOL = ProbePool()
    return _POOL
