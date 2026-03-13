# -*- coding: utf-8 -*-
"""Credential and OAuth management."""

from agent_core.core.credentials.embedded_credentials import (
    get_credential,
    get_credentials,
    has_embedded_credentials,
    encode_credential,
    generate_credentials_block,
)
from agent_core.core.credentials.oauth_server import run_oauth_flow

__all__ = [
    "get_credential",
    "get_credentials",
    "has_embedded_credentials",
    "encode_credential",
    "generate_credentials_block",
    "run_oauth_flow",
]
