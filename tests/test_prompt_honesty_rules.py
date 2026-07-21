# -*- coding: utf-8 -*-
"""
Regression guard for issue #363 (agent fabricates success confirmations).

Presence check only, not a behavior test. Two layers:
- Framework prompt templates (action.py, context.py, send_message.py) are
  injected into every LLM call — most reliable, but require an app restart
  to take effect.
- AGENT.md / INTEGRATION.md are read fresh with no restart needed, but
  AGENT.md is 100% opt-in (the model must choose to read it) while
  INTEGRATION.md's `## Essentials` block auto-injects on keyword match.
Both layers carry the same rule so neither gap is the only line of defense.
"""

from pathlib import Path

from agent_core.core.prompts.action import (
    SELECT_ACTION_PROMPT,
    SELECT_ACTION_IN_TASK_PROMPT,
    SELECT_ACTION_IN_SIMPLE_TASK_PROMPT,
)
from agent_core.core.prompts.context import AGENT_INFO_PROMPT

REPO_ROOT = Path(__file__).resolve().parent.parent

EFFECT_MARKER = "Never describe an effect you didn't actually cause"
NO_RETRY_ESCALATION = "invent a new explanation"


def test_communication_rules_hard_rule_present():
    for path in (
        REPO_ROOT / "agent_file_system" / "AGENT.md",
        REPO_ROOT / "app" / "data" / "agent_file_system_template" / "AGENT.md",
    ):
        assert EFFECT_MARKER in path.read_text(encoding="utf-8")


def test_framework_prompts_carry_the_same_honesty_rule():
    assert "HONESTY IS NON-NEGOTIABLE" in AGENT_INFO_PROMPT
    assert NO_RETRY_ESCALATION in AGENT_INFO_PROMPT
    for prompt in (
        SELECT_ACTION_PROMPT,
        SELECT_ACTION_IN_TASK_PROMPT,
        SELECT_ACTION_IN_SIMPLE_TASK_PROMPT,
    ):
        assert NO_RETRY_ESCALATION in prompt


def test_send_message_schema_reinforces_honesty():
    text = (REPO_ROOT / "app" / "data" / "action" / "send_message.py").read_text(
        encoding="utf-8"
    )
    assert "there's no way I can do that" in text
    assert NO_RETRY_ESCALATION in text


NO_SIGNATURE_MARKER = "There is no signature feature"
NO_ESCALATION_MARKER = "Do NOT escalate to inventing a new mechanism on each retry"


def test_gmail_integration_md_documents_no_signature_and_config_path():
    text = (
        REPO_ROOT
        / "craftos_integrations"
        / "integrations"
        / "gmail"
        / "INTEGRATION.md"
    ).read_text(encoding="utf-8")
    assert NO_SIGNATURE_MARKER in text
    assert NO_ESCALATION_MARKER in text
    assert "gmail_config.json" in text


def test_outlook_integration_md_documents_no_signature():
    text = (
        REPO_ROOT
        / "craftos_integrations"
        / "integrations"
        / "outlook"
        / "INTEGRATION.md"
    ).read_text(encoding="utf-8")
    assert NO_SIGNATURE_MARKER in text
    assert NO_ESCALATION_MARKER in text


def test_set_requirement_documented_with_grounding_rules():
    for path in (
        REPO_ROOT / "agent_file_system" / "AGENT.md",
        REPO_ROOT / "app" / "data" / "agent_file_system_template" / "AGENT.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "set_requirement" in text
        assert "Before locking in a requirement, check it's actually achievable" in text
        assert "Marking a requirement `satisfied` requires the same grounding" in text
        assert "If the user disputes a `satisfied` requirement, flip it to `violated` immediately" in text
