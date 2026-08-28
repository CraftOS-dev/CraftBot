"""AccountSet model and every multi-account mutation/resolution rule.

One AccountSet document per provider:

    {"version": 2,
     "primary": "a@x.com",
     "accounts": {
       "a@x.com": {"credential": {...}, "alias": "work", "listen": true,
                    "added_at": "...", "alias_updated_at": "..."},
       ...}}

Invariants (hold through crashes — every mutation is one atomic replace
under the store lock):
  - ``primary`` always points at an existing account; a dangling pointer
    is repaired on load (oldest account wins, logged).
  - Aliases live inside the account record; they die with the account.
  - Identities are stored lowercase; all comparison is case-insensitive.

Resolution contract (agents and UI both) — see AccountResolutionError
messages, which always enumerate valid choices so an LLM self-corrects:
  1. empty hint  → primary
  2. exact identity match          (identity always outranks alias)
  3. exact alias match
  4. unique substring of identity or alias
  5. ambiguous substring → error listing candidates
  6. no match → error listing connected accounts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..contracts import (
    AccountInfo,
    AccountResolutionError,
    CredentialStore,
    UNIDENTIFIED,
)
from ..logger import get_logger

logger = get_logger(__name__)

_VERSION = 2


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AccountRecord:
    credential: Dict[str, Any]
    alias: Optional[str] = None
    listen: bool = True
    added_at: str = ""
    alias_updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "credential": self.credential,
            "alias": self.alias,
            "listen": self.listen,
            "added_at": self.added_at,
            "alias_updated_at": self.alias_updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountRecord":
        return cls(
            credential=data.get("credential") or {},
            alias=data.get("alias"),
            listen=bool(data.get("listen", True)),
            added_at=data.get("added_at") or "",
            alias_updated_at=data.get("alias_updated_at") or "",
        )


@dataclass
class AccountSet:
    primary: str
    accounts: Dict[str, AccountRecord] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": _VERSION,
            "primary": self.primary,
            "accounts": {i: r.to_dict() for i, r in self.accounts.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountSet":
        # Tolerant of unknown keys by construction: only the fields named
        # here are read. Documents written during the interim bridge
        # era carry a ``legacy_coupled`` flag — ignored, never drives
        # any behavior.
        return cls(
            primary=data.get("primary") or "",
            accounts={
                i: AccountRecord.from_dict(r)
                for i, r in (data.get("accounts") or {}).items()
            },
        )

    def oldest_identity(self) -> Optional[str]:
        if not self.accounts:
            return None
        return min(self.accounts, key=lambda i: (self.accounts[i].added_at, i))


class AccountManager:
    """All AccountSet reads/mutations. Pure w.r.t. providers: identities are
    computed by the caller (system layer) and passed in explicitly."""

    def __init__(
        self,
        store: CredentialStore,
        family_members: Optional[Callable[[str], Sequence[str]]] = None,
        clock: Callable[[], str] = _utcnow,
    ) -> None:
        self._store = store
        self._family = family_members or (lambda pid: (pid,))
        self._clock = clock

    # ────────────────────────────────────────────────────────────────────
    # Loading & migration
    # ────────────────────────────────────────────────────────────────────

    def load_set(self, provider_id: str) -> Optional[AccountSet]:
        """Load and repair invariants.

        Pre-multi-account single-credential files are deliberately IGNORED here: the
        manager only reads AccountSet documents. The one-time upgrade
        upgrade — a sentinel record gaining a real identity — happens above
        this layer, which can
        derive a real identity from the provider.
        """
        raw = self._store.load(provider_id)
        if raw is None:
            return None
        account_set = AccountSet.from_dict(raw)
        if self._repair(provider_id, account_set):
            with self._store.locked(provider_id):
                self._store.replace(provider_id, account_set.to_dict())
        return account_set if account_set.accounts else None

    def _repair(self, provider_id: str, account_set: AccountSet) -> bool:
        """Re-point a dangling primary. Returns True if anything changed."""
        if account_set.primary in account_set.accounts:
            return False
        if not account_set.accounts:
            return False
        oldest = account_set.oldest_identity()
        logger.warning(
            f"[ACCOUNTS] {provider_id} primary pointer was dangling "
            f"({account_set.primary!r}); repaired to {oldest!r}"
        )
        account_set.primary = oldest or ""
        return True

    # ────────────────────────────────────────────────────────────────────
    # Reads
    # ────────────────────────────────────────────────────────────────────

    def list_accounts(self, provider_id: str) -> List[AccountInfo]:
        account_set = self.load_set(provider_id)
        if account_set is None:
            return []
        infos = [
            AccountInfo(
                identity=identity,
                alias=record.alias,
                is_primary=identity == account_set.primary,
                listen=record.listen,
                added_at=record.added_at,
            )
            for identity, record in account_set.accounts.items()
        ]
        infos.sort(key=lambda a: (not a.is_primary, a.added_at, a.identity))
        return infos

    def resolve(self, provider_id: str, hint: Optional[str]) -> str:
        account_set = self.load_set(provider_id)
        if account_set is None:
            raise AccountResolutionError(f"{provider_id} is not connected.")
        if hint is None or (isinstance(hint, str) and not hint.strip()):
            return account_set.primary
        if not isinstance(hint, str):
            raise AccountResolutionError(
                f"account must be a string (email, alias, or unique fragment), "
                f"got {type(hint).__name__}. "
                + self._connected_summary(provider_id, account_set)
            )
        needle = hint.strip().lower()

        # 1. exact identity — always outranks alias, so an alias can never
        #    shadow another account's real identity
        for identity in account_set.accounts:
            if identity.lower() == needle:
                return identity
        # 2. exact alias (uniqueness enforced at set_alias time)
        for identity, record in account_set.accounts.items():
            if record.alias and record.alias.lower() == needle:
                return identity
        # 2b. the literal words "primary"/"default" mean the primary account
        #     (models routinely pass account="primary"; observed live
        #     2026-08-21 — the send failed with a resolution error even
        #     though omitting the hint would have used the primary). An
        #     account aliased "primary" wins above; this is only the
        #     fallback meaning.
        if needle in ("primary", "default"):
            return account_set.primary
        # 3. unique substring of identity or alias
        matches = [
            identity
            for identity, record in account_set.accounts.items()
            if needle in identity.lower()
            or (record.alias and needle in record.alias.lower())
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            listed = ", ".join(
                self._describe(i, account_set.accounts[i]) for i in sorted(matches)
            )
            raise AccountResolutionError(
                f"'{hint}' matches multiple {provider_id} accounts: {listed}. "
                f"Use the full email/identity or the exact alias."
            )
        raise AccountResolutionError(
            f"No {provider_id} account matches '{hint}'. "
            + self._connected_summary(provider_id, account_set)
        )

    def credential_for(self, provider_id: str, identity: str) -> Dict[str, Any]:
        account_set = self.load_set(provider_id)
        if account_set is None or identity not in account_set.accounts:
            raise AccountResolutionError(
                f"{provider_id} account '{identity}' is no longer connected."
            )
        return account_set.accounts[identity].credential

    @staticmethod
    def _describe(identity: str, record: AccountRecord) -> str:
        return f"{identity} ({record.alias})" if record.alias else identity

    def _connected_summary(self, provider_id: str, account_set: AccountSet) -> str:
        listed = ", ".join(
            self._describe(i, r) for i, r in sorted(account_set.accounts.items())
        )
        return f"Connected {provider_id} accounts: {listed}."

    # ────────────────────────────────────────────────────────────────────
    # Mutations — each is one locked read-modify-replace
    # ────────────────────────────────────────────────────────────────────

    def upsert_account(
        self,
        provider_id: str,
        identity: Optional[str],
        credential: Dict[str, Any],
    ) -> str:
        """Add or update an account after OAuth. Returns the stored identity.

        A UNIDENTIFIED record is upgraded in place by the first re-auth
        (same credential slot, alias/listen/primary preserved) — the one
        deliberate heuristic in this file: we cannot know whether a single-account
        credential belongs to the account that just authenticated, and
        upgrading beats duplicating (see plan §5)."""
        if not identity:
            raise ValueError(
                f"{provider_id}: refusing to store a credential without an "
                f"identity — the account would be unaddressable. Providers "
                f"must re-prompt instead."
            )
        identity = identity.strip().lower()
        now = self._clock()
        with self._store.locked(provider_id):
            raw = self._store.load(provider_id)
            account_set = AccountSet.from_dict(raw) if raw else AccountSet(primary="")
            if identity in account_set.accounts:
                account_set.accounts[identity].credential = credential
            elif UNIDENTIFIED in account_set.accounts:
                # This provider previously stored a credential it could not
                # derive an identity from. Now that we have one, rename the
                # record in place — a second entry would double the account.
                record = account_set.accounts.pop(UNIDENTIFIED)
                record.credential = credential
                account_set.accounts[identity] = record
                if account_set.primary == UNIDENTIFIED:
                    account_set.primary = identity
                logger.info(
                    f"[ACCOUNTS] {provider_id}: unidentified credential is now "
                    f"identity {identity}"
                )
            else:
                account_set.accounts[identity] = AccountRecord(
                    credential=credential, added_at=now
                )
                if not account_set.primary:
                    account_set.primary = identity
            self._store.replace(provider_id, account_set.to_dict())
        return identity

    def update_credential(
        self, provider_id: str, identity: str, credential: Dict[str, Any]
    ) -> None:
        """Token-refresh write path: touches exactly one account entry."""
        with self._store.locked(provider_id):
            raw = self._store.load(provider_id)
            if raw is None:
                return
            account_set = AccountSet.from_dict(raw)
            record = account_set.accounts.get(identity)
            if record is None:
                logger.warning(
                    f"[ACCOUNTS] refresh for unknown {provider_id} account "
                    f"{identity}; dropped"
                )
                return
            record.credential = credential
            self._store.replace(provider_id, account_set.to_dict())

    def remove_account(self, provider_id: str, hint: Optional[str]) -> str:
        """Remove one account; promotes the oldest remaining if the primary
        was removed; deletes the document when the last account goes.
        Raises AccountResolutionError (no side effects) on a bad hint."""
        identity = self.resolve(provider_id, hint)
        with self._store.locked(provider_id):
            raw = self._store.load(provider_id)
            if raw is None:
                return identity
            account_set = AccountSet.from_dict(raw)
            if identity not in account_set.accounts:
                return identity
            del account_set.accounts[identity]
            if not account_set.accounts:
                self._store.delete(provider_id)
                return identity
            if account_set.primary == identity:
                account_set.primary = account_set.oldest_identity() or ""
                logger.info(
                    f"[ACCOUNTS] {provider_id}: removed primary {identity}; "
                    f"promoted {account_set.primary}"
                )
            self._store.replace(provider_id, account_set.to_dict())
        return identity

    def set_primary(self, provider_id: str, hint: Optional[str]) -> str:
        identity = self.resolve(provider_id, hint)
        with self._store.locked(provider_id):
            raw = self._store.load(provider_id)
            if raw is None:
                raise AccountResolutionError(f"{provider_id} is not connected.")
            account_set = AccountSet.from_dict(raw)
            if identity not in account_set.accounts:
                raise AccountResolutionError(
                    f"{provider_id} account '{identity}' is no longer connected."
                )
            account_set.primary = identity
            self._store.replace(provider_id, account_set.to_dict())
        return identity

    def set_listening(self, provider_id: str, hint: Optional[str], on: bool) -> str:
        identity = self.resolve(provider_id, hint)
        with self._store.locked(provider_id):
            raw = self._store.load(provider_id)
            if raw is None:
                raise AccountResolutionError(f"{provider_id} is not connected.")
            account_set = AccountSet.from_dict(raw)
            record = account_set.accounts.get(identity)
            if record is None:
                raise AccountResolutionError(
                    f"{provider_id} account '{identity}' is no longer connected."
                )
            record.listen = on
            self._store.replace(provider_id, account_set.to_dict())
        return identity

    # ────────────────────────────────────────────────────────────────────
    # Aliases — family-aware
    # ────────────────────────────────────────────────────────────────────

    def set_alias(
        self, provider_id: str, hint: Optional[str], alias: Optional[str]
    ) -> str:
        """Set (or clear, alias=None) an alias; propagates to the same
        identity across the provider's family. Enforces family-wide
        uniqueness and forbids aliases that equal any connected identity
        (they could never win resolution anyway — rule 2 outranks them)."""
        identity = self.resolve(provider_id, hint)
        if alias is not None:
            alias = alias.strip()
            if not alias:
                alias = None
        family = list(self._family(provider_id))
        if alias is not None:
            self._check_alias_free(provider_id, family, alias, identity)
        now = self._clock()
        # Ordered locking (sorted pids) so two concurrent family-wide writes
        # can't deadlock; per-file partial failure is healed by
        # sync_family_aliases() on the next list_accounts().
        for pid in sorted(set(family) | {provider_id}):
            with self._store.locked(pid):
                raw = self._store.load(pid)
                if raw is None:
                    continue
                account_set = AccountSet.from_dict(raw)
                record = account_set.accounts.get(identity)
                if record is None:
                    continue
                record.alias = alias
                record.alias_updated_at = now
                self._store.replace(pid, account_set.to_dict())
        return identity

    def _check_alias_free(
        self, provider_id: str, family: Sequence[str], alias: str, identity: str
    ) -> None:
        needle = alias.lower()
        for pid in family:
            raw = self._store.load(pid)
            if raw is None:
                continue
            account_set = AccountSet.from_dict(raw)
            for other_identity, record in account_set.accounts.items():
                if other_identity == identity:
                    continue
                if other_identity.lower() == needle:
                    raise ValueError(
                        f"'{alias}' is another connected account's identity "
                        f"({other_identity} on {pid}) — pick a different nickname."
                    )
                if record.alias and record.alias.lower() == needle:
                    raise ValueError(
                        f"'{alias}' is already the nickname of {other_identity} "
                        f"on {pid} — nicknames must be unique."
                    )

    def sync_family_aliases(self, provider_id: str) -> None:
        """Heal partial family alias writes: for each identity, the alias
        with the newest alias_updated_at across the family wins everywhere.
        Called from UI-facing paths (list flows), not from resolve()."""
        family = sorted(set(self._family(provider_id)))
        if len(family) < 2:
            return
        newest: Dict[str, Tuple[str, Optional[str]]] = {}
        sets: Dict[str, AccountSet] = {}
        for pid in family:
            raw = self._store.load(pid)
            if raw is None:
                continue
            sets[pid] = AccountSet.from_dict(raw)
            for identity, record in sets[pid].accounts.items():
                stamp = record.alias_updated_at
                if identity not in newest or stamp > newest[identity][0]:
                    newest[identity] = (stamp, record.alias)
        for pid, account_set in sets.items():
            changed = False
            for identity, record in account_set.accounts.items():
                stamp, alias = newest.get(identity, ("", None))
                if stamp and (record.alias != alias):
                    record.alias = alias
                    record.alias_updated_at = stamp
                    changed = True
            if changed:
                with self._store.locked(pid):
                    self._store.replace(pid, account_set.to_dict())

    # ────────────────────────────────────────────────────────────────────
    # Batched UI save
    # ────────────────────────────────────────────────────────────────────

    def apply_changes(
        self, provider_id: str, batch: Dict[str, Any]
    ) -> List[AccountInfo]:
        """Apply a staged UI batch in deterministic order:
        disconnects → primary → aliases → listen flags.

        ``batch`` = {"disconnect": [hint...], "primary": hint | None,
                     "aliases": {hint: alias|None}, "listen": {hint: bool}}

        Raises on the first failing step; earlier steps stay applied (each
        is individually atomic and valid) and the UI re-renders from the
        returned/refetched account list."""
        for hint in batch.get("disconnect") or []:
            self.remove_account(provider_id, hint)
        if batch.get("primary") is not None:
            self.set_primary(provider_id, batch["primary"])
        for hint, alias in (batch.get("aliases") or {}).items():
            self.set_alias(provider_id, hint, alias)
        for hint, on in (batch.get("listen") or {}).items():
            self.set_listening(provider_id, hint, bool(on))
        self.sync_family_aliases(provider_id)
        return self.list_accounts(provider_id)
