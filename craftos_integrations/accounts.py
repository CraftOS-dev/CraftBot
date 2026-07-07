"""Generic multi-account primitives, shared by every integration that
supports more than one connected account (Gmail, Outlook, Slack, ...).

An "account" here means one saved credential file for a given integration:
the bare ``<stem>.json`` is always the *primary* account (so a pre-existing
single-account install needs no migration); every other connected account
gets ``<stem>__<sanitized-identity>.json`` (see
``credentials_store.account_filename``).

Each integration supplies one thing this module doesn't know on its own:
``identity_of(cred) -> str`` — the human-identifying string pulled out of
its own credential dataclass (an email, a Slack team ID, a HubSpot hub ID,
...). Everything else here — listing, resolving a user-typed hint, placing
a freshly-authenticated credential, aliasing, promoting to primary — is
generic file manipulation that never needs to know what that string means.

Aliases (user-given names like "work"/"personal") are stored separately in
``account_aliases.json``, keyed by ``(platform_id, identity)`` — decoupled
from every credential dataclass so adding aliasing never requires touching
one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple, Type, TypeVar

from .credentials_store import (
    _credentials_dir,
    account_filename,
    has_credential,
    list_account_files,
    load_credential,
    remove_credential,
)

T = TypeVar("T")
IdentityFn = Callable[[T], str]

_ALIASES_FILE = "account_aliases.json"


# ════════════════════════════════════════════════════════════════════════
# Aliases — flat JSON dict, decoupled from any credential dataclass
# ════════════════════════════════════════════════════════════════════════


def _alias_store() -> dict:
    path = _credentials_dir() / _ALIASES_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_alias_store(data: dict) -> None:
    path = _credentials_dir() / _ALIASES_FILE
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _alias_key(platform_id: str, identity: str) -> str:
    return f"{platform_id}:{identity.strip().lower()}"


def get_alias(platform_id: str, identity: str) -> Optional[str]:
    return _alias_store().get(_alias_key(platform_id, identity))


def set_alias(platform_id: str, identity: str, alias: str) -> None:
    """Empty/whitespace-only ``alias`` clears any existing alias."""
    data = _alias_store()
    key = _alias_key(platform_id, identity)
    if alias and alias.strip():
        data[key] = alias.strip()
    else:
        data.pop(key, None)
    _save_alias_store(data)


def remove_alias(platform_id: str, identity: str) -> None:
    data = _alias_store()
    if data.pop(_alias_key(platform_id, identity), None) is not None:
        _save_alias_store(data)


# ════════════════════════════════════════════════════════════════════════
# Listing + resolving
# ════════════════════════════════════════════════════════════════════════


@dataclass
class Account:
    identity: str  # provider-native identifier (email, team id, hub id, ...)
    filename: str  # credential file on disk, relative to .credentials/
    alias: Optional[str] = None
    is_primary: bool = False

    @property
    def display(self) -> str:
        return self.alias or self.identity


def list_accounts(
    platform_id: str, stem: str, cred_class: Type[T], identity_of: IdentityFn
) -> List[Account]:
    """Every connected account for this integration, primary first."""
    accounts: List[Account] = []
    primary_file = f"{stem}.json"
    if has_credential(primary_file):
        cred = load_credential(primary_file, cred_class)
        if cred:
            identity = identity_of(cred)
            accounts.append(
                Account(identity, primary_file, get_alias(platform_id, identity), True)
            )
    for fname in list_account_files(stem):
        cred = load_credential(fname, cred_class)
        if cred:
            identity = identity_of(cred)
            accounts.append(Account(identity, fname, get_alias(platform_id, identity), False))
    return accounts


def resolve_account(
    platform_id: str,
    stem: str,
    cred_class: Type[T],
    identity_of: IdentityFn,
    account: Optional[str],
    display_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a user/agent-supplied hint to a credential filename.

    The hint may be empty (→ primary), an exact identity or alias match
    (case-insensitive), or a substring unique to exactly one connected
    account's identity or alias. Returns ``(filename, None)`` on success or
    ``(None, error)`` — the error always lists connected accounts (by alias
    where set, else identity) so the caller can self-correct without a
    separate lookup.
    """
    accounts = list_accounts(platform_id, stem, cred_class, identity_of)

    if not account:
        if not accounts:
            return None, f"{display_name}: Not connected. Connect an account first."
        primary = next((a for a in accounts if a.is_primary), accounts[0])
        return primary.filename, None

    needle = account.strip().lower()
    for a in accounts:
        if a.identity.lower() == needle or (a.alias and a.alias.lower() == needle):
            return a.filename, None

    matches = [
        a
        for a in accounts
        if needle in a.identity.lower() or (a.alias and needle in a.alias.lower())
    ]
    if len(matches) == 1:
        return matches[0].filename, None

    connected = ", ".join(a.display for a in accounts) or "none"
    if not matches:
        return None, f"No {display_name} account matches '{account}'. Connected: {connected}."
    return None, (
        f"'{account}' matches multiple {display_name} accounts: "
        f"{', '.join(a.display for a in matches)}. Use the full name or email."
    )


def resolve_save_target(
    stem: str, cred_class, identity_of: IdentityFn, identity: str
) -> str:
    """Decide which file a freshly-authenticated credential should be saved
    to: update an existing account in place if its identity already matches
    one on disk, fill the empty primary slot if nothing is connected yet, or
    allocate a new secondary file. Every integration's login()/invite()
    calls this right before ``save_credential``.
    """
    primary_file = f"{stem}.json"
    for fname in [primary_file, *list_account_files(stem)]:
        if not has_credential(fname):
            continue
        cred = load_credential(fname, cred_class)
        if cred and identity_of(cred).lower() == identity.lower():
            return fname
    if not has_credential(primary_file):
        return primary_file
    return account_filename(stem, identity)


# ════════════════════════════════════════════════════════════════════════
# Removing + promoting
# ════════════════════════════════════════════════════════════════════════


def remove_all_accounts(stem: str) -> None:
    """Delete every connected account (primary + all secondaries) for this
    integration — no promotion, since nothing is left to promote into.
    Used by "logout everything" flows."""
    remove_credential(f"{stem}.json")
    for fname in list_account_files(stem):
        remove_credential(fname)


def remove_account(stem: str, target_filename: str) -> bool:
    """Remove one connected account. If it was the primary and another
    account remains, promotes one of them into the now-empty bare file so
    the integration stays connected instead of silently dropping to
    "not connected" while a secondary file still exists.
    """
    primary_file = f"{stem}.json"
    was_primary = target_filename == primary_file
    removed = remove_credential(target_filename)
    if was_primary:
        remaining = list_account_files(stem)
        if remaining:
            _fill_empty_primary(stem, remaining[0])
    return removed


def _fill_empty_primary(stem: str, source_filename: str) -> None:
    """Move a secondary account's raw content into the (already-empty)
    bare primary file, then remove the now-duplicate secondary file."""
    dir_ = _credentials_dir()
    source_path = dir_ / source_filename
    data = json.loads(source_path.read_text(encoding="utf-8"))
    (dir_ / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    remove_credential(source_filename)


def promote_to_primary(stem: str, target_filename: str) -> bool:
    """Make ``target_filename`` the primary account by swapping its raw file
    content with the bare ``<stem>.json``.

    Filenames are opaque identifiers once written — an account's real
    identity always lives in the file *content* (read via ``identity_of``),
    so a secondary file keeping its now-stale, mismatched name after a swap
    is cosmetic only; nothing in ``resolve_account``/``list_accounts`` ever
    reads meaning from a filename. Returns False if ``target_filename`` is
    already the primary or doesn't exist.
    """
    primary_file = f"{stem}.json"
    if target_filename == primary_file or not has_credential(target_filename):
        return False
    dir_ = _credentials_dir()
    primary_path, target_path = dir_ / primary_file, dir_ / target_filename
    primary_data = (
        json.loads(primary_path.read_text(encoding="utf-8")) if primary_path.exists() else None
    )
    target_data = json.loads(target_path.read_text(encoding="utf-8"))
    if primary_data is not None:
        target_path.write_text(json.dumps(primary_data, indent=2, default=str), encoding="utf-8")
    else:
        remove_credential(target_filename)
    primary_path.write_text(json.dumps(target_data, indent=2, default=str), encoding="utf-8")
    return True


# ════════════════════════════════════════════════════════════════════════
# Structured account listing for get_integration_info (bypasses the
# fragile "- name (id)" status-string parsing for integrations that
# support aliasing/primary — see service.get_integration_info).
# ════════════════════════════════════════════════════════════════════════


def accounts_to_dicts(accounts: List[Account]) -> List[dict]:
    return [
        {
            "id": a.identity,
            "display": a.display,
            "alias": a.alias,
            "is_primary": a.is_primary,
        }
        for a in accounts
    ]
