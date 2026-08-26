"""Lark Calendar bridge provider — account-bound wrapper over ``LarkCalendarClient``.

Family member of ``_lark.LarkProviderBase`` (family="lark"): shares one
Custom App account (app_id identity) with lark / lark_drive. Everything —
identity, token-only oauth_spec, verify_token (mint tenant_access_token
from app_id + app_secret, the handler's exact fields), binding-routed
token refresh — comes from the family base. Calendar has no inbound
events (``supports_listening = False``), so ``make_listener`` resolves
to None via the base's dynamic check.
"""

from __future__ import annotations

from .client import LarkCalendarClient
from .._lark import LarkClientBinding, LarkProviderBase


class BoundLarkCalendarClient(LarkClientBinding, LarkCalendarClient):
    """LarkCalendarClient with per-account credential binding."""


class LarkCalendarProvider(LarkProviderBase):
    id = "lark_calendar"
    display_name = "Lark Calendar"
    # ----- UI metadata -----
    description = "Events, scheduling, and free/busy on Lark Calendar"
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
        "Permissions & Scopes → enable: calendar:calendar (read-write) and calendar:calendar.event.attendee (for invites)",
        "Version Management → Create Version → submit for tenant admin approval - required for new scopes to take effect",
        "Credentials & Basic Info → copy App ID + App Secret and paste them below (same values as /lark)",
    ]

    client_cls = BoundLarkCalendarClient
