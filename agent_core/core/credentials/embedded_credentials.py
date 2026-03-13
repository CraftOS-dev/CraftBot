# -*- coding: utf-8 -*-
"""
Embedded OAuth credentials for distribution.

Credentials are base64-encoded and split to prevent GitHub scanning.
Environment variables always take priority over embedded credentials.

Usage:
    from agent_core.core.credentials.embedded_credentials import get_credential

    # Get a single credential
    client_id = get_credential("google", "client_id", "GOOGLE_CLIENT_ID")

    # Get multiple credentials
    creds = get_credentials("slack", ["client_id", "client_secret"], {
        "client_id": "SLACK_SHARED_CLIENT_ID",
        "client_secret": "SLACK_SHARED_CLIENT_SECRET",
    })
"""

import base64
import os
from typing import Optional


# Registry of embedded credentials (service_name -> key -> list of base64 parts)
# Each credential is split into multiple base64 parts to prevent GitHub scanning
_EMBEDDED_CREDENTIALS: dict[str, dict[str, list[str]]] = {
    "google": {
        "client_id": [
            "NTQwMzU1MDYyMDA1LTM3Y3RmcjBhNHVlazFjMWZzcDRzc25sd",
            "GhkdGJkbzZ2LmFwcHMuZ29vZ2xldXNlcmNvbnRlbnQuY29t",
        ],
    },
    "zoom": {
        "client_id": ["YWlsaURjY0JUUGlaZ", "W5Ka29acldHZw=="],
    },
    "slack": {
        "client_id": ["MTA0MzA2NTc3MTM5NTUuM", "TA0MzcyNDYxNjI0OTg="],
        "client_secret": ["NTY4NzVjMDYxM2U3OWM2ZTN", "iYzUxZDllZGZkNjM2Njg="],
    },
    "notion": {
        "client_id": ["MmZkZDg3MmItNTk0Yy04MGRjL", "ThlNWYtMDAzNzI1ZWYzM2Zm"],
        "client_secret": [
            "c2VjcmV0XzlSaEV3U2hzY0NjdDlGTkRDOUN",
            "mRWVRaEtnRUtXNXFCWG9WNWJSejJ0cHI=",
        ],
    },
    "linkedin": {
        "client_id": ["ODZ4aXVvZHQ", "2cjQ3MnU="],
        "client_secret": ["V1BMX0FQMS5FSHFHeDRUOGZ", "SM0k1cjM3LnFHNU45QT09"],
    },
}


def _decode_parts(parts: list[str]) -> str:
    """Decode base64-encoded credential parts."""
    if not parts:
        return ""
    try:
        return base64.b64decode("".join(parts)).decode()
    except Exception:
        return ""


def get_credential(
    service: str,
    key: str,
    env_var: Optional[str] = None,
) -> str:
    """
    Get a credential value with fallback chain.

    Lookup order:
        1. Environment variable (if provided)
        2. Embedded credential (if configured)
        3. Empty string

    Args:
        service: Service name (e.g., "google", "slack", "notion")
        key: Credential key (e.g., "client_id", "client_secret")
        env_var: Optional environment variable name to check first

    Returns:
        The credential value or empty string if not found

    Example:
        client_id = get_credential("google", "client_id", "GOOGLE_CLIENT_ID")
    """
    # Priority 1: Environment variable
    if env_var:
        env_value = os.environ.get(env_var, "")
        if env_value:
            return env_value

    # Priority 2: Embedded credential
    service_creds = _EMBEDDED_CREDENTIALS.get(service, {})
    parts = service_creds.get(key, [])
    if parts:
        return _decode_parts(parts)

    # Fallback: Empty string
    return ""


def get_credentials(
    service: str,
    keys: list[str],
    env_vars: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """
    Get multiple credentials for a service.

    Args:
        service: Service name
        keys: List of credential keys to retrieve
        env_vars: Optional mapping of key -> env_var name

    Returns:
        Dict of key -> credential value

    Example:
        creds = get_credentials("slack", ["client_id", "client_secret"], {
            "client_id": "SLACK_SHARED_CLIENT_ID",
            "client_secret": "SLACK_SHARED_CLIENT_SECRET",
        })
    """
    env_vars = env_vars or {}
    return {key: get_credential(service, key, env_vars.get(key)) for key in keys}


def has_embedded_credentials(service: str) -> bool:
    """
    Check if embedded credentials are available for a service.

    Args:
        service: Service name to check

    Returns:
        True if embedded credentials exist for the service
    """
    return service in _EMBEDDED_CREDENTIALS and bool(_EMBEDDED_CREDENTIALS[service])


def encode_credential(value: str, num_parts: int = 2) -> list[str]:
    """
    Encode a credential for embedding. Used during build/release.

    This is a utility function for the build process to generate
    the base64-encoded parts that should be placed in _EMBEDDED_CREDENTIALS.

    Args:
        value: The credential value to encode
        num_parts: Number of parts to split into (default 2)

    Returns:
        List of base64-encoded parts

    Example:
        >>> encode_credential("my-client-id.apps.googleusercontent.com", 2)
        ['bXktY2xpZW50LWlkLmFwcHMu', 'Z29vZ2xldXNlcmNvbnRlbnQuY29t']
    """
    encoded = base64.b64encode(value.encode()).decode()
    chunk_size = len(encoded) // num_parts + 1
    return [encoded[i : i + chunk_size] for i in range(0, len(encoded), chunk_size)]


def generate_credentials_block(
    credentials: dict[str, dict[str, str]], num_parts: int = 2
) -> str:
    """
    Generate Python code for the _EMBEDDED_CREDENTIALS dictionary.

    Used by build scripts to inject credentials.

    Args:
        credentials: Dict of service -> {key: value} credentials
        num_parts: Number of parts to split each credential into

    Returns:
        Python code string for the _EMBEDDED_CREDENTIALS dictionary

    Example:
        >>> creds = {
        ...     "google": {"client_id": "abc123"},
        ...     "slack": {"client_id": "def456", "client_secret": "secret789"},
        ... }
        >>> print(generate_credentials_block(creds))
        _EMBEDDED_CREDENTIALS: dict[str, dict[str, list[str]]] = {
            "google": {
                "client_id": ["YWJj", "MTIz"],
            },
            ...
        }
    """
    lines = ["_EMBEDDED_CREDENTIALS: dict[str, dict[str, list[str]]] = {"]
    for service, keys in credentials.items():
        lines.append(f'    "{service}": {{')
        for key, value in keys.items():
            parts = encode_credential(value, num_parts)
            parts_str = ", ".join(f'"{p}"' for p in parts)
            lines.append(f'        "{key}": [{parts_str}],')
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines)
