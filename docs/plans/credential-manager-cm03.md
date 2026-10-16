# CM-03 — Authorization and trusted helper execution

Status: authorization core and Windows protected-service/consumer-launch/owner
transport implementation are present. **Administrator installation and native
end-to-end acceptance are still pending in this unelevated environment. The
CM-03 release gate remains open until those checks pass.** The Windows host
checks real process tokens and private job membership; ordinary in-process,
venv, shell and existing bridge callers receive no vault authority. The default
in-process boundary and unsupported platforms continue to reject secret use.

See [Windows deployment and acceptance](credential-manager-windows-host.md).

The user's request to implement supersedes the earlier planning-only instruction.
Existing access/refresh tokens, browser cookies/profiles, session IDs and their
stores retain their owners and locations. No live migration has been performed.
Subsequent Settings, consumer and offline migration code is recorded in
[current implementation and coverage](credential-manager-consumers.md).

## Components

| Component | Change |
| --- | --- |
| `app/credentials/broker.py` | Host approvals, bounded runtime grants, one-use capabilities, approved discovery, status, queued cancellation, revocation, metadata-only activity |
| `app/credentials/helpers.py` | Sealed host-installed registry and a fixed HTTPS credential-check helper; no dynamic code or arbitrary authenticated request interface |
| `app/credentials/use_errors.py` | Stable outcome codes; removes secret-bearing exception messages, contexts and inner traceback frames, including interruptions |
| `app/credentials/directory.py` | Validates vault/catalog OS-owner identity at bootstrap; serializes channel revocation with dispatch |
| `app/credentials/vault.py` | Private broker-only record window, unlock-epoch checks and SQLite writer reservation throughout dispatch; helper failures do not mark storage corrupt |
| `tests/credentials/test_broker.py` | Synthetic authorization, actual helper control flow with mocked I/O, concurrency, destination, isolation and diagnostic-output regressions |

## Authority and use

Only a trusted host resolver supplies `ExecutionContext`. Session strings,
ContextVars, WebSocket authentication, bridge tokens, app manifests, UUIDs and
caller-supplied JSON do not establish credential authority. Metadata management and isolated-worker requests use adapters documented in the
consumer phase; they cannot approve use or transport source fields.

`approve(context, reference, operation)` is an **owner-channel operation**. A
protected owner UI must display the caller (including App revision/deployment),
profile, account, credential version, operation, exact endpoint and duration,
obtain explicit consent, and then call this operation with fresh owner
verification. A verification prompt alone is not consent. No verifier ships that
silently approves, and an unlocked vault does not create grants automatically.
Do not put `approve`, `revoke`, audit access or owner vault CRUD on consumer IPC.

Each grant pins the full owner/profile reference and version, exact caller
binding/runtime/revision/deployment, immutable helper descriptor (including full
endpoint and selected secret field), unlock epoch, mode and monotonic expiry.
The default is one attempted use; optional `BINDING` consent lasts up to one hour
and never crosses a lock/re-unlock, new binding, restart or configured expiry.
Grants and bindings are not persisted or inherited by subagents/other Apps.

The consumer-use interface has these operations:

1. `status(context)` returns only the bound profile's state.
2. `find(context)` returns safe summaries/references and operations for that
   exact binding's existing approvals. It does not enumerate unapproved accounts.
3. `authorize(context, grant_id)` issues an opaque 256-bit capability, bound to
   that exact execution ID, for at most 30 seconds or the grant's remaining life.
   Server state stores only the handle digest. Capability representations redact
   the handle; the future transport must also exclude it from logs.
4. `execute(context, capability)` consumes the capability before attempting use,
   rechecks authority and current record/version, and invokes only fixed host
   code. There is no raw read, resolver callback, authenticated client, generic
   proxy, command, import path, transport/header argument or consumer callback.
   Installed JSON helpers accept bounded operation data only.
5. `cancel(context, capability)` removes a queued capability belonging to that
   execution. Owner-side `revoke(grant_id)` invalidates its pending capabilities.

Capabilities are checked atomically, so concurrent replay dispatches once. An
ONCE grant cannot be multiplied by requesting several capabilities; all its
remaining handles are discarded after the first attempt, including failure or
interruption. Cancelling queued work does not consume the underlying approval.
Wrong callers cannot redeem or cancel another execution's capability.

## Fixed helper and destination policy

Host bootstrap may install up to 1,024 immutable `HttpsCredentialCheck`
descriptors. A bare registry defaults empty; the installer supplies the reviewed
package catalog described in the consumer coverage document. Consumers cannot
register helpers.
The first helper supports a host-reviewed, read-only GET check using HTTP Basic
for login records, Bearer for API-key records, or an explicitly selected manual
service-secret field. It requires the credential's exact HTTPS origin allowlist
even for non-login items. An item with no destination policy cannot be used.
Provider-specific auth schemes need separately reviewed implementations.

The helper rejects userinfo, query/fragment URLs, insecure schemes, controls and
non-ASCII endpoint configuration. It resolves the approved host once, rejects
any private/special address (including mixed answers and IPv6 transition
addresses), connects directly to a checked numeric address and verifies TLS
against the original hostname. It uses no environment proxy, automatic
reconnect, redirect follow, cookie jar or persistent authenticated client.
Host environment, dependencies, trust roots and registry configuration must be
protected by the eventual service boundary.

Isolation, binding, epoch, grant lifetime and capability lifetime are rechecked
after DNS and after TLS, immediately before constructing the auth header.
Only `accepted` (HTTP 2xx), `rejected` (401/403), or `unavailable` returns. A 2xx
check is not proof of account identity; the host must select an appropriate
provider endpoint. Response text, headers, cookies, redirect URLs and echoed
secrets never return to consumers. Debug output is disabled. Errors cross a
fresh exception boundary that discards inner locals and exception contexts;
diagnostic redaction is not just string replacement.

This helper does not exchange passwords for OAuth tokens, log into Gmail, run
browser filling, create provider clients, stream model responses, or save any
generated token/session. Those are separate reviewed CM-05/06/07 operations.
The current token/session owners will retain generated state in those flows.

## Locking, lifetime and cancellation

One host-owned vault instance per profile remains required. The broker retains
its lock, current-binding lock, vault lock and SQLite writer reservation through
credential validation and authenticated request dispatch. JSON/Gateway helpers
then release the reservation while waiting for responses. One-use authority and
all sibling pending capabilities are retired before release. Fixed form/check
helpers retain their short dispatch reservation. Concurrent updates cannot
change the version between validation and use. Already sent provider effects
cannot be retracted or treated as an existing-session sign-out.

Public network work runs in cancellable jobs; synchronous use/use_staged RPCs
are retired so a consumer cannot monopolize the control pipe. A profile's idle
lock cancels its jobs. Explicit owner/OS lock resets the native worker and all
profiles, keys, grants and AppContainers. Revocation aborts matching active jobs
and denies later uses. Streams filter source echoes before releasing deltas;
closing a stream/cancelling an async controller stops its worker.

DNS waits are bounded to ten seconds using at most four resolver threads that
receive only host/port, never secret-bearing contexts. JSON connection/TLS setup
is bounded separately from its up-to-600-second network job budget. Socket timers
and cancellation abort active exchanges. Consumer leases expire after at most
15 minutes; repeat GET consent is pinned to one worker, operation and expiry.
Writes cannot request repeat permission. Each dispatch still needs a fresh
30-second one-use capability. Use never renews the owner's unlock deadline.
See the consumer document for output quotas and supported operation policies.

Audit retains the last 512 metadata-only events in host memory; grants and
pending capabilities are bounded at 4096 and 8192. No provider response,
credential value, capability handle, OS identity, arbitrary caller label or
filesystem path enters these events. Audit persistence/export belongs to a
protected owner adapter; a restart discards runtime approvals and activity.

## Remaining integration and acceptance gates

- Install the reviewed Windows package with administrator approval, then run
  the native acceptance script as the configured unelevated owner. Do not
  substitute mocked isolation or claimed PIDs for native evidence.
- Verify native secure-desktop success/decline, AppContainer execution, file/key
  and process isolation, cross-launch identity, session-lock/suspend teardown
  and helper use. Unit tests and native compilation do not close this gate.
- Verify the implemented Settings, entry/private view and consumer adapters
  against the coverage and remaining work in the consumer document. Windows
  account passwords are the supported native verification mode; unsupported
  Hello/PIN serialization fails closed. No browser checkbox approves use.
- Extend platform coverage beyond Windows before claiming support elsewhere.

Transport implementation references: Python's
[HTTPSConnection](https://docs.python.org/3.12/library/http.client.html#http.client.HTTPSConnection),
[TLS client defaults](https://docs.python.org/3.12/library/ssl.html#ssl.create_default_context),
and [address classification](https://docs.python.org/3.12/library/ipaddress.html).

## Validation recorded

The initial core validation passed **306 tests, 49 subtests**, with 3 optional
skips. The launcher used `--noconftest` and a temporary `app.config.PROJECT_ROOT`
stub to avoid loading unrelated full-app dependencies. Credential tests use
synthetic temporary data; helper network I/O and isolation are mocked. This is
not a full-app transport or OS sandbox test.

Changed-file Ruff checks/format checks (18 files), repository Python compilation
(excluding the documented Agent App template), and `git diff --check` passed.
No production credential was used and no token/session store was migrated.
Protected-host tests additionally cover snapshot aliases/revisions, owner/consumer
separation, denied claims, real Windows peer tokens, real squatting-pipe rejection
and consumer-runtime failure behavior. Native service deployment is not yet
validated; see the Windows acceptance record before enabling it for real data.
