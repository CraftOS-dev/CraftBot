"""Installed worker. Only the SCM host's private stdin carries kernel envelopes.

The ordinary browser/bridge is not an owner channel. Public consumer messages
cannot provide a caller context, isolated flag, PID, grant, or secret fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import time
from threading import Timer, Thread, Event, RLock
from .execution import OperationJob, OutputBudget
from uuid import UUID, uuid4

from .broker import CredentialBroker, GrantMode, UseCapability, canonical_request
from .contracts import (
    CredentialKind,
    CredentialReference,
    HelperOperation,
    IsolationUnavailable,
)
from .directory import IdentityDirectory
from .helpers import HelperRegistry, HttpsJsonOperation, JsonResult, require_match
from .catalog import specification
from .browser_helper import HttpsFormLogin
from .identity import (
    AppDeployment,
    CallerBinding,
    CallerIdentity,
    CallerKind,
    ExecutionContext,
    VaultOwner,
    VaultProfile,
    VaultScope,
)
from .owner_transport import WindowsOwnerConsent
from .use_errors import CredentialUseError, UseCode, use_boundary
from .vault import ProfileVault, VaultState
from .windows_host import IsolatedProcess, Peer, api, check_install, private_acl


@dataclass
class Launch:
    process: IsolatedProcess
    context: ExecutionContext
    controller: Peer
    deadline: float
    result: object = None
    timer: object = None
    credential_output: JsonResult | None = None
    payload_text: str = ""
    payload_ready: bool = False
    job: OperationJob | None = None
    snapshot_revision: str | None = None
    closed: Event = field(default_factory=Event)
    guard: object = field(default_factory=RLock)

    def close(self):
        with self.guard:
            if self.closed.is_set():
                return False
            self.closed.set()
            if self.job is not None:
                self.job.close()
            if self.timer is not None:
                self.timer.cancel()
            try:
                self.process.close()
            finally:
                self.controller.close()
            return True


@dataclass(frozen=True)
class OwnerView:
    pid: int
    created: int
    scope: VaultScope
    epoch: UUID
    expires: float
    items: tuple


def metadata_page(items, offset):
    if type(offset) is not int or not 0 <= offset <= len(items):
        raise CredentialUseError(UseCode.DENIED)
    page, size = [], 0
    for item in items[offset : offset + 50]:
        length = len(json.dumps(item, ensure_ascii=True).encode("utf-8"))
        if size + length > 24000:
            break
        page.append(item)
        size += length
    if offset < len(items) and not page:
        raise CredentialUseError(UseCode.LIMIT)
    next_offset = offset + len(page)
    return {
        "items": page,
        "next_offset": next_offset if next_offset < len(items) else None,
        "total": len(items),
    }


def source_files(value, entry):
    """A bounded immutable code snapshot, not host-supplied filesystem paths."""
    if (
        type(value) is not dict
        or not 1 <= len(value) <= 32
        or not isinstance(entry, str)
    ):
        raise CredentialUseError(UseCode.DENIED)
    total = 0
    names = set()
    digest = hashlib.sha256()
    digest.update(b"CraftBot snapshot v1\0" + entry.encode("utf-8") + b"\0")
    for name, content in sorted(value.items()):
        if not isinstance(name, str) or not isinstance(content, str):
            raise CredentialUseError(UseCode.DENIED)
        path = PurePosixPath(name)
        if (
            not name.isascii()
            or len(name) > 160
            or path.is_absolute()
            or not path.parts
            or path.as_posix() != name
            or any(part in (".", "..") for part in path.parts)
            or any(
                char
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-"
                for char in name
            )
            or any(
                part.split(".")[0].upper()
                in {
                    "CON",
                    "PRN",
                    "AUX",
                    "NUL",
                    *[f"COM{i}" for i in range(10)],
                    *[f"LPT{i}" for i in range(10)],
                }
                or part.endswith((".", " "))
                for part in path.parts
            )
            or name.casefold() in names
            or path.parts[0].casefold() in ("credential_client.py", "_host_entry.py")
        ):
            raise CredentialUseError(UseCode.DENIED)
        names.add(name.casefold())
        encoded = content.encode("utf-8")
        total += len(encoded)
        if total > 48000:
            raise CredentialUseError(UseCode.LIMIT)
        name_bytes = name.encode("ascii")
        digest.update(
            len(name_bytes).to_bytes(4, "little")
            + name_bytes
            + len(encoded).to_bytes(8, "little")
            + encoded
        )
    if entry not in value or not entry.endswith(".py"):
        raise CredentialUseError(UseCode.DENIED)
    # Prefix collisions (a.py plus a.py/b.py) are rejected before writing.
    for name in names:
        if any(
            parent.as_posix().casefold() in names
            for parent in PurePosixPath(name).parents
            if parent.as_posix() != "."
        ):
            raise CredentialUseError(UseCode.DENIED)
    return "sha256:" + digest.hexdigest()


class ProtectedHost:
    def __init__(self, root: Path, state: Path, configuration: dict):
        self.root, self.state = root, state
        self.owner = VaultOwner(
            UUID(configuration["owner_id"]), configuration["owner_sid"]
        )
        self.directory = IdentityDirectory()
        self.directory.register_owner(self.owner)
        self.consent = WindowsOwnerConsent(
            root / "CredentialHost.exe", self.owner.os_identity
        )
        self.vaults = {}
        self.views = {}
        catalog = state / "profiles.json"
        profiles = (
            json.loads(catalog.read_text(encoding="utf-8"))
            if catalog.exists()
            else configuration["profiles"]
        )
        if type(profiles) is not list or not 1 <= len(profiles) <= 64:
            raise IsolationUnavailable()
        for item in profiles:
            if len(item["label"]) > 64:
                raise IsolationUnavailable()
            profile = VaultProfile(
                VaultScope(self.owner.owner_id, UUID(item["id"])), item["label"]
            )
            self.directory.register_profile(profile)
            if profile.scope.profile_id in self.vaults:
                raise IsolationUnavailable()
            self.vaults[profile.scope.profile_id] = ProfileVault(
                state / "vaults", self.owner, profile, verifier=self.consent
            )
        specifications = tuple(
            specification(item) for item in configuration.get("helpers", [])
        )
        self.registry = HelperRegistry(specifications)
        self.leases: dict[UUID, Launch] = {}
        self.output_budget = OutputBudget()
        for vault in self.vaults.values():
            vault._on_lock = lambda scope=vault.profile.scope: self._cancel_profile(
                scope
            )
        self.broker = CredentialBroker(
            self.directory,
            tuple(self.vaults.values()),
            self.registry,
            isolation=self,
            owner_verifier=self.consent,
        )

    def require_isolated(self, context):
        launch = next(
            (item for item in self.leases.values() if item.context == context), None
        )
        if launch is None or time.monotonic() >= launch.deadline:
            raise IsolationUnavailable()
        peer = Peer(launch.process.pid)
        try:
            if peer.sid != self.owner.os_identity or not launch.process.matches(peer):
                raise IsolationUnavailable()
        finally:
            peer.close()

    def _cancel_profile(self, scope):
        # Called under a vault lock, so this must not acquire the broker or
        # directory lock. The HTTPS/Gateway watcher aborts active sockets.
        for launch in tuple(self.leases.values()):
            if launch.context.binding.scope == scope and launch.job is not None:
                launch.job.cancelled.set()

    def _owner(self, peer):
        if (
            peer.sid != self.owner.os_identity
            or peer.container
            or peer.elevated
            or not peer.alive()
        ):
            raise CredentialUseError(UseCode.DENIED)
        self.consent.session = peer.session

    def _consumer(self, peer):
        if peer.sid != self.owner.os_identity:
            raise CredentialUseError(UseCode.DENIED)
        for launch in self.leases.values():
            if launch.process.matches(peer):
                self.require_isolated(launch.context)
                self.consent.session = peer.session
                return launch
        raise IsolationUnavailable()

    @staticmethod
    def _shape(payload, fields):
        if type(payload) is not dict or set(payload) != {"op", *fields}:
            raise CredentialUseError(UseCode.DENIED)

    def _profile(self, value):
        vault = self.vaults.get(UUID(value))
        if vault is None:
            raise CredentialUseError(UseCode.DENIED)
        return vault

    def _prune(self):
        self.views = {
            key: value
            for key, value in self.views.items()
            if time.monotonic() < value.expires
        }
        for key, launch in tuple(self.leases.items()):
            if time.monotonic() >= launch.deadline or not launch.controller.alive():
                self._expire(key, launch)

    def _expire(self, key, launch):
        # Independent of control-pipe traffic and idempotent against stop/lock.
        first = launch.close()
        if self.leases.get(key) is launch:
            self.leases.pop(key, None)
        if not first:
            return
        Thread(
            target=self.directory.revoke,
            args=(launch.context.binding.binding_id,),
            daemon=True,
        ).start()

    def _watch(self, key, launch):
        while not launch.closed.wait(1):
            try:
                expired = time.monotonic() >= launch.deadline
                disconnected = not launch.controller.alive()
                abandoned = (
                    launch.job is not None
                    and not launch.job.done.is_set()
                    and api()[6].WaitForSingleObject(launch.process.handle, 0) == 0
                )
                if expired or disconnected or abandoned:
                    self._expire(key, launch)
                    return
            except Exception:
                self._expire(key, launch)
                return

    @use_boundary
    def dispatch(self, peer, payload):
        self._prune()
        if type(payload) is not dict or not isinstance(payload.get("op"), str):
            raise CredentialUseError(UseCode.DENIED)
        operation = payload["op"]
        if operation in {
            "profiles",
            "action_profile",
            "action_profile_set",
            "initialize",
            "entry",
            "launch",
            "result",
            "program_result",
            "response",
            "stage_payload",
            "reset_operation",
            "stop",
            "lock",
            "unlock",
            "items",
            "items_page",
            "edit",
            "delete",
            "activity",
            "revoke",
            "profile_add",
            "migrate_settings",
            "migrate_browser",
            "migrate_integration",
            "migrate_environment",
            "catalog",
            "view",
        }:
            self._owner(peer)
            if operation == "lock":
                self._shape(payload, ("profile_id",))
                self._profile(payload["profile_id"])
                # The native supervisor clears all host keys/jobs immediately,
                # including a resolver blocked before it can observe cancellation.
                return {"reset_host": True}
            if operation not in (
                "profiles",
                "action_profile",
                "result",
                "program_result",
                "response",
                "stop",
                "stage_payload",
                "reset_operation",
                "catalog",
            ) and any(
                item.job is not None
                and not item.job.done.is_set()
                and not item.job.dispatched.is_set()
                for item in self.leases.values()
            ):
                raise CredentialUseError(UseCode.BUSY)
            return self._manage(peer, operation, payload)
        launch = self._consumer(peer)
        context = launch.context
        vault = self.vaults[context.binding.scope.profile_id]
        if operation in (
            "request_use",
            "authorize_grant",
            "request_entry",
            "status",
            "find",
        ) and any(
            item.job is not None
            and not item.job.done.is_set()
            and not item.job.dispatched.is_set()
            for item in self.leases.values()
        ):
            raise CredentialUseError(UseCode.BUSY)
        if operation == "operation_status":
            self._shape(payload, ())
            if launch.job is None:
                return {"done": True, "active": False, "error": None}
            return {
                "done": launch.job.done.is_set(),
                "active": True,
                "error": launch.job.error,
                "outcome": launch.job.result.value
                if launch.job.done.is_set()
                and launch.job.result is not None
                and type(launch.job.result) is not JsonResult
                else "completed",
            }
        if operation == "authorize_grant":
            self._shape(payload, ("grant_id",))
            return {
                "capability": self.broker.authorize(
                    context, UUID(payload["grant_id"])
                ).handle
            }
        if operation == "start_use_staged":
            self._shape(payload, ("capability",))
            if any(
                item.job is not None
                and not item.job.done.is_set()
                and not item.job.dispatched.is_set()
                for item in self.leases.values()
            ):
                raise CredentialUseError(UseCode.BUSY)
            if (
                sum(
                    len(item.job.body) if item.job is not None else 0
                    for item in self.leases.values()
                )
                > 96_000_000
            ):
                raise CredentialUseError(UseCode.LIMIT)
            if (
                not launch.payload_ready
                or launch.job is not None
                and not launch.job.done.is_set()
            ):
                raise CredentialUseError(UseCode.DENIED)
            body = {"body": json.loads(launch.payload_text)}
            launch.payload_text, launch.payload_ready = "", False
            capability = UseCapability(payload["capability"])
            with launch.guard:
                if launch.closed.is_set():
                    raise CredentialUseError(UseCode.DENIED)
                if launch.job is not None:
                    launch.job.close()
                launch.job = OperationJob(
                    lambda job: self.broker.execute(
                        context, capability, body, execution=job
                    ),
                    budget=self.output_budget,
                    grant_id=self.broker.capability_grant(context, capability),
                )
                launch.job.thread.start()
            return {"started": True}
        if operation == "status":
            self._shape(payload, ())
            return {"state": self.broker.status(context).value}
        if operation == "upload_payload_part":
            self._shape(payload, ("offset", "data", "done"))
            return self._stage(launch, payload)
        if operation == "payload_info":
            self._shape(payload, ())
            return {
                "ready": launch.payload_ready,
                "sha256": hashlib.sha256(
                    launch.payload_text.encode("ascii")
                ).hexdigest()
                if launch.payload_ready
                else None,
            }
        if operation == "discard_payload":
            self._shape(payload, ())
            launch.payload_text, launch.payload_ready = "", False
            return {"discarded": True}
        if operation == "operations":
            self._shape(payload, ("offset",) if "offset" in payload else ())
            offset = payload.get("offset", 0)
            entries = tuple(self.registry._entries.values())
            if type(offset) is not int or not 0 <= offset <= len(entries):
                raise CredentialUseError(UseCode.DENIED)
            return {
                "operations": [
                    {
                        "helper": spec.operation.helper_id,
                        "operation": spec.operation.operation,
                    }
                    for spec in entries[offset : offset + 32]
                ],
                "more": offset + 32 < len(entries),
            }
        if operation == "find":
            self._shape(payload, ("offset",) if "offset" in payload else ())
            offers = self.broker.find(context)
            offset = payload.get("offset", 0)
            if type(offset) is not int or not 0 <= offset <= len(offers):
                raise CredentialUseError(UseCode.DENIED)
            return {
                "offers": [
                    {
                        "grant_id": str(offer.grant_id),
                        "credential_id": str(offer.summary.reference.credential_id),
                        "version": offer.summary.reference.version,
                        "service": offer.summary.service,
                        "account": offer.summary.account_label,
                        "helper": offer.operation.helper_id,
                        "operation": offer.operation.operation,
                    }
                    for offer in offers[offset : offset + 8]
                ],
                "more": offset + 8 < len(offers),
            }
        if operation == "request_entry":
            self._shape(payload, ("helper", "operation", "account"))
            from .identity import _label
            from .references import SourceReference

            _label(payload["account"])
            spec = self.registry.require(
                HelperOperation(payload["helper"], payload["operation"])
            )
            self.consent.message = f"Unlock {vault.profile.label} for a secure-entry request from {context.binding.caller.subject_id}?\nHelper: {spec.operation.helper_id}/{spec.operation.operation}\nDestination: {spec.endpoint}"
            if vault.status().state is not VaultState.READY:
                vault.unlock()
            names = {
                CredentialKind.LOGIN: ("username", "password"),
                CredentialKind.API_KEY: ("api_key",),
            }.get(spec.kind, (spec.secret_field,))
            if type(spec) is HttpsJsonOperation and spec.protocol == "aws_bedrock":
                names = ("access_key_id", "secret_access_key")
            if type(spec) is HttpsJsonOperation and spec.protocol == "basic":
                names = ("username", "api_token")
            if type(spec) is HttpsJsonOperation and spec.protocol == "twitter_oauth1":
                names = ("api_key", "api_secret")
            if (
                type(spec) is HttpsJsonOperation
                and spec.protocol == "telegram_mtproto"
                and spec.operation.operation == "complete_password"
            ):
                names = ("api_hash", "password")
            self.consent.message = (
                f"Save a new {spec.kind.value} in {vault.profile.label}?\nCaller: {context.binding.caller.subject_id}\n"
                f"Account label: {payload['account']}\nHelper: {spec.operation.helper_id}/{spec.operation.operation}\n"
                f"Permitted origin: {spec.origin}\nSaving does not approve credential use. No values return to the requesting app."
            )
            fields = self.consent.entry(names)
            item = vault.create(
                spec.kind,
                spec.operation.helper_id,
                payload["account"],
                fields,
                allowed_origins=(spec.origin,),
            )
            ref = item.summary.reference
            return {
                "credential_id": str(ref.credential_id),
                "version": ref.version,
                "reference": SourceReference(
                    ref.scope.profile_id, ref.credential_id, ref.version
                ).encode(),
            }
        if operation == "request_use":
            if not launch.payload_ready:
                raise CredentialUseError(UseCode.DENIED)
            approved_body, _ = canonical_request(
                {"body": json.loads(launch.payload_text)}
            )
            repeat_fields = ("repeat",) if "repeat" in payload else ()
            self._shape(
                payload,
                ("helper", "operation", "credential_id", "credential_version")
                + repeat_fields
                if "credential_version" in payload
                else ("helper", "operation", "credential_id") + repeat_fields,
            )
            specification = self.registry.require(
                HelperOperation(payload["helper"], payload["operation"])
            )
            repeat = payload.get("repeat", False)
            if (
                type(repeat) is not bool
                or repeat
                and (
                    type(specification) is not HttpsJsonOperation
                    or specification.method != "GET"
                )
            ):
                raise CredentialUseError(UseCode.DENIED)
            self.consent.message = f"Unlock {vault.profile.label} for a credential request?\nCaller: {context.binding.caller.subject_id}\nDestination: {specification.endpoint}"
            if vault.status().state is not VaultState.READY:
                vault.unlock()
            candidates = []
            for item in vault.list_items():
                try:
                    require_match(specification, item)
                except CredentialUseError:
                    continue
                if payload[
                    "credential_id"
                ] is None or item.summary.reference.credential_id == UUID(
                    payload["credential_id"]
                ):
                    candidates.append(item)
            if len(candidates) != 1:
                raise CredentialUseError(
                    UseCode.DENIED
                )  # Explicit account selection needed.
            item = candidates[0]
            if "credential_version" in payload and (
                type(payload["credential_version"]) is not int
                or payload["credential_version"] != item.summary.reference.version
            ):
                raise CredentialUseError(UseCode.CHANGED)
            caller = context.binding.caller
            self.consent.message = (
                "Authenticate to review a credential request on the private desktop.\n"
                "Review caller claims, profile, account, resolved destination and parameters before approving.\n"
                + (
                    "Allow repeated GET requests for this exact operation and isolated worker until its 15-minute lease expires, lock or revocation. Resource/query parameters may change within the displayed installed route."
                    if repeat
                    else "Expires: 30 seconds; one attempt."
                )
            )
            # Full request review travels only on the SYSTEM-only UI pipe, not
            # a command line, browser channel, log, or caller-supplied summary.
            from .request_review import review_request

            self.consent.review_request = {
                "Caller label (unverified)": json.dumps(caller.subject_id),
                "Caller kind (unverified)": caller.kind.value,
                "Claimed deployment (unverified)": caller.deployment.value
                if caller.deployment
                else "agent",
                "Code SHA256": getattr(launch, "snapshot_revision", None)
                or caller.app_revision
                or "isolated agent snapshot",
                "Profile": vault.profile.label,
                "Account": item.summary.account_label,
                "Credential": f"{item.summary.reference.credential_id} v{item.summary.reference.version}",
                "Operation": f"{specification.operation.helper_id}/{specification.operation.operation}",
                **review_request(specification, approved_body, repeat=repeat),
            }
            try:
                grant = self.broker.approve(
                    context,
                    item.summary.reference,
                    specification.operation,
                    mode=GrantMode.BINDING if repeat else GrantMode.ONCE,
                    lifetime=max(0.01, min(900, launch.deadline - time.monotonic()))
                    if repeat
                    else 30,
                    payload=approved_body,
                )
            finally:
                self.consent.review_request = None
            return {
                "capability": self.broker.authorize(context, grant.grant_id).handle,
                "grant_id": str(grant.grant_id),
            }
        if operation == "cancel":
            self._shape(payload, ("capability",))
            self.broker.cancel(context, UseCapability(payload["capability"]))
            return {"cancelled": True}
        if operation in ("use", "use_staged"):
            # All network work runs in a cancellable job. A consumer cannot
            # select a synchronous route that monopolizes the control pipe.
            raise CredentialUseError(UseCode.DENIED)
        if operation == "complete":
            self._shape(payload, ("result",))
            if len(json.dumps(payload["result"])) > 16000:
                raise CredentialUseError(UseCode.LIMIT)
            launch.result = {"result": payload["result"]}
            return {"completed": True}
        if operation == "read_response":
            self._shape(payload, ("offset",))
            if launch.job is not None:
                return launch.job.snapshot(payload["offset"])
            output, offset = launch.credential_output, payload["offset"]
            if (
                output is None
                or type(offset) is not int
                or not 0 <= offset <= len(output.body)
            ):
                raise CredentialUseError(UseCode.DENIED)
            return {
                "status": output.status,
                "content_type": output.content_type,
                "length": len(output.body),
                "chunk": output.body[offset : offset + 4000],
            }
        raise CredentialUseError(UseCode.DENIED)

    def _stage(self, launch, payload):
        if launch.closed.is_set():
            raise CredentialUseError(UseCode.DENIED)
        data, offset, done = payload["data"], payload["offset"], payload["done"]
        if (
            launch.payload_ready
            or type(offset) is not int
            or offset != len(launch.payload_text)
            or not isinstance(data, str)
            or not data.isascii()
            or len(data) > 8000
            or type(done) is not bool
            or len(launch.payload_text) + len(data) > 32_000_000
            or sum(len(item.payload_text) for item in self.leases.values()) + len(data)
            > 64_000_000
        ):
            raise CredentialUseError(UseCode.DENIED)
        launch.payload_text += data
        if done:
            value = json.loads(launch.payload_text)
            if value is not None and type(value) is not dict:
                raise CredentialUseError(UseCode.DENIED)
            launch.payload_ready = True
        return {"uploaded": len(launch.payload_text), "ready": launch.payload_ready}

    def _manage(self, peer, operation, payload):
        if operation in ("action_profile", "action_profile_set"):
            self._shape(
                payload, ("profile_id",) if operation == "action_profile_set" else ()
            )
            path = self.state / "action-profile.json"
            if operation == "action_profile_set":
                profile_id = payload["profile_id"]
                vault = self._profile(profile_id) if profile_id is not None else None
                self.consent.message = (
                    f"Use {vault.profile.label} for credential-isolated agent actions?\nEach launch and credential operation still needs owner approval."
                    if vault
                    else "Disable credential-isolated agent actions?"
                )
                self.consent.verify(self.owner)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "profile_id": str(vault.profile.scope.profile_id)
                            if vault
                            else None
                        }
                    ),
                    encoding="utf-8",
                )
                private_acl(temporary)
                temporary.replace(path)
            value = (
                json.loads(path.read_text(encoding="utf-8"))["profile_id"]
                if path.exists()
                else None
            )
            if value is not None:
                self._profile(value)
            return {"profile_id": value}
        if operation in ("migrate_integration", "migrate_environment"):
            self._shape(
                payload,
                ("profile_id", "path", "provider", "source_accounts")
                if operation == "migrate_integration"
                else ("profile_id", "path"),
            )
            from .migration import (
                migrate_integration_document,
                migrate_environment_document,
                SOURCE_FIELDS,
            )
            from .migration_source import OwnerSettingsSource
            from .secrets import Secret

            path = payload["path"]
            if (
                not isinstance(path, str)
                or len(path) > 400
                or any(ord(c) < 32 for c in path)
            ):
                raise CredentialUseError(UseCode.DENIED)
            if operation == "migrate_integration":
                provider, accounts = payload["provider"], payload["source_accounts"]
                if (
                    provider not in SOURCE_FIELDS
                    or type(accounts) is not list
                    or len(accounts) > 32
                    or any(not isinstance(a, str) or len(a) > 256 for a in accounts)
                ):
                    raise CredentialUseError(UseCode.DENIED)
                filename = provider + ".accounts.json"
            else:
                filename = Path(path).name
                if filename not in (".env", ".env.local"):
                    raise CredentialUseError(UseCode.DENIED)
            vault = self._profile(payload["profile_id"])
            self.consent.message = f"Offline source migration into {vault.profile.label}?\nFile: {path}\nClose all CraftBot instances and writers first. Saved manual sources become verified vault references; generated tokens/sessions stay with their current owners. Restart CraftBot afterwards."
            if operation == "migrate_integration":
                self.consent.message += (
                    "\nExplicit manual-source accounts: " + ", ".join(accounts)
                )
            self.consent.verify(self.owner)
            if vault.status().state is not VaultState.READY:
                vault.unlock()
            source = OwnerSettingsSource(
                path, self.owner.os_identity, peer.session, filename=filename
            )
            try:
                source_id = hashlib.sha256(
                    str(source.path).casefold().encode()
                ).hexdigest()
                catalog = [
                    {"helper": spec.operation.helper_id, "endpoint": spec.endpoint}
                    for spec in self.registry._entries.values()
                ]
                if operation == "migrate_integration":
                    result = migrate_integration_document(
                        vault,
                        source_id,
                        provider,
                        source.read(),
                        source.commit,
                        source_accounts=accounts,
                        helper_catalog=catalog,
                    )
                else:
                    document = Secret(source.read_bytes().reveal().decode("utf-8"))
                    result = migrate_environment_document(
                        vault,
                        source_id,
                        document,
                        source.commit_text,
                        helper_catalog=catalog,
                    )
                return {
                    "imported": result.imported,
                    "retained_references": result.retained_references,
                    "review_required": result.review_required,
                    "retained_derived": result.retained_derived,
                    "restart_required": True,
                }
            finally:
                source.close()
        if operation == "items_page":
            self._shape(payload, ("profile_id", "view_id", "offset"))
            vault = self._profile(payload["profile_id"])
            view = self.views.get(UUID(payload["view_id"]))
            if (
                view is None
                or view.pid != peer.pid
                or view.created != peer.created
                or view.scope != vault.profile.scope
                or view.epoch != vault.status().unlock_epoch
                or time.monotonic() >= view.expires
            ):
                raise CredentialUseError(UseCode.DENIED)
            return {
                **metadata_page(view.items, payload["offset"]),
                "view_id": payload["view_id"],
            }
        if operation == "migrate_browser":
            self._shape(payload, ("profile_id", "path"))
            vault = self._profile(payload["profile_id"])
            if (
                not isinstance(payload["path"], str)
                or len(payload["path"]) > 400
                or any(ord(c) < 32 for c in payload["path"])
            ):
                raise CredentialUseError(UseCode.DENIED)
            self.consent.message = (
                f"Offline saved-login migration into {vault.profile.label}?\nSource: {payload['path']}\n"
                "Close all CraftBot instances first. Current logins will enter the protected vault. Encrypted legacy history and its separately encrypted recovery key will be retained by the host; verified legacy source files will be removed. Browser profiles, cookies and sessions stay in place. Restart CraftBot afterwards."
            )
            self.consent.verify(self.owner)
            if vault.status().state is not VaultState.READY:
                vault.unlock()
            from .browser_migration import migrate_browser_files

            return migrate_browser_files(
                vault, payload["path"], self.state, self.owner.os_identity, peer.session
            )
        if operation == "catalog":
            self._shape(payload, ("offset",))
            offset = payload["offset"]
            entries = tuple(self.registry._entries.values())
            if type(offset) is not int or not 0 <= offset <= len(entries):
                raise CredentialUseError(UseCode.DENIED)
            rows = [
                {
                    "helper": spec.operation.helper_id,
                    "operation": spec.operation.operation,
                    "endpoint": spec.endpoint,
                    **(
                        {
                            "path_fields": list(spec.path_fields),
                            "query_fields": list(spec.query_fields),
                            "envelope": spec.envelope,
                            "request_format": spec.request_format,
                            "response_format": spec.response_format,
                            "header_fields": list(spec.header_fields),
                            "protocol": spec.protocol,
                        }
                        if type(spec) is HttpsJsonOperation
                        else {}
                    ),
                    "method": "POST"
                    if type(spec) is HttpsFormLogin
                    else spec.method
                    if type(spec) is HttpsJsonOperation
                    else "GET",
                    "type": "form"
                    if type(spec) is HttpsFormLogin
                    else "json"
                    if type(spec) is HttpsJsonOperation
                    else "check",
                }
                for spec in entries[offset : offset + 8]
            ]
            page = metadata_page(rows, 0)["items"]
            next_offset = offset + len(page)
            return {
                "helpers": page,
                "more": next_offset < len(entries),
                "next_offset": next_offset,
            }
        if operation == "migrate_settings":
            self._shape(payload, ("profile_id", "path"))
            vault = self._profile(payload["profile_id"])
            if not isinstance(payload["path"], str) or len(payload["path"]) > 400:
                raise CredentialUseError(UseCode.DENIED)
            self.consent.message = f"Offline model-key migration into {vault.profile.label}?\nSource: {payload['path']}\nClose all CraftBot instances and other Settings writers first. Source API keys become references after encrypted destination verification. Tokens and sessions retain their owners. Restart CraftBot afterwards."
            self.consent.verify(self.owner)
            if vault.status().state is not VaultState.READY:
                vault.unlock()
            from .migration import migrate_model_document
            from .migration_source import OwnerSettingsSource

            source = OwnerSettingsSource(
                payload["path"], self.owner.os_identity, peer.session
            )
            try:
                document = source.read()
                source_id = hashlib.sha256(
                    str(source.path).casefold().encode("utf-8")
                ).hexdigest()
                result = migrate_model_document(
                    vault,
                    source_id,
                    document,
                    source.commit,
                    helper_catalog=[
                        {
                            "helper": s.operation.helper_id,
                            "endpoint": s.endpoint,
                            "protocol": s.protocol,
                        }
                        for s in self.registry._entries.values()
                        if type(s) is HttpsJsonOperation
                        and (
                            s.kind is CredentialKind.API_KEY
                            or s.protocol in ("aws_bedrock", "telegram_mtproto")
                        )
                    ],
                )
                return {
                    "imported": result.imported,
                    "retained_references": result.retained_references,
                    "restart_required": True,
                }
            finally:
                source.close()
        if operation == "profiles":
            self._shape(payload, ())
            return [
                {
                    "id": str(key),
                    "label": vault.profile.label,
                    "state": "busy"
                    if any(
                        item.context.binding.scope == vault.profile.scope
                        and item.job is not None
                        and not item.job.done.is_set()
                        for item in self.leases.values()
                    )
                    else vault.status().state.value,
                }
                for key, vault in self.vaults.items()
            ]
        if operation == "profile_add":
            self._shape(payload, ("label",))
            from .identity import _label

            _label(payload["label"])
            label = payload["label"]
            if len(self.vaults) >= 64 or len(label) > 64:
                raise CredentialUseError(UseCode.LIMIT)
            self.consent.message = f"Create credential profile {label}?"
            self.consent.verify(self.owner)
            profile = VaultProfile(VaultScope(self.owner.owner_id, uuid4()), label)
            vault = ProfileVault(
                self.state / "vaults", self.owner, profile, verifier=self.consent
            )
            vault._on_lock = lambda: self._cancel_profile(profile.scope)
            # Persist a SYSTEM-owned catalog before exposing the new profile.
            catalog = self.state / "profiles.new"
            catalog.write_text(
                json.dumps(
                    [
                        {
                            "id": str(v.profile.scope.profile_id),
                            "label": v.profile.label,
                        }
                        for v in (*self.vaults.values(), vault)
                    ]
                ),
                encoding="utf-8",
            )
            private_acl(catalog)
            catalog.replace(self.state / "profiles.json")
            self.directory.register_profile(profile)
            self.vaults[profile.scope.profile_id] = vault
            self.broker.add_profile(vault)
            return {"id": str(profile.scope.profile_id)}
        if operation in (
            "items",
            "unlock",
            "edit",
            "delete",
            "view",
            "activity",
            "revoke",
        ):
            fields = {
                "items": ("profile_id",),
                "unlock": ("profile_id",),
                "activity": ("profile_id",),
                "revoke": ("profile_id", "grant_id"),
                "delete": ("profile_id", "credential_id", "version"),
                "view": ("profile_id", "credential_id", "version"),
                "edit": (
                    "profile_id",
                    "credential_id",
                    "version",
                    "service",
                    "account",
                    "origins",
                    "replace_fields",
                ),
            }[operation]
            self._shape(payload, fields)
            vault = self._profile(payload["profile_id"])
            self.consent.message = (
                f"{operation.capitalize()} credentials in {vault.profile.label}?"
            )
            if operation == "unlock":
                vault.unlock()
                return {"state": vault.status().state.value}
            if operation in ("edit", "delete", "view"):
                reference = CredentialReference(
                    vault.profile.scope,
                    UUID(payload["credential_id"]),
                    payload["version"],
                )
                current = next(
                    (i for i in vault.list_items() if i.summary.reference == reference),
                    None,
                )
                if current is None:
                    raise CredentialUseError(UseCode.CHANGED)
                self.consent.message = (
                    f"{operation.capitalize()} saved credential?\nProfile: {vault.profile.label}\n"
                    f"Service: {current.summary.service}\nAccount: {current.summary.account_label}\n"
                    f"Credential: {reference.credential_id} v{reference.version}"
                )
                if operation == "edit":
                    from .identity import _label
                    from .records import origins

                    _label(payload["service"])
                    _label(payload["account"])
                    allowed = origins(tuple(payload["origins"]))
                    self.consent.message += (
                        f"\nNew service: {payload['service']}\nNew account: {payload['account']}\n"
                        f"New permitted origins: {', '.join(allowed)}\nReplace secret fields: {payload['replace_fields'] is True}"
                    )
            if operation == "revoke":
                self.consent.message += f"\nGrant: {UUID(payload['grant_id'])}"
            if operation == "view":
                # The native executable verifies the owner before accepting the
                # private SYSTEM-only response. Public RPC returns no values.
                with vault._helper_record(
                    reference, vault.status().unlock_epoch
                ) as record:
                    self.consent.view(record.fields)
                return {"viewed": True}
            # Native verification is required even if the requesting browser was
            # authenticated and the profile already happens to be unlocked.
            self.consent.verify(self.owner)
            if operation == "items":
                if len(self.views) >= 16:
                    raise CredentialUseError(UseCode.LIMIT)
                view_id = uuid4()
                items = tuple(self._item(item) for item in vault.list_items())
                epoch = vault.status().unlock_epoch
                if epoch is None:
                    raise CredentialUseError(UseCode.LOCKED)
                self.views[view_id] = OwnerView(
                    peer.pid,
                    peer.created,
                    vault.profile.scope,
                    epoch,
                    time.monotonic() + 60,
                    items,
                )
                return {**metadata_page(items, 0), "view_id": str(view_id)}
            if operation == "activity":
                return [
                    {
                        "action": e.action,
                        "outcome": e.outcome,
                        "grant_id": str(e.grant_id) if e.grant_id else None,
                    }
                    for e in self.broker.audit_events()[-128:]
                    if e.scope == vault.profile.scope
                ]
            if operation == "revoke":
                grant_id = UUID(payload["grant_id"])
                for launch in self.leases.values():
                    if (
                        launch.context.binding.scope == vault.profile.scope
                        and launch.job is not None
                        and launch.job.grant_id == grant_id
                    ):
                        launch.job.cancelled.set()
                self.broker.revoke_scoped(grant_id, vault.profile.scope)
                return {"revoked": True}
            reference = CredentialReference(
                vault.profile.scope, UUID(payload["credential_id"]), payload["version"]
            )
            if operation == "delete":
                vault.delete(reference)
                return {"deleted": True}
            if type(payload["replace_fields"]) is not bool:
                raise CredentialUseError(UseCode.DENIED)
            item = next(
                (i for i in vault.list_items() if i.summary.reference == reference),
                None,
            )
            if item is None:
                raise CredentialUseError(UseCode.CHANGED)
            secret = None
            if payload["replace_fields"]:
                names = {
                    CredentialKind.LOGIN: ("username", "password"),
                    CredentialKind.API_KEY: ("api_key",),
                }.get(item.summary.kind)
                if names is None:
                    with vault._helper_record(
                        reference, vault.status().unlock_epoch
                    ) as record:
                        names = tuple(record.fields.reveal())
                secret = self.consent.entry(names)
            return self._item(
                vault.update(
                    reference,
                    service=payload["service"],
                    account_label=payload["account"],
                    fields=secret,
                    allowed_origins=tuple(payload["origins"]),
                )
            )
        if operation in ("initialize", "lock", "entry"):
            fields = (
                ("profile_id",)
                if operation != "entry"
                else ("profile_id", "kind", "service", "account", "origins", "fields")
            )
            self._shape(payload, fields)
            vault = self._profile(payload["profile_id"])
            self.consent.message = f"{operation.capitalize()} credentials in profile {vault.profile.label}?"
            if operation == "lock":
                vault.lock()
                return {"state": "locked"}
            if operation == "initialize":
                vault.initialize()
                return {"state": "ready"}
            kind = CredentialKind(payload["kind"])
            from .identity import _label
            from .records import origins

            _label(payload["service"])
            _label(payload["account"])
            origins(tuple(payload["origins"]))
            names = {
                CredentialKind.LOGIN: ("username", "password"),
                CredentialKind.API_KEY: ("api_key",),
            }.get(kind)
            if names is None:
                names = tuple(payload["fields"])
                import re

                if (
                    not 1 <= len(names) <= 8
                    or len(set(names)) != len(names)
                    or any(
                        not isinstance(name, str)
                        or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                        for name in names
                    )
                ):
                    raise CredentialUseError(UseCode.DENIED)
            elif payload["fields"] != []:
                raise CredentialUseError(UseCode.DENIED)
            if vault.status().state is not VaultState.READY:
                vault.unlock()
            self.consent.message = f"Save {kind.value} for {payload['service']} / {payload['account']} in {vault.profile.label}?\nPermitted origins: {', '.join(payload['origins'])}"
            secret = self.consent.entry(names)
            item = vault.create(
                kind,
                payload["service"],
                payload["account"],
                secret,
                allowed_origins=tuple(payload["origins"]),
            )
            return {"credential_id": str(item.summary.reference.credential_id)}
        if operation == "launch":
            self._shape(
                payload,
                ("profile_id", "kind", "subject", "deployment", "files", "entry"),
            )
            if len(self.leases) >= 16:
                raise CredentialUseError(UseCode.LIMIT)
            vault = self._profile(payload["profile_id"])
            revision = source_files(payload["files"], payload["entry"])
            kind = CallerKind(payload["kind"])
            instance = uuid4()
            caller = CallerIdentity(
                kind,
                payload["subject"],
                instance,
                revision if kind is CallerKind.AGENT_APP else None,
                AppDeployment(payload["deployment"])
                if kind is CallerKind.AGENT_APP
                else None,
            )
            if kind is not CallerKind.AGENT_APP and payload["deployment"] is not None:
                raise CredentialUseError(UseCode.DENIED)
            self.consent.message = f"Launch isolated {kind.value}?\nRequested label (unverified): {json.dumps(caller.subject_id)}\nProfile: {vault.profile.label}\nCode SHA256: {revision}\nClaimed deployment (unverified): {payload['deployment'] or 'agent'}\nApp name and deployment are caller claims, not trusted enrollment.\nCredential use requires a separate approval."
            self.consent.verify(self.owner)
            if not peer.alive():
                raise CredentialUseError(UseCode.DENIED)
            process = IsolatedProcess(
                self.state / "runs" / instance.hex,
                self.root / "python" / "python.exe",
                self.owner.os_identity,
                peer.session,
            )
            binding = controller = None
            try:
                for name, content in payload["files"].items():
                    path = process.root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                    private_acl(path, process.app_sid)
                client = self.root / "app" / "credentials" / "client.py"
                (process.root / "credential_client.py").write_bytes(client.read_bytes())
                private_acl(process.root / "credential_client.py", process.app_sid)
                # -I removes script dir. The protected generated entry adds only
                # its immutable snapshot; it never imports the CraftBot checkout.
                runner = process.root / "_host_entry.py"
                runner.write_text(
                    "import sys, runpy\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parent))\nrunpy.run_path("
                    + repr(str(process.root / payload["entry"]))
                    + ", run_name='__main__')\n",
                    encoding="utf-8",
                )
                private_acl(runner, process.app_sid)
                binding = CallerBinding(uuid4(), caller, vault.profile.scope)
                self.directory.bind(binding)
                context = self.directory.resolve(binding.binding_id, caller, uuid4())
                process.start("_host_entry.py")
                controller = Peer(peer.pid)
                if controller.created != peer.created or not controller.alive():
                    raise CredentialUseError(UseCode.DENIED)
                self.leases[instance] = Launch(
                    process,
                    context,
                    controller,
                    time.monotonic() + 900,
                    snapshot_revision=revision,
                )
                launch = self.leases[instance]
                timer = Timer(900, self._expire, args=(instance, launch))
                timer.daemon = True
                self.leases[instance].timer = timer
                timer.start()
                Thread(target=self._watch, args=(instance, launch), daemon=True).start()
            except BaseException:
                self.leases.pop(instance, None)
                if binding is not None:
                    self.directory.revoke(binding.binding_id)
                if controller is not None:
                    controller.close()
                process.close()
                raise
            return {
                "run_id": str(instance),
                "revision": revision,
                "identity_verified": False,
            }
        if operation in (
            "result",
            "program_result",
            "stop",
            "response",
            "stage_payload",
            "reset_operation",
        ):
            self._shape(
                payload,
                ("run_id", "offset", "data", "done")
                if operation == "stage_payload"
                else ("run_id", "offset")
                if operation == "response"
                else ("run_id",),
            )
            key = UUID(payload["run_id"])
            launch = self.leases.get(key)
            if (
                launch is None
                or launch.controller.pid != peer.pid
                or launch.controller.created != peer.created
            ):
                raise CredentialUseError(UseCode.DENIED)
            if operation == "stage_payload":
                return self._stage(launch, payload)
            if operation == "program_result":
                if launch.result is not None:
                    return launch.result
                if api()[6].WaitForSingleObject(launch.process.handle, 0) == 0:
                    return {
                        "exited": api()[3].GetExitCodeProcess(launch.process.handle)
                    }
                return {"pending": True}
            if operation == "reset_operation":
                if launch.job is None or not launch.job.done.is_set():
                    raise CredentialUseError(UseCode.DENIED)
                launch.job.close()
                launch.job, launch.credential_output, launch.result = None, None, None
                return {"ready": True}
            if operation == "response":
                if launch.job is not None:
                    return launch.job.snapshot(payload["offset"])
                output = launch.credential_output
                offset = payload["offset"]
                if (
                    output is None
                    or type(offset) is not int
                    or not 0 <= offset <= len(output.body)
                ):
                    raise CredentialUseError(UseCode.DENIED)
                return {"chunk": output.body[offset : offset + 4000]}
            if operation == "result":
                if launch.job is not None:
                    snapshot = launch.job.snapshot()
                    if snapshot["error"]:
                        raise CredentialUseError(UseCode(snapshot["error"]))
                    if snapshot["status"] is not None:
                        return {
                            "response": {
                                key: snapshot[key]
                                for key in ("status", "content_type", "length", "done")
                            }
                        }
                    if snapshot["done"]:
                        result = launch.job.result
                        return {
                            "result": {
                                "outcome": result.value
                                if result is not None
                                else "unavailable"
                            }
                        }
                if launch.credential_output is not None:
                    output = launch.credential_output
                    return {
                        "response": {
                            "status": output.status,
                            "content_type": output.content_type,
                            "length": len(output.body),
                        }
                    }
                if launch.result is not None:
                    return launch.result
                if api()[6].WaitForSingleObject(launch.process.handle, 0) == 0:
                    return {
                        "exited": api()[3].GetExitCodeProcess(launch.process.handle)
                    }
                return {"pending": True}
            self._expire(key, launch)
            return {"stopped": True}
        raise CredentialUseError(UseCode.DENIED)

    @staticmethod
    def _item(item):
        summary = item.summary
        return {
            "credential_id": str(summary.reference.credential_id),
            "version": summary.reference.version,
            "kind": summary.kind.value,
            "service": summary.service,
            "account": summary.account_label,
            "origins": list(item.allowed_origins),
            "updated_at": item.updated_at,
        }


def resolve_envelope(envelope):
    if (
        type(envelope) is not dict
        or set(envelope)
        != {"peer_pid", "peer_created", "peer_sid", "peer_app_sid", "payload"}
        or type(envelope["peer_pid"]) is not int
    ):
        raise CredentialUseError(UseCode.DENIED)
    peer = Peer(envelope["peer_pid"])
    try:
        if (
            str(peer.created) != envelope["peer_created"]
            or not peer.alive()
            or peer.sid != envelope["peer_sid"]
            or peer.app_sid != envelope["peer_app_sid"]
        ):
            raise CredentialUseError(UseCode.DENIED)
    except BaseException:
        peer.close()
        raise
    return peer


def main(root: Path):
    # No environment opt-out or developer bypass. SCM/SYSTEM is mandatory.
    import win32con
    import win32security
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(0, 0x23, None, 0, buffer) != 0:
        raise IsolationUnavailable()
    state = Path(buffer.value) / "CraftBotCredentialHost"
    check_install(root, state)
    with closing(
        win32security.OpenProcessToken(api()[0].GetCurrentProcess(), 0x28)
    ) as token:
        win32security.AdjustTokenPrivileges(
            token,
            False,
            [
                (
                    win32security.LookupPrivilegeValue(None, name),
                    win32con.SE_PRIVILEGE_ENABLED,
                )
                for name in (
                    "SeTcbPrivilege",
                    "SeAssignPrimaryTokenPrivilege",
                    "SeIncreaseQuotaPrivilege",
                    "SeRestorePrivilege",
                )
            ],
        )
    host = ProtectedHost(
        root, state, json.loads((root / "host.json").read_text(encoding="utf-8-sig"))
    )
    for line in sys.stdin:
        peer = None
        try:
            if len(line) > 400001:  # Native envelope limit plus trailing newline.
                raise CredentialUseError(UseCode.DENIED)
            envelope = json.loads(line)
            peer = resolve_envelope(envelope)
            value = host.dispatch(peer, envelope["payload"])
            response = {"ok": True, "result": value}
        except CredentialUseError as error:
            response = {"ok": False, "error": error.code.value}
        except BaseException:
            response = {"ok": False, "error": UseCode.UNAVAILABLE.value}
        finally:
            if peer is not None:
                peer.close()
        print(json.dumps(response, ensure_ascii=True), flush=True)
