# -*- coding: utf-8 -*-
"""Every module in the package must import.

Added 2026-08-26 after folding ``integrations/`` into ``providers/``. Moving
``llm_oauth`` up one directory left 13 relative imports overshooting the
package root (``from ...credentials_store`` where ``...`` now escapes
``craftos_integrations``), so subscription-mode LLM auth failed at import for
both ChatGPT and Grok — and the full suite still passed, because nothing in it
reaches that package.

A test that only exercises what the rest of the suite already touches would
not have caught it. This one walks every module.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import craftos_integrations
from craftos_integrations import configure


def _module_names():
    configure(project_root=".")
    return sorted(
        m.name
        for m in pkgutil.walk_packages(
            craftos_integrations.__path__, craftos_integrations.__name__ + "."
        )
    )


@pytest.mark.parametrize("module_name", _module_names())
def test_module_imports(module_name):
    importlib.import_module(module_name)


def test_llm_oauth_entry_points():
    """``factory.py`` calls these before building an LLM client; if the module
    cannot import, CraftBot silently loses subscription-mode auth."""
    from craftos_integrations.llm_oauth import chatgpt, grok, tokens

    assert callable(tokens.get_bearer)
    assert callable(tokens.status)
    assert callable(chatgpt.load)
    assert chatgpt.CODEX_ACCEPTED_MODELS
    assert callable(grok.load)

    # Not connected on a clean checkout, but the call must work.
    state = tokens.status("openai")
    assert state["supported"] is True
    assert "connected" in state


def test_every_provider_has_a_client_module():
    """The autoloader imports ``providers/<id>/client.py`` and nothing else —
    a provider whose client lives elsewhere registers no client at all."""
    from pathlib import Path

    from craftos_integrations.providers import provider_ids

    root = Path(craftos_integrations.__file__).parent / "providers"
    missing = [p for p in provider_ids() if not (root / p / "client.py").is_file()]
    assert not missing, f"providers with no client.py: {missing}"


def test_autoloader_registers_every_provider():
    from craftos_integrations import autoload_integrations, get_all_clients
    from craftos_integrations.providers import provider_ids

    autoload_integrations(force=True)
    assert not set(provider_ids()) - set(get_all_clients())
