# -*- coding: utf-8 -*-
"""app/instance.py and app/console.py: what lets every launcher find, reach
and stop the running CraftBot, and nothing else.

The ownership tests start real processes from throwaway CraftBot trees: a
CraftBot from another checkout or another CRAFTBOT_HOME must never look like
this installation's own, because run.py and `craftbot.py stop` kill what is
theirs.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import instance, paths

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── ports ─────────────────────────────────────────────────────────────────


def _listening_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock


def test_a_port_with_a_listener_is_not_free():
    with _listening_socket() as sock:
        port = sock.getsockname()[1]
        assert instance.port_is_free(port, "localhost") is False


def test_free_pair_skips_a_busy_port_and_keeps_the_spacing():
    with _listening_socket() as busy:
        port = busy.getsockname()[1]
        # Ask for the pair just below the busy port so the first candidate
        # collides with it.
        pair = instance.find_free_port_pair(port - 3, port - 2, "localhost")
    assert pair is not None
    front, back = pair
    assert back - front == 1
    assert port not in pair
    assert front > port - 3


# ── loopback plumbing ─────────────────────────────────────────────────────


def test_no_proxy_gains_the_loopback_names_once_and_keeps_existing_entries():
    env = {"NO_PROXY": "corp.example", "no_proxy": "localhost"}
    instance.with_no_proxy(env)
    instance.with_no_proxy(env)
    assert env["NO_PROXY"].split(",") == [
        "corp.example",
        "localhost",
        "127.0.0.1",
        "::1",
    ]
    assert env["no_proxy"].split(",") == ["localhost", "127.0.0.1", "::1"]


def test_loopback_opener_ignores_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:9")
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(instance, "_opener", None)
    import http.server
    import threading

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        assert instance.http_answers(f"http://127.0.0.1:{port}/") is True
    finally:
        server.shutdown()
        server.server_close()


def test_bind_host_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv(instance.BIND_HOST_ENV, raising=False)
    assert instance.bind_host() == "localhost"
    monkeypatch.setenv(instance.BIND_HOST_ENV, "0.0.0.0")
    assert instance.bind_host() == "0.0.0.0"
    assert instance.connect_host("0.0.0.0") == "127.0.0.1"
    assert instance.connect_host("::1") == "[::1]"
    assert instance.display_url(7927) == "http://localhost:7927"


def test_runtime_config_is_injected_before_the_bundle_runs():
    html = b'<!doctype html><html><head><script type="module" src="/a.js"></script></head></html>'
    out = instance.inject_runtime_config(html, 8123)
    script = b'<script>window.__CRAFTBOT__={"backendPort":8123}</script>'
    assert out.index(script) < out.index(b'<script type="module"')
    assert out.replace(script, b"") == html


# ── pid file and ui.json ──────────────────────────────────────────────────


def test_pid_record_round_trip_and_guarded_removal(tmp_path, monkeypatch):
    monkeypatch.setattr(instance, "PID_FILE", tmp_path / "craftbot.pid")
    instance.write_pid()
    record = instance.read_pid_record()
    assert record is not None and record[0] == os.getpid()
    assert instance.live_pid(record) == os.getpid()
    # A record from a pid that has since been reused is not live.
    assert instance.live_pid((os.getpid(), record[1] - 3600)) is None
    instance.remove_pid(only_if=os.getpid() + 1)
    assert instance.PID_FILE.exists()
    instance.remove_pid(only_if=os.getpid())
    assert not instance.PID_FILE.exists()


def test_ui_file_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(instance, "UI_FILE", tmp_path / "ui.json")
    assert instance.read_ui() is None
    instance.write_ui(7927, 7928)
    assert instance.read_ui() == {
        "url": "http://localhost:7927",
        "frontend_port": 7927,
        "backend_port": 7928,
        "edition": "browser",
    }
    instance.remove_ui()
    assert instance.read_ui() is None


def test_terminal_edition_records_its_backend(tmp_path, monkeypatch):
    # No web UI: the record names the backend, which `craftbot.py tui` attaches to.
    monkeypatch.setattr(instance, "UI_FILE", tmp_path / "ui.json")
    instance.write_ui(None, 7930, edition="terminal")
    assert instance.read_ui() == {
        "url": "http://localhost:7930",
        "frontend_port": None,
        "backend_port": 7930,
        "edition": "terminal",
    }


# ── whose CraftBot is it? ─────────────────────────────────────────────────


def _fake_checkout(root: Path) -> Path:
    """A directory that looks like a CraftBot dev checkout, with a run.py
    that just waits."""
    root.mkdir(parents=True)
    for name in ("craftbot.py", "install.py", "requirements.txt"):
        (root / name).write_text("", encoding="utf-8")
    (root / "run.py").write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
    return root


@pytest.fixture
def start_craftbot():
    started = []

    def start(tree: Path, home=None):
        env = dict(os.environ)
        env.pop("CRAFTBOT_HOME", None)
        if home is not None:
            env["CRAFTBOT_HOME"] = str(home)
        # Relative script path, as `python run.py` from a terminal gives it.
        proc = subprocess.Popen([sys.executable, "run.py"], cwd=str(tree), env=env)
        started.append(proc)
        deadline = time.time() + 20
        import psutil

        while time.time() < deadline:
            try:
                if "run.py" in " ".join(psutil.Process(proc.pid).cmdline()):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        return proc

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_craftbot_from_another_checkout_is_not_ours(
    tmp_path, monkeypatch, start_craftbot
):
    pytest.importorskip("psutil")
    # Stand in this repository, the dangerous case: resolving the other
    # process's relative "run.py" against OUR cwd would wrongly make it ours.
    # Set explicitly, because importing run.py elsewhere in the suite moves
    # the cwd into STATE_ROOT.
    monkeypatch.chdir(REPO_ROOT)
    other = start_craftbot(_fake_checkout(tmp_path / "other-checkout"))
    assert Path(os.getcwd()).resolve() == REPO_ROOT
    assert instance.belongs_to_this_home(other.pid) is False


def test_craftbot_with_another_home_is_not_ours(tmp_path, start_craftbot):
    pytest.importorskip("psutil")
    other = start_craftbot(
        _fake_checkout(tmp_path / "checkout"), home=tmp_path / "another-home"
    )
    assert instance.belongs_to_this_home(other.pid) is False


def test_craftbot_with_this_home_is_ours(tmp_path, start_craftbot):
    pytest.importorskip("psutil")
    ours = start_craftbot(_fake_checkout(tmp_path / "checkout"), home=paths.STATE_ROOT)
    assert instance.belongs_to_this_home(ours.pid) is True


def test_a_process_named_by_our_pid_file_is_ours(tmp_path, monkeypatch, start_craftbot):
    pytest.importorskip("psutil")
    monkeypatch.setattr(instance, "PID_FILE", tmp_path / "craftbot.pid")
    proc = start_craftbot(_fake_checkout(tmp_path / "elsewhere"), home=tmp_path / "x")
    assert instance.belongs_to_this_home(proc.pid) is False
    instance.write_pid(proc.pid)
    assert instance.belongs_to_this_home(proc.pid) is True


# ── windowless launches ───────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="pythonw is Windows-only")
def test_a_launch_without_stdout_writes_to_the_craftbot_log(tmp_path):
    # As run.py does it, for a state folder that does not exist yet.
    home = tmp_path / "not created yet"
    env = dict(os.environ, CRAFTBOT_HOME=str(home))
    code = (
        "import sys\n"
        "sys.stdout = None\n"
        "sys.stderr = None\n"
        "from app import instance\n"
        "from app.console import configure_console\n"
        "configure_console(log_file=str(instance.LOG_FILE))\n"
        "print('hello from a windowless start')\n"
        "sys.stderr.write('and its errors\\n')\n"
        "assert sys.stdout.isatty() is False\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT), env=env, timeout=60
    )
    assert result.returncode == 0
    log = (home / "craftbot.log").read_text(encoding="utf-8")
    assert "hello from a windowless start" in log
    assert "and its errors" in log
