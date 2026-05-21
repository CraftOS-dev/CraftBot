"""Base classes for integrations.

Two abstract lifecycles, intentionally separate:

  * IntegrationHandler — login / logout / status / invite (auth flows)
  * BasePlatformClient — connect / send_message / start_listening (runtime)

Each integration declares one of each, both holding the same IntegrationSpec
(composition). The two classes do not share a base — they are collaborators.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


# ════════════════════════════════════════════════════════════════════════
# Runtime side: PlatformMessage + BasePlatformClient
# ════════════════════════════════════════════════════════════════════════


@dataclass
class PlatformMessage:
    platform: str
    sender_id: str
    sender_name: str = ""
    text: str = ""
    channel_id: str = ""
    channel_name: str = ""
    message_id: str = ""
    timestamp: Optional[datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)


MessageCallback = Callable[[PlatformMessage], Awaitable[None]]


class BasePlatformClient(ABC):
    PLATFORM_ID: str = ""

    def __init__(self) -> None:
        self._connected = False
        self._listening = False
        self._message_callback: Optional[MessageCallback] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_listening(self) -> bool:
        return self._listening

    @abstractmethod
    def has_credentials(self) -> bool: ...

    @abstractmethod
    async def connect(self) -> None: ...

    async def disconnect(self) -> None:
        if self._listening:
            await self.stop_listening()
        self._connected = False

    @abstractmethod
    async def send_message(
        self, recipient: str, text: str, **kwargs
    ) -> Dict[str, Any]: ...

    @property
    def supports_listening(self) -> bool:
        return False

    async def start_listening(self, callback: MessageCallback) -> None:
        raise NotImplementedError(f"{self.PLATFORM_ID} does not support listening")

    async def stop_listening(self) -> None:
        self._listening = False


# ════════════════════════════════════════════════════════════════════════
# Auth side: IntegrationHandler
# ════════════════════════════════════════════════════════════════════════


class IntegrationHandler(ABC):
    # ----- UI / metadata (override on each handler) -----
    display_name: str = ""
    description: str = ""
    # auth_type: "token" | "oauth" | "both" | "interactive" | "token_with_interactive"
    auth_type: str = "token"
    fields: List[Dict[str, Any]] = []
    # Lucide icon name (PascalCase) shown on the integration card when the
    # frontend doesn't have a hand-crafted SVG override. See lucide.dev for
    # the full set — examples: "Github", "Linkedin", "Send", "MessageCircle",
    # "Mail", "FileText". Empty string falls back to a generic icon.
    icon: str = ""
    # Optional inline guidance shown when the user clicks the "?" button
    # in the connect modal. Each entry is one step / one place to look —
    # the frontend renders them as a numbered list inside a popover.
    # Keep entries short and action-oriented ("Open X console", "Copy
    # the Y token from the Z tab") — the goal is "where do I find this",
    # not a full tutorial. ``None`` hides the "?" button.
    connect_help: Optional[List[str]] = None

    # ----- Optional runtime config (post-connect knobs) -----
    # ``config_class`` is a plain ``@dataclass`` whose fields hold the
    # per-integration settings users tune from the Configure UI (e.g.
    # ``watch_tag``, ``watch_repos``, ``channel_filter``). ``config_fields``
    # is the matching render schema the frontend uses to draw the form.
    # Both default to "no config" — the Configure section is hidden for
    # integrations that don't declare them. See ``service.get_config`` /
    # ``service.update_config`` for how they get loaded and saved.
    #
    # Schema entry shape:
    #   {"key": "watch_tag", "label": "Watch tag",
    #    "type": "text" | "textarea" | "list" | "checkbox" | "select" | "number",
    #    "placeholder": "@craftbot",      # optional
    #    "help": "Trigger keyword.",      # optional
    #    "options": [...]}                # required when type=="select"
    config_class: Optional[type] = None
    config_fields: List[Dict[str, Any]] = []

    @abstractmethod
    async def login(self, args: List[str]) -> Tuple[bool, str]: ...

    @abstractmethod
    async def logout(self, args: List[str]) -> Tuple[bool, str]: ...

    @abstractmethod
    async def status(self) -> Tuple[bool, str]: ...

    async def invite(self, args: List[str]) -> Tuple[bool, str]:
        return False, "Invite not available for this integration. Use 'login' instead."

    @property
    def subcommands(self) -> List[str]:
        return ["login", "logout", "status"]

    async def handle(self, sub: str, args: List[str]) -> Tuple[bool, str]:
        if sub == "invite":
            return await self.invite(args)
        if sub == "login":
            return await self.login(args)
        if sub == "logout":
            return await self.logout(args)
        if sub == "status":
            return await self.status()
        return False, f"Unknown subcommand: {sub}. Use: {', '.join(self.subcommands)}"

    # ----- Default connect dispatchers (overridable per handler) -----

    async def connect_token(self, creds: Dict[str, str]) -> Tuple[bool, str]:
        """Map a {field_key: value} dict to login() args, in field-declaration order."""
        if not self.fields:
            return (
                False,
                f"Token-based login not supported for {self.display_name or 'this integration'}",
            )
        args: List[str] = []
        for field_def in self.fields:
            key = field_def["key"]
            value = creds.get(key, "")
            if not value and not field_def.get("optional"):
                label = field_def.get("label", key)
                return False, f"{label} is required"
            args.append(value)
        # Drop trailing optional empties so handler.login can use len(args) checks
        while args and not args[-1]:
            field_def = self.fields[len(args) - 1]
            if field_def.get("optional"):
                args.pop()
            else:
                break
        return await self.login(args)

    async def connect_oauth(self, args: Optional[List[str]] = None) -> Tuple[bool, str]:
        """OAuth dispatcher: prefers invite() for 'both' auth, else login()."""
        a = args or []
        if self.auth_type == "both" and hasattr(self, "invite"):
            return await self.invite(a)
        return await self.login(a)

    async def connect_interactive(
        self, args: Optional[List[str]] = None
    ) -> Tuple[bool, str]:
        """Interactive (e.g. QR scan) dispatcher: prefers 'login-qr' subcommand if exposed."""
        a = args or []
        sub = "login-qr" if "login-qr" in self.subcommands else "login"
        return await self.handle(sub, a)
