# -*- coding: utf-8 -*-
"""The one decision-JSON parser.

Unifies the two previously-parallel implementations:
- router `_parse_action_decision` (BOM/CRLF normalization, json →
  ast.literal_eval fallback, dict check) — now delegates here;
- runner `_parse_decision` (all of the above + markdown-fence stripping +
  batch/legacy action extraction with per-entry errors) — now delegates here.

The router additionally gains fence-stripping (a strict superset: fenced
JSON used to burn a retry). Caller-specific ACTION-LIST contracts stay with
the callers (the router's format-error coaching is prompt-contract-specific);
the strict batch extractor used by sub-agents lives here.
"""

from __future__ import annotations

import ast
import json
from typing import Any, Dict, List, Optional, Tuple


def normalize_llm_json(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """BOM/CRLF/whitespace normalization + markdown-fence stripping.

    Returns (text, None) or (None, error)."""
    if not raw or (isinstance(raw, str) and not raw.strip()):
        return None, (
            "LLM returned an empty response. This may indicate an API error "
            "or the model failed to generate output."
        )
    text = raw
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "").strip()
    # Strip markdown code fences if the LLM ignored instructions.
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if not text:
        return None, (
            "LLM response was empty or only contained whitespace after normalization."
        )
    return text, None


def loads_json_or_literal(text: str) -> Tuple[Optional[Any], Optional[str]]:
    """json.loads with ast.literal_eval fallback. (obj, None) or (None, err)."""
    try:
        return json.loads(text), None
    except json.JSONDecodeError as json_error:
        try:
            return ast.literal_eval(text), None
        except Exception as eval_error:
            return None, f"json error: {json_error}; literal_eval error: {eval_error}"


def parse_decision_dict(
    raw: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Raw LLM text → decision dict. (dict, None) or (None, error)."""
    text, err = normalize_llm_json(raw)
    if text is None:
        return None, err
    parsed, err = loads_json_or_literal(text)
    if parsed is None:
        return None, err
    if not isinstance(parsed, dict):
        return None, "parsed value is not a dictionary"
    return parsed, None


def extract_actions_strict(
    decision: Dict[str, Any],
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Batch/legacy action extraction with per-entry errors (sub-agent
    contract): accepts ``{"actions": [{action_name, parameters}, ...]}`` or
    the legacy single-action shape ``{"action_name": ..., ...}``."""
    if "actions" in decision:
        actions = decision["actions"]
        if not isinstance(actions, list) or not actions:
            return None, "'actions' must be a non-empty list"
        normalized: List[Dict[str, Any]] = []
        for i, entry in enumerate(actions):
            if not isinstance(entry, dict) or "action_name" not in entry:
                return None, f"actions[{i}] missing 'action_name'"
            normalized.append(entry)
        return normalized, None
    if "action_name" not in decision:
        return None, "missing 'actions' list (or legacy 'action_name')"
    return [decision], None
