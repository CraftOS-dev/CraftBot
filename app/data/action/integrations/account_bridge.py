"""Account-awareness bridge for the integration action layer.

Bridged platforms keep their hand-written action files unchanged; the two
halves of account selection are handled centrally:

  - schema side (HERE): ``inject_account_schemas()`` adds the same
    ``account`` input property the craftbot_adapter injects for generated
    provider actions, to every registered action whose source file lives under
    a bridged platform's directory. Called once by the host right after
    action discovery (see ``AgentBase.__init__``).
  - execution side: ``_helpers._bridge_client_or_error`` reads the hint
    from the executor's input-data context and resolves it through the
    IntegrationSystem — no per-action code.

``BRIDGED_ACTION_DIRS`` maps an action directory name under
``app/data/action/integrations/`` to its platform: the display label used
in the injected description and the provider(s) its actions belong to
(the capability catalog and integration guidance read those). Add a
directory here when its platform(s) get a provider.
"""

from __future__ import annotations

import os
from typing import Dict, NamedTuple, Optional, Tuple

from agent_core.core.action_framework.registry import ActionRegistry

from craftos_integrations.logger import get_logger

logger = get_logger(__name__)


class BridgedPlatform(NamedTuple):
    label: str
    providers: Tuple[str, ...]


BRIDGED_ACTION_DIRS: Dict[str, BridgedPlatform] = {
    "stripe": BridgedPlatform("Stripe", ("stripe",)),
    "github": BridgedPlatform("GitHub", ("github",)),
    "jira": BridgedPlatform("Jira", ("jira",)),
    "line": BridgedPlatform("LINE", ("line",)),
    "discord": BridgedPlatform("Discord", ("discord",)),
    "lark": BridgedPlatform("Lark", ("lark",)),
    "lark_calendar": BridgedPlatform("Lark Calendar", ("lark_calendar",)),
    "lark_drive": BridgedPlatform("Lark Drive", ("lark_drive",)),
    # The telegram dir hosts both the Bot API and the user-account actions.
    "telegram": BridgedPlatform("Telegram", ("telegram_bot", "telegram_user")),
    "twitter": BridgedPlatform("Twitter/X", ("twitter",)),
    # whatsapp_web + whatsapp_business both have v2 providers; every action
    # in the dir resolves through the v2 accounts system.
    "whatsapp": BridgedPlatform("WhatsApp", ("whatsapp_web", "whatsapp_business")),
}

_MARKER = os.sep + "integrations" + os.sep


def _account_schema(label: str) -> Dict[str, str]:
    # Keep wording in lockstep with craftbot_adapter._account_schema —
    # the model sees both and must treat them identically.
    return {
        "type": "string",
        # Omitted: the primary account.
        "required": False,
        "description": (
            f"Optional {label} account to act as: an identity, the user's "
            f"nickname for the account (e.g. 'work'), or any unique "
            f"fragment of either. OMIT to use the primary account. Always "
            f"set this when the user names an account in any form."
        ),
        "example": "",
    }


def integration_dir_of(handler) -> Optional[str]:
    """The integrations/<dir>/ an action's source file lives under, if any."""
    try:
        filename = handler.__code__.co_filename
    except AttributeError:
        return None
    marker_at = filename.rfind(_MARKER)
    if marker_at == -1:
        return None
    rest = filename[marker_at + len(_MARKER) :]
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
            platform = BRIDGED_ACTION_DIRS.get(
                integration_dir_of(registered.handler) or ""
            )
            if platform is None:
                continue
            schema = registered.metadata.input_schema
            if isinstance(schema, dict) and "account" not in schema:
                schema["account"] = _account_schema(platform.label)
                injected += 1
    if injected:
        logger.info(
            f"[ACCOUNT_BRIDGE] Injected 'account' input into {injected} "
            f"actions across {sorted(BRIDGED_ACTION_DIRS)}"
        )
    return injected
