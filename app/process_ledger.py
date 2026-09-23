"""Ledger of the processes CraftBot itself started — the ONLY ones it kills.

Every process-cleanup path used to decide "is this ours?" from a name or a
port: `pkill -f cloudflared` / `Stop-Process -Name cloudflared` took down
every tunnel on the machine, and `f":{port}" in netstat_line` matched :3100
against :31000 and killed whatever listened there. A foreign service that
happened to sit on "our" port was fair game too.

The rule this module enforces: **a process is ours only if we recorded its
exact identity when we started it.** Identity is (pid, create_time) — the
creation time is what makes a persisted pid safe across a restart, because a
recycled pid belongs to a process with a different start time and is never
matched. Anything the ledger cannot vouch for is left alone and logged.

A process counts as owned when it, or a live ancestor, is in the ledger — so
recording a shell (`shell=True` → cmd.exe/sh) also covers the server it
spawned. A server whose spawning shell later dies is covered by recording
the listener itself once the service is up (`adopt_listeners`).

Each ledger file has ONE writer process (the launcher and the agent keep
separate files), so there is no cross-process write race; a lock covers
threads within the process.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover - launcher may run before deps load
    import logging

    logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:  # pragma: no cover - declared in requirements.txt
    psutil = None

# psutil derives create_time from boot time + ticks on Linux, which can wobble
# by a fraction of a second between reads. A recycled pid would have to be
# started within this window of the original to be mistaken for it.
_CREATE_TIME_TOLERANCE = 1.0

ROLE_TUNNEL = "tunnel"
ROLE_AGENT_APP = "agent_app"
ROLE_LAUNCHER = "launcher"


@dataclass
class OwnedProcess:
    pid: int
    create_time: float
    role: str
    owner: str = ""  # e.g. the project id the process serves
    label: str = ""  # human-readable, for logs only

    @classmethod
    def from_dict(cls, d: Dict) -> "OwnedProcess":
        return cls(
            pid=int(d["pid"]),
            create_time=float(d["create_time"]),
            role=str(d.get("role", "")),
            owner=str(d.get("owner", "")),
            label=str(d.get("label", "")),
        )


def _create_time(pid: int) -> Optional[float]:
    """Start time of a live pid, or None if it is gone/inaccessible."""
    if psutil is None or not pid or pid <= 0:
        return None
    try:
        return psutil.Process(pid).create_time()
    except Exception:
        return None


def listening_pids(port: int) -> List[int]:
    """Pids with a TCP socket LISTENING on exactly `port`.

    Exact integer comparison on the parsed local port — never a substring of
    a netstat line. psutil first (locale-independent); netstat/lsof as the
    fallback where psutil is missing or needs root (macOS).
    """
    port = int(port)
    if psutil is not None:
        try:
            return sorted(
                {
                    c.pid
                    for c in psutil.net_connections(kind="tcp")
                    if c.pid
                    and c.status == psutil.CONN_LISTEN
                    and c.laddr
                    and c.laddr.port == port
                }
            )
        except Exception:
            pass  # AccessDenied on macOS without root — fall through

    pids = set()
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
            for line in out.splitlines():
                # Proto  Local  Foreign  State  PID. A listener's foreign
                # address is the wildcard (0.0.0.0:0 / [::]:0); matching on
                # that keeps this independent of the localized state name.
                parts = line.split()
                if len(parts) < 5 or parts[0].upper() != "TCP":
                    continue
                local, foreign, pid = parts[1], parts[2], parts[-1]
                if not foreign.endswith(":0") or not pid.isdigit():
                    continue
                try:
                    if int(local.rsplit(":", 1)[1]) == port:
                        pids.add(int(pid))
                except (IndexError, ValueError):
                    continue
        else:
            out = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            pids = {int(p) for p in out.split() if p.isdigit()}
    except Exception as e:
        logger.warning(f"[PROCESS_LEDGER] could not list listeners on {port}: {e}")
    pids.discard(0)
    return sorted(pids)


#: Scripts a CraftBot process is started from. Seeing one of these in a
#: command line proves nothing on its own — `run.py` and `main.py` are the two
#: most common script names there are — so a match only counts when the file
#: sits in a directory that also holds craftbot.py.
_CRAFTBOT_SCRIPTS = ("run.py", "main.py", "craftbot.py")


def _is_craftbot_tree(directory: str) -> bool:
    """True if `directory` is the root of a CraftBot source tree."""
    if not directory:
        return False
    try:
        return os.path.isfile(os.path.join(directory, "craftbot.py"))
    except OSError:
        return False


def identify_craftbot(pid: int) -> Optional[str]:
    """Describe `pid` if it is demonstrably a CraftBot process, else None.

    The narrow, deliberate exception to this module's rule that only a
    recorded process may be killed — and it does NOT weaken it, because
    identity is still *proved*, just from the process itself rather than from
    a record kept at spawn time.

    The rule alone cannot cover one real case: a CraftBot from a PREVIOUS
    install. Uninstall deletes the ledger, so the next run has no record of
    the process still holding port 7925, cannot stop it, and the user gets a
    port conflict that no CraftBot command can clear. That is not a foreign
    service being protected — it is our own process, orphaned by us.

    Evidence accepted, both self-describing and install-independent:
      * the command line names one of _CRAFTBOT_SCRIPTS sitting next to a
        craftbot.py (the launcher: `python <root>/run.py`);
      * the command line is `-m app.main` (or `-m app`) and the working
        directory is a CraftBot tree (the backend).

    Evidence deliberately NOT accepted: running on CraftBot's bundled
    interpreter. Agent Apps run on it too, and widening identity to "uses our
    Python" would put them in range of a port sweep for nothing gained — both
    real shapes above are already covered.

    Returns a human-readable description, because every caller that kills on
    this basis has to be able to say WHAT it killed.
    """
    if psutil is None or not pid or pid <= 0:
        return None
    try:
        proc = psutil.Process(pid)
        cmdline = proc.cmdline() or []
    except Exception:
        # Gone, or another user's process we may not inspect. Unidentifiable
        # is not "ours" — the caller reports it instead of killing it.
        return None

    for token in cmdline:
        if token.endswith(_CRAFTBOT_SCRIPTS) and _is_craftbot_tree(
            os.path.dirname(os.path.abspath(token))
        ):
            return f"pid {pid}: {os.path.basename(token)} from {os.path.dirname(token)}"

    if "-m" in cmdline:
        module = cmdline[cmdline.index("-m") + 1 : cmdline.index("-m") + 2]
        if module and module[0] in ("app.main", "app"):
            try:
                cwd = proc.cwd()
            except Exception:
                return None
            if _is_craftbot_tree(cwd):
                return f"pid {pid}: -m {module[0]} in {cwd}"

    return None


def describe_pid(pid: int) -> str:
    """Name a process we are NOT going to kill: 'pid 1234 (node.exe)'.

    A port conflict the user has to resolve themselves is only actionable if
    the message says what to close, so this degrades to the bare pid rather
    than raising when the process cannot be inspected.
    """
    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            try:
                what = proc.exe() or proc.name()
            except Exception:
                what = proc.name()
            return f"pid {pid} ({what})"
        except Exception:
            pass
    return f"pid {pid}"


def craftbot_listeners(port: int) -> List[tuple]:
    """(pid, description) for every listener on `port` provably CraftBot's.

    The port only selects candidates; identify_craftbot decides. Anything on
    the port that cannot be identified is left out, so the caller can report
    it as a genuine foreign conflict rather than killing it.
    """
    found = []
    for pid in listening_pids(port):
        if pid == os.getpid():
            continue
        description = identify_craftbot(pid)
        if description:
            found.append((pid, description))
    return found


def kill_tree(pid: int, grace: float = 5.0) -> None:
    """Stop a process and every descendant: SIGTERM, then SIGKILL whatever is
    left after `grace` seconds (Windows has no graceful signal for a windowless
    tree, so it is `taskkill /T /F` as before). Callers must have verified
    ownership first — this does not check."""
    if os.name == "nt":
        # taskkill /T walks the tree even when psutil is unavailable.
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    if psutil is None:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        return
    try:
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except Exception:
        return
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    try:
        _, alive = psutil.wait_procs(procs, timeout=grace)
    except Exception:
        alive = procs
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass


class ProcessLedger:
    """Persisted set of processes this CraftBot process started."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._by_pid: Dict[int, OwnedProcess] = {}
        self._load()

    # ── recording ─────────────────────────────────────────────────────────
    def register(
        self, pid: Optional[int], role: str, owner: str = "", label: str = ""
    ) -> Optional[OwnedProcess]:
        """Record a process we just started. Returns None (and records
        nothing) if its identity cannot be read — it then stays unkillable
        by any cleanup path, which is the safe failure."""
        if not pid:
            return None
        ct = _create_time(int(pid))
        if ct is None:
            logger.warning(
                f"[PROCESS_LEDGER] cannot record pid {pid} ({role} {label}): "
                f"identity unreadable{' (psutil missing)' if psutil is None else ''}"
            )
            return None
        entry = OwnedProcess(int(pid), ct, role, owner, label)
        with self._lock:
            self._by_pid[entry.pid] = entry
            self._save()
        return entry

    def adopt_listeners(
        self,
        port: int,
        role: str,
        owner: str = "",
        label: str = "",
        *,
        include_self: bool = False,
    ) -> List[OwnedProcess]:
        """Record the listeners on `port` that are already ours — descendants
        of a recorded process — as entries of their own. Covers a server whose
        spawning shell later dies, which the ancestor walk in `owner_of` could
        then no longer connect to its entry.

        A listener with no recorded ancestor is NOT adopted: a foreign service
        that already held the port would otherwise pass our readiness check
        and be killed by the next run. `include_self` lets the frozen launcher
        (which serves its ports in-process) record its own pid.
        """
        adopted = []
        for pid in listening_pids(port):
            if pid == os.getpid():
                if not include_self:
                    continue  # never record CraftBot's own process as killable
            elif self.owner_of(pid) is None:
                continue
            entry = self.register(pid, role, owner, label or f"listener :{port}")
            if entry:
                adopted.append(entry)
        return adopted

    def forget(self, pid: Optional[int]) -> None:
        if not pid:
            return
        with self._lock:
            if self._by_pid.pop(int(pid), None) is not None:
                self._save()

    def forget_owner(self, owner: str, role: Optional[str] = None) -> None:
        with self._lock:
            before = len(self._by_pid)
            self._by_pid = {
                pid: e
                for pid, e in self._by_pid.items()
                if not (e.owner == owner and (role is None or e.role == role))
            }
            if len(self._by_pid) != before:
                self._save()

    # ── identity ──────────────────────────────────────────────────────────
    def _live_entry(self, pid: int) -> Optional[OwnedProcess]:
        """The entry for `pid` if that pid is still the SAME process."""
        entry = self._by_pid.get(pid)
        if entry is None:
            return None
        ct = _create_time(pid)
        if ct is None or abs(ct - entry.create_time) > _CREATE_TIME_TOLERANCE:
            return None
        return entry

    def owner_of(self, pid: int) -> Optional[OwnedProcess]:
        """The ledger entry that vouches for `pid`: the pid itself, or its
        nearest live ancestor that we recorded. None means not ours."""
        with self._lock:
            entry = self._live_entry(int(pid))
            if entry is not None:
                return entry
            if psutil is None:
                return None
            try:
                parents = psutil.Process(int(pid)).parents()
            except Exception:
                return None
            for parent in parents:
                entry = self._live_entry(parent.pid)
                if entry is not None:
                    return entry
            return None

    # ── killing (owned processes only) ────────────────────────────────────
    def kill_entry(self, entry: OwnedProcess) -> bool:
        """Kill a recorded process tree if it is still the same process.
        The entry is dropped either way (a dead/recycled pid is stale)."""
        with self._lock:
            live = self._live_entry(entry.pid)
            self._by_pid.pop(entry.pid, None)
            self._save()
        if live is None:
            return False
        if live.pid == os.getpid():
            return False  # a frozen launcher records itself; never suicide
        kill_tree(live.pid)
        logger.info(
            f"[PROCESS_LEDGER] killed owned {live.role} pid {live.pid} "
            f"({live.owner or '-'} {live.label})"
        )
        return True

    def kill_pid(self, pid: Optional[int]) -> bool:
        """Kill a pid we hold only as a number (e.g. from a persisted record)
        — only if the ledger recorded exactly that process."""
        if not pid:
            return False
        with self._lock:
            entry = self._by_pid.get(int(pid))
        if entry is None:
            logger.warning(
                f"[PROCESS_LEDGER] refusing to kill pid {pid}: not a process "
                f"CraftBot recorded starting"
            )
            return False
        return self.kill_entry(entry)

    def kill_port_listeners(self, port: int) -> bool:
        """Free `port` by killing ONLY listeners we own. A listener we cannot
        vouch for is logged and left running. True if anything was killed."""
        killed = False
        for pid in listening_pids(port):
            if pid == os.getpid():
                continue  # e.g. the in-process A2App proxy holding the port
            entry = self.owner_of(pid)
            if entry is None:
                # An orphaned CraftBot is not a foreign service, and saying so
                # here would be a log that contradicts itself — the caller's
                # orphan sweep (craftbot_listeners) stops it moments later.
                orphan = identify_craftbot(pid)
                if orphan:
                    logger.info(
                        f"[PROCESS_LEDGER] port {port} is held by an unrecorded "
                        f"CraftBot ({orphan}) — leaving it to the orphan sweep"
                    )
                else:
                    logger.warning(
                        f"[PROCESS_LEDGER] port {port} is held by pid {pid}, which "
                        f"CraftBot did not start — leaving it alone"
                    )
                continue
            if entry.pid == os.getpid():
                continue  # a child of THIS process; its owner stops it
            # Kill from the recorded root so the shell that spawned the
            # listener goes too.
            killed = self.kill_entry(entry) or killed
        return killed

    def reap(self, role: Optional[str] = None, owner: Optional[str] = None) -> int:
        """Kill every still-alive recorded process (optionally filtered) —
        leftovers from a previous run. Returns how many were killed."""
        with self._lock:
            targets = [
                e
                for e in self._by_pid.values()
                if (role is None or e.role == role)
                and (owner is None or e.owner == owner)
            ]
        return sum(1 for e in targets if self.kill_entry(e))

    def entries(self, role: Optional[str] = None) -> List[OwnedProcess]:
        with self._lock:
            return [e for e in self._by_pid.values() if role is None or e.role == role]

    # ── persistence ───────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        for d in raw.get("processes", []):
            try:
                entry = OwnedProcess.from_dict(d)
            except Exception:
                continue
            self._by_pid[entry.pid] = entry
        # Drop records whose process is gone (or whose pid was recycled) so
        # the file only ever lists processes that could still be ours.
        if psutil is not None:
            stale = [pid for pid in self._by_pid if self._live_entry(pid) is None]
            for pid in stale:
                del self._by_pid[pid]
            if stale:
                self._save()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"processes": [asdict(e) for e in self._by_pid.values()]}
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception as e:
            logger.error(f"[PROCESS_LEDGER] could not persist {self._path}: {e}")


_ledgers: Dict[str, ProcessLedger] = {}
_ledgers_lock = threading.Lock()


def get_ledger(scope: str = "agent") -> ProcessLedger:
    """The process-wide ledger for `scope`. One file per writer process:
    "agent" (the CraftBot agent: Agent App servers, tunnels) and "launcher"
    (run.py: frontend + agent backend)."""
    with _ledgers_lock:
        ledger = _ledgers.get(scope)
        if ledger is None:
            from app.config import AGENT_WORKSPACE_ROOT

            ledger = ProcessLedger(
                Path(AGENT_WORKSPACE_ROOT) / f"owned_processes.{scope}.json"
            )
            _ledgers[scope] = ledger
        return ledger


__all__ = [
    "ROLE_TUNNEL",
    "ROLE_AGENT_APP",
    "ROLE_LAUNCHER",
    "OwnedProcess",
    "ProcessLedger",
    "get_ledger",
    "kill_tree",
    "listening_pids",
]
