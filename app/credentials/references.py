"""Serializable source references. A reference is an identifier, never authority."""

from dataclasses import dataclass
import re
from uuid import UUID

PREFIX = "craftbot-vault://"


@dataclass(frozen=True)
class SourceReference:
    profile_id: UUID
    credential_id: UUID
    version: int

    def encode(self):
        return f"{PREFIX}{self.profile_id}/{self.credential_id}/{self.version}"


def parse(value: str) -> SourceReference:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        raise ValueError("credential_reference_required")
    parts = value[len(PREFIX) :].split("/")
    if len(parts) != 3 or not re.fullmatch(r"[1-9][0-9]{0,8}", parts[2]):
        raise ValueError("credential_reference_invalid")
    result = SourceReference(UUID(parts[0]), UUID(parts[1]), int(parts[2]))
    if (
        not result.profile_id.int
        or not result.credential_id.int
        or result.encode() != value
    ):
        raise ValueError("credential_reference_invalid")
    return result


def is_reference(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return False
    parse(value)  # Malformed references must never fall through to raw-key use.
    return True
