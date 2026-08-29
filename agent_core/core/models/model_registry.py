# -*- coding: utf-8 -*-
"""Model registry mapping providers to default models.

Since Phase 1 (docs/PROVIDER_LAYER_CATCHUP.md) this is DERIVED from the
provider profiles in provider_config.py — the per-provider default models
live on ``ProviderProfile.default_models``. The dict shape and import path
are unchanged for all existing consumers.
"""

from agent_core.core.models.registry import default_models_registry

MODEL_REGISTRY = default_models_registry()
