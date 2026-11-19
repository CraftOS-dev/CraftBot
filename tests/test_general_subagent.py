"""General worker wiring: its definition, tools and platform-specific shell.

Its runtime behaviour is pinned with every other type in
test_subagent_runtime.py.
"""

import platform
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent_core import load_actions_from_directories, registry_instance
from app.subagent import get_subagent_definition

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registry():
    load_actions_from_directories(
        base_dir=str(REPO_ROOT), paths_to_scan=["app/data/action"]
    )
    return registry_instance


def test_definition_is_discovered_with_resolvable_tools(registry):
    definition = get_subagent_definition("general_agent")
    for name in definition.actions:
        assert registry.find_action_by_name(name) is not None, name
    assert definition.actions.count("sub_task_end") == 1
    assert {"read_file", "write_file", "stream_edit", "run_shell"} <= set(
        definition.actions
    )
    assert not {"spawn_subagent", "send_message", "add_action_sets", "use_skill"} & set(
        definition.actions
    )
    # The type's own prompt only: the runtime appends <actions> and the format.
    assert "{" not in definition.system_prompt
    spawn = registry.find_action_by_name("spawn_subagent")
    assert "general_agent" in spawn["input_schema"]["agent_type"]["enum"]
    assert definition.description in spawn["description"]
    assert spawn["parallelizable"] is True


@pytest.mark.parametrize("system", ["Windows", "Linux", "Darwin"])
def test_definition_only_offers_powershell_on_windows(monkeypatch, system):
    register = Mock()
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr("app.subagent.registry.register_subagent", register)
    runpy.run_path(str(REPO_ROOT / "app/subagent/definitions/general_agent.py"))
    register.assert_called_once()
    actions = register.call_args.kwargs["actions"]
    assert "run_shell" in actions
    assert ("run_powershell" in actions) == (system == "Windows")
