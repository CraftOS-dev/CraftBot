# -*- coding: utf-8 -*-
"""
app.network_interface.errors

Exceptions raised by the hosted-version managed-LLM integration. Catching
them is the hosted fork's responsibility — upstream CraftBot's LLM error
classifier (agent_core/core/impl/llm/errors.py) is intentionally NOT modified;
the hosted callers in app/llm/interface.py and app/vlm_interface.py catch
these and synthesise an `LLMErrorInfo` themselves so the chat surface gets
a QUOTA-category bubble identical in shape to one classified from an
upstream provider exception.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional


class ManagedQuotaExceededError(Exception):
    """Raised by the LLM/VLM interface when a managed-Bedrock call is
    attempted while `is_quota_locked()` is true. The dashboard set
    Profile.usageLockedUntil after monthly spend crossed the plan budget;
    the agent learned about it through the response body of a previous
    /usage or /heartbeat callback (see app/network_interface/state.py).

    Carries the reset timestamp so the chat error message can tell the user
    exactly when Bedrock will resume.
    """

    def __init__(self, reset_at: Optional[_dt.datetime] = None) -> None:
        self.reset_at = reset_at
        ts = reset_at.isoformat() if reset_at else "next billing period"
        super().__init__(
            f"Managed Bedrock quota exhausted; resets at {ts}. "
            f"Configure your own API key under Settings > Models to keep using LLM features."
        )
