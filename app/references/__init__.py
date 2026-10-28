"""Read-only, message-scoped references to CraftBot resources."""

from .service import ReferenceError, ReferenceService, create_reference_service

__all__ = ["ReferenceError", "ReferenceService", "create_reference_service"]
