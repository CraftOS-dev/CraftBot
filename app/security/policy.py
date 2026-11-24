"""Security settings: levels, the policy they resolve to, and where it lives.

The policy is read on every action, so it is resolved once into a frozen
snapshot and swapped atomically when the user changes a setting. Reading it
is one global lookup; nothing on the hot path touches the disk.

Levels are presets over individual settings. ``standard`` is CraftBot's
behaviour before security levels existed, so an upgrade changes nothing.
A setting the user changes on top of a level is stored as an override, and
the page then shows the level as "Custom".

Approval prompts are separate from levels: they appear only when the user
turns Auto mode off (``auto_mode``), whatever the level.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field, fields, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from app.security.files import write_private_json

SCHEMA_VERSION = 1


class SecurityLevel(str, Enum):
    STANDARD = "standard"
    ENHANCED = "enhanced"
    STRICT = "strict"


class Effect(str, Enum):
    """What an action can do to the world, as the action declares it.

    Approval and taint decisions are made on these declarations, never on
    an action's name or the text of its arguments.
    """

    EXECUTE = "execute"  # runs commands or code on this computer
    WRITE_FILES = "write_files"  # creates, changes or deletes files
    SEND_EXTERNAL = "send_external"  # sends to people or changes outside services
    CHANGE_AGENT = "change_agent"  # changes CraftBot's own setup, schedules or tools
    USE_CREDENTIALS = "use_credentials"  # reads or uses stored credentials


class ContentSource(str, Enum):
    """Where an action's result comes from (OpenClaw's resultContentSource)."""

    LOCAL = "local"
    NETWORK = "network"


# Effects that make an action high-risk: with Auto mode off, these ask first.
HIGH_RISK_EFFECTS: FrozenSet[Effect] = frozenset(
    {
        Effect.EXECUTE,
        Effect.SEND_EXTERNAL,
        Effect.CHANGE_AGENT,
        Effect.USE_CREDENTIALS,
    }
)


@dataclass(frozen=True)
class SecurityPolicy:
    """The effective security settings. Field defaults are the Standard level."""

    level: SecurityLevel = SecurityLevel.STANDARD
    # True when the user changed settings on top of the level's preset.
    customized: bool = False

    # ── Approvals (only when Auto mode is off) ──
    auto_mode: bool = True
    approval_effects: FrozenSet[Effect] = HIGH_RISK_EFFECTS
    # After a turn reads untrusted content, ask before ANY action with an effect.
    ask_after_untrusted: bool = False
    approval_timeout_s: int = 300

    # ── Untrusted content ──
    mark_untrusted_content: bool = False

    # ── Files ──
    protect_secret_files: bool = False
    extra_protected_paths: Tuple[str, ...] = ()
    confine_writes: bool = False
    workspace_paths: Tuple[str, ...] = ()

    # ── Network ──
    network_guard: bool = False
    allowed_domains: Tuple[str, ...] = ()
    third_party_reader: bool = True

    # ── Secrets and data ──
    scrub_child_env: bool = False
    redact_logs: bool = False
    log_prompts: bool = True
    retention_days: int = 0  # 0 keeps everything

    # ── Channels ──
    strict_channel_identity: bool = False
    # Only these senders' emails reach the agent (exact addresses). Empty:
    # every inbox email, as before. A From address can be forged, so this
    # narrows what arrives; it is not proof of who sent it.
    email_allowed_senders: Tuple[str, ...] = ()

    # ── Audit ──
    audit_log: bool = False

    @property
    def gate_active(self) -> bool:
        """Whether the action gate has anything to decide. False at the
        default settings, so the gate costs one attribute read per action."""
        return not self.auto_mode

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["level"] = self.level.value
        data["approval_effects"] = sorted(e.value for e in self.approval_effects)
        for key in (
            "extra_protected_paths",
            "workspace_paths",
            "allowed_domains",
            "email_allowed_senders",
        ):
            data[key] = list(data[key])
        return data


# Settings a preset decides. ``auto_mode`` and the path/domain lists are the
# user's own and never change with the level.
_PRESETS: Dict[SecurityLevel, Dict[str, Any]] = {
    SecurityLevel.STANDARD: {},
    SecurityLevel.ENHANCED: {
        "ask_after_untrusted": True,
        "mark_untrusted_content": True,
        "protect_secret_files": True,
        "network_guard": True,
        "scrub_child_env": True,
        "redact_logs": True,
        "log_prompts": False,
        "retention_days": 90,
        "strict_channel_identity": True,
        "audit_log": True,
    },
    SecurityLevel.STRICT: {
        "approval_effects": HIGH_RISK_EFFECTS | {Effect.WRITE_FILES},
        "ask_after_untrusted": True,
        "mark_untrusted_content": True,
        "protect_secret_files": True,
        "confine_writes": True,
        "network_guard": True,
        "third_party_reader": False,
        "scrub_child_env": True,
        "redact_logs": True,
        "log_prompts": False,
        "retention_days": 30,
        "strict_channel_identity": True,
        "audit_log": True,
    },
}

_USER_FIELDS = frozenset(
    {
        "auto_mode",
        "extra_protected_paths",
        "workspace_paths",
        "allowed_domains",
        "email_allowed_senders",
    }
)
_FIELD_TYPES = {f.name: f for f in fields(SecurityPolicy)}
_SETTABLE = frozenset(_FIELD_TYPES) - {"level", "customized"}


class SecurityConfigError(ValueError):
    """A security setting has the wrong type or value."""


def preset(level: SecurityLevel) -> SecurityPolicy:
    return replace(SecurityPolicy(level=level), **_PRESETS[level])


def _coerce(name: str, value: Any) -> Any:
    """Validate one stored or submitted setting into the policy's type."""
    current = getattr(SecurityPolicy(), name)
    if name == "approval_effects":
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise SecurityConfigError(f"{name} must be a list")
        try:
            return frozenset(Effect(v) for v in value)
        except ValueError as exc:
            raise SecurityConfigError(str(exc)) from None
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise SecurityConfigError(f"{name} must be true or false")
        return value
    if isinstance(current, int):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SecurityConfigError(f"{name} must be a whole number of 0 or more")
        if name == "approval_timeout_s" and not 10 <= value <= 3600:
            raise SecurityConfigError(f"{name} must be between 10 and 3600")
        return value
    if isinstance(current, tuple):
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(v, str) and v.strip() for v in value
        ):
            raise SecurityConfigError(f"{name} must be a list of non-empty text")
        return tuple(v.strip() for v in value)
    raise SecurityConfigError(f"Unknown setting: {name}")


def resolve(level: SecurityLevel, overrides: Dict[str, Any]) -> SecurityPolicy:
    base = preset(level)
    changes = {name: _coerce(name, value) for name, value in overrides.items()}
    policy = replace(base, **changes)
    customized = any(
        getattr(policy, name) != getattr(base, name)
        for name in changes
        if name not in _USER_FIELDS
    )
    return replace(policy, customized=customized)


@dataclass
class _Stored:
    level: SecurityLevel = SecurityLevel.STANDARD
    overrides: Dict[str, Any] = field(default_factory=dict)


class SecurityStore:
    """``security.json``: the chosen level plus the user's overrides.

    The file is written owner-only. The agent's file tools refuse it from the
    Enhanced level up, so the agent cannot lower its own security.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._stored = self._read()
        self._policy = resolve(self._stored.level, self._stored.overrides)
        self._listeners: List[Callable[[SecurityPolicy], None]] = []

    # ── reading ──

    @property
    def policy(self) -> SecurityPolicy:
        return self._policy

    def _read(self) -> _Stored:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _Stored()
        except (OSError, ValueError):
            # An unreadable file must not silently lower security below what
            # it held; Standard is today's behaviour, never weaker than it.
            return _Stored()
        try:
            level = SecurityLevel(raw.get("level", SecurityLevel.STANDARD.value))
        except ValueError:
            level = SecurityLevel.STANDARD
        overrides = {
            k: v for k, v in (raw.get("overrides") or {}).items() if k in _SETTABLE
        }
        try:
            resolve(level, overrides)
        except SecurityConfigError:
            overrides = {}
        return _Stored(level=level, overrides=overrides)

    # ── writing ──

    def set_level(self, level: SecurityLevel, *, keep_overrides: bool = False) -> SecurityPolicy:
        """Switch level. Overrides of preset-controlled settings are dropped
        unless asked to keep them; the user's own lists and Auto mode stay."""
        with self._lock:
            overrides = dict(self._stored.overrides)
            if not keep_overrides:
                overrides = {k: v for k, v in overrides.items() if k in _USER_FIELDS}
            return self._commit(_Stored(level=level, overrides=overrides))

    def update(self, changes: Dict[str, Any]) -> SecurityPolicy:
        """Apply setting changes on top of the current level."""
        unknown = set(changes) - _SETTABLE
        if unknown:
            raise SecurityConfigError(f"Unknown setting: {', '.join(sorted(unknown))}")
        with self._lock:
            overrides = dict(self._stored.overrides)
            base = preset(self._stored.level)
            for name, value in changes.items():
                coerced = _coerce(name, value)
                if coerced == getattr(base, name) and name not in _USER_FIELDS:
                    overrides.pop(name, None)  # back to the preset's value
                else:
                    overrides[name] = _serialize(coerced)
            return self._commit(_Stored(level=self._stored.level, overrides=overrides))

    def reset(self) -> SecurityPolicy:
        with self._lock:
            return self._commit(_Stored())

    def _commit(self, stored: _Stored) -> SecurityPolicy:
        policy = resolve(stored.level, stored.overrides)
        write_private_json(
            self.path,
            {
                "version": SCHEMA_VERSION,
                "level": stored.level.value,
                "overrides": stored.overrides,
            },
        )
        self._stored = stored
        self._policy = policy
        for listener in list(self._listeners):
            try:
                listener(policy)
            except Exception:  # a listener never blocks a settings change
                pass
        return policy

    def subscribe(self, listener: Callable[[SecurityPolicy], None]) -> None:
        self._listeners.append(listener)

    def reload(self) -> SecurityPolicy:
        with self._lock:
            self._stored = self._read()
            self._policy = resolve(self._stored.level, self._stored.overrides)
            return self._policy

    def describe(self) -> Dict[str, Any]:
        """The settings page's view: effective policy plus each level's preset."""
        policy = self._policy
        return {
            "policy": policy.to_dict(),
            "level": policy.level.value,
            "customized": policy.customized,
            "overrides": sorted(
                k for k in self._stored.overrides if k not in _USER_FIELDS
            ),
            "presets": {lvl.value: preset(lvl).to_dict() for lvl in SecurityLevel},
            "effects": [e.value for e in Effect],
            "high_risk_effects": sorted(e.value for e in HIGH_RISK_EFFECTS),
        }


def _serialize(value: Any) -> Any:
    if isinstance(value, frozenset):
        return sorted(e.value if isinstance(e, Enum) else e for e in value)
    if isinstance(value, tuple):
        return list(value)
    return value


_store: Optional[SecurityStore] = None
_store_lock = threading.Lock()


def default_path() -> Path:
    from app.config import APP_CONFIG_PATH

    return APP_CONFIG_PATH / "security.json"


def get_store() -> SecurityStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SecurityStore(default_path())
    return _store


def get_policy() -> SecurityPolicy:
    """The current policy. Cheap: safe to call on every action."""
    store = _store
    return store.policy if store is not None else get_store().policy


def set_store_for_tests(store: Optional[SecurityStore]) -> None:
    global _store
    _store = store
