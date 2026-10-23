# -*- coding: utf-8 -*-
"""Integration guidance delivered with an integration's action schemas.

When an integration's actions are loaded into a session (add_action_sets, a
skill's recommended sets, or a run's declared sets), the schemas arrive in the
event stream together with that integration's workflow guidance, so the model
has the rules in context before its first call. Action sets name either a
provider or one of its underscore-separated subgroups ("github_workflows"
-> github). Only ids that name a provider directory count; the longest
matching provider id owns a subgroup.

Guidance sources, in order:
  1. ``craftos_integrations/providers/<id>/GUIDANCE.md`` — multi-account
     providers (the file is already essentials-sized and includes the
     multi-account rules: extract account qualifiers like "my school
     calendar" into the ``account`` param).
  2. ``craftos_integrations/providers/<id>/INTEGRATION.md`` ``##
     Essentials`` block.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional, Set

# Project root → craftos_integrations/{integrations,providers}/...
_PACKAGE_ROOT = Path(__file__).resolve().parents[4] / "craftos_integrations"
_PROVIDERS_ROOT = _PACKAGE_ROOT / "providers"


def integration_ids() -> Set[str]:
    """Every provider id (fs scan — no registry import, sidestepping the
    startup-ordering issue)."""
    ids: Set[str] = set()
    if _PROVIDERS_ROOT.is_dir():
        for child in _PROVIDERS_ROOT.iterdir():
            name = child.name
            if name.startswith(("_", ".")) or name == "__pycache__":
                continue
            if child.is_dir():
                ids.add(name)
    return ids


def integration_ids_for_action_sets(set_names: Iterable[str]) -> Set[str]:
    """Resolve provider and subgroup sets to their owning provider ids.

    Match whole ids before stripping underscore-separated subgroup suffixes,
    so google_calendar_admin belongs to google_calendar even if a provider
    named google also exists. Unrelated and non-integration sets are ignored.
    """
    providers = integration_ids()
    ids: Set[str] = set()
    for set_name in set_names:
        candidate = set_name
        while candidate:
            if candidate in providers:
                ids.add(candidate)
                break
            candidate = candidate.rpartition("_")[0]
    return ids


def _connected_accounts_note(integration_id: str) -> str:
    """Live account list for multi-account integrations, appended to the
    essentials so the model can map natural phrasing ("my job email") to the
    right alias/identity on the FIRST call instead of learning the accounts
    from a resolution error. Costs a line per account, only when this
    integration's actions are loaded."""
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
    guidance_path = _PROVIDERS_ROOT / integration_id / "GUIDANCE.md"
    if guidance_path.is_file():
        try:
            text = guidance_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
    candidates = [_PROVIDERS_ROOT / integration_id / "INTEGRATION.md"]
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


def get_essentials_for_integrations(ids: Iterable[str]) -> str:
    """Guidance for these integrations: each one's essentials plus its
    connected accounts, under a ``### <id>`` heading per integration.

    Returns ``""`` when none of them has guidance.
    """
    blocks = []
    for integration_id in sorted(set(ids)):
        essentials = _extract_essentials(integration_id)
        if essentials:
            blocks.append(
                f"### {integration_id}\n{essentials}"
                + _connected_accounts_note(integration_id)
            )
    if not blocks:
        return ""
    return (
        "Workflow guidance for these integrations. Use it BEFORE asking the "
        "user for information the integration could look up itself.\n\n"
        + "\n\n".join(blocks)
    )
