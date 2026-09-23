# -*- coding: utf-8 -*-
"""One launch at a time per Agent App.

Regression cover for the 2026-09-02 17:06 incident (opentetris 949f0cad): the
watchdog restarted the crashed app while the agent's own relaunch was already
in flight, both raced for :3105, and the loser reported

    A2App adapter failed to bind :3105: [Errno 10048] only one usage of each
    socket address (protocol/network address/port) is normally permitted

...so the rounded-blocks edit sat on disk undeployed and the user was never
told why.
"""

import asyncio
import socket
import types

import pytest

from app.agent_app.manager import AgentAppManager


@pytest.fixture
def manager(tmp_path):
    return AgentAppManager(workspace_root=tmp_path)


def _project(**over):
    p = types.SimpleNamespace(
        id="949f0cad",
        name="opentetris",
        path="/tmp/opentetris",
        port=3105,
        internal_port=3106,
        process=None,
        project_type="external",
        bridge_token="t",
        status="running",
    )
    for k, v in over.items():
        setattr(p, k, v)
    return p


class TestLaunchLock:
    def test_the_lock_is_per_project_and_stable(self, manager):
        assert manager._launch_lock("a") is manager._launch_lock("a")
        assert manager._launch_lock("a") is not manager._launch_lock("b")

    def test_two_launches_of_one_project_do_not_overlap(self, manager, monkeypatch):
        # The actual race: without the lock both bodies interleave and both
        # drive the pipeline over the same ports.
        overlap = {"peak": 0, "now": 0}

        async def slow_launch(project):
            overlap["now"] += 1
            overlap["peak"] = max(overlap["peak"], overlap["now"])
            await asyncio.sleep(0.05)
            overlap["now"] -= 1
            return {"status": "success"}

        monkeypatch.setattr(manager, "_launch_native_locked", slow_launch)
        project = _project()

        async def race():
            await asyncio.gather(
                manager._launch_native(project), manager._launch_native(project)
            )

        asyncio.run(race())
        assert overlap["peak"] == 1

    def test_distinct_projects_still_launch_concurrently(self, manager, monkeypatch):
        # Serializing per project must not serialize the whole workspace.
        started = []

        async def slow_launch(project):
            started.append(project.id)
            await asyncio.sleep(0.05)
            return {"status": "success"}

        monkeypatch.setattr(manager, "_launch_native_locked", slow_launch)

        async def race():
            await asyncio.gather(
                manager._launch_native(_project(id="a")),
                manager._launch_native(_project(id="b")),
            )

        asyncio.run(race())
        assert sorted(started) == ["a", "b"]


class TestWatchdogRestart:
    def test_it_does_nothing_when_the_app_came_back_while_we_waited(
        self, manager, monkeypatch
    ):
        # The exact interleaving: the agent's relaunch fixed it during the
        # watchdog's retry delay. Restarting anyway would kill that app.
        monkeypatch.setattr(manager, "_project_is_dead", lambda _p: False)

        async def boom(_project):
            raise AssertionError("must not restart a healthy app")

        monkeypatch.setattr(manager, "_run_external_pipeline", boom)
        assert asyncio.run(manager._watchdog_restart(_project())) is True

    def test_it_restarts_an_app_that_is_still_dead(self, manager, monkeypatch):
        monkeypatch.setattr(manager, "_project_is_dead", lambda _p: True)
        calls = []

        async def pipeline(project):
            calls.append(project.id)
            return {"status": "success", "process": object()}

        monkeypatch.setattr(manager, "_run_external_pipeline", pipeline)
        assert asyncio.run(manager._watchdog_restart(_project())) is True
        assert calls == ["949f0cad"]

    def test_a_failed_restart_reports_false(self, manager, monkeypatch):
        monkeypatch.setattr(manager, "_project_is_dead", lambda _p: True)

        async def pipeline(_project):
            return {"status": "error", "step": "adapter", "errors": ["10048"]}

        monkeypatch.setattr(manager, "_run_external_pipeline", pipeline)
        assert asyncio.run(manager._watchdog_restart(_project())) is False

    def test_it_waits_for_a_launch_already_in_flight(self, manager, monkeypatch):
        """The watchdog must not enter the pipeline while a launch is running."""
        order = []
        monkeypatch.setattr(manager, "_project_is_dead", lambda _p: True)

        async def pipeline(_project):
            order.append("watchdog")
            return {"status": "success", "process": object()}

        monkeypatch.setattr(manager, "_run_external_pipeline", pipeline)
        project = _project()

        async def holder():
            async with manager._launch_lock(project.id):
                await asyncio.sleep(0.05)
                order.append("agent-launch")

        async def race():
            await asyncio.gather(holder(), manager._watchdog_restart(project))

        asyncio.run(race())
        assert order == ["agent-launch", "watchdog"]


class TestLiveness:
    def test_a_dead_process_handle_is_dead(self, manager):
        p = _project(process=types.SimpleNamespace(poll=lambda: 1))
        assert manager._project_is_dead(p) is True

    def test_an_external_app_is_dead_when_its_internal_port_is_silent(self, manager):
        # The proxy keeps the PROJECT port answering, which is why the
        # internal port is the honest probe.
        p = _project(internal_port=59999)
        assert manager._project_is_dead(p) is True

    def test_a_live_external_app_is_not_dead(self, manager):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            live = s.getsockname()[1]
            p = _project(port=live, internal_port=live)
            assert manager._project_is_dead(p) is False


class TestPortAllocation:
    def test_a_bound_port_is_not_offered(self, manager):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            taken = s.getsockname()[1]
            assert manager._can_bind(taken) is False

    def test_a_free_port_is_bindable(self, manager):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            free = s.getsockname()[1]
        assert manager._can_bind(free) is True
