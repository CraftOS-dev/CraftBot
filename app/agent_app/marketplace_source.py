"""CraftBot marketplace branch preference, passed to the upstream CLI."""

def ref() -> str:
    """Use settings.json's marketplace branch, defaulting to main."""
    from app.config import get_marketplace_ref

    return get_marketplace_ref() or "main"
