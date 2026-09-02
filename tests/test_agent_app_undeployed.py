# -*- coding: utf-8 -*-
"""Editing an Agent App's files is not shipping them.

Regression cover for the 2026-09-02 incident (brainstorm_graph f1eb1c85): two
rounds of edits ended with "Done — I made the suggestions more visible" and
"Yes — they should now show up automatically" and no agent_app_notify_ready
call at all, so the running app never changed while the user was told twice
that it had.
"""

import asyncio
import subprocess
import types
from pathlib import Path

import pytest

from app.agent_base import AgentBase


@pytest.fixture
def agent():
    """A bare AgentBase: none of the runtime is involved in this check.

    __init__ builds the whole runtime (LLM, action library, memory); none of
    it is involved in deciding whether a run left un-deployed edits behind.
    """
    a = AgentBase.__new__(AgentBase)
    a._lui_run_writes = {}
    return a


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "agent_app" / "brainstorm_graph_f1eb1c85"
    (root / "frontend" / "src" / "app").mkdir(parents=True)
    return types.SimpleNamespace(
        id="f1eb1c85",
        name="Brainstorm Graph",
        path=str(root),
        status="ready",
        project_type="native",
        url=None,
        backend_url=None,
        port=3100,
        app_runtime=None,
    )


@pytest.fixture
def wired(monkeypatch, agent, project):
    """agent + a session bound to `project` + a stubbed app manager."""
    session = types.SimpleNamespace(
        id="lui_f1eb1c85", agent_app_project_id=project.id, selected_skills=[]
    )
    agent.session_manager = types.SimpleNamespace(get=lambda _sid: session)
    manager = types.SimpleNamespace(
        get_project=lambda pid: project if pid == project.id else None
    )
    monkeypatch.setattr("app.agent_app.get_agent_app_manager", lambda: manager)
    return agent, session, project


def _act(name, **params):
    return (types.SimpleNamespace(name=name), params)


def _edit(project, rel="frontend/src/app/components/GraphView.tsx"):
    return _act("stream_edit", file_path=str(Path(project.path) / rel))


OK = {"status": "success"}


class TestUnshippedDetection:
    """Content against the baseline — not a guess from which actions ran."""

    def _shipped(self, project):
        """Stamp the baseline, i.e. pretend the tree was just promoted."""
        from app.agent_app.verify_scope import verify_store_dir, write_baseline

        write_baseline(Path(project.path), verify_store_dir(project))

    def test_a_tree_matching_the_baseline_is_shipped(self, agent, project):
        self._shipped(project)
        assert agent._unshipped_fingerprint(project) is None

    def test_any_edit_after_the_last_ship_shows_up(self, agent, project):
        self._shipped(project)
        (Path(project.path) / "frontend" / "src" / "app" / "x.ts").write_text("//e")
        assert agent._unshipped_fingerprint(project) is not None

    def test_an_edit_made_outside_the_action_layer_is_still_seen(self, agent, project):
        # The whole point of comparing content: an edit through run_shell
        # (sed -i, a python script) never touches a file-writing ACTION, so
        # no list of action names could ever have caught it.
        target = Path(project.path) / "frontend" / "src" / "app" / "App.tsx"
        target.write_text("const a = 1\n")
        self._shipped(project)
        subprocess.run(["sed", "-i", "s/1/2/", str(target)], check=True)
        assert agent._unshipped_fingerprint(project) is not None

    def test_shipping_again_clears_it(self, agent, project):
        self._shipped(project)
        (Path(project.path) / "frontend" / "src" / "app" / "y.ts").write_text("//e")
        assert agent._unshipped_fingerprint(project) is not None
        self._shipped(project)  # promote / live launch stamps a new baseline
        assert agent._unshipped_fingerprint(project) is None

    def test_an_app_that_never_shipped_is_not_warned_about(self, agent, project):
        # No baseline at all: an unfinished build belongs to the factory arc.
        assert agent._unshipped_fingerprint(project) is None


class TestUndeployedWarning:
    def _capture(self, monkeypatch, project, differs):
        said = []
        host = types.SimpleNamespace(
            announce_undeployed=lambda pid, name: said.append((pid, name))
        )
        monkeypatch.setattr("app.factory.host_craftbot.get_factory_host", lambda: host)
        monkeypatch.setattr(
            AgentBase,
            "_unshipped_fingerprint",
            staticmethod(lambda _p: "abc123" if differs else None),
        )
        return said

    def test_a_run_ending_with_unshipped_work_names_the_app(self, wired, monkeypatch):
        agent, session, project = wired
        said = self._capture(monkeypatch, project, differs=True)
        asyncio.run(agent._warn_if_undeployed(session))
        assert said == [(project.id, "Brainstorm Graph")]

    def test_a_shipped_run_says_nothing(self, wired, monkeypatch):
        agent, session, project = wired
        said = self._capture(monkeypatch, project, differs=False)
        asyncio.run(agent._warn_if_undeployed(session))
        assert said == []

    def test_a_session_with_no_project_says_nothing(self, wired, monkeypatch):
        agent, session, project = wired
        said = self._capture(monkeypatch, project, differs=True)
        session.agent_app_project_id = None
        asyncio.run(agent._warn_if_undeployed(session))
        assert said == []

    def test_an_unfinished_build_is_left_to_the_factory(self, wired, monkeypatch):
        agent, session, project = wired
        said = self._capture(monkeypatch, project, differs=True)
        project.status = "creating"
        asyncio.run(agent._warn_if_undeployed(session))
        assert said == []


class TestTheContextNote:
    """The note attached to every message in a project session.

    The agent can already load any skill it wants; what it could not do was
    know there WAS a deploy step. The EXTERNAL-app note has always named the
    call inline — and in the 2026-09-02 log the one session with that note is
    the one session where the agent loaded a skill and deployed. The native
    note said only "load the right Agent App skill", and those rounds edited,
    said "Done", and shipped nothing three times.
    """

    def _note(self, monkeypatch, project):
        from app.agent_base import AgentBase

        manager = types.SimpleNamespace(get_project=lambda _pid: project)
        monkeypatch.setattr("app.agent_app.get_agent_app_manager", lambda: manager)
        return AgentBase._build_agent_app_note(project.id)

    def test_the_native_note_names_both_deploy_calls(self, monkeypatch, project):
        note = self._note(monkeypatch, project)
        assert 'agent_app_notify_ready(project_id="f1eb1c85")' in note
        assert 'agent_app_walk_verify(project_id="f1eb1c85")' in note

    def test_it_says_plainly_that_editing_is_not_shipping(self, monkeypatch, project):
        note = self._note(monkeypatch, project)
        assert "EDITING FILES IS NOT SHIPPING THEM" in note
        assert "only when walk_verify returns success" in note

    def test_it_still_leaves_the_choice_of_skill_to_the_agent(
        self, monkeypatch, project
    ):
        # Information, not instruction: nothing here loads a skill for it.
        note = self._note(monkeypatch, project)
        assert "list_skills shows all skills" in note

    def test_an_external_app_keeps_its_own_note(self, monkeypatch, project):
        project.project_type = "external"
        project.app_runtime = "node"
        project.url = "http://127.0.0.1:3105"
        project.port = 3105
        note = self._note(monkeypatch, project)
        assert "EXTERNAL app" in note
        assert 'agent_app_notify_ready(project_id="f1eb1c85")' in note
