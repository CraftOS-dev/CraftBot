# -*- coding: utf-8 -*-
"""Inject just-in-time integration guidance into the routing-time prompt.

When a user message mentions an integration by name (e.g. "send a whatsapp
message...") — or by a natural bare word like "calendar" / "docs" — this
helper looks up the integration's guidance and injects it into the routing
prompt, so the routing-time LLM has the workflow rules in context BEFORE
deciding what to do.

Guidance sources, in order:
  1. ``craftos_integrations/providers/<id>/GUIDANCE.md`` — multi-account
     providers (the file is already essentials-sized and includes the
     multi-account rules: extract account qualifiers like "my school
     calendar" into the ``account`` param).
  2. ``craftos_integrations/integrations/<id>/INTEGRATION.md`` ``##
     Essentials`` block, or ``<id>.md`` — legacy integrations.

Matching rules:
  - Keys match on WORD BOUNDARIES, not substrings — "drive" fires, but
    "driver" / "hard drive to the airport" wordplay like "doctor" for
    "doc" does not.
  - Multi-token ids contribute their meaningful tokens as keys, so bare
    "calendar" / "docs" / "drive" / "youtube" work (historically only the
    full "google calendar" form matched — the guidance never fired for
    the most natural phrasing).
  - A bare token may map to several integrations ("calendar" →
    google_calendar AND lark_calendar). If connection state is available,
    only connected ones are injected; if none are connected (or state is
    unavailable, e.g. before the registry is populated), all are — false
    positives are cheap, false negatives are the whole reason this exists.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

# Project root → craftos_integrations/{integrations,providers}/...
_PACKAGE_ROOT = Path(__file__).resolve().parents[4] / "craftos_integrations"
_INTEGRATIONS_ROOT = _PACKAGE_ROOT / "integrations"
_PROVIDERS_ROOT = _PACKAGE_ROOT / "providers"

# Tokens too generic to serve as bare keywords ("user" would fire on
# nearly every message; "telegram_user" is still matched via its full id).
_TOKEN_STOPLIST = {"bot", "user", "business", "web", "oauth", "llm", "shared"}

# Built lazily on first call so we don't import the registry at module load.
_KEYWORD_INDEX: Optional[Dict[str, List[str]]] = None


def _integration_ids() -> List[str]:
    """Union of legacy integration ids and multi-account provider ids (fs scan — no
    registry import, sidestepping the startup-ordering issue)."""
    ids: List[str] = []
    for root in (_INTEGRATIONS_ROOT, _PROVIDERS_ROOT):
        if not root.is_dir():
            continue
        for child in root.iterdir():
            name = child.name
            if name.startswith(("_", ".")) or name == "__pycache__":
                continue
            if child.is_dir():
                ids.append(name)
            elif child.suffix == ".py":
                ids.append(child.stem)
    # De-dup, shorter first → generic keys (e.g. "lark") land on the
    # simpler id via the setdefault below.
    return sorted(set(ids), key=len)


def _build_keyword_index() -> Dict[str, List[str]]:
    """Map keyword → integration ids it may refer to."""
    index: Dict[str, List[str]] = {}

    def add(key: str, integration_id: str) -> None:
        key = key.lower().strip()
        if not key:
            return
        ids = index.setdefault(key, [])
        if integration_id not in ids:
            ids.append(integration_id)

    for integration_id in _integration_ids():
        add(integration_id, integration_id)
        add(integration_id.replace("_", " "), integration_id)
        tokens = integration_id.split("_")
        if len(tokens) > 1:
            for token in tokens:
                if token not in _TOKEN_STOPLIST:
                    add(token, integration_id)
    # Natural-language synonyms that no id/token covers ("my job email"
    # names gmail/outlook without saying either). Ambiguity is fine — the
    # connection filter narrows multi-id keys to connected integrations.
    for keyword, ids in {
        "email": ("gmail", "outlook"),
        "inbox": ("gmail", "outlook"),
        "mailbox": ("gmail", "outlook"),
        "crm": ("hubspot",),
    }.items():
        for integration_id in ids:
            add(keyword, integration_id)
    return index


def _get_keyword_index() -> Dict[str, List[str]]:
    global _KEYWORD_INDEX
    if _KEYWORD_INDEX is None:
        try:
            _KEYWORD_INDEX = _build_keyword_index()
        except Exception:
            _KEYWORD_INDEX = {}
    return _KEYWORD_INDEX


def _is_connected(integration_id: str) -> Optional[bool]:
    """Best-effort connection check; None = state unavailable."""
    try:
        from app.integrations import get_system

        system = get_system()
        if system.registry.get(integration_id) is not None:
            return bool(system.list_accounts(integration_id))
    except Exception:
        pass
    try:
        from craftos_integrations import service as legacy_service

        return bool(legacy_service.is_connected(integration_id))
    except Exception:
        return None


def _filter_by_connection(ids: List[str]) -> List[str]:
    """Prefer connected integrations when several share a keyword; keep
    everything if none are (or state can't be read)."""
    if len(ids) < 2:
        return ids
    connected = [i for i in ids if _is_connected(i)]
    return connected or ids


def _connected_accounts_note(integration_id: str) -> str:
    """Live account list for multi-account integrations, appended to the
    injected essentials so the router can map natural phrasing ("my job
    email") to the right alias/identity on the FIRST call instead of
    learning the accounts from a resolution error. Costs a line per
    account, only on turns that mention this integration."""
    try:
        from app.integrations import get_system

        system = get_system()
        if system.registry.get(integration_id) is None:
            return ""
        infos = system.list_accounts(integration_id)
        if not infos:
            return ""
        lines = ", ".join(
            i.identity
            + (f' (alias: "{i.alias}")' if i.alias else "")
            + (" [primary]" if i.is_primary else "")
            for i in infos
        )
        return (
            f"\nConnected accounts: {lines}. When the user's phrasing points "
            f"at one of these (semantically, not just literally), pass its "
            f"alias or identity as `account`."
        )
    except Exception:
        return ""


def _extract_essentials(integration_id: str) -> Optional[str]:
    """Load guidance for one integration (provider GUIDANCE.md first)."""
    v2_guidance = _PROVIDERS_ROOT / integration_id / "GUIDANCE.md"
    if v2_guidance.is_file():
        try:
            text = v2_guidance.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
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
    # Longer keys first so e.g. "google calendar" wins before bare "calendar".
    sorted_keys = sorted(keyword_index.keys(), key=len, reverse=True)
    matched_ids: List[str] = []
    matched_keys: List[str] = []
    seen: set = set()
    for key in sorted_keys:
        # A generic key inside an already-matched specific one adds noise,
        # not signal: "google docs" matched → bare "google" (which maps to
        # every google_* id) must not drag in calendar/drive/youtube.
        if any(key in matched for matched in matched_keys):
            continue
        if not re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lower):
            continue
        matched_keys.append(key)
        for integration_id in _filter_by_connection(keyword_index[key]):
            if integration_id not in seen:
                seen.add(integration_id)
                matched_ids.append(integration_id)
    if not matched_ids:
        return ""
    blocks: List[str] = []
    for integration_id in matched_ids:
        essentials = _extract_essentials(integration_id)
        if essentials:
            blocks.append(
                f"### {integration_id}\n{essentials}"
                + _connected_accounts_note(integration_id)
            )
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
