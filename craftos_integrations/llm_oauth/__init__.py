# -*- coding: utf-8 -*-
"""Subscription-OAuth backends for LLM providers.

Lets users connect a consumer ChatGPT Plus/Pro/Team or SuperGrok subscription
and have CraftBot draw inference quota from it instead of a paid API key.

Not an integration: no ``BasePlatformClient``, no provider, no listener
machinery, and no entry in the integrations grid. It lived under
``integrations/`` until 2026-08-26 purely so the autoloader would import it;
now it sits at the package root and ``__init__`` imports the submodules
itself, so ``factory.py`` can reach them with no autoload step. Connection
state is surfaced inside the model settings panel.

The public entry point is ``tokens.get_bearer(provider)`` — the model factory
calls it before constructing an LLM client; if it returns a token + headers,
the client is built in subscription mode and bypasses the stored API key.

WHAT IS DELIBERATELY NOT HERE: Anthropic Claude Max/Pro OAuth. Anthropic
explicitly forbade third-party tools from using Pro/Max OAuth tokens in
Feb 2026. We do not implement it. Anthropic stays API-key-only.
"""

from __future__ import annotations

from . import chatgpt, grok, tokens  # noqa: F401  (re-export side imports)

__all__ = ["chatgpt", "grok", "tokens"]
