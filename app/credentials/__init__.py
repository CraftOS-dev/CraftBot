# -*- coding: utf-8 -*-
"""Credentials module - re-exports from agent_core plus project-specific handlers."""

# Re-export from agent_core
from agent_core import (
    get_credential,
    get_credentials,
    has_embedded_credentials,
    run_oauth_flow,
)

# Project-specific
from .handlers import (
    IntegrationHandler,
    INTEGRATION_HANDLERS,
    LOCAL_USER_ID,
)

__all__ = [
    # From agent_core
    "get_credential",
    "get_credentials",
    "has_embedded_credentials",
    "run_oauth_flow",
    # Project-specific handlers
    "IntegrationHandler",
    "INTEGRATION_HANDLERS",
    "LOCAL_USER_ID",
]
