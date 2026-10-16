# CM-01: credential identity and trusted execution boundary

Phase record: this document describes the CM-01 contracts. Subsequent storage,
Windows isolation and consumer implementation is recorded in
[current implementation and coverage](credential-manager-consumers.md).
Authorization to start implementation supersedes the earlier planning-only hold.
This change does not read, move, copy, or modify user credentials or sessions.

## Identity decisions

One human owner may have multiple vault profiles (Personal, Work, etc.). A profile
is a credential namespace, not an agent personality bundle, provider profile,
chat session, browser tab owner, or browser cookie jar. Account labels and profile
names are not unique identifiers. Every credential reference carries owner and
profile UUIDs plus an item UUID and version.

The trusted owner enrollment adapter must obtain a stable, platform-qualified OS
account identity and mint the owner ID. Neither an environment variable, Telegram
owner flag, UI session token, nor a caller-supplied ID performs this verification.
Different OS accounts cannot share an owner record. Importing an agent bundle
must not import vault owner IDs, grants, unlock state or caller bindings.

`app/credentials/identity.py` defines immutable owner/profile/caller/binding/run
metadata. `directory.py` is an in-memory **host-only** catalog, not an exposed
registration or authentication endpoint. Persistence and OS enrollment are CM-02
and CM-03 work. Records must be validated inside the trusted service; constructing
a Python dataclass does not authenticate its creator.

Caller kinds are agent session, subagent and Agent App. The host dispatcher or
launcher supplies stable subject ID and fresh authenticated channel/runtime ID.
Agent Apps also carry the approved immutable code revision and live/development
deployment identity. An app manifest declares requested capabilities, not consent.
An authenticated transport must supply the caller identity out of band; never
reconstruct it from request JSON or trust `_session_id` as authentication.

Bindings explicitly associate an authenticated channel with a profile. Switching
profiles requires a new binding; existing requests keep their previous scope.
Multiple profiles for one app/session use separately authorized channels. There
is no ambient active profile, `main` fallback, inherited subagent binding, or
automatic cross-account grant. A binding grants no secret use by itself. Use-time
checks must revalidate a binding, including previously resolved contexts. Revoked
binding IDs cannot be recycled within a service lifetime. Service restart must
discard runtime bindings; it must never restore them from consumer input.

## Required trusted boundary

Trusted: credential service, OS key/verification adapter, protected helper code,
and owner approval UI/channel. Untrusted: generated scripts, custom actions,
skills, Agent Apps, page content, and all tool/request parameters. Model output
is input to a dispatcher, not a principal or an instruction to expand authority.

```text
authenticated isolated caller -> host identity resolver -> profile binding
    -> operation/account/destination grant check -> registered trusted helper
    -> approved destination -> sanitized result or existing connection owner
```

The registered helper is the only place outside vault storage where a saved
secret may be handled. No callback returning values to consumers, authenticated
client object, arbitrary module import, script, command, or URL proxy is allowed.
Consumer summaries contain references and metadata only, without OS identities,
secret suffixes/lengths, values, or encryption material.

`contracts.py` declares an isolation adapter contract. The only provided adapter
rejects all use with `credential_isolation_unavailable`. No production route or
legacy code path is wired to these contracts. An unavailable backend must never
fall back to the legacy vault or claim the required boundary is already enforced.

OS isolation must protect files/keys, process memory/handles, trusted code and
dependencies, owner approval interfaces, and private IPC credentials. Trusted
helpers cannot import from agent-writable source trees, action directories, or
the shared sandbox venv. Agent/app children need minimal environments, constrained
resources, authenticated channels and separate per-deployment identity. Broker
operations must not become an unrestricted host shell outside the sandbox.
Sandbox escape, IPC impersonation, data leaks, update integrity, and approved
folder symlink/reparse-point behaviour need platform validation. Arbitrary host
shell access remains incompatible with this isolation claim. No OS sandbox is
selected, installed, or claimed by this CM-01 change; unsupported platforms must
fail closed rather than accept an attestation supplied by the consumer.

## Current-code gaps and next changes

| Component | Current situation | Required follow-up |
| --- | --- | --- |
| `app/config.py`, `app/paths.py` | State root is project/per-user data directory | Protected vault metadata/key location; explicit owner enrollment |
| `app/mini_browser/actions_api.py` | Browser owner resolves from `_session_id`, with `main` fallback | Keep for tab routing; use independent authenticated credential bindings |
| `agent_core/core/impl/action/context.py`, `manager.py` | Host provenance exists; action inputs are logged | Add protected caller resolution; never place secret entry in action inputs |
| `agent_core/core/impl/action/executor.py` | Venv child processes and in-process `exec` paths | Isolate untrusted code; only fixed audited host code may execute trusted operations |
| `app/data/action/run_shell.py`, `run_powershell.py`, file tools | Ordinary user processes / host file access | Enforce OS restrictions and resource grants; no alternate bypass path |
| `app/node_runtime.py` | Child environment copies host environment | Explicit allowlist for untrusted children |
| `app/agent_app/manager.py` | Ordinary children; project-scoped bridge bearer token | Isolated launch/build/install/runtime and identity per approved revision/deployment |
| `app/agent_app/integration_bridge.py` | Token/manifest/destination guards | Separate profile/account grants; no authority based solely on writable manifest |
| `app/ui_layer/adapters/ws_auth.py` | Host/origin/UI-session guards | Separate locally verified owner authority and consumer use authority |
| `app/mini_browser/vault.py` | Cached decrypted state and raw-key fallback | CM-02 extraction and fail-closed OS key/lock lifecycle |

## Source-secret classification

Field names alone cannot determine ownership or migration. Provider/auth mode and
provenance are mandatory; unknown legacy records need explicit review/re-entry,
not guesses or reads of live user values.

| Record | Classification | Ownership/location after migration |
| --- | --- | --- |
| Browser saved username/password | Source login | Shared vault, bound to explicit profile |
| Model primary/extra API keys | Source keys | Shared vault; key-pool state uses references |
| Figma PAT in `access_token`, `auth_kind=pat` | Manually supplied source secret | Shared vault; ordinary provider clients must not retain it |
| Figma `auth_kind=oauth`, Google OAuth completion | Generated authentication state | Existing integration token owner/store |
| Static bot tokens, PATs, service API secrets | Source service secrets | Shared vault; provider-specific reviewed classification |
| Subscription OAuth access/refresh/ID tokens | Generated authentication state | Existing `craftos_integrations/llm_oauth` owners/stores |
| Browser cookies/profiles, WhatsApp login/session data | Generated sessions | Existing browser/provider owners/stores |
| Static AWS keys / user-supplied OAuth application secrets | Source secrets | Reviewed source fields in shared vault |
| Temporary AWS/session credentials | Derived or externally managed state | Existing owner; do not migrate by field-name heuristic |
| Shipped public OAuth application configuration | Application configuration | Not automatically a user-vault item |

Profile-aware connection bindings must filter existing account selection even
though generated tokens stay where they are. No token file, refresh behaviour,
browser context or existing session is moved/changed by this foundation. Vault
profiles do not automatically isolate already authenticated website sessions.

## CM-01 validation and remaining gates

Synthetic identity tests cover multiple profiles/owners, duplicate display names,
explicit profile switching, foreign scopes, runtime/revision/deployment changes,
subagent non-inheritance, immutable bindings, and revocation of in-flight contexts.
Default isolation always refuses use. These are contract tests, not evidence of
OS isolation or credential leak resistance of the existing application.

Still required before enabling secret use: OS owner enrollment and verification,
protected service/key persistence, isolated execution on each supported platform,
helper code/update integrity, authenticated transport binding, owner approvals,
credential-operation grants and capability replay/expiry enforcement, complete
provider/auth-mode inventory, and end-to-end boundary tests. CM-01 establishes the
contracts and recorded decisions; it does not close these security gates.
