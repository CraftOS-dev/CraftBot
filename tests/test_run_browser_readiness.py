"""Exercise the real browser startup sequence without bootstrapping an agent."""

import ast
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import instance

SOURCE = Path(__file__).resolve().parents[1] / "run.py"
FRONTEND_URL = "http://localhost:8925"
BACKEND_URL = "http://localhost:8926"


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Response:
    def __init__(self, body=b'<div id="root"></div>', status=200):
        self.body = body
        self.status = status

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run_py(monkeypatch, outcomes):
    calls = []

    def open_url(url, timeout):
        outcome = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(
        instance, "loopback_opener", lambda: SimpleNamespace(open=open_url)
    )
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("wait_for_frontend_silent", "wait_for_backend_silent")
    ]
    namespace = {
        "time": _FakeClock(),
        "_instance": instance,
        "_local_url": lambda port: f"http://localhost:{port}",
        "FRONTEND_PORT": 8925,
        "BACKEND_PORT": 8926,
    }
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"),
        namespace,
    )
    return SimpleNamespace(**namespace), calls


@pytest.mark.parametrize("code", [400, 403, 404, 500, 503])
def test_frontend_http_error_is_not_ready(monkeypatch, code):
    error = urllib.error.HTTPError(FRONTEND_URL, code, "error", None, None)
    run, calls = _run_py(monkeypatch, [error])
    assert run.wait_for_frontend_silent(2) is False
    assert set(calls) == {FRONTEND_URL}


@pytest.mark.parametrize(
    "response", [_Response(b"Directory listing"), _Response(status=302)]
)
def test_frontend_requires_success_and_react_root(monkeypatch, response):
    run, _ = _run_py(monkeypatch, [response])
    assert run.wait_for_frontend_silent(2) is False


def test_frontend_retries_until_ui_is_served(monkeypatch):
    run, calls = _run_py(monkeypatch, [urllib.error.URLError("refused"), _Response()])
    assert run.wait_for_frontend_silent(2) is True
    assert calls == [FRONTEND_URL, FRONTEND_URL]


@pytest.mark.parametrize("code, expected", [(404, True), (500, False)])
def test_backend_response_semantics_are_preserved(monkeypatch, code, expected):
    error = urllib.error.HTTPError(BACKEND_URL, code, "error", None, None)
    run, calls = _run_py(monkeypatch, [error])
    assert run.wait_for_backend_silent(2) is expected
    assert set(calls) == {BACKEND_URL}


def _startup_sequence():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Assign) and any(
            getattr(target, "id", None) == "frontend_ready" for target in first.targets
        ):
            return ast.Module(body=node.body, type_ignores=[])
    raise AssertionError("Browser startup sequence not found")


def _run_startup(
    frontend_results, *, no_open_browser=False, frontend_alive=True, agent_state="ready"
):
    events = []
    results = iter(frontend_results)

    def frontend_wait(timeout):
        ready = next(results)
        events.append(("frontend", ready))
        return ready

    def fail_agent(*args):
        raise SystemExit(1)

    namespace = {
        "wait_for_frontend_silent": frontend_wait,
        "_wait_for_agent_ready": lambda proc: (
            events.append(("agent", agent_state)) or agent_state
        ),
        "_wait_for_backend_port": lambda proc: "ready",
        "_fail_agent_exited": fail_agent,
        "_adopt_port_listeners": lambda *ports: events.append(("adopt", ports)),
        "frontend_process": SimpleNamespace(poll=lambda: None if frontend_alive else 1),
        "agent_process": SimpleNamespace(wait=lambda: events.append(("wait", True))),
        "_instance": SimpleNamespace(
            write_ui=lambda *ports: events.append(("publish", ports))
        ),
        "print_ready_banner": lambda url: events.append(("banner", url)),
        "webbrowser": SimpleNamespace(open=lambda url: events.append(("open", url))),
        "time": _FakeClock(),
        "sys": sys,
        "FRONTEND_PORT": 8925,
        "BACKEND_PORT": 8926,
        "FRONTEND_URL": FRONTEND_URL,
        "BIND_HOST": "localhost",
        "no_open_browser": no_open_browser,
        "use_conda": False,
        "env_name": None,
    }
    exec(compile(_startup_sequence(), str(SOURCE), "exec"), namespace)
    return events


def test_frontend_not_ready_does_not_publish_announce_or_open(capsys):
    events = _run_startup([False, False])
    assert not [event for event in events if event[0] in ("publish", "banner", "open")]
    assert all(8925 not in ports for kind, ports in events if kind == "adopt")
    assert "not responding" in capsys.readouterr().out


def test_ready_frontend_publishes_dynamic_ports_and_opens():
    events = _run_startup([True])
    assert ("publish", (8925, 8926)) in events
    assert ("banner", FRONTEND_URL) in events
    assert ("open", FRONTEND_URL) in events
    assert [event for event in events if event[0] == "frontend"] == [("frontend", True)]


def test_no_open_browser_still_announces_ready_ui():
    events = _run_startup([True], no_open_browser=True)
    assert ("banner", FRONTEND_URL) in events
    assert not [event for event in events if event[0] == "open"]


def test_frontend_crash_does_not_announce_success():
    with pytest.raises(SystemExit):
        _run_startup([True], frontend_alive=False)


def test_agent_crash_does_not_announce_success():
    with pytest.raises(SystemExit):
        _run_startup([True], agent_state="exited")
