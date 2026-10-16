"""Versioned encrypted document format and metadata-only owner results."""

from __future__ import annotations

from dataclasses import dataclass
import json
import ipaddress
import re
from urllib.parse import urlsplit
from uuid import UUID

from .contracts import CredentialKind, CredentialReference, CredentialSummary
from .errors import VaultError, VaultErrorCode as Code
from .identity import VaultOwner, VaultProfile, VaultScope
from .secrets import Secret

MAX_ITEMS = 5000


@dataclass(frozen=True)
class CredentialDetails:
    summary: CredentialSummary
    allowed_origins: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(repr=False)
class _Record:
    details: CredentialDetails
    fields: Secret

    def __repr__(self) -> str:
        return "<vault record: secret fields redacted>"


def validate_fields(kind: CredentialKind, fields: Secret) -> None:
    if not isinstance(kind, CredentialKind):
        raise VaultError(Code.INVALID)
    if not isinstance(fields, Secret) or not isinstance(fields.reveal(), dict):
        raise VaultError(Code.INVALID)
    if not 1 <= len(fields.reveal()) <= 32:
        raise VaultError(Code.INVALID)
    for entry in map(Secret, fields.reveal().items()):
        if (
            not isinstance(entry.reveal()[0], str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", entry.reveal()[0])
            or not isinstance(entry.reveal()[1], str)
            or not 0 < len(entry.reveal()[1]) <= 32768
        ):
            raise VaultError(Code.INVALID)
    expected = {
        CredentialKind.LOGIN: {"username", "password"},
        CredentialKind.API_KEY: {"api_key"},
    }.get(kind)
    if expected is not None and set(fields.reveal()) != expected:
        raise VaultError(Code.INVALID)


def origins(values: tuple[str, ...]) -> tuple[str, ...]:
    """Exact ASCII HTTPS origins; no www folding or inferred login domains.

    These are stored policy metadata, not authorization to issue a request.
    Destination/network validation and browser canonicalization belong to CM-03/05.
    """
    if not isinstance(values, tuple) or len(values) > 32:
        raise VaultError(Code.INVALID)
    result = set()
    try:
        for value in values:
            if (
                not isinstance(value, str)
                or not value.isascii()
                or len(value) > 2048
                or any(char.isspace() or ord(char) < 32 for char in value)
                or "\\" in value
            ):
                raise ValueError()
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.path not in ("", "/")
                or url.query
                or url.fragment
                or not re.fullmatch(r"[a-zA-Z0-9.:-]+", url.hostname)
                or url.port == 0
            ):
                raise ValueError()
            host = url.hostname.lower()
            if ":" in host:
                ipaddress.IPv6Address(host)
                host = f"[{host}]"
            else:
                dns = host[:-1] if host.endswith(".") else host
                if len(dns) > 253 or not all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in dns.split(".")
                ):
                    raise ValueError()
            port = f":{url.port}" if url.port not in (None, 443) else ""
            result.add(f"https://{host}{port}")
    except ValueError:
        raise VaultError(Code.INVALID) from None
    return tuple(sorted(result))


def encode(owner: VaultOwner, profile: VaultProfile, records: list[_Record]) -> Secret:
    document = Secret(
        {
            "format": 1,
            "owner_id": str(owner.owner_id),
            "os_identity": owner.os_identity,
            "profile_id": str(profile.scope.profile_id),
            "profile_label": profile.label,
            "items": [
                {
                    "id": str(record.details.summary.reference.credential_id),
                    "version": record.details.summary.reference.version,
                    "kind": record.details.summary.kind.value,
                    "service": record.details.summary.service,
                    "account_label": record.details.summary.account_label,
                    "origins": record.details.allowed_origins,
                    "created_at": record.details.created_at,
                    "updated_at": record.details.updated_at,
                    "fields": record.fields.reveal(),
                }
                for record in records
            ],
        }
    )
    return Secret(json.dumps(document.reveal(), ensure_ascii=True).encode("ascii"))


def decode(plaintext: Secret, owner: VaultOwner, scope: VaultScope):
    """Reject corrupt/unknown documents, never repair by silently dropping data."""
    try:
        document = Secret(json.loads(plaintext.reveal()))
        if (
            not isinstance(document.reveal(), dict)
            or set(document.reveal())
            != {
                "format",
                "owner_id",
                "os_identity",
                "profile_id",
                "profile_label",
                "items",
            }
            or type(document.reveal()["format"]) is not int
            or document.reveal()["format"] != 1
            or document.reveal()["owner_id"] != str(scope.owner_id)
            or document.reveal()["profile_id"] != str(scope.profile_id)
            or document.reveal()["os_identity"] != owner.os_identity
        ):
            raise ValueError()
        profile = VaultProfile(scope, document.reveal()["profile_label"])
        items = Secret(document.reveal()["items"])
        if not isinstance(items.reveal(), list) or len(items.reveal()) > MAX_ITEMS:
            raise ValueError()
        seen = set()
        records = []
        for raw in map(Secret, items.reveal()):
            if not isinstance(raw.reveal(), dict) or set(raw.reveal()) != {
                "id",
                "version",
                "kind",
                "service",
                "account_label",
                "origins",
                "created_at",
                "updated_at",
                "fields",
            }:
                raise ValueError()
            reference = CredentialReference(
                scope, UUID(raw.reveal()["id"]), raw.reveal()["version"]
            )
            if reference.credential_id in seen:
                raise ValueError()
            seen.add(reference.credential_id)
            summary = CredentialSummary(
                reference,
                CredentialKind(raw.reveal()["kind"]),
                raw.reveal()["service"],
                raw.reveal()["account_label"],
            )
            fields = Secret(raw.reveal()["fields"])
            validate_fields(summary.kind, fields)
            if not isinstance(raw.reveal()["origins"], list):
                raise ValueError()
            allowed = origins(tuple(raw.reveal()["origins"]))
            if summary.kind is CredentialKind.LOGIN and not allowed:
                raise ValueError()
            for name in ("created_at", "updated_at"):
                if not isinstance(raw.reveal()[name], str) or not raw.reveal()[name]:
                    raise ValueError()
            records.append(
                _Record(
                    CredentialDetails(
                        summary,
                        allowed,
                        raw.reveal()["created_at"],
                        raw.reveal()["updated_at"],
                    ),
                    fields,
                )
            )
        return profile, records
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        VaultError,
    ):
        raise VaultError(Code.UNREADABLE) from None
