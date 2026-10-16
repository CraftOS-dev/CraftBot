"""Secret-free consumer/helper-boundary contracts for CM-01.

No implementation here authenticates callers, unlocks a vault, executes a
helper, or reads a credential. Those require CM-02/03 and OS-enforced isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID

from .identity import ExecutionContext, VaultScope, _label, _uuid


class CredentialKind(str, Enum):
    LOGIN = "login"
    API_KEY = "api_key"
    SERVICE_SECRET = "service_secret"


@dataclass(frozen=True)
class CredentialReference:
    scope: VaultScope
    credential_id: UUID
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.scope, VaultScope):
            raise ValueError("A vault scope is required")
        _uuid(self.credential_id)
        if type(self.version) is not int or self.version < 1:
            raise ValueError("A positive credential version is required")


@dataclass(frozen=True)
class CredentialSummary:
    reference: CredentialReference
    kind: CredentialKind
    service: str
    account_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, CredentialReference) or not isinstance(
            self.kind, CredentialKind
        ):
            raise ValueError("A credential reference and kind are required")
        _label(self.service)
        _label(self.account_label)


@dataclass(frozen=True)
class HelperOperation:
    """Registered operation identifier, never a module path or callback."""

    helper_id: str
    operation: str

    def __post_init__(self) -> None:
        _label(self.helper_id)
        _label(self.operation)


class IsolationBoundary(Protocol):
    """Trusted host/platform adapter; never implemented by agent/app code.

    Must reject use unless code integrity, filesystem/process separation and
    authenticated channel binding are enforced. Missing support fails closed.
    A separate PID, venv, OS-user encryption or a context variable is not proof.
    """

    def require_isolated(self, context: ExecutionContext) -> None: ...


class IsolationUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("credential_isolation_unavailable")


class UnavailableIsolationBoundary:
    """Default outside the installed Windows SYSTEM host; no permissive fallback."""

    def require_isolated(self, context: ExecutionContext) -> None:
        raise IsolationUnavailable()
