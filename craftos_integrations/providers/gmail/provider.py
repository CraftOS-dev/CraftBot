"""Gmail provider — the multi-account reference implementation.

API surface comes from ``GmailClient`` (all Gmail REST methods
live there and are unchanged); this class only rebinds its credential
plumbing to the injected per-account credential.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from ...contracts import Operation
from .._google_common import GMAIL_SCOPES
from .client import GmailClient, GmailConfig
from .._google import GoogleProviderBase, GoogleClientBinding
from .._shared import read_guidance
from .listener import GmailListener
from .operations import build_operations


class BoundGmailClient(GoogleClientBinding, GmailClient):
    """GmailClient with per-account credential binding (see GoogleClientBinding)."""


class GmailProvider(GoogleProviderBase):
    id = "gmail"
    display_name = "Gmail"
    # ----- UI metadata -----
    description = "Email - read, search, and send"
    auth_type = "oauth"
    icon = "gmail"
    config_class = GmailConfig
    config_fields = [
        {
            "key": "process_incoming",
            "label": "Auto-process incoming emails",
            "type": "checkbox",
            "help": "When on, every new INBOX message is forwarded to the agent. Turn off to keep Gmail send-only - the agent ignores incoming mail.",
        },
    ]

    scopes = GMAIL_SCOPES
    client_cls = BoundGmailClient

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> GmailListener:
        """INBOX poll listener (see listener.py)."""
        return GmailListener(client, cursor, emit)
