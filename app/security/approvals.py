"""Pending approvals: the gate asks, the user answers on an approval card.

Modelled on OpenClaw's exec approvals and Hermes' gateway approvals:

- Each request has an id; the card answers it with ``allow_once``,
  ``allow_session`` or ``deny``. ``allow_session`` covers the same action
  for the rest of the session (Hermes' session grant); for a command it
  covers that exact command in that folder only (OpenClaw's allow-always
  binding), so one approval never lets every later command through.
- Hidden characters in inputs (invisible, bidi, odd spaces) are shown as
  ``\\u{XXXX}`` on the card, so a command cannot look like another one
  (OpenClaw's exec-approval-text-sanitize.ts).
- No answer within the timeout, or no window to show the card in, counts as
  a denial (OpenClaw's ``askFallback: deny``).
- Consecutive denials in a session are counted, so the agent can be told to
  stop and ask instead of trying again (Hermes' denial circuit breaker).

Only the waiting action blocks; other sessions and actions keep running.
"""

from __future__ import annotations

import asyncio
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from agent_core.utils.logger import logger


class Decision(str, Enum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    DENY = "deny"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    @property
    def allowed(self) -> bool:
        return self in (Decision.ALLOW_ONCE, Decision.ALLOW_SESSION)


@dataclass
class ApprovalRequest:
    id: str
    session_id: str
    action_name: str
    action_display_name: str
    effects: List[str]
    reason: str  # "high_risk", "untrusted_content" or "risky_command"
    reason_detail: str
    inputs: Dict[str, Any]
    created_at: float
    expires_at: float
    # What "allow for this session" grants; not shown on the card.
    grant_key: str = ""
    # "command" when it covers this exact command only, else "action".
    grant_scope: str = "action"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("grant_key", None)
        return data


Notifier = Callable[[Dict[str, Any]], Awaitable[None]]

# Inputs larger than this are shortened on the card; the action still gets
# the full value. A command is shown up to OpenClaw's display cap, so what
# runs is what the user reads.
_PREVIEW_CHARS = 2000
_COMMAND_PREVIEW_CHARS = 16 * 1024

# Characters that can hide or disguise text (OpenClaw: Cc, Cf, Cs, Zl, Zp and
# odd spaces); line breaks and tabs stay as they are.
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_ODD_SPACES = frozenset(
    "\u00a0\u1680\u202f\u205f\u3000\u115f\u1160\u3164\uffa0"
    + "".join(chr(c) for c in range(0x2000, 0x200B))
)


def show_hidden(text: str) -> str:
    if text.isascii() and text.isprintable():
        return text
    return "".join(
        f"\\u{{{ord(ch):X}}}"
        if ch not in "\n\t"
        and (ch in _ODD_SPACES or unicodedata.category(ch) in _HIDDEN_CATEGORIES)
        else ch
        for ch in text
    )


def _shown(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        value = show_hidden(value)
        if len(value) > limit:
            value = value[:limit] + f"… ({len(value)} characters)"
        return value
    if isinstance(value, dict):
        return {k: _shown(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_shown(v, limit) for v in value]
    return value


def _preview(inputs: Dict[str, Any], command_keys=()) -> Dict[str, Any]:
    shown: Dict[str, Any] = {}
    for key, value in inputs.items():
        if key.startswith("_"):
            continue  # internal routing keys, not chosen by the agent
        limit = _COMMAND_PREVIEW_CHARS if key in command_keys else _PREVIEW_CHARS
        shown[key] = _shown(value, limit)
    return shown


@dataclass
class ApprovalBroker:
    _pending: Dict[str, Tuple[ApprovalRequest, asyncio.Future]] = field(
        default_factory=dict
    )
    _grants: Dict[str, Set[str]] = field(default_factory=dict)
    _denials: Dict[str, int] = field(default_factory=dict)
    _notify: Optional[Notifier] = None
    _ui_connected: Callable[[], bool] = lambda: False

    # ── wiring ──

    def attach_ui(self, notify: Notifier, is_connected: Callable[[], bool]) -> None:
        self._notify = notify
        self._ui_connected = is_connected

    def ui_available(self) -> bool:
        try:
            return self._notify is not None and bool(self._ui_connected())
        except Exception:
            return False

    # ── grants and denials ──

    def is_granted(self, session_id: str, grant_key: str) -> bool:
        return grant_key in self._grants.get(session_id, ())

    def consecutive_denials(self, session_id: str) -> int:
        return self._denials.get(session_id, 0)

    def clear_session(self, session_id: str) -> None:
        self._grants.pop(session_id, None)
        self._denials.pop(session_id, None)
        for request_id, (request, _) in list(self._pending.items()):
            if request.session_id == session_id:
                self.resolve(request_id, Decision.CANCELLED)

    # ── asking ──

    async def request(
        self,
        *,
        session_id: str,
        action_name: str,
        action_display_name: str,
        effects: List[str],
        reason: str,
        reason_detail: str,
        inputs: Dict[str, Any],
        timeout_s: float,
        grant_key: str = "",
        grant_scope: str = "action",
        command_keys: Tuple[str, ...] = (),
    ) -> Decision:
        now = time.time()
        request = ApprovalRequest(
            id=uuid.uuid4().hex,
            session_id=session_id,
            action_name=action_name,
            action_display_name=action_display_name,
            effects=effects,
            reason=reason,
            reason_detail=reason_detail,
            inputs=_preview(inputs, command_keys),
            created_at=now,
            expires_at=now + timeout_s,
            grant_key=grant_key or action_name,
            grant_scope=grant_scope,
        )
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request.id] = (request, future)
        await self._send({"type": "security_approval_request", "data": request.to_dict()})
        try:
            decision = await asyncio.wait_for(asyncio.shield(future), timeout_s)
        except asyncio.TimeoutError:
            decision = Decision.TIMEOUT
        except asyncio.CancelledError:
            # The turn was stopped while waiting; the card must not linger.
            self._finish(request, Decision.CANCELLED)
            await self._send_resolved(request.id, Decision.CANCELLED)
            raise
        self._finish(request, decision)
        await self._send_resolved(request.id, decision)
        return decision

    def resolve(self, request_id: str, decision: Decision) -> bool:
        """Answer a pending request (from the card). False if unknown."""
        entry = self._pending.get(request_id)
        if entry is None:
            return False
        _, future = entry

        def settle() -> None:
            if not future.done():
                future.set_result(decision)

        # Safe from any thread: the answer may arrive outside the loop the
        # waiting action runs on.
        future.get_loop().call_soon_threadsafe(settle)
        return True

    def pending(self) -> List[Dict[str, Any]]:
        return [request.to_dict() for request, _ in self._pending.values()]

    # ── internals ──

    def _finish(self, request: ApprovalRequest, decision: Decision) -> None:
        self._pending.pop(request.id, None)
        if decision == Decision.ALLOW_SESSION:
            self._grants.setdefault(request.session_id, set()).add(request.grant_key)
        if decision.allowed:
            self._denials.pop(request.session_id, None)
        elif decision in (Decision.DENY, Decision.TIMEOUT):
            self._denials[request.session_id] = self._denials.get(request.session_id, 0) + 1

    async def _send_resolved(self, request_id: str, decision: Decision) -> None:
        await self._send(
            {
                "type": "security_approval_resolved",
                "data": {"id": request_id, "decision": decision.value},
            }
        )

    async def _send(self, message: Dict[str, Any]) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(message)
        except Exception as exc:
            logger.warning(f"[SECURITY] Could not reach the UI: {exc}")


broker = ApprovalBroker()
