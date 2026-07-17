"""Sharing URLs for Living UI projects (mixin of LivingUIManager):
local URL, LAN URL, and cloudflared quick-tunnels — discovery, install,
lifecycle, and startup revalidation of persisted tunnel URLs.
Mechanically extracted from manager.py — bodies unchanged.
"""

import asyncio
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class TunnelMixin:
    """LAN + tunnel sharing.

    Relies on host attributes/methods: ``projects``, ``_save_projects``,
    ``_terminate_process``.
    """

    def _validate_saved_tunnels(self, entries: List[Tuple[str, str]]) -> None:
        """Verify saved tunnel URLs are still reachable; clear dead ones.

        Runs on a background thread at startup so the event loop never blocks
        on network round-trips. Dead tunnels are cleared and persisted.
        """
        import urllib.request

        changed = False
        for project_id, url in entries:
            alive = False
            try:
                req = urllib.request.Request(url, method="HEAD")
                urllib.request.urlopen(req, timeout=3)
                alive = True
            except Exception:
                pass
            project = self.projects.get(project_id)
            if not project or project.tunnel_url != url:
                continue  # Deleted or re-tunneled while we were checking
            if alive:
                logger.info(
                    f"[LIVING_UI] Tunnel still active for '{project.name}': {url}"
                )
            else:
                logger.info(
                    f"[LIVING_UI] Tunnel expired for '{project.name}', clearing"
                )
                project.tunnel_url = None
                changed = True
        if changed:
            self._save_projects()

    def get_project_url(self, project_id: str) -> Optional[str]:
        """Get the URL for a running project."""
        project = self.projects.get(project_id)
        if project and project.status == "running":
            return project.url
        return None

    @staticmethod
    def get_lan_ip() -> Optional[str]:
        """Get the machine's LAN IP address."""
        try:
            # Connect to a public IP to determine the right interface
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return None

    def get_lan_url(self, project_id: str) -> Optional[str]:
        """Get the LAN-accessible URL for a running project.

        Uses the backend port since the backend also serves the frontend
        static files — single port for everything.
        """
        project = self.projects.get(project_id)
        if not project or project.status != "running":
            return None
        # Prefer backend port (serves both API + frontend static files)
        port = project.backend_port or project.port
        if not port:
            return None
        ip = self.get_lan_ip()
        if not ip or ip.startswith("127."):
            return None
        return f"http://{ip}:{port}"

    # Cloudflared binary download URLs per platform
    _CLOUDFLARED_URLS = {
        "win32": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        "darwin": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        "linux": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    }

    def _get_cloudflared_path(self) -> Optional[str]:
        """Find cloudflared — check PATH first, then our local bin directory."""
        system_path = shutil.which("cloudflared")
        if system_path:
            return system_path
        # Check our local bin
        import sys

        ext = ".exe" if sys.platform == "win32" else ""
        local_bin = Path(__file__).parent.parent / "bin" / f"cloudflared{ext}"
        if local_bin.exists():
            return str(local_bin)
        return None

    async def _ensure_cloudflared(self) -> Optional[str]:
        """Find cloudflared or auto-install it. Returns the binary path or None."""
        path = self._get_cloudflared_path()
        if path:
            return path

        logger.info("[LIVING_UI] cloudflared not found, auto-installing...")
        import sys
        import urllib.request

        platform_key = sys.platform
        if platform_key not in self._CLOUDFLARED_URLS:
            logger.error(f"[LIVING_UI] Unsupported platform: {platform_key}")
            return None

        bin_dir = Path(__file__).parent.parent / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        ext = ".exe" if platform_key == "win32" else ""
        target = bin_dir / f"cloudflared{ext}"

        try:
            url = self._CLOUDFLARED_URLS[platform_key]
            req = urllib.request.Request(url, headers={"User-Agent": "CraftBot"})
            resp = urllib.request.urlopen(req, timeout=60)

            if platform_key == "darwin":
                import tarfile
                import io

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

            logger.info(f"[LIVING_UI] cloudflared installed at {target}")
            return str(target)
        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to download cloudflared: {e}")
            if target.exists():
                target.unlink()
            return None

    async def start_tunnel(
        self, project_id: str, provider: str = "cloudflared"
    ) -> Optional[str]:
        """Start a cloudflare tunnel for remote access. Returns the public URL."""
        logger.info(f"[LIVING_UI] start_tunnel called for {project_id}")
        project = self.projects.get(project_id)
        if not project or project.status != "running":
            logger.warning(
                f"[LIVING_UI] Cannot start tunnel: project={project is not None}, status={project.status if project else 'N/A'}"
            )
            return None

        logger.info("[LIVING_UI] Stopping any existing tunnel...")
        await self.stop_tunnel(project_id)

        # Only kill orphans on first tunnel start (no other tunnels active)
        other_tunnels = any(
            p.tunnel_process is not None and p.id != project_id
            for p in self.projects.values()
        )
        if not other_tunnels:
            logger.info(
                "[LIVING_UI] No other tunnels active, cleaning orphan cloudflared processes..."
            )
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
                    )
                else:
                    subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
                await asyncio.sleep(1)
            except Exception:
                pass

        port = project.backend_port or project.port
        if not port:
            return None

        cloudflared = await self._ensure_cloudflared()
        if not cloudflared:
            logger.error("[LIVING_UI] cloudflared binary not found")
            return None

        logger.info(
            f"[LIVING_UI] Starting cloudflared: {cloudflared} tunnel --url http://localhost:{port}"
        )
        proc = subprocess.Popen(
            [cloudflared, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        logger.info(f"[LIVING_UI] cloudflared started, PID={proc.pid}, parsing URL...")
        url = await self._parse_cloudflare_url(proc)
        logger.info(f"[LIVING_UI] cloudflared URL parse result: {url}")

        if url:
            project.tunnel_process = proc
            project.tunnel_url = url
            self._save_projects()
            logger.info(f"[LIVING_UI] Tunnel started for {project.name}: {url}")
            return url
        else:
            self._terminate_process(proc)
            logger.error("[LIVING_UI] Failed to get tunnel URL")
            return None

    async def stop_tunnel(self, project_id: str) -> None:
        """Stop the tunnel for a project."""
        project = self.projects.get(project_id)
        if not project:
            return
        if project.tunnel_process:
            self._terminate_process(project.tunnel_process)
            project.tunnel_process = None
        project.tunnel_url = None
        self._save_projects()
        logger.info(f"[LIVING_UI] Tunnel stopped for {project.name}")

    async def _parse_cloudflare_url(
        self, proc: subprocess.Popen, timeout: int = 30
    ) -> Optional[str]:
        """Parse the public URL from cloudflared output."""
        import re
        import threading

        url_result = [None]
        pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        def _read_stream(stream):
            try:
                for line_bytes in stream:
                    text = line_bytes.decode("utf-8", errors="replace")
                    match = pattern.search(text)
                    if match:
                        url_result[0] = match.group(0)
                        return
            except Exception:
                pass

        # Read both stdout and stderr in parallel threads
        t1 = threading.Thread(target=_read_stream, args=(proc.stdout,), daemon=True)
        t2 = threading.Thread(target=_read_stream, args=(proc.stderr,), daemon=True)
        t1.start()
        t2.start()

        # Wait for either thread to find the URL
        deadline = time.time() + timeout
        while time.time() < deadline and url_result[0] is None:
            if proc.poll() is not None and url_result[0] is None:
                break
            await asyncio.sleep(0.5)

        if url_result[0]:
            logger.info(f"[LIVING_UI] Parsed cloudflare URL: {url_result[0]}")
        else:
            logger.error("[LIVING_UI] Failed to parse cloudflare URL within timeout")

        return url_result[0]
