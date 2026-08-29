import os
import ssl
import sys

import pytest
from pathlib import Path

# Windows SSL-store shim: importing aiohttp in this env can hit a broken
# certificate in the Windows cert store (ssl.SSLError [ASN1: NOT_ENOUGH_DATA]).
# Swallow the error so collection/imports succeed (mirrors app/main.py shim).
_orig_load_windows_store_certs = ssl.SSLContext._load_windows_store_certs


def _safe_load_windows_store_certs(self, storename, purpose):
    try:
        _orig_load_windows_store_certs(self, storename, purpose)
    except ssl.SSLError:
        pass


ssl.SSLContext._load_windows_store_certs = _safe_load_windows_store_certs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


@pytest.fixture
def event_stream_limits(monkeypatch):
    """Pin EventStream's summarization thresholds for a test.

    EventStream reads them from settings.json, so without this a local config
    edit would silently change what an event-stream test exercises. The import
    is inside the fixture so collecting unrelated tests does not pull in
    event_stream (and sklearn with it).

    Call with no arguments for thresholds high enough that nothing folds — the
    right choice for tests that are not about summarization at all.
    """
    from agent_core.core.impl.event_stream import event_stream as event_stream_module

    def _pin(
        summarize_at_tokens: int = 100000,
        tail_keep_after_summarize_tokens: int = 10000,
    ) -> None:
        monkeypatch.setattr(
            event_stream_module,
            "_configured_context_limits",
            lambda: (summarize_at_tokens, tail_keep_after_summarize_tokens),
        )

    return _pin
