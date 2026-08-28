"""Telegram User (MTProto) bridge provider — auth-layer-only port of the
API client.

Bridge pattern (see telegram_bot/provider.py for the binding rationale):
``TelegramUserClient`` keeps its entire API surface; only the credential plumbing is overridden by a small binding
mixin so the credential is injected per account and never read from
``telegram_user.json``. ``operations()`` is empty and
``guidance()`` blank — the action functions remain the tool
surface; account routing happens centrally in the host adapter.

Auth is Telegram's phone-login (no OAuth): ``oauth_spec()`` raises
NotImplementedError and there is no ``run_login``. The handler's UI
``fields`` (phone_number / code / password) drive a **two-phase**
``verify_token``:

* Phase 1 — phone only, no code: send the login code via the same
  ``start_auth`` helper the CLI ``/telegram_user login`` step 1 uses,
  park ``phone_code_hash`` + the partial session in the SAME module-level
  ``_pending_telegram_auth`` dict the CLI flow uses (one pending flow per
  phone, shared deliberately so either surface can finish what the other
  started), and return ``(False, "code sent — submit again…", None)``.
  ``system_connect_token`` surfaces a False message to the connect UI,
  which is how this phase talks to the user.
* Phase 2 — phone + code (+ optional 2FA password): complete auth via
  ``complete_auth`` exactly like CLI step 2, build the credential dict
  (credential dataclass fields + the provider-level ``telegram_user_id``),
  clear the pending entry, return (True, message, credential). Error
  branches mirror the CLI mapping: invalid code keeps the pending entry
  (retry with a corrected code), expired code clears it, 2FA-needed keeps
  it and asks for the password field.

The entire session state is the Telethon ``StringSession`` string inside
the credential — no session files on disk — so ``refresh()`` returns
None (sessions don't expire on a timer; a revoked session surfaces as
``session_expired`` from the API client and needs a re-login).

One account = one **phone number**. ``identity_of`` normalizes the phone
to digits only with leading zeros stripped: ``+92 300 1234567``,
``923001234567`` and ``0092-300-1234567`` all collapse to
``923001234567`` (Telegram logins use international format, so the
digits are country code + subscriber number; stripping leading zeros
removes the ``00`` international-prefix ambiguity). When the phone is
missing (e.g. a QR-login credential), the stored ``telegram_user_id``
is the fallback identity.

Disk touchpoints the binding neutralizes: ``has_credentials``
(reads ``telegram_user.json``) and ``_load`` (falls back to
``load_credential`` from disk) — both answer purely from the injected
credential. Everything else is already per-instance: ``_live_client``,
``_live_loop``, ``_send_queue``, ``_my_user_id`` and ``_agent_sent_ids``
all live on the client, and each listener builds its own Telethon
``TelegramClient`` from its own ``StringSession`` — no module-level
Telethon state, so two concurrently listening accounts never collide.
The one shared bit is the module-level *config* file
(``telegram_user_config.json``, the ``self_messages_only`` knob) read
inside ``_handle_event`` — a global read-only preference applied to
every account alike, left as-is (same call as telegram_bot).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple

from ...config import ConfigStore
from ...contracts import OAuthSpec, Operation
from .client import (
    TelegramUserClient,
    TelegramUserConfig,
    TelegramUserCredential,
    _pending_telegram_auth,
)
from .._shared import ClientListenerAdapter

_CRED_FIELDS = {f.name for f in fields(TelegramUserCredential)}

_NON_DIGITS = re.compile(r"\D+")


def _run_coro(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async auth helper from the sync ``verify_token`` contract.

    ``system_connect_token`` calls verifiers synchronously (the browser
    adapter already hops to a worker thread via ``asyncio.to_thread``),
    so there is normally no running loop here and ``asyncio.run`` is
    correct. If a caller ever invokes us on a loop thread, fall back to
    a throwaway thread so we never deadlock the running loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class TelegramUserClientBinding:
    """Overrides TelegramUserClient's disk plumbing: credential is
    injected per account. MRO puts this before the API client:

        class BoundTelegramUserClient(TelegramUserClientBinding, TelegramUserClient): pass

    No refresh — the StringSession doesn't rotate — so ``_persist`` is
    never called (kept so the build_client contract is uniform).
    """

    _cred: Optional[TelegramUserCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        # Filters to the credential dataclass's fields — drops the provider-level
        # ``telegram_user_id`` identity key the API client doesn't
        # know about.
        self._cred = TelegramUserCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> TelegramUserCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundTelegramUserClient(TelegramUserClientBinding, TelegramUserClient):
    """TelegramUserClient with per-account credential binding (see TelegramUserClientBinding)."""


class TelegramUserProvider:
    id = "telegram_user"
    family = None  # standalone — no cross-provider alias sharing
    display_name = "Telegram (User)"
    # ----- UI metadata -----
    description = "MTProto user account"
    icon = "telegram"
    fields = [
        {
            "key": "phone_number",
            "label": "Phone Number",
            "placeholder": "+923001234567",
            "password": False,
        },
        {
            "key": "code",
            "label": "Login Code (optional)",
            "placeholder": "(optional) leave empty on first submit",
            "password": False,
        },
        {
            "key": "password",
            "label": "2FA Password (optional)",
            "placeholder": "(optional) only if two-step verification is on",
            "password": True,
        },
    ]
    connect_help = [
        "One-time app credentials: open my.telegram.org, log in, click 'API development tools', submit the form (any app name works)",
        "Set the api_id and api_hash as TELEGRAM_API_ID and TELEGRAM_API_HASH in CraftBot config (they are NOT entered below)",
        "Connect step 1: enter your phone number only (international format, e.g. +923001234567) and submit - a login code is sent to your Telegram app",
        "Connect step 2: submit again with the same phone number AND the code filled in (add your 2FA password if your account has one)",
    ]
    # No "login-qr": the QR flow only ever wrote the single-account
    # telegram_user.json, which the account store never reads. The supported
    # connect is the two-phase phone+code verify_token below.
    config_class = TelegramUserConfig
    config_fields = [
        {
            "key": "self_messages_only",
            "label": "Self-messages only",
            "type": "checkbox",
            "help": "Only forward messages from your own Saved Messages chat. Drops DMs from contacts and group/channel messages before they reach the agent.",
        },
    ]

    client_cls = BoundTelegramUserClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Normalized phone number: digits only, leading zeros stripped
        (collapses ``+92…`` / ``0092…`` / spacing-and-dash variants of
        the same international number to one key). Falls back to the
        stored ``telegram_user_id`` for phone-less credentials (QR
        logins). None for junk shapes — never raises."""
        try:
            phone = credential.get("phone_number")
        except AttributeError:
            return None
        if isinstance(phone, str):
            digits = _NON_DIGITS.sub("", phone).lstrip("0")
            if digits:
                return digits
        user_id = credential.get("telegram_user_id")
        if isinstance(user_id, bool):  # bool is an int subclass — junk here
            return None
        if isinstance(user_id, int):
            return str(user_id)
        if isinstance(user_id, str) and user_id.strip():
            return user_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError("telegram_user uses phone login")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # StringSessions don't expire on a timer

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Two-phase phone login over the handler's UI fields
        (``phone_number`` / ``code`` / ``password``) — same machinery
        and pending-state dict as the CLI ``_login_phone`` flow."""
        phone = (credentials.get("phone_number") or "").strip()
        if not phone:
            return (
                False,
                "A phone number is required (international format, "
                "e.g. +923001234567).",
                None,
            )

        api_id_str = ConfigStore.get_oauth("TELEGRAM_API_ID")
        api_hash = ConfigStore.get_oauth("TELEGRAM_API_HASH")
        if not api_id_str or not api_hash:
            return (
                False,
                "Not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH.\n"
                "Get them from https://my.telegram.org → API development tools.",
                None,
            )
        try:
            api_id = int(api_id_str)
        except ValueError:
            return False, "TELEGRAM_API_ID must be a number.", None

        from . import _telegram_mtproto as helpers

        code = (credentials.get("code") or "").strip()

        # ── Phase 1 — phone only: send the login code ────────────────
        if not code:
            result = _run_coro(
                helpers.start_auth(api_id=api_id, api_hash=api_hash, phone_number=phone)
            )
            if "error" in result:
                return False, f"Failed to send code: {result['error']}", None
            _pending_telegram_auth[phone] = {
                "phone_code_hash": result["result"]["phone_code_hash"],
                "session_string": result["result"]["session_string"],
            }
            return (
                False,
                f"Verification code sent to {phone} — check your Telegram "
                "app, then submit again with the code filled in.",
                None,
            )

        # ── Phase 2 — phone + code (+ optional 2FA password) ─────────
        pending = _pending_telegram_auth.get(phone)
        if not pending:
            return (
                False,
                f"No pending login for {phone}. Submit again with the code "
                "field empty to request a new code.",
                None,
            )

        password = (credentials.get("password") or "").strip() or None
        result = _run_coro(
            helpers.complete_auth(
                api_id=api_id,
                api_hash=api_hash,
                phone_number=phone,
                code=code,
                phone_code_hash=pending["phone_code_hash"],
                password=password,
                pending_session_string=pending["session_string"],
            )
        )

        if "error" in result:
            details = result.get("details", {})
            # Same branch → message mapping as the CLI flow; pending
            # state is kept for retries, cleared only where the CLI
            # clears it (expiry — the code_hash is dead).
            if details.get("status") == "2fa_required":
                return (
                    False,
                    "2FA enabled. Submit again with the code and your "
                    "2FA password filled in.",
                    None,
                )
            if details.get("status") == "invalid_code":
                return False, "Invalid verification code. Try again.", None
            if details.get("status") == "code_expired":
                _pending_telegram_auth.pop(phone, None)
                return (
                    False,
                    "Code expired. Submit again with the code field empty "
                    "to request a new one.",
                    None,
                )
            return False, f"Auth failed: {result['error']}", None

        auth = result["result"]
        _pending_telegram_auth.pop(phone, None)

        credential = asdict(
            TelegramUserCredential(
                session_string=auth["session_string"],
                api_id=str(api_id),
                api_hash=api_hash,
                phone_number=auth.get("phone") or phone,
            )
        )
        # Provider-level identity fallback — filtered out by the binding
        # before the dataclass is constructed.
        user_id = auth.get("user_id")
        credential["telegram_user_id"] = str(user_id) if user_id is not None else ""

        account_name = (
            f"{auth.get('first_name', '')} {auth.get('last_name', '')}".strip()
        )
        username = f" (@{auth['username']})" if auth.get("username") else ""
        return True, f"Telegram user connected: {account_name}{username}", credential

    def operations(self) -> List[Operation]:
        return []  # bridge provider — action functions stay the surface

    def guidance(self) -> str:
        return ""

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> ClientListenerAdapter:
        """The API client's own Telethon event listener
        (``events.NewMessage`` + ``catch_up`` on start), reused verbatim
        via the generic adapter. Each bound client builds its own
        ``TelegramClient`` from its own ``StringSession``, and all
        listener state (_live_client, _send_queue, _my_user_id,
        _agent_sent_ids) is instance-level — per-account listeners are
        fully independent. No restart-safe cursor, same as under the
        client's own loop (Telethon's catch_up covers the gap)."""
        return ClientListenerAdapter(client, emit)
