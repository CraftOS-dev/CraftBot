# -*- coding: utf-8 -*-
"""run.py's browser-mode readiness: a 404 from the UI is not ready (#488)."""

from __future__ import annotations

import ast
import sys
import typing
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_URL = "http://localhost:7925"
BACKEND_URL = "http://localhost:7926"

_FUNCTIONS = (
    "wait_for_frontend_silent",
    "wait_for_backend_silent",
    "print_ready_banner",
    "_announce_startup",
)


class _FakeClock:
    """Stands in for run.py's time module: sleeping advances time instantly."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run_py(clock=None, opened=None):
    """run.py's real readiness functions, compiled without importing run.py.

    Importing run.py would bootstrap the developer's state directory (see
    tests/test_state_sync.py); only the functions themselves are taken from
    its source.
    """
    source = (REPO_ROOT / "run.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    marker = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "CRAFTBOT_READY_MARKER" for t in n.targets)
    ]
    nodes = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in _FUNCTIONS
    ]
    assert len(marker) == 1 and nodes
    namespace = {
        "urllib": urllib,
        "time": clock or _FakeClock(),
        "sys": sys,
        "webbrowser": SimpleNamespace(
            open=(opened if opened is not None else []).append
        ),
        "Optional": typing.Optional,
        "FRONTEND_URL": FRONTEND_URL,
        "BACKEND_URL": BACKEND_URL,
        "ORANGE": "",
        "GREEN": "",
        "RESET": "",
    }
    module = ast.Module(body=marker + nodes, type_ignores=[])
    exec(compile(module, str(REPO_ROOT / "run.py"), "exec"), namespace)
    return SimpleNamespace(**namespace)


def _fake_urlopen(monkeypatch, *outcomes):
    """Patch urlopen to play `outcomes` in order (the last one repeats)."""
    calls = []

    def fake(url, timeout=None):
        outcome = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def _http_error(url, code):
    return urllib.error.HTTPError(url, code, "err", None, None)


# ── Frontend wait ────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", [404, 403, 400, 500])
def test_frontend_error_response_is_not_ready(monkeypatch, code):
    clock = _FakeClock()
    run = _run_py(clock)
    calls = _fake_urlopen(monkeypatch, _http_error(FRONTEND_URL, code))

    assert run.wait_for_frontend_silent(timeout=5) is False
    assert set(calls) == {FRONTEND_URL}
    assert sum(clock.sleeps) <= 5.5  # bounded by the timeout


def test_frontend_is_ready_once_it_serves_after_startup_failures(monkeypatch):
    run = _run_py()
    calls = _fake_urlopen(
        monkeypatch,
        urllib.error.URLError("connection refused"),
        _http_error(FRONTEND_URL, 404),
        _FakeResponse(),
    )

    assert run.wait_for_frontend_silent(timeout=30) is True
    assert len(calls) == 3


# ── Backend wait: unchanged — any answer below 500 means it is listening ──


def test_backend_404_still_means_the_server_is_responding(monkeypatch):
    run = _run_py()
    _fake_urlopen(monkeypatch, _http_error(BACKEND_URL, 404))

    assert run.wait_for_backend_silent(timeout=60) is True


def test_backend_500_is_not_responding(monkeypatch):
    run = _run_py()
    _fake_urlopen(monkeypatch, _http_error(BACKEND_URL, 500))

    assert run.wait_for_backend_silent(timeout=5) is False


# ── Ready banner ─────────────────────────────────────────────────────────


def test_frontend_not_ready_fallback_does_not_print_ready_banner(capsys):
    opened = []
    run = _run_py(opened=opened)

    run._announce_startup(
        frontend_ready=False,
        backend_ready=True,
        frontend_alive=True,
        backend_alive=True,
        open_browser=True,
    )

    output = capsys.readouterr().out
    assert run.CRAFTBOT_READY_MARKER not in output
    assert f"not responding at {FRONTEND_URL}" in output
    assert opened == []


def test_ready_prints_banner_and_opens_browser(capsys):
    opened = []
    run = _run_py(opened=opened)

    run._announce_startup(True, True, True, True, open_browser=True)

    assert run.CRAFTBOT_READY_MARKER in capsys.readouterr().out
    assert opened == [FRONTEND_URL]


def test_slow_backend_still_proceeds_with_banner(capsys):
    # Existing behaviour: the UI is up, only the agent is slow.
    opened = []
    run = _run_py(opened=opened)

    run._announce_startup(True, False, True, True, open_browser=True)

    assert run.CRAFTBOT_READY_MARKER in capsys.readouterr().out
    assert opened == [FRONTEND_URL]


def test_no_open_browser_prints_banner_without_opening(capsys):
    opened = []
    run = _run_py(opened=opened)

    run._announce_startup(True, True, True, True, open_browser=False)

    assert run.CRAFTBOT_READY_MARKER in capsys.readouterr().out
    assert opened == []


# ── __main__ wiring ──────────────────────────────────────────────────────


def _main_wiring_problems(source: str) -> list:
    """Ways run.py's __main__ no longer routes startup through the helpers.

    The tests above only exercise the helpers; this checks that __main__
    actually uses them, without importing (and so bootstrapping) run.py.
    """
    tree = ast.parse(source)
    mains = [
        n
        for n in tree.body
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and getattr(n.test.left, "id", None) == "__name__"
    ]
    if len(mains) != 1:
        return ["run.py has no single `if __name__ == '__main__':` block"]

    def called(node):
        return isinstance(node, ast.Call) and getattr(node.func, "id", None)

    assigned = {"frontend_ready": [], "backend_ready": []}
    announce = []
    for node in ast.walk(mains[0]):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", None) in assigned:
                    assigned[target.id].append(node)
        elif called(node) == "_announce_startup":
            announce.append(node)
    for name in assigned:  # ast.walk is breadth-first; restore source order
        assigned[name].sort(key=lambda n: n.lineno)

    problems = []
    frontend = assigned["frontend_ready"]
    if not frontend or any(
        called(n.value) != "wait_for_frontend_silent" for n in frontend
    ):
        problems.append(
            "frontend_ready must only ever be set from wait_for_frontend_silent(...)"
            " — an inline probe is how a 404 got counted as ready (#488)"
        )
    backend = assigned["backend_ready"]
    if not backend or called(backend[0].value) != "wait_for_backend_silent":
        problems.append(
            "backend_ready must first be set from wait_for_backend_silent(...)"
        )
    if len(announce) != 1:
        problems.append("__main__ must call _announce_startup(...) exactly once")
    else:
        call = announce[0]
        args = {k.arg: k.value for k in call.keywords}
        for i, name in enumerate(("frontend_ready", "backend_ready")):
            arg = call.args[i] if len(call.args) > i else args.get(name)
            if getattr(arg, "id", None) != name:
                problems.append(f"_announce_startup must be passed {name} as {name}")
    return problems


def test_main_routes_startup_through_the_readiness_helpers():
    source = (REPO_ROOT / "run.py").read_text(encoding="utf-8")

    assert _main_wiring_problems(source) == []


# ── __main__ startup sequence: a frontend that was slow gets a second look ──


def _startup_sequence(source: str) -> ast.Module:
    """__main__'s statements from the first readiness wait to the announcement."""

    def is_announce(stmt):
        return (
            isinstance(stmt, ast.Expr)
            and getattr(getattr(stmt.value, "func", None), "id", None)
            == "_announce_startup"
        )

    def is_first_wait(stmt):
        return isinstance(stmt, ast.Assign) and any(
            getattr(t, "id", None) == "frontend_ready" for t in stmt.targets
        )

    for node in ast.walk(ast.parse(source)):
        for field in ("body", "orelse"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            ends = [i for i, s in enumerate(stmts) if is_announce(s)]
            starts = [i for i, s in enumerate(stmts) if is_first_wait(s)]
            if ends and starts and starts[0] < ends[0]:
                return ast.Module(body=stmts[starts[0] : ends[0] + 1], type_ignores=[])
    raise AssertionError("run.py's __main__ startup sequence not found")


class _Alive:
    returncode = None

    def poll(self):
        return None


def _run_startup(frontend_results, source=None):
    """Run run.py's real startup sequence against scripted readiness waits."""
    source = source or (REPO_ROOT / "run.py").read_text(encoding="utf-8")
    opened = []
    run = _run_py(opened=opened)
    log = []
    frontend_results = iter(frontend_results)

    def wait_for_frontend_silent(timeout=30):
        ready = next(frontend_results)
        log.append(("frontend", ready))
        return ready

    def wait_for_backend_silent(timeout=60):
        log.append(("backend", True))
        return True

    def announce(*args, **kwargs):
        log.append(("announce", args[0]))
        run._announce_startup(*args, **kwargs)

    namespace = {
        "wait_for_frontend_silent": wait_for_frontend_silent,
        "wait_for_backend_silent": wait_for_backend_silent,
        "_adopt_port_listeners": lambda *ports: log.append(("adopt", ports)),
        "_wait_for_agent_ready": lambda process: log.append(("agent", True)) or True,
        "_announce_startup": announce,
        "time": _FakeClock(),
        "frontend_process": _Alive(),
        "agent_process": _Alive(),
        "FRONTEND_PORT": 7925,
        "BACKEND_PORT": 7926,
        "no_open_browser": False,
        "env_name": None,
        "use_conda": False,
    }
    exec(
        compile(_startup_sequence(source), str(REPO_ROOT / "run.py"), "exec"), namespace
    )
    return run, log, opened


def test_frontend_ready_during_agent_startup_is_rechecked_and_opened(capsys):
    run, log, opened = _run_startup([False, True])

    assert log == [
        ("frontend", False),
        ("backend", True),
        ("adopt", (7926,)),  # the frontend port is not adopted while it is down
        ("agent", True),
        ("frontend", True),  # second look, only after the agent finished
        ("adopt", (7925,)),
        ("announce", True),
    ]
    assert run.CRAFTBOT_READY_MARKER in capsys.readouterr().out
    assert opened == [FRONTEND_URL]


def test_frontend_still_down_after_agent_startup_is_not_announced(capsys):
    run, log, opened = _run_startup([False, False])

    assert [e for e in log if e[0] == "frontend"] == [("frontend", False)] * 2
    assert all(7925 not in e[1] for e in log if e[0] == "adopt")
    assert ("announce", False) in log
    output = capsys.readouterr().out
    assert run.CRAFTBOT_READY_MARKER not in output
    assert f"not responding at {FRONTEND_URL}" in output
    assert opened == []


def test_frontend_ready_first_time_is_not_waited_for_again(capsys):
    run, log, opened = _run_startup([True])  # a second call would raise

    assert [e for e in log if e[0] == "frontend"] == [("frontend", True)]
    assert ("adopt", (7925, 7926)) in log
    assert opened == [FRONTEND_URL]
