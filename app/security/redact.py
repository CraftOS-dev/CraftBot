"""Redact CraftBot's own secrets from log lines (Settings > Security).

OpenClaw's approach: redact the exact values CraftBot knows are secret,
rather than guessing from what a string looks like. The values come from
CraftBot's secret stores: LLM API keys and cloud credentials in
settings.json, MCP servers' env values, and the integration credential
files. Any occurrence of one of them in a log message becomes
``[REDACTED]``.

The set is rebuilt when one of those files changes, checked at most every
few seconds, so a log call does no file I/O on its own.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Iterable, List, Tuple

from app.security.policy import get_policy

MASK = "[REDACTED]"
# Shorter values ("true", "en", ids like "1") would mangle ordinary text and
# are not secrets worth hiding.
_MIN_LENGTH = 8
_RECHECK_S = 5.0


def _strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sources() -> List[Path]:
    from app.config import APP_CONFIG_PATH, PROJECT_ROOT

    paths = [APP_CONFIG_PATH / "settings.json", APP_CONFIG_PATH / "mcp_config.json"]
    credentials = Path(PROJECT_ROOT) / ".credentials"
    if credentials.is_dir():
        paths.extend(sorted(credentials.glob("*.json")))
    return paths


def collect_secrets(sources: Iterable[Path]) -> Tuple[str, ...]:
    found = set()
    for path in sources:
        data = _load(path)
        if data is None:
            continue
        if path.name == "settings.json":
            for section in SECRET_SECTIONS:
                found.update(_strings(data.get(section)))
        elif path.name == "mcp_config.json":
            for server in data.get("mcp_servers") or []:
                if isinstance(server, dict):
                    found.update(_strings(server.get("env")))
                    found.update(_strings(server.get("headers")))
        else:
            # A credential file holds nothing but credential material.
            found.update(_strings(data))
    # Longest first, so a secret that contains another is masked whole.
    return tuple(sorted((s for s in found if len(s) >= _MIN_LENGTH), key=len, reverse=True))


SECRET_SECTIONS = ("api_keys", "aws_credentials")


def hide_secrets(settings: dict) -> dict:
    """A copy of settings.json for the agent: every value in a secret
    section becomes whether it is set, and any other value that equals a
    known secret is masked."""
    known = set(collect_secrets(_sources()))

    def mask(value):
        if isinstance(value, dict):
            return {k: mask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [mask(v) for v in value]
        if isinstance(value, str) and value in known:
            return MASK
        return value

    out = {}
    for key, value in settings.items():
        if key in SECRET_SECTIONS and isinstance(value, dict):
            out[key] = {k: ("set" if v else "not set") for k, v in value.items()}
        else:
            out[key] = mask(value)
    return out


class Redactor:
    def __init__(self) -> None:
        self._secrets: Tuple[str, ...] = ()
        self._signature: Tuple = ()
        self._checked = 0.0
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        now = time.monotonic()
        if now - self._checked < _RECHECK_S:
            return
        with self._lock:
            if now - self._checked < _RECHECK_S:
                return
            sources = _sources()
            signature = tuple(
                (str(p), p.stat().st_mtime_ns if p.exists() else 0) for p in sources
            )
            if signature != self._signature:
                self._secrets = collect_secrets(sources)
                self._signature = signature
            self._checked = now

    def __call__(self, message: str) -> str:
        if not get_policy().redact_logs:
            return message
        self._refresh()
        for secret in self._secrets:
            if secret in message:
                message = message.replace(secret, MASK)
        return message


redactor = Redactor()


def install() -> None:
    from agent_core.utils.logger import set_redactor

    set_redactor(redactor)
