"""IntegrationSystem — the single object a host embeds.

Multi-account is handled HERE, uniformly: ``execute()`` resolves
``account → identity → client`` once, centrally. Providers and their
operations never see account selection — they receive a ready client.
Host adapters advertise the ``account`` input on every generated action
schema in one place, so partial coverage is impossible by construction.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import (
    AccountInfo,
    CredentialStore,
    EventSink,
    LEGACY_IDENTITY,
    OAuthTransport,
    Operation,
    Provider,
)
from ..logger import get_logger
from .accounts import AccountManager
from .registry import IntegrationRegistry

logger = get_logger(__name__)


class IntegrationSystem:
    def __init__(
        self,
        store: CredentialStore,
        oauth: Optional[OAuthTransport] = None,
        sink: Optional[EventSink] = None,
        providers: Optional[List[Provider]] = None,
    ) -> None:
        self.registry = IntegrationRegistry()
        for provider in providers or []:
            self.registry.register(provider)
        self.accounts = AccountManager(
            store, family_members=self.registry.family_members
        )
        self._store = store
        self._oauth = oauth
        self._sink = sink
        # Optional ListenerManager, attached by the host after construction
        # (system.listeners = manager). Mutation paths poke it via
        # reconcile_listeners() so UI changes take effect immediately.
        self.listeners: Optional[Any] = None

    # ── capability discovery ─────────────────────────────────────────────

    def providers(self) -> List[Provider]:
        return self.registry.all_providers()

    def operations(self, provider_id: Optional[str] = None) -> List[Operation]:
        if provider_id is not None:
            provider = self._require_provider(provider_id)
            return provider.operations()
        return [op for p in self.registry.all_providers() for op in p.operations()]

    def guidance(self, connected_only: bool = True) -> str:
        sections = []
        for provider in self.registry.all_providers():
            if connected_only and not self.accounts.list_accounts(provider.id):
                continue
            text = provider.guidance().strip()
            if text:
                sections.append(text)
        return "\n\n".join(sections)

    # ── execution ────────────────────────────────────────────────────────

    async def execute(
        self,
        provider_id: str,
        op_name: str,
        input_data: Dict[str, Any],
        account: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one operation against one resolved account.

        Raises AccountResolutionError for bad hints (hosts map it to their
        error envelope — the message is written for LLM self-correction).
        Operation-level failures are whatever the operation returns/raises."""
        provider = self._require_provider(provider_id)
        operation = next(
            (op for op in provider.operations() if op.name == op_name), None
        )
        if operation is None:
            raise LookupError(f"{provider_id} has no operation '{op_name}'")
        self._migrate_legacy(provider)
        identity = self.accounts.resolve(provider_id, account)
        client = self._client_for(provider, identity)
        return await operation.fn(client, input_data)

    def _migrate_legacy(self, provider: Provider) -> None:
        """One-time upgrade migration for pre-multi-account installs (≤ V1.4.2).

        A legacy single-account credential file with NO AccountSet document is
        imported as the provider's first account, under a
        provider-derived identity (the LEGACY sentinel when the credential
        predates identity capture — upgraded in place on the next re-auth).
        Once an AccountSet document exists the legacy file is never consulted again;
        removing the last account deletes BOTH files (see
        ``remove_account``), so a disconnect can never resurrect through
        this path.
        """
        store = self._store
        if not hasattr(store, "load_legacy"):
            return
        pid = provider.id
        try:
            if hasattr(store, "has_document"):
                if store.has_document(pid):
                    return
            elif store.load(pid) is not None:
                return
            credential = store.load_legacy(pid)
            if not credential:
                return
            identity = provider.identity_of(credential) or LEGACY_IDENTITY
            stored = self.accounts.upsert_account(pid, identity, credential)
            self.registry.invalidate(pid, stored)
            logger.info(
                f"[INTEGRATIONS] migrated legacy {pid} credential to account '{stored}'"
            )
        except Exception as e:
            logger.warning(f"[INTEGRATIONS] legacy migration for {pid} failed: {e}")

    def _delete_legacy_if_disconnected(self, provider_id: str) -> None:
        """After a removal that may have deleted the AccountSet document (last
        account gone), delete the legacy credential file too — otherwise
        the one-time upgrade migration would re-import it on the next load
        and resurrect the just-disconnected account. Best-effort."""
        store = self._store
        if not hasattr(store, "delete_legacy"):
            return
        try:
            if hasattr(store, "has_document"):
                if store.has_document(provider_id):
                    return
            elif store.load(provider_id) is not None:
                return
            store.delete_legacy(provider_id)
        except Exception as e:
            logger.warning(
                f"[INTEGRATIONS] legacy cleanup for {provider_id} failed: {e}"
            )

    def _client_for(self, provider: Provider, identity: str) -> Any:
        cached = self.registry.get_cached_client(provider.id, identity)
        if cached is not None:
            return cached
        credential = self.accounts.credential_for(provider.id, identity)

        def persist(updated: Dict[str, Any]) -> None:
            self.accounts.update_credential(provider.id, identity, updated)

        client = provider.build_client(credential, persist)
        self.registry.cache_client(provider.id, identity, client)
        return client

    def client_for(self, provider_id: str, identity: str) -> Any:
        """Public client path for core plumbing (e.g. ListenerManager):
        cached-or-built client bound to one resolved account."""
        return self._client_for(self._require_provider(provider_id), identity)

    def reconcile_listeners(self) -> None:
        """Fire-and-forget listener reconcile, safe from any context.

        No-op when no manager is attached. Never raises — listener
        fan-out is best-effort from mutation paths; the next startup
        reconcile catches anything missed here."""
        manager = self.listeners
        if manager is None:
            return
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(manager.reconcile())
                return
            # Called from sync/non-loop context: hop onto the manager's
            # own loop if it has one running; otherwise skip quietly.
            manager_loop = getattr(manager, "loop", None)
            if manager_loop is not None and manager_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    manager.reconcile(), manager_loop
                )
        except Exception as e:
            logger.warning(f"[INTEGRATIONS] listener reconcile scheduling failed: {e}")

    # ── account management (drives any settings UI) ──────────────────────

    def list_accounts(self, provider_id: str) -> List[AccountInfo]:
        provider = self.registry.get(provider_id)
        if provider is not None:
            self._migrate_legacy(provider)
        self.accounts.sync_family_aliases(provider_id)
        return self.accounts.list_accounts(provider_id)

    def resolve(self, provider_id: str, hint: Optional[str]) -> str:
        return self.accounts.resolve(provider_id, hint)

    def set_alias(
        self, provider_id: str, hint: Optional[str], alias: Optional[str]
    ) -> str:
        identity = self.accounts.set_alias(provider_id, hint, alias)
        for pid in self.registry.family_members(provider_id):
            self.registry.invalidate(pid, identity)
        return identity

    async def add_account(self, provider_id: str) -> Tuple[bool, str, List[AccountInfo]]:
        """Interactive OAuth add-account flow, driven by the provider's
        ``run_login()``. Returns (ok, message, accounts-after).

        A provider without ``run_login`` (token-entry-only integrations)
        raises LookupError — hosts surface that as "connect via settings".
        An identity-less success is still stored (under LEGACY_IDENTITY,
        upgraded in place on the next re-auth)."""
        provider = self._require_provider(provider_id)
        run_login = getattr(provider, "run_login", None)
        if run_login is None:
            raise LookupError(
                f"{provider_id} does not support interactive login"
            )
        identity, credential, message = await run_login()
        if not credential:
            return False, message, self.list_accounts(provider_id)
        self.store_credential(provider_id, identity or LEGACY_IDENTITY, credential)
        accounts = self.list_accounts(provider_id)
        self.reconcile_listeners()
        return True, message, accounts

    def set_primary(self, provider_id: str, hint: Optional[str]) -> str:
        identity = self.accounts.set_primary(provider_id, hint)
        self.registry.invalidate(provider_id)
        return identity

    def set_listening(self, provider_id: str, hint: Optional[str], on: bool) -> str:
        identity = self.accounts.set_listening(provider_id, hint, on)
        self.reconcile_listeners()
        return identity

    def remove_account(self, provider_id: str, hint: Optional[str]) -> str:
        identity = self.accounts.remove_account(provider_id, hint)
        self.registry.invalidate(provider_id, identity)
        self._delete_legacy_if_disconnected(provider_id)
        self.reconcile_listeners()
        return identity

    def apply_account_changes(
        self, provider_id: str, batch: Dict[str, Any]
    ) -> List[AccountInfo]:
        result = self.accounts.apply_changes(provider_id, batch)
        # Batch may have re-pointed primary/aliases arbitrarily — drop the
        # provider's whole cache (and family siblings', for alias moves).
        for pid in self.registry.family_members(provider_id):
            self.registry.invalidate(pid)
        # A batch may disconnect the last account — same resurrection
        # hazard as remove_account.
        self._delete_legacy_if_disconnected(provider_id)
        self.reconcile_listeners()
        return result

    def store_credential(
        self, provider_id: str, identity: Optional[str], credential: Dict[str, Any]
    ) -> str:
        """OAuth-completion write path (used by add_account / re-auth)."""
        stored = self.accounts.upsert_account(provider_id, identity, credential)
        self.registry.invalidate(provider_id, stored)
        return stored

    def update_credential(
        self, provider_id: str, identity: str, credential: Dict[str, Any]
    ) -> None:
        """Token-refresh write path."""
        self.accounts.update_credential(provider_id, identity, credential)

    # ── internals ────────────────────────────────────────────────────────

    def _require_provider(self, provider_id: str) -> Provider:
        provider = self.registry.get(provider_id)
        if provider is None:
            raise LookupError(f"Unknown integration '{provider_id}'")
        return provider
