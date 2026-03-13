"""Backwards-compatible re-export — real module lives in app.external_comms.integration_settings."""
from app.external_comms.integration_settings import *  # noqa: F401,F403
from app.external_comms.integration_settings import (  # explicit re-exports for type checkers
    INTEGRATION_REGISTRY,
    PLATFORM_MAP,
    list_integrations,
    get_integration_info,
    get_integration_accounts,
    get_integration_auth_type,
    get_integration_fields,
    connect_integration_token,
    connect_integration_oauth,
    connect_integration_interactive,
    disconnect_integration,
    start_whatsapp_qr_session,
    check_whatsapp_session_status,
    cancel_whatsapp_session,
)
