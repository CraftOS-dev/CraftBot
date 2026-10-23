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
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

REPO = "CraftOS-dev/agent-app-collection"
LEGACY_REPO = "CraftOS-dev/living-ui-marketplace"
REPOS = (REPO, LEGACY_REPO)
REPO_URL = f"https://github.com/{REPO}/"
DEFAULT_REF = "main"
logger = logging.getLogger(__name__)

# v1.4.4 supports both names; the repository is renamed in v1.4.7.
# Keep the new name first even while only the legacy repository exists.


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
    parent = Path(__file__).resolve().parents[2].parent
    branch = ref()
    for repository in REPOS:
        root = parent / repository.split("/")[-1]
        if _checkout_branch(root) == branch:
            catalogue = root / "catalogue.json"
            if catalogue.exists():
                return catalogue
    return None


def catalogue_url(repository: str = REPO) -> str:
    """Raw URL of the catalogue listing installable apps."""
    return f"https://raw.githubusercontent.com/{repository}/{ref()}/catalogue.json"


def zip_url(owner: str, repo: str) -> str:
    """Source-archive URL an app is installed from.

    Branch names containing slashes ("feature/pipeline") work as-is.
    """
    return f"https://github.com/{owner}/{repo}/archive/refs/heads/{ref()}.zip"


def thumbnail_url(folder: str, repository: str = REPO) -> str:
    """Card thumbnail for a marketplace app, on the ref being used."""
    return (
        f"https://raw.githubusercontent.com/{repository}/{ref()}/{folder}/thumbnail.png"
    )


def _read_url(url: str, timeout: float) -> bytes:
    """Blocking download; async callers must run this off the event loop."""
    import certifi

    context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(url, headers={"User-Agent": "CraftBot"})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read()


def fetch_catalogue(timeout: float = 20) -> dict:
    """Try the new catalogue, then the legacy name, with matching thumbnails."""
    for index, repository in enumerate(REPOS):
        try:
            raw = _read_url(catalogue_url(repository), timeout).decode("utf-8")
            # Tolerate trailing commas in hand-edited JSON.
            catalogue = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            if not isinstance(catalogue, dict) or not isinstance(
                catalogue.get("apps", []), list
            ):
                raise ValueError("Invalid marketplace catalogue")
        except (urllib.error.URLError, OSError, ValueError) as error:
            if index == len(REPOS) - 1:
                raise
            logger.debug(
                "Marketplace %s unavailable: %s; trying fallback", repository, error
            )
            continue
        for app in catalogue.get("apps", []):
            if isinstance(app, dict) and not app.get("preview") and app.get("folder"):
                app["preview"] = thumbnail_url(app["folder"], repository)
        return catalogue


def download_archive(owner: str, repo: str, timeout: float = 60) -> bytes:
    """Download either marketplace alias in new-first order, or a custom repo.

    Only the two official marketplace names are aliases. A caller supplying
    another repository must never silently install from the marketplace.
    """
    repository = f"{owner}/{repo}"
    candidates = (
        REPOS if repository.lower() in {r.lower() for r in REPOS} else (repository,)
    )
    for index, candidate in enumerate(candidates):
        candidate_owner, candidate_repo = candidate.split("/", 1)
        url = zip_url(candidate_owner, candidate_repo)
        try:
            return _read_url(url, timeout)
        except (urllib.error.URLError, OSError) as error:
            if index == len(candidates) - 1:
                raise
            logger.debug(
                "Marketplace %s unavailable: %s; trying fallback", candidate, error
            )
