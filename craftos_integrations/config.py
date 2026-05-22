"""Host-injected configuration for the integrations package.

The host calls configure(...) once at startup. Every module reads from
ConfigStore — no module imports from the host application.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

OAuthRunner = Callable[..., Awaitable[Tuple[Optional[str], Optional[str]]]]
MessageCallback = Callable[[Dict[str, Any]], Awaitable[None]]
OnboardingHook = Callable[[str, Dict[str, Any]], Awaitable[None]]


class ConfigStore:
    project_root: Path = Path.cwd()
    logger: Optional[logging.Logger] = None
    on_message: Optional[MessageCallback] = None
    oauth_runner: Optional[OAuthRunner] = None
    onboarding_hook: Optional[OnboardingHook] = None
    extras: Dict[str, Any] = {}
    _oauth: Dict[str, str] = {}

    @classmethod
    def get_oauth(cls, key: str, default: str = "") -> str:
        if key in cls._oauth and cls._oauth[key]:
            return cls._oauth[key]
        return os.environ.get(key, default)

    @classmethod
    def require_oauth(cls, key: str) -> str:
        value = cls.get_oauth(key)
        if not value:
            raise RuntimeError(
                f"Integrations: required OAuth setting '{key}' is not configured. "
                f"Pass it to configure(oauth={{...}}) or set the {key} env var."
            )
        return value


def configure(
    *,
    project_root: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
    oauth: Optional[Dict[str, str]] = None,
    oauth_runner: Optional[OAuthRunner] = None,
    onboarding_hook: Optional[OnboardingHook] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> None:
    if project_root is not None:
        ConfigStore.project_root = Path(project_root)
    if logger is not None:
        ConfigStore.logger = logger
    if oauth is not None:
        ConfigStore._oauth = {k: v for k, v in oauth.items() if v is not None}
    if oauth_runner is not None:
        ConfigStore.oauth_runner = oauth_runner
    if onboarding_hook is not None:
        ConfigStore.onboarding_hook = onboarding_hook
    if extras is not None:
        ConfigStore.extras = dict(extras)
