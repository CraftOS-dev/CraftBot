"""Telegram Bot bridge provider — auth-layer-only port of the legacy client.

Bridge pattern (see slack/provider.py for the full binding rationale):
the battle-tested legacy ``TelegramBotClient`` keeps its entire API
surface; only the credential plumbing is overridden by a small binding
mixin so the credential is injected per account and never read from the
legacy ``telegram_bot.json``. ``operations()`` is empty and
``guidance()`` blank — the legacy action functions remain the tool
surface; account routing happens centrally in the host adapter.

Telegram bots are token-only (a BotFather token per bot):
``oauth_spec()`` raises NotImplementedError (the conformance suite's
explicit token-only declaration) and there is no ``run_login``. Bot
tokens do not rotate, so ``refresh()`` returns None.

One account = one **bot**; identity is the bot's numeric id from
``getMe`` (Telegram's stable identifier — the username can be changed
via BotFather, the id cannot). The legacy ``TelegramBotCredential`` has
no id field, so ``verify_token`` stores it under a new ``bot_id`` key
alongside the legacy fields; the binding filters it out before
constructing the legacy dataclass, so the legacy client never sees it.

Two legacy disk touchpoints the binding must neutralize:

* ``has_credentials`` — reads ``telegram_bot.json`` and, worse,
  auto-SAVES shared-bot credentials from ConfigStore env as a side
  effect. The binding's override answers purely from the injected
  credential, so that write never fires for bound clients.
* ``_load`` — falls back to ``load_credential`` from disk when
  ``_cred`` is None. The binding raises instead.

Listener state is safely per-instance: ``_poll_offset``, ``_bot_info``,
``_catchup_done``, ``_poll_task``, and ``_listening`` all live on the
client instance — no module-level offset or singleton session, so two
concurrently listening bot accounts never fight. The one shared bit is
the module-level *config* file (``telegram_bot_config.json``, the
``self_messages_only`` knob) read inside ``_process_update`` — a global
read-only preference applied to every bot account alike, not offset
state, so it is left as-is.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...integrations.telegram_bot import (
    TELEGRAM_API_BASE,
    TelegramBotClient,
    TelegramBotCredential,
    _telegram_call_sync,
)
from .._shared import LegacyListenerAdapter

_CRED_FIELDS = {f.name for f in fields(TelegramBotCredential)}


class TelegramBotClientBinding:
    """Overrides TelegramBotClient's disk plumbing: credential is
    injected per account. MRO puts this before the legacy client:

        class BoundTelegramBotClient(TelegramBotClientBinding, TelegramBotClient): pass

    No token refresh — bot tokens are non-rotating — so ``_persist`` is
    never called (kept so the build_client contract is uniform across
    providers). ``has_credentials`` MUST be overridden here: the legacy
    version reads the credential file and auto-saves shared-bot env
    credentials to disk as a side effect.
    """

    _cred: Optional[TelegramBotCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        # Filters to legacy dataclass fields — drops the provider-level
        # ``bot_id`` identity key the legacy client doesn't know about.
        self._cred = TelegramBotCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> TelegramBotCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundTelegramBotClient(TelegramBotClientBinding, TelegramBotClient):
    """TelegramBotClient with per-account credential binding (see TelegramBotClientBinding)."""


class TelegramBotProvider:
    id = "telegram_bot"
    family = None  # standalone — no cross-provider alias sharing
    display_name = "Telegram Bot"
    client_cls = BoundTelegramBotClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """The bot's numeric id (``bot_id``, captured from getMe at
        verify time), as a string. None for pre-bridge credentials saved
        without it (legacy ``telegram_bot.json`` has only token +
        username) and for junk shapes. Tolerates an int-typed id from a
        hand-edited or json-roundtripped credential."""
        try:
            bot_id = credential.get("bot_id")
        except AttributeError:
            return None
        if isinstance(bot_id, bool):  # bool is an int subclass — junk here
            return None
        if isinstance(bot_id, int):
            return str(bot_id)
        if isinstance(bot_id, str) and bot_id.strip():
            return bot_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError("telegram_bot is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # BotFather tokens do not rotate

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Same verification the legacy TelegramBotHandler.login() runs:
        ``GET /bot<token>/getMe``; same ``fields`` key (``bot_token``).
        The bot's numeric ``id`` is stored as ``bot_id`` (plus the
        username as ``bot_username``) so ``identity_of`` resolves the
        account immediately.
        """
        token = (credentials.get("bot_token") or "").strip()
        if not token:
            return (
                False,
                "A Telegram bot token is required. "
                "Get one from @BotFather on Telegram.",
                None,
            )

        data = _telegram_call_sync(f"{TELEGRAM_API_BASE}/bot{token}/getMe")
        if "error" in data:
            return False, f"Invalid bot token: {data['error']}", None
        info = data.get("result") or {}

        credential = asdict(
            TelegramBotCredential(
                bot_token=token,
                bot_username=info.get("username", ""),
            )
        )
        bot_id = info.get("id")
        credential["bot_id"] = str(bot_id) if bot_id is not None else ""
        return (
            True,
            f"Telegram bot connected: @{info.get('username')} ({bot_id})",
            credential,
        )

    def operations(self) -> List[Operation]:
        return []  # bridge provider — legacy action functions stay the surface

    def guidance(self) -> str:
        return ""

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> LegacyListenerAdapter:
        """Long-poll listener — the legacy client's own ``getUpdates``
        loop (30s long poll with per-instance ``_poll_offset`` watermark
        and a catch-up drain on start), reused verbatim via the generic
        adapter. The offset lives on the bound client instance, so each
        account's listener keeps its own watermark. No restart-safe
        cursor, same as under the legacy manager."""
        return LegacyListenerAdapter(client, emit)
