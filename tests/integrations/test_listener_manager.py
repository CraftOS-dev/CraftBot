"""ListenerManager / FileCursorStore behavior — all fakes, no network.

Covers the §8 guarantees: exact-diff reconciliation, per-account event
tagging, per-identity cursors, crash-loop isolation, credential-change
restarts, and cursor persistence on stop.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple


from craftos_integrations.contracts import OAuthSpec
from craftos_integrations.core.listeners import (
    PAUSED_STATUS,
    FileCursorStore,
    ListenerManager,
)
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem


# ── fakes ────────────────────────────────────────────────────────────────


class FakeListener:
    def __init__(
        self,
        emit,
        cursor: Optional[Dict[str, Any]],
        *,
        events: Tuple[Dict[str, Any], ...] = (),
        crash: bool = False,
        cursor_out: Optional[Dict[str, Any]] = None,
        poll_interval: Optional[float] = None,
    ) -> None:
        self.emit = emit
        self.cursor_in = cursor
        self.events = events
        self.crash = crash
        self.cursor_out = cursor_out
        if poll_interval is not None:
            self.poll_interval = poll_interval
        self.start_count = 0
        self.stop_called = False
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self.start_count += 1
        if self.crash:
            raise RuntimeError("boom")
        for event in self.events:
            await self.emit(event)
        await self._stop.wait()

    async def stop(self) -> None:
        self.stop_called = True
        self._stop.set()

    def cursor(self) -> Optional[Dict[str, Any]]:
        return self.cursor_out


class FakeProvider:
    family = None

    def __init__(
        self,
        pid: str = "fakemail",
        *,
        has_listener: bool = True,
        crash_for: Tuple[str, ...] = (),
        poll_interval: Optional[float] = None,
    ) -> None:
        self.id = pid
        self.has_listener = has_listener
        self.crash_for = crash_for
        self.poll_interval = poll_interval
        self.built: List[Dict[str, Any]] = []  # every make_listener call

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        email = credential.get("email")
        return email.lower() if isinstance(email, str) else None

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec("https://auth.example/a", "https://auth.example/t")

    def build_client(self, credential, persist) -> Dict[str, Any]:
        return {
            "email": credential.get("email"),
            "token": credential.get("access_token"),
        }

    async def refresh(self, credential):
        return None

    def operations(self):
        return []

    def guidance(self) -> str:
        return ""

    def make_listener(self, client, cursor, emit):
        if not self.has_listener:
            return None
        identity = client.get("email")
        listener = FakeListener(
            emit,
            cursor,
            events=({"kind": "mail", "for": identity},),
            crash=identity in self.crash_for,
            cursor_out={"last_seen": f"msg-{identity}"},
            poll_interval=self.poll_interval,
        )
        self.built.append({"client": client, "cursor": cursor, "listener": listener})
        return listener


class FakeSink:
    def __init__(self) -> None:
        self.events: List[Tuple[str, str, Dict[str, Any]]] = []

    async def on_event(self, provider_id, identity, event) -> None:
        self.events.append((provider_id, identity, event))


# ── helpers ──────────────────────────────────────────────────────────────


def cred(identity: str, token: str = "tok") -> Dict[str, Any]:
    return {"email": identity, "access_token": f"{token}-{identity}"}


def build(tmp_path, provider, **manager_kwargs):
    system = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[provider]
    )
    sink = FakeSink()
    cursors = FileCursorStore(root=tmp_path)
    manager_kwargs.setdefault("max_failures", 3)
    manager_kwargs.setdefault("backoff_base", 0.005)
    manager_kwargs.setdefault("stagger_default", 0.0)
    manager = ListenerManager(system, sink, cursors, **manager_kwargs)
    return system, sink, cursors, manager


async def eventually(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return predicate()


def running_keys(manager) -> set:
    return set(manager._instances.keys())


# ── reconciliation ───────────────────────────────────────────────────────


def test_reconcile_starts_and_stops_exact_instances(tmp_path):
    provider = FakeProvider()
    system, sink, cursors, manager = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))
    system.store_credential("fakemail", "b@y.com", cred("b@y.com"))

    async def main():
        await manager.reconcile()
        assert running_keys(manager) == {
            ("fakemail", "a@x.com"),
            ("fakemail", "b@y.com"),
        }
        assert len(provider.built) == 2
        survivor = manager._instances[("fakemail", "a@x.com")].listener

        # Toggle one off → exactly that instance stops; the other is the
        # very same listener object, untouched.
        system.set_listening("fakemail", "b@y.com", False)
        await manager.reconcile()
        assert running_keys(manager) == {("fakemail", "a@x.com")}
        assert manager._instances[("fakemail", "a@x.com")].listener is survivor
        # Instances are built in sorted-identity order: [0]=a@x.com, [1]=b@y.com
        assert provider.built[1]["listener"].stop_called
        assert not survivor.stop_called

        # Remove the remaining account → nothing runs.
        system.remove_account("fakemail", "a@x.com")
        await manager.reconcile()
        assert running_keys(manager) == set()
        assert survivor.stop_called
        await manager.stop()

    asyncio.run(main())


def test_listen_false_accounts_never_start(tmp_path):
    provider = FakeProvider()
    system, sink, cursors, manager = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))
    system.store_credential("fakemail", "b@y.com", cred("b@y.com"))
    system.set_listening("fakemail", "b@y.com", False)

    async def main():
        await manager.reconcile()
        assert running_keys(manager) == {("fakemail", "a@x.com")}
        assert [b["client"]["email"] for b in provider.built] == ["a@x.com"]
        await manager.stop()

    asyncio.run(main())


def test_provider_without_listener_starts_nothing(tmp_path):
    provider = FakeProvider(has_listener=False)
    system, sink, cursors, manager = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))

    async def main():
        await manager.reconcile()
        assert running_keys(manager) == set()
        await manager.stop()

    asyncio.run(main())


# ── event tagging ────────────────────────────────────────────────────────


def test_events_tagged_with_provider_and_identity(tmp_path):
    provider = FakeProvider()
    system, sink, cursors, manager = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))
    system.store_credential("fakemail", "b@y.com", cred("b@y.com"))

    async def main():
        await manager.reconcile()
        assert await eventually(lambda: len(sink.events) >= 2)
        tagged = {(pid, ident) for pid, ident, _ in sink.events}
        assert tagged == {("fakemail", "a@x.com"), ("fakemail", "b@y.com")}
        for pid, ident, event in sink.events:
            assert event == {"kind": "mail", "for": ident}
        await manager.stop()

    asyncio.run(main())


# ── cursors ──────────────────────────────────────────────────────────────


def test_cursor_persisted_per_identity_and_handed_back(tmp_path):
    provider = FakeProvider()
    system, sink, cursors, manager = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))
    system.store_credential("fakemail", "b@y.com", cred("b@y.com"))

    async def main():
        await manager.reconcile()
        # First build gets no cursor (nothing persisted yet).
        assert all(b["cursor"] is None for b in provider.built)
        await manager.stop()

    asyncio.run(main())

    assert cursors.get("fakemail", "a@x.com") == {"last_seen": "msg-a@x.com"}
    assert cursors.get("fakemail", "b@y.com") == {"last_seen": "msg-b@y.com"}

    # A fresh manager hands each identity exactly its own cursor back.
    manager2 = ListenerManager(
        system,
        sink,
        cursors,
        max_failures=3,
        backoff_base=0.005,
        stagger_default=0.0,
    )

    async def again():
        await manager2.reconcile()
        by_identity = {b["client"]["email"]: b["cursor"] for b in provider.built[2:]}
        assert by_identity == {
            "a@x.com": {"last_seen": "msg-a@x.com"},
            "b@y.com": {"last_seen": "msg-b@y.com"},
        }
        await manager2.stop()

    asyncio.run(again())


def test_stop_persists_cursors(tmp_path):
    provider = FakeProvider()
    system, sink, cursors, manager = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))

    async def main():
        await manager.reconcile()
        assert await eventually(
            lambda: (
                manager._instances[("fakemail", "a@x.com")].state in ("running", "idle")
            )
        )
        await manager.stop()

    asyncio.run(main())
    assert cursors.get("fakemail", "a@x.com") == {"last_seen": "msg-a@x.com"}
    # Written to <credentials dir>/_cursors/<provider_id>.json
    assert (tmp_path / "_cursors" / "fakemail.json").exists()


def test_cursor_store_survives_corrupt_file(tmp_path):
    cursors = FileCursorStore(root=tmp_path)
    cursors.set("fakemail", "a@x.com", {"last_seen": "1"})
    (tmp_path / "_cursors" / "fakemail.json").write_text("{not json", "utf-8")
    assert cursors.get("fakemail", "a@x.com") is None  # harmless loss
    cursors.set("fakemail", "a@x.com", {"last_seen": "2"})
    assert cursors.get("fakemail", "a@x.com") == {"last_seen": "2"}


# ── failure isolation ────────────────────────────────────────────────────


def test_crash_loop_pauses_instance_and_isolates_others(tmp_path):
    provider = FakeProvider(crash_for=("b@y.com",))
    system, sink, cursors, manager = build(tmp_path, provider, max_failures=3)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))
    system.store_credential("fakemail", "b@y.com", cred("b@y.com"))

    async def main():
        await manager.reconcile()
        bad = manager._instances[("fakemail", "b@y.com")]
        assert await eventually(lambda: bad.state == "paused")
        assert bad.failures == 3
        status = manager.status()
        assert status["fakemail:b@y.com"]["state"] == "paused"
        assert status["fakemail:b@y.com"]["detail"] == PAUSED_STATUS
        # The healthy sibling keeps running and its events keep flowing.
        assert status["fakemail:a@x.com"]["state"] in ("running", "idle")
        assert ("fakemail", "a@x.com", {"kind": "mail", "for": "a@x.com"}) in [
            (p, i, e) for p, i, e in sink.events
        ]

        # A plain reconcile (no account/credential change) leaves it paused
        # — no new listener is built for the paused identity.
        built_before = len(provider.built)
        await manager.reconcile()
        assert manager._instances[("fakemail", "b@y.com")].state == "paused"
        assert len(provider.built) == built_before

        # Re-auth (credential change) is what revives it.
        system.store_credential("fakemail", "b@y.com", cred("b@y.com", "new"))
        await manager.reconcile()
        revived = manager._instances[("fakemail", "b@y.com")]
        assert revived is not bad and revived.failures == 0
        await manager.stop()

    asyncio.run(main())


def test_credential_change_restarts_instance(tmp_path):
    provider = FakeProvider()
    system, sink, cursors, manager = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com", "old"))

    async def main():
        await manager.reconcile()
        original = manager._instances[("fakemail", "a@x.com")].listener
        assert provider.built[0]["client"]["token"] == "old-a@x.com"

        # No change → no restart.
        await manager.reconcile()
        assert manager._instances[("fakemail", "a@x.com")].listener is original

        # Re-auth with a new token → exactly this instance restarts,
        # rebuilt against the new credential.
        system.store_credential("fakemail", "a@x.com", cred("a@x.com", "new"))
        await manager.reconcile()
        replacement = manager._instances[("fakemail", "a@x.com")].listener
        assert replacement is not original
        assert original.stop_called
        assert provider.built[-1]["client"]["token"] == "new-a@x.com"
        await manager.stop()

    asyncio.run(main())


# ── stagger ──────────────────────────────────────────────────────────────


def test_same_provider_pollers_are_staggered(tmp_path):
    provider = FakeProvider(poll_interval=60.0)
    system, sink, cursors, manager = build(tmp_path, provider)
    for identity in ("a@x.com", "b@y.com", "c@z.com"):
        system.store_credential("fakemail", identity, cred(identity))

    async def main():
        await manager.reconcile()
        delays = sorted(info["delay"] for info in manager.status().values())
        assert delays == [0.0, 20.0, 40.0]  # k * (60 / 3)
        await manager.stop()

    asyncio.run(main())


# ── system integration ───────────────────────────────────────────────────


def test_system_mutations_trigger_reconcile(tmp_path):
    provider = FakeProvider()
    system, sink, cursors, manager = build(tmp_path, provider)
    system.listeners = manager
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))

    async def main():
        await manager.reconcile()
        assert running_keys(manager) == {("fakemail", "a@x.com")}

        # set_listening schedules a reconcile by itself — no manual call.
        system.set_listening("fakemail", "a@x.com", False)
        assert await eventually(lambda: running_keys(manager) == set())

        system.set_listening("fakemail", "a@x.com", True)
        assert await eventually(
            lambda: running_keys(manager) == {("fakemail", "a@x.com")}
        )

        # apply_account_changes schedules one too.
        system.apply_account_changes("fakemail", {"listen": {"a@x.com": False}})
        assert await eventually(lambda: running_keys(manager) == set())
        await manager.stop()

    asyncio.run(main())


def test_reconcile_listeners_without_manager_is_noop(tmp_path):
    provider = FakeProvider()
    system, _, _, _ = build(tmp_path, provider)
    system.store_credential("fakemail", "a@x.com", cred("a@x.com"))
    # No manager attached, no running loop — must not raise.
    system.reconcile_listeners()
    system.set_listening("fakemail", "a@x.com", False)
