"""Lark Drive bridge provider — auth-layer port of ``LarkDriveClient``.

Family member of ``_lark.LarkProviderBase`` (family="lark"): shares one
Custom App account (app_id identity) with lark / lark_calendar.

Note on the drive client's direct ``ensure_token(self._load(), ...)``
call sites (upload/download paths that need a bare bearer token without
the JSON content-type): the binding's ``_load()`` pre-refreshes the bound
credential through ``persist`` with a margin wider than the legacy 60s
check, so those legacy ``ensure_token`` calls always cache-hit and never
write ``lark_drive.json`` (see ``_lark._REFRESH_MARGIN``).

Drive has no inbound events (``supports_listening = False``), so
``make_listener`` resolves to None via the base's dynamic check.
"""

from __future__ import annotations

from ...integrations.lark_drive import LarkDriveClient
from .._lark import LarkClientBinding, LarkProviderBase


class BoundLarkDriveClient(LarkClientBinding, LarkDriveClient):
    """LarkDriveClient with per-account credential binding."""


class LarkDriveProvider(LarkProviderBase):
    id = "lark_drive"
    display_name = "Lark Drive"
    client_cls = BoundLarkDriveClient
