"""Process cleanup kills only what CraftBot started (app/process_ledger.py).

Pins the two over-broad kills this replaced:
  * `pkill -f cloudflared` / `Stop-Process -Name cloudflared` took down every
    cloudflared on the machine, including tunnels CraftBot never started.
  * `f":{port}" in netstat_line` matched :3100 against :31000, and any
    listener on "our" port was killed whether or not we launched it.

Real processes, real sockets — no mocks of the OS layer.
"""

import socket
import subprocess
import sys
import time

import psutil
import pytest

from app.process_ledger import ProcessLedger, ROLE_TUNNEL, listening_pids

# A child that listens on the port given as argv[1] and sleeps.
_LISTENER = (
    "import socket,sys,time\n"
    "s=socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "time.sleep(120)\n"
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn_listener(port: int) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-c", _LISTENER, str(port)])
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.pid in listening_pids(port):
            return proc
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"listener on {port} never came up")


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


@pytest.fixture
def procs():
    started = []
    yield started
    for p in started:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)


def _gone(proc: subprocess.Popen) -> bool:
    try:
        proc.wait(timeout=10)
        return True
    except subprocess.TimeoutExpired:
        return False


def test_listening_pids_matches_exact_port_only(procs):
    port = _free_port()
    proc = _spawn_listener(port)
    procs.append(proc)
    assert proc.pid in listening_pids(port)
    # A port whose digits contain ours (and one that is its prefix) must
    # not match — the old substring check would have hit both.
    for other in (port * 10 % 65536 or 1, int(str(port)[:-1] or 1)):
        if other != port:
            assert proc.pid not in listening_pids(other)


def test_foreign_listener_on_our_port_is_left_alone(tmp_path, procs):
    port = _free_port()
    foreign = _spawn_listener(port)  # started, but never recorded
    procs.append(foreign)
    ledger = ProcessLedger(tmp_path / "ledger.json")

    assert ledger.kill_port_listeners(port) is False
    assert foreign.poll() is None, "a process CraftBot did not start was killed"


def test_owned_listener_is_killed(tmp_path, procs):
    port = _free_port()
    ours = _spawn_listener(port)
    procs.append(ours)
    ledger = ProcessLedger(tmp_path / "ledger.json")
    ledger.register(ours.pid, "agent_app", owner="p1")

    assert ledger.kill_port_listeners(port) is True
    assert _gone(ours)
    assert ledger.entries() == []


def test_only_recorded_tunnel_is_reaped(tmp_path, procs):
    ours, theirs = _spawn_sleeper(), _spawn_sleeper()
    procs += [ours, theirs]
    path = tmp_path / "ledger.json"
    ProcessLedger(path).register(ours.pid, ROLE_TUNNEL, owner="p1")

    # A fresh ledger (= after a CraftBot restart) reaps from the file.
    assert ProcessLedger(path).reap(role=ROLE_TUNNEL) == 1
    assert _gone(ours)
    assert theirs.poll() is None, "an unrelated tunnel was killed"


def test_recycled_pid_is_never_killed(tmp_path, procs):
    victim = _spawn_sleeper()
    procs.append(victim)
    path = tmp_path / "ledger.json"
    ledger = ProcessLedger(path)
    entry = ledger.register(victim.pid, ROLE_TUNNEL)
    # Same pid, different start time: what a recycled pid looks like.
    entry.create_time -= 3600
    ledger._save()

    assert ProcessLedger(path).kill_pid(victim.pid) is False
    assert victim.poll() is None, "a recycled pid was treated as ours"


def test_descendant_of_owned_shell_is_owned(tmp_path, procs):
    port = _free_port()
    # shell-style parent: a python that spawns the real listener and waits.
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; subprocess.run([sys.executable,'-c',"
            f"{_LISTENER!r},'{port}'])",
        ]
    )
    procs.append(parent)
    deadline = time.time() + 15
    while time.time() < deadline and not listening_pids(port):
        time.sleep(0.1)
    listener_pid = listening_pids(port)[0]
    assert listener_pid != parent.pid

    ledger = ProcessLedger(tmp_path / "ledger.json")
    ledger.register(parent.pid, "agent_app")
    assert ledger.kill_port_listeners(port) is True
    assert _gone(parent)
    assert not psutil.pid_exists(listener_pid) or listener_pid not in listening_pids(port)


def test_adopt_skips_a_foreign_listener(tmp_path, procs):
    # A service that already held the port answers our readiness check; it
    # must not become "ours" (the next run would kill it).
    port = _free_port()
    foreign = _spawn_listener(port)
    procs.append(foreign)
    ledger = ProcessLedger(tmp_path / "ledger.json")
    assert ledger.adopt_listeners(port, "launcher") == []
    assert ledger.kill_port_listeners(port) is False
    assert foreign.poll() is None


def test_adopted_server_survives_its_shell_dying(tmp_path, procs):
    port = _free_port()
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
            f"{_LISTENER!r},'{port}']); import time; time.sleep(120)",
        ]
    )
    procs.append(parent)
    deadline = time.time() + 15
    while time.time() < deadline and not listening_pids(port):
        time.sleep(0.1)
    server_pid = listening_pids(port)[0]

    ledger = ProcessLedger(tmp_path / "ledger.json")
    ledger.register(parent.pid, "agent_app")
    assert [e.pid for e in ledger.adopt_listeners(port, "agent_app")] == [server_pid]

    parent.kill()  # the shell dies; the server is orphaned
    parent.wait(timeout=10)
    assert ledger.kill_port_listeners(port) is True
    deadline = time.time() + 10
    while time.time() < deadline and psutil.pid_exists(server_pid):
        time.sleep(0.1)
    assert not psutil.pid_exists(server_pid)
