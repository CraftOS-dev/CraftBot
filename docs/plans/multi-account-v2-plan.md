# Integrations v2 — Composable, Host-Agnostic Integration System with Multi-Account Support

**Status:** Approved direction — decisions locked in §15
**Target base:** `V1.4.2` — new branch `feature/integrations-v2`, built from scratch
**Origin:** Issue #368 (multi-account). PR #370 is abandoned; this design does not
reuse its architecture (condensed pitfalls checklist in §14).

---

## 1. Goals

1. **Multi-account:** each integration holds **one primary account plus any
   number of additional accounts**, each with an optional user alias; every
   agent operation takes an optional `account` selector; Settings UI manages
   add/rename/switch-primary/disconnect.
2. **Composition:** the integration system is a **self-contained,
   host-agnostic package**. Individual integrations are plugins ("providers")
   that register themselves; the whole package can be mounted into a different
   agent — or exposed over MCP — without touching CraftBot code. CraftBot is
   simply the first host.
3. **Listener fan-out:** inbound event sources (Gmail/Outlook polling, Slack
   events) run **per account**, not just for the primary — with a per-account
   on/off toggle in the UI (§8).

**Providers in scope (10):** Gmail, Google Calendar, Google Drive, Google Docs,
YouTube, Outlook, LinkedIn, Notion, HubSpot, Slack. Existing other
integrations keep working unchanged during the transition (§12).

**Out of scope:** the chat-questionnaire subsystem (unrelated feature, own
issue).

---

## 2. Composition architecture (ports & adapters)

```
craftos_integrations/                  # ZERO imports from app/ or agent_core/
  contracts.py                         # every Protocol the package speaks
  core/
    accounts.py                        # AccountSet: primary + N accounts (§4)
    storage.py                         # CredentialStore backends (file default)
    oauth.py                           # generic OAuth engine (host supplies transport)
    registry.py                        # provider + client instance registry
    listeners.py                       # ListenerManager: per-account fan-out (§8)
    guidance.py                        # assembles agent guidance from providers
  providers/
    gmail/
      provider.py                      # implements Provider
      operations.py                    # Operation descriptors (the "actions", neutral)
      GUIDANCE.md                      # provider prompt guidance (host-agnostic wording)
    outlook/ … slack/                  # one folder per provider, self-registering
  hosts/
    mcp/server.py                      # later: whole package as an MCP server
CraftBot side (the host adapter — the ONLY CraftBot-specific code):
  app/data/action/integrations/craftbot_adapter.py
  app/ui_layer/... settings handlers   # UI ops via IntegrationSystem (§6)
```

### The contracts (`contracts.py`)

What a **provider** implements:

```python
class Provider(Protocol):
    id: str                            # "gmail"
    family: str | None                 # "google" → shared aliases (§4)
    def identity_of(self, credential: dict) -> str | None
    def oauth_spec(self) -> OAuthSpec          # urls, scopes, chooser params (§7)
    def build_client(self, credential: dict) -> Any
    def refresh(self, credential: dict) -> dict | None   # None = non-expiring
    def operations(self) -> list[Operation]
    def guidance(self) -> str                  # contents of GUIDANCE.md
    def make_listener(self, client, cursor: dict | None) -> Listener | None
                                               # one instance PER listening account (§8)
```

```python
@dataclass(frozen=True)
class Operation:                      # a framework-neutral "action"
    name: str                         # "send_gmail"
    description: str
    input_schema: dict                # JSON-Schema properties (NO account key here)
    output_schema: dict
    fn: Callable[[Any, dict], Awaitable[dict]]   # (client, input) -> result
    destructive: bool = False         # hosts may confirm/guard these
    tags: tuple[str, ...] = ()
```

What a **host** implements:

```python
class OAuthTransport(Protocol):       # how a redirect/callback physically happens
    async def authorize(self, url: str) -> CallbackParams   # CraftBot: local server + browser

class CredentialStore(Protocol):      # where AccountSets + listener cursors persist
    def load(self, provider_id) -> dict | None
    def replace(self, provider_id, data) -> None    # atomic
    def locked(self, provider_id) -> ContextManager  # RMW lock

class EventSink(Protocol):            # where listener events go (host trigger system)
    async def on_event(self, provider_id: str, identity: str, event: dict) -> None
```

The package ships a filesystem `CredentialStore` (the default, §5) and a
loopback `OAuthTransport`; a different agent can inject keyring/DB storage,
its own OAuth UX, and its own event routing without forking the package.

### The single host-facing entry point

```python
class IntegrationSystem:              # what any agent embeds
    def __init__(self, store, oauth, sink: EventSink | None = None, providers=DEFAULT)
    # capability discovery
    def providers(self) -> list[ProviderInfo]
    def operations(self, provider_id=None) -> list[Operation]
    def guidance(self, connected_only=True) -> str      # for system prompts
    # execution — multi-account handled HERE, uniformly
    async def execute(self, provider_id, op_name, input: dict, account: str | None = None) -> dict
    # account management (drives any settings UI)
    def list_accounts(pid) / resolve(pid, hint)
    async def add_account(pid)        # runs OAuth via transport, upserts by identity
    def set_alias(pid, hint, alias) / set_primary(pid, hint) / remove_account(pid, hint)
    def set_listening(pid, hint, on: bool)
    async def apply_account_changes(pid, batch) -> AccountList   # UI batched save (§10)
    # listeners
    async def start_listeners(self) / stop_listeners(self)       # host lifecycle hooks
```

**Why this solves multi-account better than per-action edits:** `execute()`
resolves `account → identity → client` once, centrally. Providers and their
operations never see account selection — they receive a ready client. The host
adapter advertises the `account` input on every generated action schema in one
line of code. There is no way to "forget" it on 80 of 290 actions (the failure
that made the old PR dangerous), and a `destructive=True` flag lets hosts add
confirm-or-clarify behavior uniformly.

### Host adapters

- **CraftBot adapter** (`craftbot_adapter.py`): iterates
  `system.operations()`, generates one `@action` wrapper per Operation —
  schema = `input_schema` + injected `account` property, execution =
  `system.execute(...)`, errors mapped to the standard
  `{"status": "error", "message": ...}` self-correction dict. INTEGRATION.md
  essentials come from `system.guidance()`. Implements `EventSink` by mapping
  events into CraftBot's trigger system with account context (§8). ~250 lines
  total, replacing ~10 hand-maintained action files.
- **MCP host** (later): the same `operations()` list exposed as MCP tools,
  `guidance()` as MCP resources/prompts, account management as tools. This is
  the "plug the whole system into a different agent" story with an
  industry-standard socket — any MCP-capable agent gets all 10 integrations,
  multi-account included, for free. Aligns with the DONUT agent-agnostic
  direction.

Rules that keep it composable (CI-enforced, §11):
- `craftos_integrations/` may not import from `app/` or `agent_core/`
  (import-linter contract in CI).
- Providers may not import each other or the host; they self-register via the
  package registry on import.
- All host-visible behavior goes through `contracts.py` types.

---

## 3. What changes vs. today's repo layout

| Today | v2 |
|---|---|
| `app/data/action/integrations/<x>_actions.py` — ~290 hand-written `@action` defs | generated by the CraftBot adapter from Operation descriptors |
| `craftos_integrations/integrations/<x>/__init__.py` — login/status/logout + client, imports app config | `providers/<x>/` — Provider impl + operations, host-blind |
| INTEGRATION.md essentials scattered per integration | `GUIDANCE.md` per provider, assembled by `guidance()` (connected-aware) |
| UI adapter calls integration functions directly | UI calls `IntegrationSystem` account-management API |
| one bare credential file per integration | one `AccountSet` document per provider (§5) |
| listeners hardwired to the single account | `ListenerManager` fan-out per listening account (§8) |

Migration strategy for the other (non-scoped) integrations: they stay on the
old path untouched; the old and new registries coexist behind the current
`service.py` facade until each is ported (§12). Nothing breaks mid-transition.

---

## 4. Account model

One **AccountSet** document per provider:

```
{ version: 2,
  primary: "a@x.com",                      # pointer — always valid, self-repairing
  accounts: {
    "a@x.com": {credential: {...}, alias: "work",   listen: true,  added_at: ...},
    "b@y.com": {credential: {...}, alias: "school", listen: true,  added_at: ...} } }
```

- **Identity** = provider-stable key (email / workspace id / hub id / team id),
  lowercase, from `Provider.identity_of`.
- **Primary is a pointer, not a copy** — two primaries structurally impossible;
  dangling pointer repaired on load (oldest account, logged).
- **Aliases live in the account record** — no separate store to corrupt/leak.
  Uniqueness enforced per family at set-time. `family="google"` propagates an
  alias to the same identity across all five Google AccountSets (lazy
  consistency sweep on read heals partial writes).
- **`listen`** — whether this account's inbound listener runs (§8). Defaults
  `true` for every account ("connected means fully connected"); per-account
  toggle in the Manage modal.

**Resolution contract** for `account` hints (agents and UI both):
1. empty → primary
2. exact identity match (case-insensitive) — identity always outranks alias
3. exact alias match
4. unique substring of identity or alias
5. ambiguous → `AccountResolutionError` listing candidates
6. no match → `AccountResolutionError` listing connected accounts
Errors enumerate valid choices so the LLM self-corrects. Non-string hints are
rejected at the boundary — nothing unhashable reaches a cache key.

---

## 5. Storage (default filesystem backend)

- Same paths as today (`<config>/credentials/gmail.json`) — the v2 wrapper
  migrates a legacy bare credential on first load (idempotent, invisible).
  Identity-less legacy credentials (old LinkedIn/Notion) get sentinel identity
  `"legacy"` and are upgraded in place on next re-auth — never duplicated.
- **Atomic writes only:** tmp file (0600) + `os.replace`; read-modify-write
  under an advisory `flock` (token refresh vs UI edit can't interleave).
- Corrupt file → quarantine as `.corrupt`, log loudly, provider reads as
  disconnected. Never a silent `{}`, never a parse error escaping the API.
- Dir `0700`, files `0600`, enforced at every write.
- **Listener cursors** (per-account poll state, §8) persist separately from
  credentials: `<config>/credentials/_cursors/<provider>.json`, keyed by
  identity — losing a cursor is harmless (worst case: one duplicate or missed
  poll window), so they're excluded from the AccountSet's stronger guarantees.

Client instances cached by `(provider_id, resolved_identity)` — resolution
happens **before** the cache, so alias spellings share one client and bad
hints never pollute the cache. `remove_account` / `set_primary` / `set_alias`
invalidate affected entries (alias changes re-point routing immediately).

Token refresh: provider's `refresh()` result is written back via a locked RMW
of that one account entry.

---

## 6. Multi-account UX spec

- `check_integration_status` → per-provider `accounts` array
  `{identity, alias, isPrimary, listen}`, plus a shared status text format
  `- {alias or identity} ({identity}) [primary]` — formatted once in core,
  impossible to drift per provider.
- Add account → real OAuth with account chooser (§7), applies immediately.
- Rename / set-primary / disconnect / listen-toggle → staged in the UI,
  batched on save (§10).
- Removing the primary promotes the oldest remaining account and reports it.
- Removing the last account = plain disconnect, **uniform across all 10
  providers** (HubSpot's legacy stop-the-platform special case is dropped;
  PR 2 verifies normal cache invalidation covers whatever it was masking).
- Disconnect deletes credentials **locally only** (today's semantics).
  Provider-side token revocation is a flagged follow-up — it needs
  Google-family awareness first (revoking one Google token can kill the whole
  grant, i.e. disconnecting Gmail could break Calendar/Drive/Docs/YouTube for
  that account).

---

## 7. Provider specifics

| Provider | Identity | Add-account chooser | Refresh | Listener | Notes |
|---|---|---|---|---|---|
| Gmail | `email` (userinfo) | `prompt=consent select_account` | yes (google mixin) | poller | reject empty-email userinfo (re-prompt) |
| Calendar / Drive / Docs / YouTube | `email` (userinfo) | same | yes | none | |
| Outlook | `email`/UPN | `prompt=select_account` — must ship | yes | poller | |
| LinkedIn | `email`, fallback `sub` | none exists in LinkedIn OAuth | yes (~60d) | none | UI copy: "log out of linkedin.com first to add a different account"; no fictitious params |
| Notion | workspace/bot id | native workspace picker | no | none | legacy token-only files → `"legacy"` sentinel |
| HubSpot | hub id | provider chooser | yes | none | last-logout unified (§6) |
| Slack | team id | provider-side picker | no | event listener | one connection per listening team |

`OAuthSpec` carries these per-provider params declaratively; `core/oauth.py`
runs the flow through the host's `OAuthTransport`.

---

## 8. Listener fan-out

**Model:** one `Listener` instance per `(provider, account)` where
`listen=true` and the provider has inbound events (Gmail/Outlook pollers,
Slack event connection). Managed centrally by `core/listeners.py
ListenerManager`; providers only implement `make_listener(client, cursor)`.

1. **Reconciliation:** the manager diffs desired state (AccountSets ×
   `listen` flags) against running instances — on account add/remove,
   listen-toggle, or credential change it starts/stops exactly the affected
   instance. Called on startup, after every `apply_account_changes`, and
   after OAuth completion.
2. **Event tagging:** every event is delivered as
   `sink.on_event(provider_id, identity, event)`. The CraftBot adapter
   injects account context into the trigger payload so the agent (and the
   user) can see *which* account fired: "New email in school Gmail
   (b@y.com)". Trigger-driven replies then pass `account=<identity>` back
   into operations — reply-from-the-right-mailbox falls out naturally.
3. **Per-account cursors:** poll state (last-seen ids/timestamps) is keyed by
   identity (§5) — two Gmail accounts never share dedup state. Legacy
   single-account cursor migrates to the primary's key on first run.
4. **Quota hygiene:** pollers for the same provider are staggered
   (`stagger = interval / instance_count`) so N accounts don't burst
   simultaneously; per-instance backoff on 429/5xx so one throttled account
   doesn't stall the others.
5. **Failure isolation:** a listener crash-loop (e.g. revoked credential)
   disables that instance after K consecutive failures, marks the account's
   status ("listening paused — reconnect to resume"), and never affects other
   accounts' listeners.
6. **Defaults:** `listen: true` for all accounts, primary included. The user
   turns noise off per account in the Manage modal rather than discovering
   that a connected account silently doesn't trigger.

---

## 9. Agent guidance & prompts

- `system.guidance(connected_only=True)` assembles provider GUIDANCE.md
  sections for **connected** providers — replacing `_integration_essentials`'s
  hardcoded keyword table. Keyword seeding (for just-in-time injection)
  matches on **word boundaries** (`\bcalendar\b` — no "doctor"/"docker"/
  "driver" false-positives) and comes from provider metadata, not a central
  hardcoded dict.
- Routing prompt (`agent_core/core/prompts/action.py`, written against
  V1.4.2's structure): extract account qualifiers from natural language into
  `account`; relay resolver errors verbatim (they list options); for
  `destructive=True` operations with multiple accounts and no qualifier, ask
  instead of defaulting to primary.
- AGENT.md: "every integration action accepts optional `account`" — true by
  construction (adapter-injected). Document per-account listening and the
  LinkedIn add-account caveat. Fix the pre-existing
  `check_integration_status("google")` umbrella trap.

---

## 10. Frontend — Manage modal (V1.4.2 session-native)

UX: the integration card opens a Manage modal listing accounts (alias,
identity, primary badge, listen toggle). Edits — rename, set primary,
disconnect, listen on/off — are **staged locally** and committed on "Save
changes"; closing discards. "Add account" launches the real OAuth flow and
applies immediately.

1. **Request correlation** — client `requestId` echoed in results; no
   wall-clock timers; broadcasts from other tabs update data only.
2. **No side-effect modal opens** — only explicit user clicks open it.
3. **Staged-state lifecycle** — reset on every close path; pruned when
   accounts vanish from refreshed lists; primary badge falls back to the real
   primary.
4. **One batched save** — a single `integration_apply_account_changes`
   request (server applies disconnects → primary → aliases → listen flags
   inside the storage lock, then reconciles listeners); response carries the
   final account list; on failure staged edits are kept and the error shown.
5. **Reliable transport** — saves use the queued/outbox send path; user input
   is never dropped behind an `isConnected` guard.
6. Types: `accounts: [{identity, alias, isPrimary, listen}]` added to
   integration status/info payloads in `app/ui_layer/components/types.py` ↔
   frontend `types/index.ts`, per session-native wire conventions. No
   chat-component or chat-storage changes.

---

## 11. Testing & CI

1. **Accounts core** (pure, tmpdir): migration idempotency + `"legacy"`
   upgrade-in-place; every resolution rule (identity-beats-alias, ambiguity,
   non-string hints); alias uniqueness + family propagation + cleanup on
   removal; primary repair / oldest-promotion / no-side-effects-on-failed-
   remove; injected-crash atomicity; lock serialization; corruption
   quarantine.
2. **Contracts conformance suite** — a reusable test class run against *every*
   provider: `identity_of` on captured credential fixtures, `oauth_spec`
   completeness (chooser params present unless explicitly declared
   unsupported), every Operation's schema is valid JSON-Schema and
   `destructive` set on anything named delete/clear/remove/revoke. New
   providers inherit the suite — the plug-and-play quality gate.
3. **ListenerManager** (fake providers, fake clock): reconciliation
   starts/stops exactly the right instances on add/remove/toggle; per-account
   cursor isolation + legacy cursor migration; stagger + backoff; K-failure
   disable isolates one account; events arrive tagged with the right
   identity.
4. **Adapter test** — every generated CraftBot action has the injected
   `account` property and routes through `execute()`; resolution errors come
   back as the standard error dict, never a traceback; trigger payloads carry
   account context.
5. **Isolation gate** — import-linter: `craftos_integrations` imports nothing
   from `app/`/`agent_core/`; providers import neither hosts nor each other.
   Plus `python -m compileall` + import-every-module, and `tsc --noEmit`
   (cheap gates; their absence let a syntactically broken branch sit green for
   a month).
6. **Manual matrix:** Google with two real accounts (add/alias/switch/
   disconnect + cross-account 403/404 isolation); Outlook, LinkedIn, Notion,
   HubSpot, Slack against real accounts; two-account Gmail listener test
   (event fires from the non-primary account, reply goes out from that
   account); live conversational test ("my school calendar" routes correctly;
   destructive ambiguity triggers a question).

---

## 12. Delivery plan

Branch `feature/integrations-v2` off `V1.4.2`. Old and new systems coexist
behind the current `service.py` facade until cut-over; non-scoped
integrations stay on the old path indefinitely.

1. **PR 1 — Package skeleton + accounts core:** `contracts.py`, `core/*`
   (AccountSet incl. `listen` field, storage, registry, oauth engine),
   conformance suite, isolation gate. No user-visible change. (~1.5 days)
2. **PR 2 — Providers:** the 10 providers implemented against `Provider`
   (client code largely portable from the existing integrations), OAuth
   chooser params, GUIDANCE.md files, legacy sentinel upgrades, HubSpot
   logout unification. Manual OAuth verification per provider lands here.
   (~2 days + verification — the long pole)
3. **PR 3 — CraftBot adapter + prompts:** generated actions replace the 10
   hand-written action files, `_helpers` routing through `execute()`,
   guidance/essentials rewiring, routing-prompt + AGENT.md updates, adapter
   test. (~1 day)
4. **PR 4 — Frontend:** Manage modal (request-correlated batched saves incl.
   listen toggles), type plumbing. (~1 day)
5. **PR 5 — Listener fan-out:** `ListenerManager`, Gmail/Outlook/Slack
   listener ports to per-account instances, cursor migration, trigger
   account-context in the adapter, failure isolation. (~1.5–2 days)
6. **PR 6 (later) — MCP host:** expose the system as an MCP server.

Note the ordering: PRs 1–4 ship multi-account with listeners still effectively
primary-only (the `listen` flag exists but the manager isn't live); PR 5 turns
fan-out on. Each PR leaves the app fully working.

---

## 13. Why composition + the AccountSet model reinforce each other

- Account selection implemented **once** in `execute()` — not 290 times in
  action files. The old PR's worst bug (destructive actions missing the
  `account` param and silently hitting primary) is impossible by construction.
- Multi-account — outbound *and* inbound — arrives for **every current and
  future provider** the moment it implements `Provider`; listeners need only
  `make_listener`, and fan-out/stagger/failure-isolation come from the
  manager.
- A different agent embeds `IntegrationSystem(store, oauth, sink)` — or
  speaks MCP to it — and gets integrations, multi-account, aliases, listeners,
  and guidance without any CraftBot code.

## 14. Pitfalls checklist (from the abandoned PR's review — each has a regression test)

- filename-collision credential overwrites → *no per-account filenames*
- non-atomic multi-file promote/remove losing tokens → *single-document atomic writes*
- alias shadowing a real identity; duplicate aliases → *§4 rules 2–3 + set-time uniqueness*
- stale cached clients after alias/primary changes → *§5 invalidation*
- cache keyed by raw hint → duplicate clients → *resolve-first caching*
- resolution errors escaping as tracebacks (incl. non-string hints) → *adapter error mapping*
- partial `account` coverage on destructive actions → *central injection + adapter test*
- missing (Outlook) or fictitious (LinkedIn) OAuth chooser params → *§7 + conformance suite*
- identity-less legacy credentials duplicating on re-auth → *`"legacy"` sentinel*
- corrupt store read as "no accounts" → *quarantine + loud log*
- substring keyword false-positives ("doctor", "hard drive") → *word-boundary matching*
- secondary accounts silently never triggering (undocumented primary-only
  listeners) → *fan-out by default + visible listen toggle*
- UI: wall-clock save timers, broadcast-opened modals, staged edits surviving
  close or wiped before results, unqueued sends dropping input → *§10*
- no compile/import CI → *§11.5 gates*

## 15. Decisions (resolved 2026-08-10)

1. **Listeners: build fan-out now** — per-account listener instances with
   `listen` toggle, `ListenerManager`, account-tagged triggers (§8; PR 5).
2. **HubSpot last-logout: unified** on plain disconnect; PR 2 verifies cache
   invalidation covers what the platform-stop was masking.
3. **Disconnect: local-delete only** (today's semantics). Provider-side
   revocation deferred until Google-family-aware revoke logic exists.
4. **Packaging: in-tree** with the CI isolation gate; extract to a separate
   distribution when a second consumer (MCP host / another agent) exists.
