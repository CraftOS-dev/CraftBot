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
    from .discord import DiscordProvider
    from .github import GitHubProvider
    from .gmail import GmailProvider
    from .google_calendar import GoogleCalendarProvider
    from .google_docs import GoogleDocsProvider
    from .google_drive import GoogleDriveProvider
    from .google_youtube import GoogleYoutubeProvider
    from .hubspot import HubSpotProvider
    from .jira import JiraProvider
    from .lark import LarkProvider
    from .lark_calendar import LarkCalendarProvider
    from .lark_drive import LarkDriveProvider
    from .line import LineProvider
    from .linkedin import LinkedInProvider
    from .notion import NotionProvider
    from .outlook import OutlookProvider
    from .slack import SlackProvider
    from .stripe import StripeProvider
    from .telegram_bot import TelegramBotProvider
    from .telegram_user import TelegramUserProvider
    from .twitter import TwitterProvider
    from .whatsapp_business import WhatsAppBusinessProvider
    from .whatsapp_web import WhatsAppWebProvider

    return [
        # Full ports — operations generated from the provider.
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
        # Auth-layer bridges — multi-account storage/UI/listeners; the
        # legacy action surface stays, made account-aware centrally
        # (see app/data/action/integrations/account_bridge.py).
        # Wave 1:
        GitHubProvider(),
        JiraProvider(),
        LineProvider(),
        StripeProvider(),
        WhatsAppBusinessProvider(),
        # Wave 2 (lark siblings share family="lark" aliases):
        DiscordProvider(),
        LarkProvider(),
        LarkCalendarProvider(),
        LarkDriveProvider(),
        TelegramBotProvider(),
        TwitterProvider(),
        # Wave 3 — interactive logins (QR / phone+code):
        TelegramUserProvider(),
        WhatsAppWebProvider(),
    ]
