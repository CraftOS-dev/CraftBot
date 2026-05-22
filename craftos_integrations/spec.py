"""IntegrationSpec — shared metadata held by both handler and client.

Each integration declares one IntegrationSpec instance (frozen dataclass)
and assigns it as a class attribute on its handler and client. This is
composition: there is no shared base class for "Slack-the-thing", just
two collaborators referencing the same metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type


@dataclass(frozen=True)
class IntegrationSpec:
    name: str
    cred_class: Type
    cred_file: str
    platform_id: str = ""

    def __post_init__(self) -> None:
        if not self.platform_id:
            object.__setattr__(self, "platform_id", self.name)
