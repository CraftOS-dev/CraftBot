"""Marketplace catalog access.

Talks to the CraftOS Marketplace server (catalog metadata: tags, stats,
ratings, featured banners) and falls back to the public GitHub
living-ui-marketplace repo when the server is unreachable or unconfigured.
"""

from app.marketplace.client import MarketplaceClient
from app.marketplace.instance_id import get_instance_id

__all__ = ["MarketplaceClient", "get_instance_id"]
