"""The integrations system — the complete host/provider boundary.

Every type that crosses between a host application, the core, and a
provider plugin lives here. Providers implement ``Provider``; hosts
implement ``CredentialStore`` / ``OAuthTransport`` / ``EventSink`` (or use
the defaults in ``core/``). Nothing in ``craftos_integrations`` may import
from a host application — see tests/integrations/test_isolation.py.

Design reference: docs/plans/multi-account-v2-plan.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    ContextManager,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

# Sentinel identity for credentials saved before identity capture existed
# (old LinkedIn/Notion files). Upgraded in place on the next successful
# re-auth — never duplicated into a second account.
LEGACY_IDENTITY = "legacy"


class AccountResolutionError(Exception):
    """An ``account`` hint could not be resolved to a connected account.

    Messages are written for an LLM to self-correct from: they always
    enumerate the valid choices ("No gmail account matches 'x'.
    Connected: a@… (work), b@…").
    """


@dataclass(frozen=True)
class AccountInfo:
    """UI/agent-facing view of one connected account."""

    identity: str
    alias: Optional[str]
    is_primary: bool
    listen: bool
    added_at: str

    @property
    def display(self) -> str:
        return self.alias or self.identity


@dataclass(frozen=True)
class OAuthSpec:
    """Declarative OAuth parameters for one provider.

    ``extra_authorize_params`` is where account-chooser params live
    (e.g. Google's ``prompt=consent select_account``). ``has_chooser=False``
    is an explicit declaration that the provider's OAuth has no chooser
    (LinkedIn) — the conformance suite requires one or the other, so a
    missing chooser param is always a decision, never an oversight.
    """

    authorize_url: str
    token_url: str
    scopes: Tuple[str, ...] = ()
    extra_authorize_params: Mapping[str, str] = field(default_factory=dict)
    has_chooser: bool = True


@dataclass(frozen=True)
class Operation:
    """A framework-neutral action: hosts turn these into agent tools.

    ``input_schema`` must NOT contain an ``account`` key — account
    selection is injected centrally by the host adapter and resolved by
    ``IntegrationSystem.execute()``; operations receive a ready client.
    ``destructive`` lets hosts add confirm-or-clarify behavior uniformly.
    """

    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    fn: Callable[[Any, Dict[str, Any]], Awaitable[Dict[str, Any]]]
    destructive: bool = False
    parallelizable: bool = True
    tags: Tuple[str, ...] = ()


@runtime_checkable
class Listener(Protocol):
    """One inbound event source instance for one (provider, account)."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def cursor(self) -> Optional[Dict[str, Any]]:
        """Current poll/dedup state, persisted per account across restarts."""
        ...


@runtime_checkable
class Provider(Protocol):
    """What an integration plugin implements. Host-blind by contract."""

    id: str
    family: Optional[str]  # e.g. "google" — aliases shared across the family

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Provider-stable key for the human account (email/workspace id/…).

        Returning None means the credential predates identity capture; the
        core stores it under LEGACY_IDENTITY."""
        ...

    def oauth_spec(self) -> OAuthSpec: ...

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        """Build an API client bound to this one account's credential.

        ``persist`` must be called with the updated credential dict whenever
        the client refreshes tokens internally — the system routes it to the
        right account entry (a locked single-entry write). Clients must
        never write credential files themselves."""
        ...

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return a refreshed credential dict, or None if non-expiring."""
        ...

    def operations(self) -> List[Operation]: ...

    def guidance(self) -> str: ...

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Optional[Listener]:
        """Per-account listener instance, or None if no inbound events.

        ``emit`` is an already-account-bound async callable — the listener
        calls it with each event payload dict, and the core routes it to
        ``EventSink.on_event(provider_id, identity, payload)``. Listeners
        never know which account they serve."""
        ...


# ════════════════════════════════════════════════════════════════════════
# Host-implemented contracts
# ════════════════════════════════════════════════════════════════════════


class CredentialStore(Protocol):
    """Where AccountSet documents persist. Implementations must make
    ``replace`` atomic and ``locked`` a real mutual-exclusion boundary."""

    def load(self, provider_id: str) -> Optional[Dict[str, Any]]: ...

    def replace(self, provider_id: str, data: Dict[str, Any]) -> None: ...

    def delete(self, provider_id: str) -> None: ...

    def locked(self, provider_id: str) -> ContextManager[None]: ...

    def load_legacy(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """Bare single-account credential from a pre-multi-account install, if any.

        Read exactly once per provider by the one-time upgrade migration
        (``IntegrationSystem._migrate_legacy``: legacy file present, no
        AccountSet document). Stores may additionally offer ``has_document`` and
        ``delete_legacy`` (both optional, detected via hasattr) — the
        latter lets the system delete the legacy file when the last
        account is removed, so the migration cannot resurrect it."""
        ...


class OAuthTransport(Protocol):
    """How an authorize redirect/callback physically happens for this host."""

    async def authorize(self, url: str) -> Dict[str, str]:
        """Send the user to ``url``; return the callback query params."""
        ...


class EventSink(Protocol):
    """Where listener events go — the host's trigger system."""

    async def on_event(
        self, provider_id: str, identity: str, event: Dict[str, Any]
    ) -> None: ...


class FamilyLookup(Protocol):
    """Maps a provider id to every provider id sharing its alias family
    (including itself). The registry implements this; tests fake it."""

    def __call__(self, provider_id: str) -> Sequence[str]: ...
