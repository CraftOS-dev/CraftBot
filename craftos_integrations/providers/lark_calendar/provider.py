"""Lark Calendar bridge provider — auth-layer port of ``LarkCalendarClient``.

Family member of ``_lark.LarkProviderBase`` (family="lark"): shares one
Custom App account (app_id identity) with lark / lark_drive. Everything —
identity, token-only oauth_spec, verify_token (mint tenant_access_token
from app_id + app_secret, the handler's exact fields), binding-routed
token refresh — comes from the family base. Calendar has no inbound
events (``supports_listening = False``), so ``make_listener`` resolves
to None via the base's dynamic check.
"""

from __future__ import annotations

from ...integrations.lark_calendar import LarkCalendarClient
from .._lark import LarkClientBinding, LarkProviderBase


class BoundLarkCalendarClient(LarkClientBinding, LarkCalendarClient):
    """LarkCalendarClient with per-account credential binding."""


class LarkCalendarProvider(LarkProviderBase):
    id = "lark_calendar"
    display_name = "Lark Calendar"
    client_cls = BoundLarkCalendarClient
