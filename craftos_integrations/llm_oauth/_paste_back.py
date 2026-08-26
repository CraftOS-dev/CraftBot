# -*- coding: utf-8 -*-
"""Shared paste-back state for LLM OAuth flows.

Both the ChatGPT and Grok OAuth backends need to support the "browser
shows a code, user pastes it back into the app" fallback flow (xAI's
hermes-agent client family sometimes does this instead of redirecting to
the loopback callback; OpenAI's Codex flow can also fall into it on some
browser contexts). The mechanics are identical for both providers —
generate PKCE, open the browser, remember the verifier keyed by an
attempt id, exchange the pasted code later — so this module carries the
shared skeleton and each backend only supplies its own credential-save
step.

The underscore prefix marks this as a package-private helper.
autoload_integrations skips modules starting with ``_``, so this
module won't try to register as an integration on import.
"""

from __future__ import annotations

import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..logger import get_logger
from ..oauth_flow import OAuthFlow

logger = get_logger(__name__)


PASTEBACK_MAX_AGE_SECONDS = 15 * 60  # OAuth codes live ~5 min; give headroom.


@dataclass
class PastebackAttempt:
    """One in-progress paste-back flow.

    Persisted between ``prepare_login()`` (which builds the auth URL and
    opens the browser) and ``complete_login_with_code()`` (which exchanges
    the pasted code). We keep the constructed ``OAuthFlow`` around because
    its ``_exchange_token_sync`` is what does the actual code → tokens
    call and it already knows this attempt's token endpoint, client
    credentials, and redirect URI shape.
    """

    verifier: str
    state: str
    client_id: str
    oauth: OAuthFlow
    created_at: float = field(default_factory=time.time)


class PastebackRegistry:
    """Per-provider in-memory registry of pending paste-back attempts.

    Each provider (chatgpt / grok) owns its own instance so their
    attempt-ids can't collide. The registry is a thin dict wrapper —
    the interesting logic lives in the ``prepare`` and ``pop_most_recent``
    helpers that both backends use.
    """

    def __init__(self, provider_label: str):
        self._provider_label = provider_label
        self._attempts: Dict[str, PastebackAttempt] = {}

    def prune(self) -> None:
        """Drop entries older than ``PASTEBACK_MAX_AGE_SECONDS``."""
        now = time.time()
        stale = [
            k
            for k, v in self._attempts.items()
            if now - v.created_at > PASTEBACK_MAX_AGE_SECONDS
        ]
        for k in stale:
            self._attempts.pop(k, None)

    async def prepare(self, oauth: OAuthFlow) -> Dict[str, str]:
        """Build the authorize URL from ``oauth``, open the browser,
        persist the PKCE verifier, and return the identifiers the
        frontend needs to complete the flow later.

        Returns ``{"auth_url": ..., "attempt_id": ...}`` — the same
        shape both backends' ``prepare_login`` returned before this
        refactor.
        """
        self.prune()
        url, ctx = oauth._build_auth_url()
        attempt_id = uuid.uuid4().hex
        self._attempts[attempt_id] = PastebackAttempt(
            verifier=ctx.get("code_verifier", "") or "",
            state=ctx.get("state", "") or "",
            client_id=ctx.get("client_id", "") or "",
            oauth=oauth,
        )
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(
                f"[{self._provider_label}-OAUTH] could not open browser ({e}); "
                f"user must visit URL manually"
            )
        return {"auth_url": url, "attempt_id": attempt_id}

    def find(self, attempt_id: Optional[str]) -> Optional[PastebackAttempt]:
        """Return the attempt for a given id, or the most-recent one if
        no id was supplied. ``None`` if the registry is empty or the id
        doesn't match. Pruning runs first so expired entries never leak
        into the result.
        """
        self.prune()
        if attempt_id:
            return self._attempts.get(attempt_id)
        if not self._attempts:
            return None
        newest_id = max(
            self._attempts.keys(), key=lambda k: self._attempts[k].created_at
        )
        return self._attempts.get(newest_id)

    def find_id(self, attempt_id: Optional[str]) -> Optional[str]:
        """Same lookup as ``find`` but return the id itself — useful when
        the caller wants to pass it to ``pop`` after a successful exchange.
        """
        self.prune()
        if attempt_id:
            return attempt_id if attempt_id in self._attempts else None
        if not self._attempts:
            return None
        return max(self._attempts.keys(), key=lambda k: self._attempts[k].created_at)

    def pop(self, attempt_id: str) -> None:
        self._attempts.pop(attempt_id, None)


def exchange_pasted_code(attempt: PastebackAttempt, code: str) -> Dict[str, Any]:
    """Run the OAuth token exchange for a paste-back attempt.

    Thin wrapper over ``OAuthFlow._exchange_token_sync`` — extracted here
    so both backends invoke it the same way. Returns the raw token dict
    (``access_token``, ``refresh_token``, optionally ``id_token``, etc.)
    or ``{"error": "..."}`` on failure.
    """
    ctx = {"client_id": attempt.client_id, "code_verifier": attempt.verifier}
    return attempt.oauth._exchange_token_sync(code.strip(), ctx)


__all__ = [
    "PastebackAttempt",
    "PastebackRegistry",
    "exchange_pasted_code",
    "PASTEBACK_MAX_AGE_SECONDS",
]
