"""Integrations providers — one folder per integration.

Each provider implements the ``Provider`` protocol from
``craftos_integrations.contracts`` and is host-blind: no imports from the
host application, no direct credential-file access (credentials are
injected by the core, refreshed tokens go back through ``persist``).

``default_providers()`` returns instances of every shipped provider —
what a host passes to ``IntegrationSystem(providers=...)``.
"""

from __future__ import annotations

from typing import List

from ..contracts import Provider


def default_providers() -> List[Provider]:
    from .gmail import GmailProvider
    from .google_calendar import GoogleCalendarProvider
    from .google_docs import GoogleDocsProvider
    from .google_drive import GoogleDriveProvider
    from .google_youtube import GoogleYoutubeProvider
    from .hubspot import HubSpotProvider
    from .linkedin import LinkedInProvider
    from .notion import NotionProvider
    from .outlook import OutlookProvider
    from .slack import SlackProvider

    return [
        GmailProvider(),
        GoogleCalendarProvider(),
        GoogleDocsProvider(),
        GoogleDriveProvider(),
        GoogleYoutubeProvider(),
        HubSpotProvider(),
        LinkedInProvider(),
        NotionProvider(),
        OutlookProvider(),
        SlackProvider(),
    ]
