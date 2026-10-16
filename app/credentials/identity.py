"""CM-01 identity model, independent of browser owners and agent bundles.

All records are host-owned metadata. Never deserialize a CallerBinding from
agent/tool input: UUIDs and immutable records are identifiers, not credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import unicodedata
from uuid import UUID


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError("A nonzero UUID is required")


def _label(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(
            unicodedata.category(char) in ("Cc", "Cf", "Cs", "Zl", "Zp")
            for char in value
        )
    ):
        raise ValueError("A nonempty label of at most 256 characters is required")


@dataclass(frozen=True)
class VaultOwner:
    """Human owner provisioned against a verified local OS account.

    os_identity is a platform-qualified stable account identifier, not a display
    name, email, Telegram owner flag, session id, or environment variable.
    CM-01 does not implement OS verification or owner provisioning.
    """

    owner_id: UUID
    os_identity: str = field(repr=False)

    def __post_init__(self) -> None:
        _uuid(self.owner_id)
        _label(self.os_identity)


@dataclass(frozen=True)
class VaultScope:
    owner_id: UUID
    profile_id: UUID

    def __post_init__(self) -> None:
        _uuid(self.owner_id)
        _uuid(self.profile_id)


@dataclass(frozen=True)
class VaultProfile:
    """Credential namespace; labels are not unique or security identifiers."""

    scope: VaultScope
    label: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, VaultScope):
            raise ValueError("A vault scope is required")
        _label(self.label)


class CallerKind(str, Enum):
    AGENT_SESSION = "agent_session"
    SUBAGENT = "subagent"
    AGENT_APP = "agent_app"


class AppDeployment(str, Enum):
    LIVE = "live"
    DEVELOPMENT = "development"


@dataclass(frozen=True)
class CallerIdentity:
    """Host binding identity, pinned to an authenticated isolated process.

    instance_id rotates when the authenticated execution channel is replaced.
    Agent Apps additionally bind the actual immutable snapshot hash. Subject,
    kind and deployment are unverified caller labels, never trusted enrollment.
    Neither a manifest capability nor knowing these values is authentication.
    """

    kind: CallerKind
    subject_id: str
    instance_id: UUID
    app_revision: str | None = None
    deployment: AppDeployment | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CallerKind):
            raise ValueError("A caller kind is required")
        _label(self.subject_id)
        _uuid(self.instance_id)
        if self.kind is CallerKind.AGENT_APP:
            _label(self.app_revision)
            if not isinstance(self.deployment, AppDeployment):
                raise ValueError("An app deployment is required")
        elif self.app_revision is not None or self.deployment is not None:
            raise ValueError("App identity fields require an Agent App caller")


@dataclass(frozen=True)
class CallerBinding:
    """Host-selected profile for an authenticated consumer channel.

    Multiple channels may bind the same app/session to different profiles, but
    a channel's binding never changes underneath an in-flight request.
    """

    binding_id: UUID
    caller: CallerIdentity
    scope: VaultScope

    def __post_init__(self) -> None:
        _uuid(self.binding_id)
        if not isinstance(self.caller, CallerIdentity) or not isinstance(
            self.scope, VaultScope
        ):
            raise ValueError("A caller identity and vault scope are required")


@dataclass(frozen=True)
class ExecutionContext:
    """Out-of-band host context, never a tool's session/profile claims."""

    binding: CallerBinding
    execution_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.binding, CallerBinding):
            raise ValueError("A host caller binding is required")
        _uuid(self.execution_id)
