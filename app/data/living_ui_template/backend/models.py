"""
Living UI Models (SYSTEM-MANAGED — do not edit)

There is nothing to hand-write here. App data models are DECLARED, not
coded: define your entities in config/schema.json and the engine
(engine.py) materializes the SQLAlchemy models AND their full REST CRUD
API automatically — correct autoincrement ids, timestamps, camelCase
serialization, filters, ordering, bulk insert, and relationship-aware
deletes, all pre-tested.

    config/schema.json  ->  models + /api/<plural> CRUD routes

This module re-exports everything so `from models import <Entity>` works
for tests and custom routes.
"""

from system_models import Base, AppState, UISnapshot, UIScreenshot  # noqa: F401
from engine import get_models as _get_engine_models

# Engine-materialized entities become importable by name: from models import Card
_ENGINE_MODELS = _get_engine_models()
globals().update(_ENGINE_MODELS)

__all__ = ["Base", "AppState", "UISnapshot", "UIScreenshot"] + list(_ENGINE_MODELS)
