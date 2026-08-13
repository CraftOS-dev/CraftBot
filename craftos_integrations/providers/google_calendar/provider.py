"""Google Calendar provider — multi-account port of the legacy calendar integration.

API surface comes from the legacy ``GoogleCalendarClient`` (all Calendar
REST methods live there and are unchanged); this class only rebinds its
credential plumbing to the injected per-account credential.
"""

from __future__ import annotations

from typing import List

from ...contracts import Operation
from ...integrations._google_common import CALENDAR_SCOPES
from ...integrations.google_calendar import GoogleCalendarClient
from .._google import GoogleProviderBase, GoogleClientBinding, read_guidance
from .operations import build_operations


class BoundGoogleCalendarClient(GoogleClientBinding, GoogleCalendarClient):
    """GoogleCalendarClient with per-account credential binding (see GoogleClientBinding)."""


class GoogleCalendarProvider(GoogleProviderBase):
    id = "google_calendar"
    display_name = "Google Calendar"
    scopes = CALENDAR_SCOPES
    client_cls = BoundGoogleCalendarClient

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)
