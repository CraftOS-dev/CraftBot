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


@pytest.fixture(autouse=True)
def configured_context_window(monkeypatch):
    """Give every test a configured model.context_window.

    It is required configuration -- the agent refuses to start without it --
    and the tracked settings.json ships it as null on purpose. A test that
    exercises the missing-window error patches get_settings itself, which
    takes precedence over this fixture for that test.
    """
    from app import config as app_config

    real_get_settings = app_config.get_settings

    def _with_window(reload: bool = False):
        settings = dict(real_get_settings(reload))
        model = dict(settings.get("model") or {})
        if not model.get("context_window"):
            model["context_window"] = 128000
        settings["model"] = model
        context = dict(settings.get("context") or {})
        context.setdefault("stream_fraction_of_window", 0.5)
        context.setdefault("tail_keep_fraction", 0.4)
        settings["context"] = context
        return settings

    monkeypatch.setattr(app_config, "get_settings", _with_window)


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
