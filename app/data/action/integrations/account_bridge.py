"""Account-awareness bridge for legacy integration actions.

Bridged platforms keep their hand-written action files unchanged; the two
halves of account selection are handled centrally:

  - schema side (HERE): ``inject_account_schemas()`` adds the same
    ``account`` input property the craftbot_adapter injects for generated
    v2 actions, to every registered action whose source file lives under
    a bridged platform's directory. Called once by the host right after
    action discovery (see ``AgentBase.__init__``).
  - execution side: ``_helpers._bridge_client_or_error`` reads the hint
    from the executor's input-data context and resolves it through the
    IntegrationSystem — no per-action code.

``BRIDGED_ACTION_DIRS`` maps an action directory name under
``app/data/action/integrations/`` to the display label used in the
injected description. Add a directory here when its platform(s) get a
v2 provider. The ``whatsapp`` directory intentionally stays out until
whatsapp_web is bridged (wave 3): whatsapp_business shares the
directory, and advertising ``account`` on whatsapp_web actions before
its provider exists would only produce resolution errors.
"""

from __future__ import annotations

import os
from typing import Dict

from agent_core.core.action_framework.registry import ActionRegistry

from craftos_integrations.logger import get_logger

logger = get_logger(__name__)

BRIDGED_ACTION_DIRS: Dict[str, str] = {
    "stripe": "Stripe",
    "github": "GitHub",
    "jira": "Jira",
    "line": "LINE",
    # Wave 2. The telegram dir also hosts telegram_user actions (wave 3):
    # a hint on those errors loudly and self-correctingly until it's
    # bridged.
    "discord": "Discord",
    "lark": "Lark",
    "lark_calendar": "Lark Calendar",
    "lark_drive": "Lark Drive",
    "telegram": "Telegram",
    "twitter": "Twitter/X",
}

_MARKER = os.sep + "integrations" + os.sep


def _account_schema(label: str) -> Dict[str, str]:
    # Keep wording in lockstep with craftbot_adapter._account_schema —
    # the model sees both and must treat them identically.
    return {
        "type": "string",
        "description": (
            f"Optional {label} account to act as: an identity, the user's "
            f"nickname for the account (e.g. 'work'), or any unique "
            f"fragment of either. OMIT to use the primary account. Always "
            f"set this when the user names an account in any form."
        ),
        "example": "",
    }


def _dir_for(handler) -> str | None:
    """The integrations/<dir>/ an action's source file lives under, if any."""
    try:
        filename = handler.__code__.co_filename
    except AttributeError:
        return None
    marker_at = filename.rfind(_MARKER)
    if marker_at == -1:
        return None
    rest = filename[marker_at + len(_MARKER):]
    return rest.split(os.sep, 1)[0] if os.sep in rest else None


def inject_account_schemas() -> int:
    """Add the ``account`` input to every bridged platform's actions.

    Idempotent (setdefault semantics); returns the number of actions
    touched. Runs against the live registry, so it must be called after
    ``load_actions_from_directories`` and before the first prompt build.
    """
    injected = 0
    registry = ActionRegistry()
    # _registry: {name: {platform_key: RegisteredAction}} — no public
    # iterator exists; the registry is in-repo and this read is the same
    # one list_all_actions_as_json performs.
    for impls in registry._registry.values():
        for registered in impls.values():
            label = BRIDGED_ACTION_DIRS.get(_dir_for(registered.handler) or "")
            if label is None:
                continue
            schema = registered.metadata.input_schema
            if isinstance(schema, dict) and "account" not in schema:
                schema["account"] = _account_schema(label)
                injected += 1
    if injected:
        logger.info(
            f"[ACCOUNT_BRIDGE] Injected 'account' input into {injected} "
            f"legacy actions across {sorted(BRIDGED_ACTION_DIRS)}"
        )
    return injected
