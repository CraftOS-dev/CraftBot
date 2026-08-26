"""Lark Drive bridge provider — account-bound wrapper over ``LarkDriveClient``.

Family member of ``_lark.LarkProviderBase`` (family="lark"): shares one
Custom App account (app_id identity) with lark / lark_calendar.

Note on the drive client's direct ``ensure_token(self._load(), ...)``
call sites (upload/download paths that need a bare bearer token without
the JSON content-type): the binding's ``_load()`` pre-refreshes the bound
credential through ``persist`` with a margin wider than the 60s
check, so those ``ensure_token`` calls always cache-hit and never
write ``lark_drive.json`` (see ``_lark._REFRESH_MARGIN``).

Drive has no inbound events (``supports_listening = False``), so
``make_listener`` resolves to None via the base's dynamic check.
"""

from __future__ import annotations

from .client import LarkDriveClient
from .._lark import LarkClientBinding, LarkProviderBase


class BoundLarkDriveClient(LarkClientBinding, LarkDriveClient):
    """LarkDriveClient with per-account credential binding."""


class LarkDriveProvider(LarkProviderBase):
    id = "lark_drive"
    display_name = "Lark Drive"
    # ----- UI metadata -----
    description = "Files and folders in Lark Drive"
    icon = "lark"
    fields = [
        {
            "key": "app_id",
            "label": "App ID",
            "placeholder": "cli_xxxxxxxxxx",
            "password": False,
        },
        {
            "key": "app_secret",
            "label": "App Secret",
            "placeholder": "From Credentials & Basic Info tab",
            "password": True,
        },
    ]
    connect_help = [
        "Use the same Custom App you created for /lark (or create one at open.larksuite.com/app)",
        "Permissions & Scopes → enable: drive:drive (read-write) and drive:file:upload",
        "Version Management → Create Version → submit for tenant admin approval - required for the new scopes to take effect",
        "Credentials & Basic Info → copy App ID + App Secret and paste them below (same values as /lark)",
    ]

    client_cls = BoundLarkDriveClient
