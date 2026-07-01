# -*- coding: utf-8 -*-
"""Subscription-OAuth backends for LLM providers.

Lets users connect a consumer ChatGPT Plus/Pro/Team or SuperGrok subscription
and have CraftBot draw inference quota from it instead of a paid API key.

Not a normal integration: there is no ``BasePlatformClient`` and no listener
machinery. The autoloader imports this package (good — that's how
the inner ``chatgpt`` and ``grok`` modules become resolvable from
``factory.py``), but no ``register_handler`` is called and no entry shows up
in the integrations grid. Connection state is surfaced inside the model
settings panel instead.

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
