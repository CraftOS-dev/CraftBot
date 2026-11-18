# -*- coding: utf-8 -*-
"""How replies render is stated once, per interface (prompt audit T11).

send_message's ``message`` parameter said "terminal friendly format and DO
NOT include mark down" in every interface, while the browser chat (and the
terminal edition on the same socket) renders agent messages as Markdown, so
replies came out flat where formatting would have shown. The rule now lives
in the role text of each interface mode, which states how that interface
renders replies, and the parameter points to it. These tests pin:

* browser mode says replies render as Markdown;
* CLI mode, which prints raw text, says to write plain text;
* the parameter carries no format rule of its own.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.agent_base import AgentBase

REPO = Path(__file__).resolve().parents[1]


def _replies(mode, monkeypatch):
    monkeypatch.setattr(AgentBase, "_mini_browser_usable", staticmethod(lambda: False))
    agent = AgentBase.__new__(AgentBase)
    agent._interface_mode = mode
    prompt = agent._get_interface_capabilities_prompt()
    assert "\n\n## Replies\n" in prompt
    return prompt.split("## Replies\n", 1)[1].split("\n\n## ", 1)[0]


def test_browser_mode_says_replies_render_as_markdown(monkeypatch):
    replies = _replies("browser", monkeypatch)
    assert "renders" in replies and "as Markdown" in replies


def test_cli_mode_says_to_write_plain_text(monkeypatch):
    replies = _replies("cli", monkeypatch)
    assert "plain text without Markdown" in replies


def _message_description() -> str:
    tree = ast.parse((REPO / "app/data/action/send_message.py").read_text("utf-8"))
    decorator = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(k.arg == "name" and getattr(k.value, "value", None) == "send_message" for k in node.keywords)
    )
    schema = ast.literal_eval(next(k.value for k in decorator.keywords if k.arg == "input_schema"))
    return schema["message"]["description"]


def test_the_message_parameter_points_to_the_replies_section():
    description = _message_description()
    assert "Replies section" in description
    low = description.lower()
    assert "markdown" not in low and "mark down" not in low


@pytest.mark.parametrize("mode", ["browser", "cli"])
def test_the_replies_text_is_the_same_on_every_build(mode, monkeypatch):
    # Part of the system prompt: it must not vary between calls.
    assert _replies(mode, monkeypatch) == _replies(mode, monkeypatch)
