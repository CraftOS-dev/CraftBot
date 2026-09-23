"""Where marketplace apps are fetched from — repo, ref, and the URLs.

Lives in its own file (like `_state.py`) so `wizard.py`, `manager.py` and the
agent actions can all agree on ONE branch without importing each other. Before
this module the branch was hard-coded three separate times, so the catalogue a
user browsed and the app they installed could silently come from different
places.

Set CRAFTBOT_MARKETPLACE_REF to test against a branch other than main:

    CRAFTBOT_MARKETPLACE_REF=staging <start CraftBot>

Read per call, so tests can patch the environment without re-importing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

REPO = "CraftOS-dev/living-ui-marketplace"
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


def _checkout_branch(root: Path) -> Optional[str]:
    """Branch a git checkout is on, or None (detached HEAD, not a repo)."""
    try:
        git = root / ".git"
        if git.is_file():  # worktree/submodule: ".git" points elsewhere
            pointer = git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git = Path(pointer.split(":", 1)[1].strip())
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except Exception:
        return None
    prefix = "ref: refs/heads/"
    return head[len(prefix) :] if head.startswith(prefix) else None


def local_catalogue() -> Optional[Path]:
    """Sibling checkout's catalogue.json, but ONLY when it is on ref().

    Developer machines keep a checkout next to CraftBot and reading it is
    faster and works offline. It is only usable when it happens to be on the
    branch being tested, though — otherwise it silently serves a DIFFERENT
    branch's app list than the one apps install from, which is exactly the
    mismatch this module exists to prevent.
    """
    root = Path(__file__).resolve().parents[2].parent / REPO.split("/")[-1]
    if _checkout_branch(root) != ref():
        return None
    catalogue = root / "catalogue.json"
    return catalogue if catalogue.exists() else None


def catalogue_url() -> str:
    """Raw URL of the catalogue listing installable apps."""
    return f"https://raw.githubusercontent.com/{REPO}/{ref()}/catalogue.json"


def zip_url(owner: str, repo: str) -> str:
    """Source-archive URL an app is installed from.

    Branch names containing slashes ("feature/pipeline") work as-is.
    """
    return f"https://github.com/{owner}/{repo}/archive/refs/heads/{ref()}.zip"


def thumbnail_url(folder: str) -> str:
    """Card thumbnail for a marketplace app, on the ref being used."""
    return f"https://raw.githubusercontent.com/{REPO}/{ref()}/{folder}/thumbnail.png"
