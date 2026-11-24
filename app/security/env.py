"""Environment for processes the agent starts (Settings > Security > Secrets).

With "Keep keys out of tools" on (Enhanced and Strict):

- An MCP server inherits only what the official MCP SDK passes by default
  (``mcp.client.stdio.get_default_environment``: the variables a program
  needs to run) plus the variables its own config declares. Anything else
  in CraftBot's environment, such as cloud keys or tokens from the user's
  shell, stays out of third-party server code.
- A command the agent runs keeps the user's environment, so their tools
  work as in their own terminal, minus CraftBot's own keys: the variables
  CraftBot's provider profiles read API keys from (their declared
  ``api_key_env``), and any variable whose value is one of the secrets in
  CraftBot's stores (app/security/redact.py).

CraftBot's own network configuration (proxy and certificate settings) is
passed on to MCP servers too, so they keep working behind a corporate proxy.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Mapping

# The MCP Python SDK's DEFAULT_INHERITED_ENV_VARS.
_SDK_DEFAULT = (
    (
        "APPDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "USERNAME",
        "USERPROFILE",
    )
    if sys.platform == "win32"
    else ("HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER")
)

# How CraftBot itself reaches the network (app/instance.py, app/main.py).
_NETWORK_CONFIG = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)


def child_environment(declared: Mapping[str, str], base: Mapping[str, str] = os.environ) -> Dict[str, str]:
    """The environment for a child process that declares ``declared``."""
    from app.security.policy import get_policy

    if not get_policy().scrub_child_env:
        env = dict(base)
        env.update(declared)
        return env
    env = {}
    for key in _SDK_DEFAULT + _NETWORK_CONFIG:
        value = base.get(key)
        # Exported shell functions ("() {...}") are skipped, as the SDK does.
        if value is not None and not value.startswith("()"):
            env[key] = value
    env.update(declared)
    return env


def craftbot_key_variables() -> set:
    """The environment variables CraftBot's provider profiles read API keys
    from, as each profile declares them."""
    names = set()
    try:
        from agent_core.core.models.provider_config import PROVIDER_CONFIG

        profiles = list(PROVIDER_CONFIG.values())
        try:
            from agent_core.core.models.registry import get_registry

            profiles.extend(get_registry().values())
        except Exception:
            pass
        names.update(p.api_key_env for p in profiles if getattr(p, "api_key_env", None))
    except Exception:
        pass
    return names


def command_environment(env: Mapping[str, str]) -> Dict[str, str]:
    """``env`` for a command the agent runs, without CraftBot's own keys
    when "Keep keys out of tools" is on; unchanged otherwise."""
    from app.security.policy import get_policy

    if not get_policy().scrub_child_env:
        return dict(env)
    from app.security.redact import collect_secrets, _sources

    names = craftbot_key_variables()
    secrets = set(collect_secrets(_sources()))
    return {k: v for k, v in env.items() if k not in names and v not in secrets}
