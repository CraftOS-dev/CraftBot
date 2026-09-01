# -*- coding: utf-8 -*-
"""
What the agent and the user each SEE of a Agent App.

Two jobs, both about presentation rather than mechanism:

1. `schema_block()` — the app's data model, inlined into the agent's prompt.
   Advisory pointers do not work on weak models: across two recorded incidents
   the agent ignored "Read AGENT_APP.md", never ran `lui ops`, and guessed
   collection names instead (`items`, `tasks`). It cannot ignore what is
   already in its context.

2. `humanise_write()` — one plain sentence describing what a write actually
   did, built from the stored record. The user should never read
   `cards.create [kapp872i5etufxb] due_date='2026-07-31 00:00:00.000Z'`.

Both read the app's own A2APP `describe` surface, so neither can drift from
what the app actually is.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from app.logger import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

# describe is cheap but not free, and it is fetched on every user message.
# A few minutes of staleness is harmless: the app validates writes itself, so
# a stale block can only cost a retry, never a bad write.
_CACHE: Dict[str, tuple] = {}
_TTL_SECONDS = 300
_TIMEOUT_SECONDS = 2.0

_SKIP_FIELDS = {"id", "collectionId", "collectionName", "created", "updated"}


def _describe(base_url: str) -> Optional[Dict[str, Any]]:
    """Fetch (and cache) the app's data model. None when the app is down."""
    cached = _CACHE.get(base_url)
    if cached is not None and time.time() - cached[0] < _TTL_SECONDS:
        return cached[1]
    try:
        request = urllib.request.Request(
            f"{base_url}/api/_a2app/describe", headers={"User-Agent": "CraftBot"}
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        _CACHE[base_url] = (time.time(), data)
        return data
    except Exception as e:
        logger.debug(f"[AGENT_VIEW] describe unavailable at {base_url}: {e}")
        _CACHE[base_url] = (time.time(), None)
        return None


def _type_label(spec: Dict[str, Any]) -> str:
    """Render a field's type the way the agent needs to see it — including the
    enum's actual values, whose absence caused a rejected write."""
    kind = str(spec.get("type", "string"))
    if kind == "enum" and spec.get("values"):
        return "one of " + "|".join(str(v) for v in spec["values"])
    if kind in ("ref", "list<ref>") and spec.get("entity"):
        arrow = "->" if kind == "ref" else "->[]"
        return f"{arrow}{spec['entity']}"
    if spec.get("format"):
        return str(spec["format"])
    return kind


def schema_block(base_url: str, max_chars: int = 2000) -> Optional[str]:
    """The data model, compact enough to sit in every prompt.

    Read-only and server-managed fields are omitted: the agent cannot write
    them, so naming them only invites it to try.
    """
    described = _describe(base_url)
    if not described:
        return None
    entities = described.get("entities") or {}
    if not entities:
        return None

    lines = []
    for name, entity in entities.items():
        fields = []
        for field_name, spec in (entity.get("fields") or {}).items():
            if spec.get("readOnly"):
                continue
            star = "*" if spec.get("required") else ""
            fields.append(f"{field_name}({_type_label(spec)}){star}")
        if fields:
            lines.append(f"  {name}: {' '.join(fields)}")
        else:
            # Silently omitting an empty collection HID the evidence of a
            # failed migration once (a weather app whose readings collection
            # held only `id` rendered 0° everywhere). Show the anomaly — the
            # agent can only reason about what it can see.
            lines.append(
                f"  {name}: NO WRITABLE FIELDS — writes to it are silently dropped"
            )

    block = "\n".join(lines)
    if len(block) > max_chars:  # very large apps: names only, still better than nothing
        block = "\n".join(
            f"  {n}: {len((e.get('fields') or {}))} fields" for n, e in entities.items()
        )
    return block


_CAP_CACHE: Dict[str, tuple] = {}
_CAP_TTL_SECONDS = 300

# Names that read as a read. Weak evidence on its own, which is why it only
# ever narrows a choice here and never widens one.
_READ_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "find_",
    "check_",
    "fetch_",
    "read_",
    "download_",
)


def _is_safe(meta) -> bool:
    """Metadata's best guess at "changes nothing" — good enough to ORDER by,
    never good enough to recommend a call on.

    Classifying by name prefix was tried first and dropped every action
    matching neither list (forward_gmail, reply_gmail, trash_gmail …) out of
    BOTH buckets. The flags never drop anything: irreversible is the
    provider's `destructive`, and everything else falls in here. But they
    also do not mean what the name suggests — `parallelizable` defaults True
    and providers set it False only on SOME writes, so create_gmail_draft,
    create_google_meet and create_google_doc all land in this bucket. Both
    buckets are printed, so a misfile costs a line of ordering. It must not
    cost more than that: see _probe_action.
    """
    return not getattr(meta, "irreversible", False) and getattr(
        meta, "parallelizable", False
    )


def _probe_action(safe: List[tuple]) -> str:
    """The one call an app may make JUST to ask "is this connected?".

    Both conditions are required, because a wrong answer here is worse than
    no answer at all:

    - the NAME must read as a read. The flags cannot be trusted for this —
      create_google_doc carries neither `destructive` nor `parallelizable`,
      scored as safe, took the fewest parameters, and won the pick. Every app
      checking whether Google Docs was connected would have created a blank
      document in the user's Drive, one line under a sentence saying "never a
      send/create".
    - it must take NO arguments. get_google_doc_text is a genuine read that
      wants a document_id the app hasn't got: it would fail, and the app
      would report "not connected" — the original bug wearing a new hat.

    Nothing qualifies for google_docs, google_drive or hubspot today, so they
    get no named probe. The general instruction still tells the app to call a
    read; naming nothing beats naming a write.
    """
    ranked = sorted(
        n
        for n, m in safe
        if n.startswith(_READ_PREFIXES)
        and set((getattr(m, "input_schema", None) or {}).keys()) <= {"account"}
    )
    return ranked[0] if ranked else ""


def capability_block() -> Optional[str]:
    """What the app CAN reach through the bridge — connected integrations
    with their key actions, plus the facts that kill recurring myths.

    Injected (not referenced): three separate builds invented an SMTP
    requirement and stubbed the user's email feature because nothing in
    context said `send_gmail` exists. Weak models fail on missing facts,
    not on fifteen extra lines. ~300 tokens, cached 5 minutes.
    """
    cached = _CAP_CACHE.get("caps")
    if cached is not None and time.time() - cached[0] < _CAP_TTL_SECONDS:
        return cached[1]

    block: Optional[str] = None
    try:
        from craftos_integrations import get_registered_platforms
        from agent_core.core.action_framework.registry import ActionRegistry
        from app.data.action.integrations._helpers import system_for

        connected, disconnected = [], []
        for pid in get_registered_platforms():
            try:
                system = system_for(pid)
                ok = bool(system and system.list_accounts(pid))
            except Exception:
                ok = False
            (connected if ok else disconnected).append(pid)

        # Key actions per connected integration, from the registry's
        # action_sets convention (["gmail_mail", "gmail"] → gmail). Both
        # KINDS are shown and capped separately: sorting writes first and then
        # truncating showed Gmail as four ways to send and pushed
        # get_gmail_profile behind the ellipsis, so an app that only wanted to
        # know whether Gmail was CONNECTED probed with send_gmail and died on
        # the irreversible gate. A safe action must always be in view.
        registry = ActionRegistry().list_all_actions()
        by_integration: Dict[str, list] = {pid: [] for pid in connected}
        for action_name, impls in registry.items():
            impl = impls.get("all") or next(iter(impls.values()), None)
            if impl is None:
                continue
            sets = set(getattr(impl.metadata, "action_sets", None) or [])
            for pid in connected:
                if pid in sets:
                    by_integration[pid].append((action_name, impl.metadata))

        probes: Dict[str, str] = {}
        shown_by: Dict[str, tuple] = {}
        for pid, entries in by_integration.items():
            safe = [(n, m) for n, m in entries if _is_safe(m)]
            # Everything not safe is a change — no third bucket to fall into,
            # so nothing can silently vanish from the block the way a
            # prefix test dropped forward_gmail and reply_gmail.
            #
            # ORDER, unlike membership, is not in the metadata: "which write
            # will an app reach for" is a judgement no flag records, and
            # alphabetically Gmail leads with batch_delete_gmail while
            # send_gmail sits 20 names down — the exact invisibility that had
            # three builds inventing an SMTP requirement. A name hint decides
            # the order only; it can no longer decide membership, so the worst
            # it can do now is bury a name, never drop one.
            changing = sorted(
                (n for n, m in entries if not _is_safe(m)),
                key=lambda n: (not n.startswith(("send_", "post_", "create_")), n),
            )
            probe = _probe_action(safe)
            probes[pid] = probe
            # The probe leads its group: alphabetically it loses to id-taking
            # reads (get_gmail before get_gmail_profile) and would fall off
            # the cap, which is the whole bug this shape exists to fix.
            safe_names = sorted(n for n, _ in safe)
            if probe:
                safe_names = [probe] + [n for n in safe_names if n != probe]
            shown_by[pid] = (changing[:3], safe_names[:3], len(entries))

        lines = ["[INTEGRATIONS this app can use — bridge.callAction(name, params)]"]
        for pid in sorted(connected):
            changing, safe_names, total = shown_by.get(pid) or ([], [], 0)
            names = changing + safe_names
            shown = ", ".join(names) + (", …" if total > len(names) else "")
            lines.append(
                f"  connected: {pid} ({shown})" if names else f"  connected: {pid}"
            )
        if disconnected:
            lines.append(
                "  NOT connected (user must connect in CraftBot first): "
                + ", ".join(sorted(disconnected))
            )
        lines.append(
            "  FACTS: There is NO SMTP and NO API-key config anywhere in this platform —\n"
            "  email IS callAction('send_gmail', {subject, body}, {confirmIrreversible: true});\n"
            "  omit 'to' to email the user. Credentials are injected by the bridge; never\n"
            "  ask the user for keys, never stub a feature 'until SMTP is configured'."
        )
        # To CHECK a connection, call a read. An app once probed Gmail with
        # send_gmail (the only action its capability line showed) and reported
        # the irreversible-confirmation refusal to the user as "not connected".
        probe_examples = ", ".join(
            f"{pid} → callAction('{probes[pid]}')"
            for pid in sorted(connected)
            if probes.get(pid)
        )
        # The RULE is stated for every connected integration; the named call
        # only where one is provably safe AND argument-free (_probe_action).
        # Where none exists the app picks its own read — a weaker answer, but
        # the only honest one.
        if connected:
            check = (
                "  CONNECTION CHECKS: to show whether an integration is connected, call a\n"
                "  READ action (get_*/list_*) and treat a 2xx as connected — never a\n"
                "  send/create, and never one that needs an id you do not have."
            )
            if probe_examples:
                check += f"\n  Use: {probe_examples}."
            lines.append(check)
        block = "\n".join(lines)
    except Exception as e:
        logger.debug(f"[AGENT_VIEW] capability block unavailable: {e}")
        block = None

    _CAP_CACHE["caps"] = (time.time(), block)
    return block


def _resolve_ref(base_url: str, entity: str, record_id: str) -> Optional[str]:
    """A referenced record's human label, so the user reads 'To Do' not an id."""
    described = _describe(base_url)
    if not described:
        return None
    target = (described.get("entities") or {}).get(entity) or {}
    label_field = target.get("label")
    if not label_field:
        return None
    try:
        url = f"{base_url}/api/collections/{entity}/records/{record_id}"
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
            record = json.loads(response.read().decode("utf-8"))
        value = record.get(label_field)
        return str(value) if value else None
    except Exception:
        return None


def _humanise_date(value: str) -> str:
    """'2026-07-31 00:00:00.000Z' -> 'Fri 31 Jul'. Times are kept when present."""
    text = str(value).strip()
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    except Exception:
        return text[:10] or text
    if stamp.hour == 0 and stamp.minute == 0:
        return stamp.strftime("%a %-d %b")
    return stamp.strftime("%a %-d %b %H:%M")


_VERBS = {"create": "Added", "update": "Updated", "delete": "Removed"}


def humanise_write(
    base_url: str, collection: str, op: str, record: Dict[str, Any]
) -> str:
    """One sentence a person can read, built from what was actually stored.

    Example: Added "Eat chicken" to To Do — due Fri 31 Jul, priority medium
    """
    described = _describe(base_url)
    entities = (described or {}).get("entities") or {}
    entity = entities.get(collection) or {}
    specs = entity.get("fields") or {}
    label_field = entity.get("label")

    name = record.get(label_field) if label_field else None
    verb = _VERBS.get(op, "Changed")
    subject = f'"{name}"' if name else f"a {collection.rstrip('s')}"

    into = ""
    details = []
    for key, value in record.items():
        if key in _SKIP_FIELDS or key == label_field:
            continue
        if value in ("", None, [], {}, False, 0):
            continue
        spec = specs.get(key) or {}
        kind = str(spec.get("type", ""))

        if kind == "ref" and spec.get("entity"):
            resolved = _resolve_ref(base_url, str(spec["entity"]), str(value))
            if resolved and not into:
                into = f" to {resolved}"  # the containing thing reads best inline
                continue
            details.append(f"{key.replace('_', ' ')} {resolved or value}")
        elif kind == "datetime":
            details.append(
                f"{key.replace('_', ' ').replace(' date', '')} {_humanise_date(value)}"
            )
        elif kind in ("json", "binary", "list<ref>"):
            continue  # nothing a person wants to read
        else:
            details.append(f"{key.replace('_', ' ')} {value}")

    sentence = f"{verb} {subject}{into}"
    if details:
        sentence += " — " + ", ".join(details[:4])
    return sentence
