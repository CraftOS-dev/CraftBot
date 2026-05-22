# -*- coding: utf-8 -*-
"""
Sliding-window token rate limiter for Slow Mode.

When Slow Mode is enabled, this module throttles LLM calls to stay
within a configurable tokens-per-minute (TPM) limit.
"""

import logging
import time
import threading
from collections import deque
from typing import Tuple

logger = logging.getLogger(__name__)


class TokenRateLimiter:
    """Sliding-window rate limiter for tokens per minute."""

    def __init__(self):
        self._window: deque[Tuple[float, int]] = deque()  # (timestamp, token_count)
        self._lock = threading.Lock()

    def _get_tpm_limit(self) -> int:
        """Read TPM limit from settings (single source of truth)."""
        from app.config import get_slow_mode_tpm_limit

        return get_slow_mode_tpm_limit()

    def _prune_window(self):
        """Remove entries older than 60 seconds."""
        cutoff = time.monotonic() - 60.0
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

    def tokens_used_in_window(self) -> int:
        """Return total tokens consumed in the current 60-second window."""
        with self._lock:
            self._prune_window()
            return sum(t for _, t in self._window)

    def wait_if_needed(self, estimated_tokens: int = 0) -> float:
        """Block until there is capacity for estimated_tokens.

        Returns the number of seconds waited.
        """
        tpm_limit = self._get_tpm_limit()
        waited = 0.0
        with self._lock:
            while True:
                self._prune_window()
                used = sum(t for _, t in self._window)
                if used + estimated_tokens <= tpm_limit:
                    break
                if not self._window:
                    break
                # Wait until the oldest entry expires from the window
                oldest_ts = self._window[0][0]
                wait_time = oldest_ts + 60.0 - time.monotonic() + 0.1
                if wait_time <= 0:
                    continue
                # Release lock while sleeping so other threads aren't blocked
                self._lock.release()
                logger.info(
                    f"[SLOW MODE] Rate limit approaching ({used}/{tpm_limit} TPM). "
                    f"Waiting {wait_time:.1f}s..."
                )
                time.sleep(wait_time)
                waited += wait_time
                self._lock.acquire()
        return waited

    def record_usage(self, tokens: int):
        """Record that tokens were consumed just now."""
        if tokens > 0:
            with self._lock:
                self._window.append((time.monotonic(), tokens))

    def reset(self):
        """Clear the sliding window."""
        with self._lock:
            self._window.clear()


# Module-level singleton
_rate_limiter = TokenRateLimiter()


def get_rate_limiter() -> TokenRateLimiter:
    """Return the global rate limiter instance."""
    return _rate_limiter
