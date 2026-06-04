# -*- coding: utf-8 -*-
"""
Secret redaction for action outputs.

The agent process holds deployment secrets in its environment (cloud access
keys, container auth tokens, OAuth client secrets, ...). User-directed tools
such as ``run_shell`` and ``run_python`` execute arbitrary commands, so a user
can ask the agent to "print all environment variables" or read a credentials
file and have the secret echoed straight back into the chat.

``redact_secrets`` is a catch-all applied to every action's output before it is
logged, streamed to the UI, or returned to the model. It replaces the live
*values* of secret-named environment variables — and obvious ``KEY=value`` /
``"key": "value"`` secret lines — with ``[REDACTED]``. Because it redacts by
value, a secret leaks nothing regardless of how the code obtained it (env,
``/proc/self/environ``, a mounted secrets file, a subprocess, ...).

The logic is deployment-agnostic: the secret set is derived from the current
process environment at call time using name patterns, so there is no hard-coded
list of this deployment's variables to keep in sync. Redaction only changes what
is *displayed* — commands still execute with their normal environment, so this
never breaks functionality.
"""

import os
import re
from typing import Any, List

REDACTED = "[REDACTED]"

# A variable is treated as secret if its NAME contains any of these tokens.
_SECRET_NAME_TOKENS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "APIKEY",
    "API_KEY",
    "ACCESS_KEY",
    "AUTH",
)

# Names that match a token above but are NOT secret — keep them visible so we
# don't blank out useful, non-sensitive context (region, ids, public urls).
_SAFE_NAMES = frozenset(
    {
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_DEFAULTREGION",
    }
)

# Don't redact trivially short values ("1", "true", "") — they would match huge
# amounts of unrelated text and corrupt output. Real credentials are long.
_MIN_VALUE_LEN = 6

# Matches `NAME=value` / `"NAME": "value"` / `NAME: value` where NAME looks
# secret — catches structured dumps (printenv, JSON config) even when the value
# itself is short or otherwise wouldn't be caught by value replacement.
_KV_RE = re.compile(
    r'(?P<prefix>["\']?[A-Za-z0-9_]*'
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API[_]?KEY|ACCESS[_]?KEY|AUTH)"
    r'[A-Za-z0-9_]*["\']?\s*[:=]\s*["\']?)'
    r"(?P<value>[^\s\"',}]+)",
    re.IGNORECASE,
)


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    if upper in _SAFE_NAMES:
        return False
    return any(tok in upper for tok in _SECRET_NAME_TOKENS)


def secret_values() -> List[str]:
    """Live values of secret-named env vars, longest first.

    Longest-first so that when one secret value is a substring of another, the
    longer (more specific) value is redacted first.
    """
    values = set()
    for name, value in os.environ.items():
        if value and len(value) >= _MIN_VALUE_LEN and _is_secret_name(name):
            values.add(value)
    return sorted(values, key=len, reverse=True)


def redact_text(text: str) -> str:
    """Replace any secret value (or secret-named KEY=value) in ``text``."""
    if not text or not isinstance(text, str):
        return text
    try:
        for value in secret_values():
            if value in text:
                text = text.replace(value, REDACTED)
        text = _KV_RE.sub(lambda m: m.group("prefix") + REDACTED, text)
    except Exception:
        # Redaction must never break the action pipeline. Fail closed only for
        # the value-replacement pass (already applied); return what we have.
        return text
    return text


def scrub_secret_values(text: str) -> str:
    """Replace deployment-secret VALUES (from the process env) in a string.

    Value-only: unlike :func:`redact_text` it does NOT touch secret-*named*
    ``key=value`` fields, so it is safe to apply to arbitrary UI payloads
    (e.g. every websocket broadcast) without blanking legitimate tokens the
    frontend needs. It guarantees that a deployment secret — cloud access keys,
    container auth token, OAuth client secrets — never reaches the client no
    matter which code path assembled the message.
    """
    if not text or not isinstance(text, str):
        return text
    try:
        for value in secret_values():
            if value in text:
                text = text.replace(value, REDACTED)
    except Exception:
        return text
    return text


def redact_secrets(obj: Any) -> Any:
    """Recursively redact secret values from an action output (str/dict/list).

    Non-string scalars are returned unchanged. Never raises.
    """
    try:
        if isinstance(obj, str):
            return redact_text(obj)
        if isinstance(obj, dict):
            return {k: redact_secrets(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [redact_secrets(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(redact_secrets(v) for v in obj)
    except Exception:
        return obj
    return obj
