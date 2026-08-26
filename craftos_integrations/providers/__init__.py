"""Integrations providers — one folder per integration.

Each provider implements the ``Provider`` protocol from
``craftos_integrations.contracts`` and is host-blind: no imports from the
host application, no direct credential-file access (credentials are
injected by the core, refreshed tokens go back through ``persist``).

``default_providers()`` returns instances of every shipped provider —
what a host passes to ``IntegrationSystem(providers=...)``.
"""

from __future__ import annotations

from typing import Dict, List, Optional

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
        # action surface stays, made account-aware centrally
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


# ════════════════════════════════════════════════════════════════════════
# Metadata registry
# ════════════════════════════════════════════════════════════════════════
#
# Providers are the enumeration and metadata source for everything
# user-facing. This is a cache of ``default_providers()`` for callers that
# want static metadata without a configured IntegrationSystem.
#
# Safe to cache: the instances hold no credential state (the core injects
# credentials per call), and the shipped provider set is fixed at import time.

_INSTANCES: Optional[Dict[str, Provider]] = None


def _instances() -> Dict[str, "Provider"]:
    global _INSTANCES
    if _INSTANCES is None:
        _INSTANCES = {p.id: p for p in default_providers()}
    return _INSTANCES


def provider_ids() -> List[str]:
    """Every shipped provider id, in ``default_providers()`` order."""
    return list(_instances().keys())


def get_provider(provider_id: str) -> Optional["Provider"]:
    """One shipped provider by id, or None. For static metadata only —
    use ``IntegrationSystem.registry`` for anything credential-bound."""
    return _instances().get(provider_id)
