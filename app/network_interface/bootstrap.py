# -*- coding: utf-8 -*-
"""
app.network_interface.bootstrap

One-shot startup helpers that prepare the agent for managed-LLM hosting on
craftbot.live before it boots.

`seed_default_provider_from_env`
    The dashboard's instances/index.ts containerEnv() injects
    `CRAFTBOT_DEFAULT_PROVIDER=craftbot` and `CRAFTBOT_DEFAULT_MODEL` (plus the
    underlying AWS_* creds for the boto3 default chain) into every container
    so a fresh agent boots straight into the managed CraftBot provider without
    an onboarding prompt. `craftbot` is the metered managed provider — usage
    is reported back to the dashboard. The unrelated BYOK `bedrock` provider
    is for users supplying their own AWS account.

    But we MUST NOT trample a user who has already chosen BYOK — settings.json
    is the user's preference. So we only seed when no settings.json exists yet
    (first boot of a brand-new container). Subsequent restarts re-read whatever
    the user last chose.

    Idempotent and tolerant of missing env vars: when CRAFTBOT_DEFAULT_PROVIDER
    is unset, or settings.json already exists, it's a no-op.
"""

from __future__ import annotations

import json
import os

try:
    from app.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)


def seed_default_provider_from_env() -> None:
    """Write settings.json with the env-supplied managed provider/model when
    no settings file exists yet. No-op when CRAFTBOT_DEFAULT_PROVIDER is unset
    or the user already has a settings.json (their choices win)."""
    provider = os.environ.get("CRAFTBOT_DEFAULT_PROVIDER", "").strip()
    if not provider:
        return

    # Late import so this module loads cleanly even before app.config is wired
    # (e.g. in test harnesses that haven't constructed PROJECT_ROOT yet).
    from app.config import SETTINGS_CONFIG_PATH, _get_default_settings  # type: ignore

    if SETTINGS_CONFIG_PATH.exists():
        # User-controlled settings present — don't touch.
        return

    model = os.environ.get("CRAFTBOT_DEFAULT_MODEL", "").strip() or None

    settings = _get_default_settings()
    # Overlay just the model section; everything else stays at agent defaults.
    settings.setdefault("model", {})
    settings["model"]["llm_provider"] = provider
    settings["model"]["vlm_provider"] = provider
    settings["model"]["llm_model"] = model
    settings["model"]["vlm_model"] = model

    try:
        SETTINGS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        logger.info(
            f"[network_interface] seeded settings.json with default provider={provider!r} model={model!r}"
        )
    except OSError as exc:
        # Filesystem errors here are best-effort — the agent can still boot
        # using in-memory defaults; the user will just see an onboarding screen.
        logger.warning(f"[network_interface] failed to seed settings.json: {exc}")
