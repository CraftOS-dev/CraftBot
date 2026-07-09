"""
App secrets (SYSTEM-MANAGED — do not edit)

`backend/.env` is the ONLY home for secrets an app needs at runtime —
external API keys the user provides (Stripe, OpenWeather, ...), the
optional DATABASE_URL, etc. Rules:

  - NEVER hardcode a secret in code, schema, or LIVING_UI.md
  - NEVER log/print/echo a secret value anywhere
  - CraftBot-connected services (Google, Slack, Discord, ...) do NOT go
    here — use services/integration_client.py, which needs no keys at all

Usage:
    from services.secrets import get_secret

    stripe_key = get_secret("STRIPE_SECRET_KEY")
    if not stripe_key:
        raise HTTPException(503, "STRIPE_SECRET_KEY not configured in backend/.env")
"""

from pathlib import Path

_ENV_FILE = Path(__file__).parent.parent / ".env"


def get_secret(key: str, default: str = "") -> str:
    """Read one value from backend/.env (KEY=VALUE lines, # comments)."""
    try:
        if _ENV_FILE.exists():
            for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, value = line.partition("=")
                if k.strip() == key:
                    return value.strip().strip("'\"")
    except OSError:
        pass
    return default


def set_secret(key: str, value: str) -> None:
    """Write/replace one value in backend/.env (idempotent)."""
    lines = []
    try:
        if _ENV_FILE.exists():
            lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            if stripped.partition("=")[0].strip() == key:
                lines[i] = f"{key}={value}"
                replaced = True
                break
    if not replaced:
        lines.append(f"{key}={value}")
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
