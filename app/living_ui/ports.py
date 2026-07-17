"""Port allocation for Living UI projects (mixin of LivingUIManager).

Owns the port pool (range + used-set + lock, initialized by the manager's
__init__) and every system-level port probe/free operation. Mechanically
extracted from manager.py — bodies unchanged.
"""

import asyncio
import os
import socket
import subprocess
from typing import Dict, Optional, Set

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class PortAllocationMixin:
    """Port pool + orphan-process eviction.

    Relies on host attributes: ``_ports_lock``, ``_used_ports``,
    ``_port_range`` (all set in LivingUIManager.__init__).
    """

    def _allocate_port(self) -> int:
        """Allocate a free port for a Living UI project.

        Checks both the internal tracking set AND actual system port usage
        to avoid conflicts with orphan processes.
        """
        with self._ports_lock:
            for port in range(self._port_range[0], self._port_range[1] + 1):
                # Skip if tracked as used
                if port in self._used_ports:
                    continue
                # Skip if actually in use on the system
                if self._is_port_in_use(port):
                    logger.warning(
                        f"[LIVING_UI] Port {port} in use by external process, skipping"
                    )
                    continue
                self._used_ports.add(port)
                return port
            raise RuntimeError("No available ports in the Living UI port range")

    def _release_port(self, port: int) -> None:
        """Release a port back to the pool."""
        with self._ports_lock:
            self._used_ports.discard(port)

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is actually in use on the system."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("localhost", port)) == 0

    async def _ensure_port_available(self, port: int) -> bool:
        """Ensure a port is available, killing orphan processes if needed."""
        if not self._is_port_in_use(port):
            return True

        logger.warning(f"[LIVING_UI:PIPELINE] Port {port} in use, attempting to free")
        self._kill_process_on_port(port)
        await asyncio.sleep(1)

        if self._is_port_in_use(port):
            logger.error(f"[LIVING_UI:PIPELINE] Could not free port {port}")
            return False
        return True

    def _get_pids_on_ports(
        self, ports_to_check: Optional[Set[int]] = None
    ) -> Dict[int, str]:
        """
        Get PIDs of processes listening on ports in the Living UI range.
        Uses a single system call for efficiency.

        Args:
            ports_to_check: Optional set of specific ports to check.
                           If None, checks all ports in the Living UI range.

        Returns:
            Dict mapping port numbers to PIDs
        """
        port_pids = {}

        if os.name == "nt":
            # Windows: run netstat once and parse all results
            try:
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True,
                    text=True,
                    shell=True,
                    timeout=5,
                )
                for line in result.stdout.split("\n"):
                    if "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            addr = parts[1]
                            pid = parts[-1]
                            if ":" in addr:
                                try:
                                    port = int(addr.split(":")[-1])
                                    # Check if port is in range and optionally in the filter set
                                    if (
                                        self._port_range[0]
                                        <= port
                                        <= self._port_range[1]
                                    ):
                                        if (
                                            ports_to_check is None
                                            or port in ports_to_check
                                        ):
                                            port_pids[port] = pid
                                except ValueError:
                                    pass
            except Exception as e:
                logger.warning(f"[LIVING_UI] Failed to get ports via netstat: {e}")
        else:
            # Linux/Mac: use lsof
            try:
                result = subprocess.run(
                    ["lsof", "-i", "-P", "-n"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.split("\n"):
                    if "LISTEN" in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            # PID is typically the second column
                            pid = parts[1]
                            # Find the port in the line
                            for part in parts:
                                if ":" in part:
                                    try:
                                        port = int(part.split(":")[-1])
                                        if (
                                            self._port_range[0]
                                            <= port
                                            <= self._port_range[1]
                                        ):
                                            if (
                                                ports_to_check is None
                                                or port in ports_to_check
                                            ):
                                                port_pids[port] = pid
                                                break
                                    except ValueError:
                                        pass
            except Exception as e:
                logger.warning(f"[LIVING_UI] Failed to get ports via lsof: {e}")

        return port_pids

    def _kill_process_by_pid(self, pid: str) -> bool:
        """
        Kill a process by its PID.

        Args:
            pid: Process ID to kill

        Returns:
            True if process was killed, False otherwise
        """
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid], capture_output=True, shell=True
                )
            else:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            return True
        except Exception as e:
            logger.warning(f"[LIVING_UI] Failed to kill process {pid}: {e}")
            return False

    def _kill_process_on_port(self, port: int) -> bool:
        """
        Kill any process listening on the specified port (Windows-specific).

        Args:
            port: The port to free

        Returns:
            True if a process was killed, False otherwise
        """
        if os.name != "nt":
            # Linux/Mac: use lsof and kill
            try:
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"], capture_output=True, text=True
                )
                if result.stdout.strip():
                    pids = result.stdout.strip().split("\n")
                    for pid in pids:
                        subprocess.run(["kill", "-9", pid], capture_output=True)
                    logger.info(f"[LIVING_UI] Killed process(es) on port {port}")
                    return True
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Failed to kill process on port {port}: {e}"
                )
            return False
        else:
            # Windows: use netstat and taskkill
            try:
                result = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True, shell=True
                )
                killed = False
                for line in result.stdout.split("\n"):
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            # /T kills entire process tree (shell + child processes)
                            subprocess.run(
                                ["taskkill", "/T", "/F", "/PID", pid],
                                capture_output=True,
                                shell=True,
                            )
                            logger.info(
                                f"[LIVING_UI] Killed process tree {pid} on port {port}"
                            )
                            killed = True
                if killed:
                    return True
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Failed to kill process on port {port}: {e}"
                )
            return False
