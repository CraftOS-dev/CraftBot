"""CraftBot marketplace branch preference, passed to the upstream CLI."""

import os

DEFAULT_REF = "main"


def ref() -> str:
    """The branch/tag marketplace content is read from.

    Precedence, highest first:
      1. CRAFTBOT_MARKETPLACE_REF   — one-off override for a single run
      2. agent_app.marketplace_ref  — settings.json, persists across restarts
      3. DEFAULT_REF                — the constant below
    """
    env = os.environ.get("CRAFTBOT_MARKETPLACE_REF")
    if env and env.strip():
        return env.strip()
    try:
        from app.config import get_marketplace_ref

        configured = get_marketplace_ref()
    except Exception as e:  # settings unreadable — never block a build over it
        try:
            from loguru import logger

            logger.debug(f"[MARKETPLACE] settings ref unreadable, using default: {e}")
        except Exception:
            pass
        configured = None
    return configured or DEFAULT_REF
