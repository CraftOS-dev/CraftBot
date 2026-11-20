"""The running CraftBot, as everything outside it sees it.

run.py is the process that IS CraftBot. craftbot.py, the desktop launcher and
service managers only ever look at it from outside, and these files under
app.paths.STATE_ROOT are the whole contract between them:

  craftbot.pid  {"pid": N, "started": T}: run.py's own pid (after any
                interpreter re-exec) and its start time, written when it
                starts, removed on a clean exit. The start time is what tells
                our process from a later one that reused the pid.
  ui.json       {"url", "frontend_port", "backend_port"}: written once the UI
                answers, removed on a clean exit. The ports can differ from
                7925/7926 when another program holds those.
  craftbot.log  where craftbot.py sends run.py's output, and where a
                windowless launch (pythonw, Task Scheduler) writes its own
                (app/console.py).

Plus the loopback plumbing both sides need: an HTTP opener that never goes
through a proxy, NO_PROXY for child processes, the interface to bind
(CRAFTBOT_BIND_HOST), free-port search, and the test for whether a CraftBot
holding a port belongs to THIS state root or to another checkout or home.

Stdlib-only (psutil is used when present): craftbot.py and run.py import this
before dependencies exist.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app import paths

PID_FILE: Path = paths.STATE_ROOT / "craftbot.pid"
UI_FILE: Path = paths.STATE_ROOT / "ui.json"
LOG_FILE: Path = paths.STATE_ROOT / "craftbot.log"

DEFAULT_FRONTEND_PORT = 7925
DEFAULT_BACKEND_PORT = 7926

#: Interface the UI servers bind to. Loopback by default; Docker sets 0.0.0.0
#: so the published ports reach them. The backend's Host/Origin guard stays
#: loopback-only either way (ws_auth.py).
BIND_HOST_ENV = "CRAFTBOT_BIND_HOST"

LOOPBACK_NAMES: Tuple[str, ...] = ("localhost", "127.0.0.1", "::1")

# macOS `ps lstart` has one-second resolution.
_START_TIME_TOLERANCE_S = 2.0


# ── process identity ────────────────────────────────────────────────────────


def process_start_time(pid: int) -> Optional[float]:
    """Epoch start time of a live pid, or None when it is gone."""
    try:
        from installer.helpers import process_start_time as _start_time

        return _start_time(pid)
    except ImportError:
        pass
    try:
        import psutil

        return psutil.Process(int(pid)).create_time()
    except Exception:
        return None


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def write_pid(pid: Optional[int] = None) -> None:
    """Record `pid` (default: this process) as the running CraftBot."""
    pid = int(pid or os.getpid())
    _write_json_atomic(PID_FILE, {"pid": pid, "started": process_start_time(pid)})


def read_pid_record() -> Optional[Tuple[int, Optional[float]]]:
    """(pid, start time or None) from the pid file, or None. Accepts the
    legacy bare-integer format."""
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
            started = data.get("started")
            return int(data["pid"]), (float(started) if started else None)
        return int(raw), None
    except (ValueError, KeyError, TypeError):
        return None


def live_pid(record: Optional[Tuple[int, Optional[float]]]) -> Optional[int]:
    """The recorded pid if that exact process is still running."""
    if not record:
        return None
    pid, started = record
    actual = process_start_time(pid)
    if actual is None:
        return None
    if started is not None and abs(actual - started) > _START_TIME_TOLERANCE_S:
        return None  # the pid was reused by another program
    return pid


def remove_pid(only_if: Optional[int] = None) -> None:
    """Delete the pid file; with `only_if`, only while it still names that
    pid (a newer CraftBot may have replaced the record)."""
    if only_if is not None:
        record = read_pid_record()
        if record is None or record[0] != int(only_if):
            return
    try:
        PID_FILE.unlink()
    except OSError:
        pass


# ── ui.json ─────────────────────────────────────────────────────────────────


def display_url(port: int) -> str:
    """The address a user opens. Always localhost: the backend only accepts
    loopback Host headers, and Docker publishes its ports on the host's
    loopback too."""
    return f"http://localhost:{int(port)}"


def write_ui(
    frontend_port: Optional[int], backend_port: int, edition: str = "browser"
) -> dict:
    """Record where the running CraftBot answers.

    The terminal edition serves no web UI (its client is `craftbot.py tui`):
    its record has no frontend port and its url is the backend, which answers
    a browser with a pointer to that command.
    """
    data = {
        "url": display_url(frontend_port if frontend_port else backend_port),
        "frontend_port": int(frontend_port) if frontend_port else None,
        "backend_port": int(backend_port),
        "edition": edition,
    }
    _write_json_atomic(UI_FILE, data)
    return data


def read_ui() -> Optional[dict]:
    try:
        data = json.loads(UI_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("url"):
        return None
    return data


def remove_ui() -> None:
    try:
        UI_FILE.unlink()
    except OSError:
        pass


def inject_runtime_config(html: bytes, backend_port: int) -> bytes:
    """index.html with the backend port this run actually uses.

    The production bundle is compiled once, with VITE_BACKEND_PORT baked in
    (7926 in a release). Whoever serves index.html knows the real port, so
    it tells the page here; src/utils/connection.ts prefers this value.
    """
    script = b'<script>window.__CRAFTBOT__={"backendPort":%d}</script>' % int(
        backend_port
    )
    lowered = html.lower()
    at = lowered.find(b"<head>")
    if at != -1:
        at += len(b"<head>")
    else:
        at = lowered.find(b"<script")
        if at == -1:
            at = 0
    return html[:at] + script + html[at:]


# ── loopback HTTP ───────────────────────────────────────────────────────────


def with_no_proxy(env: Dict[str, str]) -> Dict[str, str]:
    """Add the loopback names to NO_PROXY/no_proxy in `env` (in place).

    A corporate HTTP(S)_PROXY without NO_PROXY otherwise sends CraftBot's own
    localhost traffic (UI proxy, readiness checks, MCP servers, Agent Apps)
    to the proxy, which cannot reach this machine's loopback.
    """
    for key in ("NO_PROXY", "no_proxy"):
        current = [p.strip() for p in env.get(key, "").split(",") if p.strip()]
        for name in LOOPBACK_NAMES:
            if name not in current:
                current.append(name)
        env[key] = ",".join(current)
    return env


_opener: Optional[urllib.request.OpenerDirector] = None


def loopback_opener() -> urllib.request.OpenerDirector:
    """urllib opener that never uses a proxy (for loopback URLs only)."""
    global _opener
    if _opener is None:
        _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _opener


def http_answers(url: str, timeout: float = 2.0) -> bool:
    """True when a server answers `url` with anything below a 5xx."""
    try:
        with loopback_opener().open(url, timeout=timeout) as response:
            return response.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


# ── binding and ports ───────────────────────────────────────────────────────


def bind_host() -> str:
    return os.environ.get(BIND_HOST_ENV, "").strip() or "localhost"


def connect_host(bind: Optional[str] = None) -> str:
    """Host to reach a server bound to `bind` from this machine."""
    bind = (bind if bind is not None else bind_host()).strip().strip("[]")
    if bind in ("", "0.0.0.0", "localhost", "127.0.0.1", "::"):
        return "127.0.0.1"
    if bind == "::1":
        return "[::1]"
    return f"[{bind}]" if ":" in bind else bind


def _bind_addresses(host: str) -> List[Tuple[int, str]]:
    host = host.strip("[]")
    try:
        infos = socket.getaddrinfo(
            host, None, socket.AF_UNSPEC, socket.SOCK_STREAM, 0, socket.AI_PASSIVE
        )
    except OSError:
        return [(socket.AF_INET, "127.0.0.1")]
    seen: List[Tuple[int, str]] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        entry = (family, sockaddr[0])
        if family in (socket.AF_INET, socket.AF_INET6) and entry not in seen:
            seen.append(entry)
    return seen or [(socket.AF_INET, "127.0.0.1")]


def port_is_free(port: int, host: Optional[str] = None) -> bool:
    """True when nothing listens on `port` and it can be bound on `host`."""
    host = host or bind_host()
    # Something already answering on loopback means taken, even where the OS
    # would still let us bind a more specific address next to it (Windows).
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.3)
                if probe.connect_ex((address, int(port))) == 0:
                    return False
        except OSError:
            pass
    for family, address in _bind_addresses(host):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                if sys.platform == "win32":
                    sock.setsockopt(
                        socket.SOL_SOCKET,
                        getattr(socket, "SO_EXCLUSIVEADDRUSE", -5),
                        1,
                    )
                sock.bind((address, int(port)))
        except OSError:
            return False
    return True


def find_free_port_pair(
    frontend_port: int,
    backend_port: int,
    host: Optional[str] = None,
    attempts: int = 50,
) -> Optional[Tuple[int, int]]:
    """The next (frontend, backend) pair after the given one with both ports
    free, keeping the two ports' spacing. None if none is found."""
    gap = abs(int(backend_port) - int(frontend_port)) or 1
    step = gap + 1
    for i in range(1, attempts + 1):
        front = int(frontend_port) + i * step
        back = int(backend_port) + i * step
        if back > 65535 or front > 65535:
            break
        if port_is_free(front, host) and port_is_free(back, host):
            return front, back
    return None


# ── which CraftBot is this? ─────────────────────────────────────────────────

_CRAFTBOT_SCRIPTS = ("run.py", "main.py", "craftbot.py")


def _is_craftbot_tree(directory: str) -> bool:
    try:
        return bool(directory) and os.path.isfile(
            os.path.join(directory, "craftbot.py")
        )
    except OSError:
        return False


def _craftbot_tree_of(proc) -> Optional[str]:
    """The CraftBot source tree a psutil process runs from, or None."""
    try:
        cmdline = proc.cmdline() or []
    except Exception:
        return None
    for token in cmdline:
        if token.endswith(_CRAFTBOT_SCRIPTS):
            if not os.path.isabs(token):
                # `python run.py` is relative to THAT process's directory,
                # never to ours: resolving it against our own cwd would make
                # every CraftBot started that way look like this checkout.
                try:
                    token = os.path.join(proc.cwd(), token)
                except Exception:
                    continue
            directory = os.path.dirname(os.path.abspath(token))
            if _is_craftbot_tree(directory):
                return directory
    if "-m" in cmdline:
        module = cmdline[cmdline.index("-m") + 1 : cmdline.index("-m") + 2]
        if module and module[0] in ("app.main", "app"):
            try:
                cwd = proc.cwd()
            except Exception:
                return None
            if _is_craftbot_tree(cwd):
                return cwd
    return None


def _user_data_root_for(env: Dict[str, str]) -> Path:
    """app.paths._user_data_root() as seen with another process's env."""
    if sys.platform == "win32":
        root = env.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        return Path(root) / "CraftBot"
    if sys.platform == "darwin":
        return Path(os.path.expanduser("~/Library/Application Support/CraftBot"))
    root = env.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(root) / "craftbot"


def _state_root_of(tree: str, env: Dict[str, str]) -> Path:
    """app.paths._resolve_state_root() for a process running from `tree`
    with environment `env`."""
    override = (env.get("CRAFTBOT_HOME") or "").strip()
    if override:
        return Path(override).expanduser()
    root = Path(tree)
    managed = (root / paths.MANAGED_MARKER).is_file()
    if (
        not managed
        and (root / "install.py").is_file()
        and (root / "requirements.txt").is_file()
    ):
        return root
    return _user_data_root_for(env)


def _same_path(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
            os.path.realpath(b)
        )
    except OSError:
        return False


def belongs_to_this_home(pid: int, recorded_pids: Iterable[int] = ()) -> bool:
    """True if the CraftBot process `pid` was started for THIS state root.

    Either it, or one of its ancestors, is the run.py named by our pid file
    (or by `recorded_pids`), or it runs from a CraftBot tree whose state root,
    resolved with its own environment, is ours. A CraftBot from another
    checkout or another CRAFTBOT_HOME is a different installation, never a
    leftover of this one: it is left running and treated like any other
    program holding the port. Anything that cannot be inspected is not ours.
    """
    try:
        import psutil
    except ImportError:
        return False
    try:
        proc = psutil.Process(int(pid))
        chain = [proc] + proc.parents()
    except Exception:
        return False

    owners = {int(p) for p in recorded_pids if p}
    current = live_pid(read_pid_record())
    if current:
        owners.add(current)
    owners.discard(os.getpid())
    if owners and any(p.pid in owners for p in chain):
        return True

    tree = _craftbot_tree_of(proc)
    if tree is None:
        return False
    try:
        env = proc.environ()
    except Exception:
        return False
    return _same_path(_state_root_of(tree, env), paths.STATE_ROOT)


__all__ = [
    "PID_FILE",
    "UI_FILE",
    "LOG_FILE",
    "BIND_HOST_ENV",
    "belongs_to_this_home",
    "bind_host",
    "connect_host",
    "display_url",
    "find_free_port_pair",
    "http_answers",
    "inject_runtime_config",
    "live_pid",
    "loopback_opener",
    "port_is_free",
    "process_start_time",
    "read_pid_record",
    "read_ui",
    "remove_pid",
    "remove_ui",
    "with_no_proxy",
    "write_pid",
    "write_ui",
]
