# -*- coding: utf-8 -*-
"""Mini Browser agent integration: every agent can find and use the browser.

Covers the agent-facing wiring (no Chromium needed):

- the ``mini_browser_*`` actions load through the real action loader, sit in
  the ``mini_browser`` set, and their STRIPPED source (what the executor
  really runs: only the function, exec'd with ``input_data``/``json``/
  ``asyncio``) works — simulated, and delegating to ``actions_api.run_action``
  with the right op name;
- the LLM sees optional parameters as optional;
- the set description, the skill (discovered, enabled, declaring the set),
  the prompt rule, the docs and the playbook catalogue;
- ``add_action_sets`` name normalisation and unknown-name handling;
- workflow (slash/scheduled) skills loading their action sets;
- AgentBase lifecycle hooks forwarding to ``app.mini_browser.lifecycle``;
- the ``browser_agent`` sub-agent type.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import string
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest

from agent_core import load_actions_from_directories, registry_instance
from agent_core.core.action_framework.formatting import format_action_candidates

REPO_ROOT = Path(__file__).resolve().parent.parent

# action name -> op name handed to app.mini_browser.actions_api.run_action
ACTION_OPS: Dict[str, str] = {
    "mini_browser_navigate": "navigate",
    "mini_browser_read": "read",
    "mini_browser_click": "click",
    "mini_browser_type": "type",
    "mini_browser_press_key": "press_key",
    "mini_browser_select_option": "select_option",
    "mini_browser_hover": "hover",
    "mini_browser_scroll": "scroll",
    "mini_browser_wait": "wait",
    "mini_browser_upload_file": "upload_file",
    "mini_browser_login": "login",
    "mini_browser_screenshot": "screenshot",
    "mini_browser_tabs": "tabs",
}

# Parameters the LLM must see as REQUIRED; every other one must read as
# optional (the prompt formatter decides by "optional"/"default" in the
# description).
REQUIRED_PARAMS: Dict[str, set] = {
    "mini_browser_navigate": {"url"},
    "mini_browser_read": set(),
    "mini_browser_click": {"element_id"},
    "mini_browser_type": {"element_id", "text"},
    "mini_browser_press_key": {"keys"},
    "mini_browser_select_option": {"element_id", "value"},
    "mini_browser_hover": {"element_id"},
    "mini_browser_scroll": set(),
    "mini_browser_wait": set(),
    "mini_browser_upload_file": {"element_id", "paths"},
    "mini_browser_login": set(),
    "mini_browser_screenshot": set(),
    "mini_browser_tabs": {"action"},
}

OLD_PROTOTYPE_ACTIONS = (
    "browser_navigate",
    "browser_read",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_login",
    "browser_new_tab",
    "browser_switch_tab",
    "browser_screenshot",
)


# ── helpers ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registry():
    """Load app/data/action through the real loader (from the code tree)."""
    load_actions_from_directories(
        base_dir=str(REPO_ROOT), paths_to_scan=["app/data/action"]
    )
    return registry_instance


def _impl(name: str):
    return registry_instance.get_action_implementation(name)


def _exec_stripped(code: str, input_data: dict):
    """Run an action's stored source exactly like the internal executor."""
    namespace = {"input_data": input_data, "json": json, "asyncio": asyncio}
    pre_exec = set(namespace)
    exec(code, namespace, namespace)
    function = next(
        value
        for key, value in namespace.items()
        if key not in pre_exec and key != "__builtins__" and inspect.isfunction(value)
    )
    assert inspect.iscoroutinefunction(function), "Mini Browser actions are async"
    return asyncio.run(function(input_data))


def _install_fake_module(monkeypatch, dotted: str, **attrs: Any) -> types.ModuleType:
    """Put a fake ``app.mini_browser.<name>`` module in place of the real one."""
    import app.mini_browser as package

    module = types.ModuleType(dotted)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, dotted, module)
    monkeypatch.setattr(package, dotted.rsplit(".", 1)[1], module, raising=False)
    return module


# ── the actions ──────────────────────────────────────────────────────────


def test_every_mini_browser_action_is_registered_in_its_set(registry):
    names = {n for n in registry.list_all_actions() if n.startswith("mini_browser_")}
    assert names == set(ACTION_OPS)
    for name in ACTION_OPS:
        meta = _impl(name).metadata
        assert meta.action_sets == ["mini_browser"], name
        assert meta.execution_mode == "internal", name
        assert meta.mode == "ALL", name
        assert meta.parallelizable is False, name
        assert meta.irreversible is False, name
        assert meta.requirements == [], name  # no JIT pip install on the loop
        assert meta.test_payload and meta.test_payload.get("simulated_mode") is True


def test_prototype_web_agent_actions_are_gone(registry):
    actions = registry.list_all_actions()
    for old in OLD_PROTOTYPE_ACTIONS:
        assert old not in actions, f"stale prototype action {old} still registered"
    from app.action.action_set import action_set_manager

    assert "web_agent" not in action_set_manager.list_all_sets()
    assert not (REPO_ROOT / "app/data/action/browser_actions.py").exists()


@pytest.mark.parametrize("name", sorted(ACTION_OPS))
def test_llm_sees_required_and_optional_params_correctly(registry, name):
    action_json = registry.find_action_by_name(name)
    rendered = json.loads(format_action_candidates([action_json]))[0]["params"]
    required = {p for p, text in rendered.items() if ", required - " in text}
    assert required == REQUIRED_PARAMS[name]
    assert rendered, f"{name} must declare its inputs"


@pytest.mark.parametrize("name", sorted(ACTION_OPS))
def test_stripped_source_runs_simulated_in_executor_namespace(registry, name):
    action_json = registry.find_action_by_name(name)
    code = action_json["code"]
    assert code.lstrip().startswith("async def "), "decorator must be stripped"
    payload = dict(_impl(name).metadata.test_payload)

    result = _exec_stripped(code, dict(payload))
    assert isinstance(result, dict)
    assert result.get("status") == "success", result


@pytest.mark.parametrize("name", sorted(ACTION_OPS))
def test_stripped_source_runs_through_the_real_executor(registry, name):
    from agent_core.core.impl.action.executor import _atomic_action_internal_async

    code = registry.find_action_by_name(name)["code"]
    payload = dict(_impl(name).metadata.test_payload)
    result = asyncio.run(_atomic_action_internal_async(name, code, payload, "CLI"))
    assert result.get("status") == "success", result


@pytest.mark.parametrize("name", sorted(ACTION_OPS))
def test_stripped_source_delegates_to_run_action(registry, monkeypatch, name):
    calls: List[tuple] = []

    async def fake_run_action(op: str, input_data: dict) -> dict:
        calls.append((op, input_data))
        return {"status": "success", "op": op}

    _install_fake_module(
        monkeypatch, "app.mini_browser.actions_api", run_action=fake_run_action
    )
    code = registry.find_action_by_name(name)["code"]
    payload = {
        k: v
        for k, v in _impl(name).metadata.test_payload.items()
        if k != "simulated_mode"
    }
    payload["_session_id"] = "chat_1234"

    result = _exec_stripped(code, payload)

    assert result == {"status": "success", "op": ACTION_OPS[name]}
    assert len(calls) == 1
    op, forwarded = calls[0]
    assert op == ACTION_OPS[name]
    assert forwarded is payload, "input_data (incl. _session_id) must pass through"


def test_original_handlers_answer_simulated_mode(registry):
    """What tests/e2e/test_smoke.py runs: the decorated handler itself."""
    for name in ACTION_OPS:
        impl = _impl(name)
        result = asyncio.run(impl.handler(dict(impl.metadata.test_payload)))
        assert result.get("status") == "success", name


# Inputs that exercise every declared parameter of each op.
_SAMPLE_INPUTS: Dict[str, dict] = {
    "navigate": {"url": "https://example.com", "timeout_ms": 20000},
    "read": {"max_text_chars": 2000, "max_elements": 50, "text_offset": 0},
    "click": {"element_id": 3, "button": "left", "double": False},
    "type": {"element_id": 2, "text": "hello", "submit": True, "clear": True},
    "press_key": {"keys": "Enter", "element_id": 2},
    "select_option": {"element_id": 4, "value": "M"},
    "hover": {"element_id": 1},
    "scroll": {"direction": "down", "amount": 600},
    "wait": {"seconds": 1},
    "login": {"submit": True},
    "screenshot": {"full_page": False},
    "tabs": {"action": "list"},
}


def test_action_inputs_match_actions_api_validate(registry):
    """The stubs' input names must be what actions_api.validate understands."""
    try:
        from app.mini_browser.actions_api import validate
    except Exception as exc:  # not written yet / still being written
        pytest.skip(f"app.mini_browser.actions_api not importable: {exc}")

    for name, op in ACTION_OPS.items():
        schema_keys = set(_impl(name).metadata.input_schema)
        sample = _SAMPLE_INPUTS.get(op)
        if sample is None:
            continue  # upload_file: path checks belong to the op itself
        assert set(sample) <= schema_keys, name
        params = validate(op, dict(sample))
        assert isinstance(params, dict), op
        missing = set(sample) - set(params)
        assert not missing, f"validate({op!r}) dropped declared inputs {missing}"


# ── set description, prompts and docs ───────────────────────────────────


def test_set_descriptions(registry):
    from app.action.action_set import DEFAULT_SET_DESCRIPTIONS, action_set_manager

    assert "web_agent" not in DEFAULT_SET_DESCRIPTIONS
    desc = DEFAULT_SET_DESCRIPTIONS["mini_browser"]
    for phrase in ("logins", "own tab", "take control", "web_fetch", "NOT for plain"):
        assert phrase in desc
    assert "mini_browser" in DEFAULT_SET_DESCRIPTIONS["mcp_playwright-mcp"]
    # The catalog line the LLM reads is the curated text, not "Custom action set".
    assert action_set_manager.list_all_sets()["mini_browser"] == desc
    catalog = action_set_manager.format_sets_for_prompt(exclude_core=True)
    assert f"- mini_browser: {desc}" in catalog


@pytest.mark.parametrize("mode", ["CLI", "GUI"])
def test_set_compiles_in_every_mode_and_under_its_old_name(registry, mode):
    from app.action.action_set import action_set_manager

    for name in ("mini_browser", "web_agent"):  # a persisted prototype name
        compiled = set(action_set_manager.compile_action_list([name], mode=mode))
        assert set(ACTION_OPS) <= compiled, name
    assert not set(ACTION_OPS) & set(action_set_manager.compile_action_list([]))


def test_action_prompt_rule_and_placeholders():
    from agent_core.core.prompts.action import SELECT_ACTION_PROMPT
    from agent_core.core.prompts.context import AGENT_INFO_PROMPT

    assert "load the 'mini_browser' action set" in SELECT_ACTION_PROMPT
    assert "the Mini Browser, ...)? Use 'add_action_sets'" in SELECT_ACTION_PROMPT
    fields = {f for _, f, _, _ in string.Formatter().parse(SELECT_ACTION_PROMPT) if f}
    assert fields == {
        "action_candidates",
        "session_state",
        "event_stream",
        "query",
        "integration_essentials",
    }
    assert "Mini Browser" in AGENT_INFO_PROMPT


def test_web_fetch_points_to_the_mini_browser(registry):
    action_json = registry.find_action_by_name("web_fetch")
    assert "Mini Browser" in action_json["description"]
    assert "mini_browser" in action_json["code"]
    assert "browser tools (Playwright)" not in action_json["code"]


def test_add_action_sets_action_examples(registry):
    schema = registry.find_action_by_name("add_action_sets")["input_schema"]
    assert schema["action_sets"]["example"] == ["mini_browser"]
    assert "shell" not in json.dumps(schema)


def test_schedule_task_describes_action_sets_honestly(registry):
    schema = registry.find_action_by_name("schedule_task")["input_schema"]
    text = schema["action_sets"]["description"]
    assert "auto-selected" not in text
    assert "mini_browser" in text
    assert text.startswith("Optional.")
    assert schema["action_sets"]["example"] == ["mini_browser"]


def test_agent_md_copies_identical_and_mention_mini_browser():
    live = (REPO_ROOT / "agent_file_system/AGENT.md").read_bytes()
    template = (REPO_ROOT / "app/data/agent_file_system_template/AGENT.md").read_bytes()
    assert live == template
    text = live.decode("utf-8")
    for needle in ("mini_browser", "mini-browser", "browser_agent", "unknown_sets"):
        assert needle in text
    assert "web_agent` → `mini_browser" in text


def test_custom_action_guide_lists_mini_browser():
    text = (REPO_ROOT / "app/data/action/CUSTOM_ACTION_GUIDE.md").read_text("utf-8")
    assert '`"mini_browser"`' in text


def test_playbooks_suggest_mini_browser_next_to_playwright():
    data = json.loads(
        (REPO_ROOT / "app/data/playbooks/catalogue.json").read_text("utf-8")
    )
    with_playwright = 0
    for playbook in data["playbooks"]:
        skills = (playbook.get("works_best_with") or {}).get("skills") or []
        if "playwright-mcp" in skills:
            with_playwright += 1
            index = skills.index("playwright-mcp")
            assert skills[index + 1 : index + 2] == ["mini-browser"], playbook["id"]
    assert with_playwright >= 1


def test_agent_app_trigger_brief_mentions_the_mini_browser():
    source = (REPO_ROOT / "app/agent_app/manager.py").read_text("utf-8")
    assert 'add_action_sets(["mini_browser"])' in source


# ── skills ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def discovered_skills():
    from agent_core.core.impl.skill.config import SkillsConfig
    from agent_core.core.impl.skill.loader import SkillLoader

    config = SkillsConfig.load(REPO_ROOT / "app/config/skills_config.json")
    skills = SkillLoader.discover_skills([REPO_ROOT / "skills"], config)
    return {s.name: s for s in skills}


def test_mini_browser_skill_is_discovered_enabled_and_declares_the_set(
    discovered_skills,
):
    skill = discovered_skills.get("mini-browser")
    assert skill is not None, "skills/mini-browser/SKILL.md not discovered"
    assert skill.enabled, "mini-browser must be in enabled_skills (whitelist)"
    assert not skill.is_system, "user-invocable: /mini-browser must work"
    assert skill.metadata.action_sets == ["mini_browser"]
    assert skill.metadata.argument_hint
    assert "USED" in skill.description
    body = skill.instructions
    # Injected into every turn while loaded: keep it small (~1.5K tokens).
    assert len(body) <= 6500, len(body)
    for needle in (
        "mini_browser_login",
        "for_user=true",
        "untrusted",
        "send_message_with_attachment",
        "mini_browser_tabs",
        "FULLY done",
    ):
        assert needle in body, needle


def test_playwright_mcp_skill_uses_real_mcp_tool_names(discovered_skills):
    skill = discovered_skills["playwright-mcp"]
    assert "Mini Browser" in skill.description
    assert "invisible" in skill.description
    assert skill.metadata.action_sets == ["mcp_playwright-mcp"]
    bare = re.findall(r"(?<![\w-])browser_[a-z_]+", skill.instructions)
    assert not bare, f"bare Playwright MCP tool names left: {sorted(set(bare))}"
    assert "mcp_playwright-mcp_browser_navigate" in skill.instructions


def test_heartbeat_skill_explains_browser_work(discovered_skills):
    body = discovered_skills["heartbeat-processor"].instructions
    assert 'action_sets=["mini_browser"]' in body
    assert 'add_action_sets(["mini_browser"])' in body
    assert "code_analysis" not in body


# ── add_action_sets normalisation ───────────────────────────────────────


class _FakeSession:
    def __init__(self, action_sets=None):
        self.action_sets = list(action_sets or [])
        self.selected_skills: List[str] = []


class _FakeSessionManager:
    def __init__(self, action_sets=None):
        self.session = _FakeSession(action_sets)
        self.add_calls: List[List[str]] = []
        self.remove_calls: List[List[str]] = []

    def get(self, sid):
        return self.session if sid == "s1" else None

    def get_action_sets(self, sid):
        return list(self.session.action_sets) if sid == "s1" else []

    def add_action_sets(self, sid, sets):
        self.add_calls.append(list(sets))
        before = set(self.session.action_sets)
        for s in sets:
            if s not in self.session.action_sets:
                self.session.action_sets.append(s)
        added = [f"{s}_action" for s in sets if s not in before]
        return {
            "success": True,
            "current_sets": list(self.session.action_sets),
            "added_actions": added,
            "total_actions": 40 + len(added),
        }

    def remove_action_sets(self, sid, sets):
        self.remove_calls.append(list(sets))
        self.session.action_sets = [
            s for s in self.session.action_sets if s not in sets
        ]
        return {"success": True, "current_sets": list(self.session.action_sets)}

    def add_skill(self, sid, name):
        if name not in self.session.selected_skills:
            self.session.selected_skills.append(name)
        return True


def _fake_skill(name, action_sets=(), enabled=True, system=False):
    return types.SimpleNamespace(
        name=name,
        description=f"{name} skill",
        enabled=enabled,
        is_system=system,
        metadata=types.SimpleNamespace(action_sets=list(action_sets)),
    )


@pytest.fixture
def iai(monkeypatch):
    from agent_core.core.impl.skill.manager import skill_manager
    from app.action.action_set import action_set_manager
    from app.internal_action_interface import InternalActionInterface

    known = [
        "core",
        "file_operations",
        "document_processing",
        "mini_browser",
        "mcp_playwright-mcp",
    ]
    monkeypatch.setattr(action_set_manager, "get_available_set_names", lambda: known)
    skills = {
        "pdf": _fake_skill("pdf"),
        "mini-browser": _fake_skill("mini-browser", ["mini_browser"]),
        "odd-skill": _fake_skill("odd-skill", ["no_such_set"]),
    }
    monkeypatch.setattr(skill_manager, "get_skill", lambda name: skills.get(name))
    monkeypatch.setattr(
        skill_manager,
        "get_skill_action_sets",
        lambda names: [s for n in names for s in skills[n].metadata.action_sets],
    )
    manager = _FakeSessionManager()
    monkeypatch.setattr(InternalActionInterface, "session_manager", manager)
    invalidated: List[str] = []
    monkeypatch.setattr(
        InternalActionInterface,
        "_invalidate_action_selection_caches",
        classmethod(lambda cls, sid=None: invalidated.append(sid)),
    )
    return types.SimpleNamespace(
        api=InternalActionInterface, manager=manager, invalidated=invalidated
    )


@pytest.mark.parametrize(
    "requested, stored",
    [
        (["mini_browser"], ["mini_browser"]),
        (["Mini-Browser"], ["mini_browser"]),
        ([" MINI_BROWSER "], ["mini_browser"]),
        (["mini browser"], ["mini_browser"]),
        (["web_agent"], ["mini_browser"]),  # legacy alias
        (["mcp_playwright-mcp"], ["mcp_playwright-mcp"]),  # hyphens kept
        (["mini_browser", "mini-browser", "MINI_BROWSER"], ["mini_browser"]),
        ("mini_browser", ["mini_browser"]),  # a bare string is one name
    ],
)
def test_add_action_sets_normalises_names(iai, requested, stored):
    result = iai.api.add_action_sets(requested, session_id="s1")
    assert result["success"] is True
    assert iai.manager.add_calls == [stored]
    assert "unknown_sets" not in result
    assert result["added_sets"] == stored
    assert "available from your next turn" in result["message"]
    assert iai.invalidated == ["s1"]


def test_add_action_sets_skips_unknown_names_but_loads_the_rest(iai):
    result = iai.api.add_action_sets(["mini_browser", "nonsense_set"], session_id="s1")
    assert result["success"] is True
    assert iai.manager.add_calls == [["mini_browser"]]
    assert iai.manager.session.action_sets == ["mini_browser"]
    assert result["unknown_sets"] == ["nonsense_set"]
    assert "nonsense_set" in result["hint"]


def test_add_action_sets_with_only_unknown_names_fails_and_stores_nothing(iai):
    result = iai.api.add_action_sets(["minibrowser", "pdf", ""], session_id="s1")
    assert result["success"] is False
    assert iai.manager.add_calls == []
    assert iai.invalidated == []
    assert result["unknown_sets"] == ["minibrowser", "pdf"]
    assert "did you mean mini_browser" in result["hint"]
    assert "use_skill('pdf')" in result["hint"]
    assert result["current_sets"] == []


def test_add_action_sets_explains_empty_and_disconnected_sets(iai):
    result = iai.api.add_action_sets(["web_research", "mcp_github-mcp"], "s1")
    assert result["success"] is False
    assert result["unknown_sets"] == ["web_research", "mcp_github-mcp"]
    assert "'web_research' has no actions in this build" in result["hint"]
    assert "MCP server is not connected" in result["hint"]


def test_add_action_sets_reports_already_loaded_sets(iai):
    iai.api.add_action_sets(["mini_browser"], session_id="s1")
    result = iai.api.add_action_sets(["mini-browser"], session_id="s1")
    assert result["success"] is True
    assert result["added_sets"] == []
    assert result["message"] == "Already loaded: mini_browser."


def test_remove_action_sets_normalises_names(iai):
    iai.manager.session.action_sets = ["mini_browser", "web_agent"]
    iai.api.remove_action_sets(["Mini-Browser", "web_agent", "never_loaded"], "s1")
    assert iai.manager.remove_calls == [["mini_browser", "web_agent", "never_loaded"]]
    assert iai.manager.session.action_sets == []


def test_use_skill_accepts_the_set_spelling_and_loads_the_set(iai):
    result = iai.api.use_skill("mini_browser", session_id="s1")
    assert result["success"] is True
    assert iai.manager.session.selected_skills == ["mini-browser"]
    assert result["added_action_sets"] == ["mini_browser"]
    assert iai.manager.session.action_sets == ["mini_browser"]


def test_use_skill_still_rebuilds_caches_when_its_sets_are_unknown(iai):
    result = iai.api.use_skill("odd-skill", session_id="s1")
    assert result["success"] is True
    assert result["added_action_sets"] == []
    assert iai.manager.add_calls == []
    assert iai.invalidated == ["s1"]


# ── AgentBase: workflow skills and lifecycle hooks ─────────────────────


class _WorkflowSessionManager:
    def __init__(self):
        self.added_sets: List[List[str]] = []
        self.added_skills: List[str] = []

    def add_action_sets(self, sid, sets):
        self.added_sets.append(list(sets))
        return {"success": True}

    def add_skill(self, sid, name):
        self.added_skills.append(name)
        return True


@pytest.fixture
def bare_agent(monkeypatch):
    from agent_core.core.impl.skill.manager import skill_manager
    from app.agent_base import AgentBase

    skills = {
        "mini-browser": _fake_skill("mini-browser", ["mini_browser"]),
        "heartbeat-processor": _fake_skill(
            "heartbeat-processor", ["file_operations", "scheduler"], system=True
        ),
        "off-skill": _fake_skill("off-skill", ["image"], enabled=False),
        "scalar-sets": _fake_skill("scalar-sets"),
    }
    skills["scalar-sets"].metadata.action_sets = "document_processing"
    monkeypatch.setattr(skill_manager, "get_skill", lambda name: skills.get(name))

    agent = AgentBase.__new__(AgentBase)
    agent.session_manager = _WorkflowSessionManager()
    agent.busy_sessions = set()
    agent.ui_controller = None
    agent._interface_mode = "browser"
    monkeypatch.setattr(agent, "_invalidate_session_caches", lambda sid: None)
    monkeypatch.setattr(agent, "_persist_session_stream", lambda sid: None)
    return agent


@pytest.mark.parametrize(
    "payload, expected_sets",
    [
        ({"workflow_skills": ["mini-browser"]}, [["mini_browser"]]),
        (
            {
                "workflow_skills": ["mini-browser"],
                "workflow_action_sets": ["mini_browser", "file_operations"],
            },
            [["mini_browser", "file_operations"]],
        ),
        # System workflow skills keep their explicit, hand-picked sets.
        (
            {
                "workflow_skills": ["heartbeat-processor"],
                "workflow_action_sets": ["file_operations", "proactive"],
            },
            [["file_operations", "proactive"]],
        ),
        ({"workflow_skills": ["off-skill"]}, []),
        ({"workflow_skills": ["scalar-sets"]}, [["document_processing"]]),
        ({"workflow_skills": ["no-such-skill"]}, []),
        ({}, []),
    ],
)
def test_workflow_skills_load_their_action_sets(bare_agent, payload, expected_sets):
    session = types.SimpleNamespace(id="main")
    asyncio.run(bare_agent._apply_workflow_capabilities(session, payload))
    assert bare_agent.session_manager.added_sets == expected_sets
    assert bare_agent.session_manager.added_skills == payload.get("workflow_skills", [])


@pytest.fixture
def fake_lifecycle(monkeypatch):
    calls: List[tuple] = []

    def record(name):
        def hook(*args, **kwargs):
            calls.append((name, args, kwargs))

        return hook

    async def shutdown(timeout: float = 15.0) -> None:
        calls.append(("shutdown", (), {}))

    module = _install_fake_module(
        monkeypatch,
        "app.mini_browser.lifecycle",
        on_run_state=record("on_run_state"),
        release_owner=record("release_owner"),
        cancel_owner=record("cancel_owner"),
        shutdown=shutdown,
    )
    module.calls = calls
    return module


def test_run_state_is_forwarded(bare_agent, fake_lifecycle):
    bare_agent._emit_run_state("chat1", "running")
    bare_agent._emit_run_state("chat1", "idle")
    assert fake_lifecycle.calls == [
        ("on_run_state", ("chat1", "running"), {}),
        ("on_run_state", ("chat1", "idle"), {}),
    ]


def test_stop_cancels_browser_work_before_the_runtime_stop(bare_agent, fake_lifecycle):
    order: List[str] = []

    class _Runtime:
        async def request_stop(self, sid):
            order.append(f"runtime_stop:{sid}")
            return True

    bare_agent.session_runtime = _Runtime()
    original = fake_lifecycle.cancel_owner

    def cancel_owner(*args, **kwargs):
        order.append("cancel_owner")
        original(*args, **kwargs)

    fake_lifecycle.cancel_owner = cancel_owner

    assert asyncio.run(bare_agent.request_run_stop("chat1")) is True
    assert order == ["cancel_owner", "runtime_stop:chat1"]
    assert ("cancel_owner", ("chat1",), {"include_children": True}) in (
        fake_lifecycle.calls
    )


def test_stop_finaliser_cancels_again_as_a_safety_net(bare_agent, fake_lifecycle):
    class _SessionManager:
        def get(self, sid):
            return None

        def persist(self, sid):
            pass

    bare_agent.session_manager = _SessionManager()
    bare_agent.event_stream_manager = None
    bare_agent._memory_run_snapshot = None
    asyncio.run(bare_agent._on_run_stopped("chat1"))
    assert fake_lifecycle.calls[0] == (
        "cancel_owner",
        ("chat1",),
        {"include_children": True},
    )
    assert ("on_run_state", ("chat1", "idle"), {}) in fake_lifecycle.calls


def test_deleting_a_chat_releases_its_tabs(bare_agent, fake_lifecycle):
    from agent_core.core.session import SessionType

    class _SessionManager:
        def get(self, sid):
            return types.SimpleNamespace(id=sid, type=SessionType.CHAT)

        def delete_session(self, sid):
            return True

    class _TriggerService:
        async def cancel_sessions(self, ids):
            pass

    bare_agent.session_manager = _SessionManager()
    bare_agent.trigger_service = _TriggerService()
    assert asyncio.run(bare_agent.delete_session("chat1")) is True
    assert fake_lifecycle.calls == [("release_owner", ("chat1",), {})]


@pytest.mark.parametrize("session_type", ["main", "mini_browser"])
def test_fixture_sessions_cannot_be_deleted(bare_agent, fake_lifecycle, session_type):
    """The main chat and the Mini Browser page's dedicated chat are UI
    fixtures: deleting them is refused (they can still be cleared)."""
    deleted: List[str] = []

    class _SessionManager:
        def get(self, sid):
            return types.SimpleNamespace(id=sid, type=session_type)

        def delete_session(self, sid):
            deleted.append(sid)
            return True

    class _TriggerService:
        async def cancel_sessions(self, ids):
            deleted.append(f"cancel:{ids}")

    bare_agent.session_manager = _SessionManager()
    bare_agent.trigger_service = _TriggerService()
    assert asyncio.run(bare_agent.delete_session(session_type)) is False
    assert deleted == [] and fake_lifecycle.calls == []


def test_stream_removal_listener_releases_the_owner(bare_agent, fake_lifecycle):
    from app.agent_base import AgentBase

    bare_agent._release_mini_browser_owner("sub_1234", object())
    assert fake_lifecycle.calls == [("release_owner", ("sub_1234",), {})]
    init_source = inspect.getsource(AgentBase.__init__)
    assert "add_removal_listener(self._release_mini_browser_owner)" in init_source


def test_lifecycle_failures_never_reach_the_agent(bare_agent, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("browser exploded")

    _install_fake_module(
        monkeypatch,
        "app.mini_browser.lifecycle",
        on_run_state=boom,
        release_owner=boom,
        cancel_owner=boom,
    )
    bare_agent._emit_run_state("chat1", "running")
    bare_agent._release_mini_browser_owner("sub_1", None)
    assert bare_agent.busy_sessions == {"chat1"}

    # A missing lifecycle module (ImportError) is swallowed too.
    monkeypatch.setitem(sys.modules, "app.mini_browser.lifecycle", None)
    import app.mini_browser as package

    monkeypatch.delattr(package, "lifecycle", raising=False)
    bare_agent._emit_run_state("chat1", "idle")
    assert bare_agent.busy_sessions == set()


def test_shutdown_only_when_the_browser_host_was_loaded(
    bare_agent, fake_lifecycle, monkeypatch
):
    monkeypatch.delitem(sys.modules, "app.mini_browser.host", raising=False)
    asyncio.run(bare_agent._shutdown_mini_browser())
    assert fake_lifecycle.calls == []

    monkeypatch.setitem(
        sys.modules, "app.mini_browser.host", types.ModuleType("app.mini_browser.host")
    )
    asyncio.run(bare_agent._shutdown_mini_browser())
    assert fake_lifecycle.calls == [("shutdown", (), {})]

    async def failing_shutdown(timeout: float = 15.0) -> None:
        raise RuntimeError("could not close")

    fake_lifecycle.shutdown = failing_shutdown
    asyncio.run(bare_agent._shutdown_mini_browser())  # logged, never raised


def test_browser_mode_prompt_explains_the_live_view(bare_agent):
    prompt = bare_agent._get_interface_capabilities_prompt()
    assert "## Mini Browser" in prompt
    assert "for_user=true" in prompt
    bare_agent._interface_mode = "cli"
    assert bare_agent._get_interface_capabilities_prompt() == ""


# ── browser_agent sub-agent ─────────────────────────────────────────────


def test_browser_agent_is_registered_with_existing_actions(registry):
    from app.subagent import SUB_TASK_END_ACTION, get_subagent_definition

    definition = get_subagent_definition("browser_agent")
    actions = set(definition.actions)
    assert SUB_TASK_END_ACTION in actions
    assert "mini_browser_login" not in actions, "sub-agents never use the vault"
    assert set(ACTION_OPS) - {"mini_browser_login"} <= actions
    registered = registry.list_all_actions()
    for name in actions:
        assert name in registered, f"browser_agent lists unknown action {name}"
    assert set(definition.compact_actions) <= actions
    assert definition.max_iterations > 0 and definition.max_wall_seconds > 0

    prompt = definition.system_prompt.format(
        action_list="<ACTIONS>", output_format="<FORMAT>"
    )
    assert "<ACTIONS>" in prompt and "<FORMAT>" in prompt
    assert '{"action_name": "<name>"' in prompt

    spawn = registry.find_action_by_name("spawn_subagent")
    assert "browser_agent" in spawn["input_schema"]["agent_type"]["enum"]
    assert "browser_agent:" in spawn["description"]
