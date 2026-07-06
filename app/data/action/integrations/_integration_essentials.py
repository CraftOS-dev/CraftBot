# -*- coding: utf-8 -*-
"""Inject just-in-time integration guidance into the routing-time prompt.

When a user message mentions an integration by name (e.g. "send a whatsapp
message..."), this helper looks up the integration's ``INTEGRATION.md`` and
extracts its ``## Essentials`` block. That block goes into the routing
prompt so the routing-time LLM has the workflow rules in context BEFORE
deciding what to do — instead of asking the user for info the integration
could look up itself.

The match is intentionally loose (case-insensitive substring against
integration ids + display names + first tokens). False positives are
cheap (~200 tokens of extra context); false negatives are the whole
reason this exists.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

# Project root → ``craftos_integrations/integrations/<id>/INTEGRATION.md``.
# This file is at app/data/action/integrations/_integration_essentials.py
# → parents[4] is the project root.
_INTEGRATIONS_ROOT = (
    Path(__file__).resolve().parents[4] / "craftos_integrations" / "integrations"
)

# Built lazily on first call so we don't import the registry at module load.
_KEYWORD_INDEX: Optional[Dict[str, str]] = None


def _build_keyword_index() -> Dict[str, str]:
    """Map keyword variants → integration id.

    Scans ``craftos_integrations/integrations/`` and treats each
    non-underscore-prefixed subdirectory OR ``<id>.py`` file as an
    integration id. Doing the file-system scan (rather than calling
    ``integration_registry()``) sidesteps a startup ordering issue
    where the registry isn't populated by the time the router fires
    its first call.

    Shorter ids are processed first so a generic keyword like "lark"
    binds to ``lark``, not ``lark_calendar`` (specific integrations
    keep their own ids as keys — the generic key just doesn't get
    overwritten).
    """
    if not _INTEGRATIONS_ROOT.is_dir():
        return {}

    integration_ids: List[str] = []
    for child in _INTEGRATIONS_ROOT.iterdir():
        name = child.name
        if name.startswith(("_", ".")) or name == "__pycache__":
            continue
        if child.is_dir():
            integration_ids.append(name)
        elif child.suffix == ".py":
            integration_ids.append(child.stem)

    # Shorter ids first → generic keys (e.g. "lark") land on the simpler one.
    integration_ids.sort(key=len)

    index: Dict[str, str] = {}
    for integration_id in integration_ids:
        keys = {integration_id, integration_id.replace("_", " ")}
        first_token = integration_id.split("_", 1)[0]
        if first_token != integration_id:
            keys.add(first_token)
        for key in keys:
            key = key.lower().strip()
            if key:
                index.setdefault(key, integration_id)
    return index


def _get_keyword_index() -> Dict[str, str]:
    global _KEYWORD_INDEX
    if _KEYWORD_INDEX is None:
        try:
            _KEYWORD_INDEX = _build_keyword_index()
        except Exception:
            _KEYWORD_INDEX = {}
    return _KEYWORD_INDEX


def _extract_essentials(integration_id: str) -> Optional[str]:
    """Extract the ``## Essentials`` block from an integration's docs.

    Looks in two places, in order:
      1. ``<id>/INTEGRATION.md`` (directory-style; used by integrations
         that are themselves a directory, e.g. whatsapp_web with its bridge).
      2. ``<id>.md`` (sibling file; used by single-file integrations).
    """
    candidates = [
        _INTEGRATIONS_ROOT / integration_id / "INTEGRATION.md",
        _INTEGRATIONS_ROOT / f"{integration_id}.md",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(
            r"^##\s+Essentials\s*\n(.*?)(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            return match.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Living UI essentials — injected whenever the task touches a Living UI.
#
# The livingui-CLI knowledge must be IN the prompt before the agent's first
# action: leaving it to skill selection or AGENT.md retrieval is probabilistic
# and has failed in practice (agents default to raw sqlite on "populate the
# kanban" tasks). Same loose-match philosophy as integrations: false
# positives cost ~250 tokens; false negatives cost a failure spiral.
# ---------------------------------------------------------------------------

_LIVINGUI_ESSENTIALS = """### living_ui (operating Living UI apps)
You operate Living UIs ONLY through the `livingui` CLI via run_shell (it is
on PATH — run it bare). NEVER touch living_ui.db with sqlite3/python, never
curl the app directly; the CLI is the single supported path.

Loop: `livingui ls` -> `livingui <project> --help` (capability card: tables,
operations, commands) -> command. Every level supports --help.

- Data (works even when the app is stopped):
  livingui <project> select <table> --where "id<=10" --columns a,b --limit 20
  livingui <project> insert <table> --file rows.json      (bulk: N rows, 1 command)
  livingui <project> update <table> --where "..." --set k=v
  livingui <project> sql "SELECT ... GROUP BY ..."
- App verbs (prefer over raw writes — they run the app's real logic):
  livingui <project> run <op> --params-file params.json
  (ALWAYS use --params-file when any value has spaces/punctuation — inline
  quotes get stripped by the shell; write the JSON file first.)
- Schema/lifecycle: livingui <project> migrate | restart | logs --tail 50
- Errors end with `Try: livingui ...` — run exactly that. If a command
  fails, fix the invocation (usually --params-file); NEVER fall back to
  direct DB access or manual server starts."""

# Cached registry keywords: (mtime, [name/slug/id variants])
_LIVINGUI_KEYWORDS_CACHE: Optional[tuple] = None


def _livingui_keywords() -> List[str]:
    """Registered project names/ids/slugs so mentioning a project by name
    (e.g. 'add these to my kanban board') triggers the essentials."""
    global _LIVINGUI_KEYWORDS_CACHE
    import json
    import os

    workspace = os.environ.get("CRAFTBOT_WORKSPACE") or str(
        Path(__file__).resolve().parents[4] / "agent_file_system" / "workspace"
    )
    registry = Path(workspace) / "living_ui_projects.json"
    try:
        mtime = registry.stat().st_mtime
    except OSError:
        return []
    if _LIVINGUI_KEYWORDS_CACHE and _LIVINGUI_KEYWORDS_CACHE[0] == mtime:
        return _LIVINGUI_KEYWORDS_CACHE[1]
    keywords: List[str] = []
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
        for project in data.get("projects", []):
            name = str(project.get("name", "")).strip().lower()
            if len(name) >= 4:
                keywords.append(name)
            project_id = str(project.get("id", "")).strip().lower()
            if project_id:
                keywords.append(project_id)
            folder = Path(str(project.get("path", ""))).name.lower()
            if folder:
                keywords.append(folder)
    except Exception:
        return []
    _LIVINGUI_KEYWORDS_CACHE = (mtime, keywords)
    return keywords


def _livingui_block(lower_message: str) -> str:
    """Return the Living UI essentials when the text references one."""
    generic = ("living ui", "living_ui", "livingui", "living-ui")
    if any(k in lower_message for k in generic):
        return _LIVINGUI_ESSENTIALS
    for keyword in _livingui_keywords():
        if keyword in lower_message:
            return _LIVINGUI_ESSENTIALS
    return ""


def get_essentials_for_message(message: str) -> str:
    """Build the integration-essentials block for the routing prompt.

    Returns ``""`` when no known integration is mentioned. Otherwise
    returns a tagged block listing each matched integration's essentials,
    deduplicated.
    """
    if not message:
        return ""
    keyword_index = _get_keyword_index()
    if not keyword_index:
        return ""
    lower = message.lower()
    # Longer keys first so e.g. "telegram_user" wins over a bare "telegram".
    sorted_keys = sorted(keyword_index.keys(), key=len, reverse=True)
    matched_ids: List[str] = []
    seen: set = set()
    for key in sorted_keys:
        integration_id = keyword_index[key]
        if integration_id in seen:
            continue
        if key in lower:
            seen.add(integration_id)
            matched_ids.append(integration_id)
    blocks: List[str] = []
    for integration_id in matched_ids:
        essentials = _extract_essentials(integration_id)
        if essentials:
            blocks.append(f"### {integration_id}\n{essentials}")

    # Living UI essentials ride the same injection channel.
    try:
        livingui_block = _livingui_block(lower)
    except Exception:
        livingui_block = ""
    if livingui_block:
        blocks.append(livingui_block)

    if not blocks:
        return ""
    return (
        "<integration_essentials>\n"
        "Workflow guidance for integrations mentioned in the user's message. "
        "Use this BEFORE asking the user for information the integration "
        "could look up itself.\n\n"
        + "\n\n".join(blocks)
        + "\n</integration_essentials>"
    )
