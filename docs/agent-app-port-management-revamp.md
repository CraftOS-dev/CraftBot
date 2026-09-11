# Agent App Port & Instance Management Revamp — Design

Status: IMPLEMENTED (2026-09-10). Core module `app/agent_app/instances.py`
(`PortAllocator`, `Instance`, `InstanceRegistry`) plus full rewiring of the
shadow lifecycle, probe pool, browser-probe stamp, staging-record consumers,
manager live launch/stop/delete/watchdog, and startup reconciliation.
Author: CraftBot
Scope chosen by user: full revamp; identity = stable instance id + token; keep the two port ranges.

Follow-up (2026-09-10): the custom `browser_probe` action and the `ProbePool`
were RETIRED shortly after this revamp in favour of Playwright MCP (see
agent-app-pipeline-issues.md). References to them below are historical — the
probe-pool wiring described here (drop-by-instance-id, the `probed_at` stamp,
`by_port`) has been removed. The port allocator + instance registry (the core
of this document) are unaffected and remain in force.

Implementation note (diverged from the first draft, for the better): startup
reconciliation kills leftovers ONLY on ports the system OWNS — every project's
sticky live port plus every port a prior registry instance claimed — across
BOTH ranges. Ownership is structural (our port ranges and our own persisted
records), so there is NO process-command-line/string matching to decide "is
this ours", and a foreign process on a port we never claimed is never touched.

---

## 1. Why

Port handling for Agent App is spread across three subsystems that do not share
state, and identity is repeatedly inferred from a bare port number. That
coupling is the direct cause of the 2026-09-10 deadlock (a probe stamped
`probed_at` onto the wrong project because two projects both held a staging
record claiming port 3900) and a family of related leaks and mis-kills.

The fix is not another patch. Identity must stop being "the port," ports must
be allocated under one discipline, and there must be one source of truth for
"what is running."

---

## 2. Root causes (from the investigation)

| # | Problem | Where |
|---|---------|-------|
| R1 | Identity-by-port: probe stamps first project whose record matches the port, then `break`s | `browser_probe.py:104-112` |
| R2 | Probe pool keyed by bare port (`Dict[int,_Session]`); reused port serves a stale warm page | `probe_pool.py:75,139-160` |
| R3 | Kill-by-port with no ownership check (orphan killer, stop, adopt, watchdog restart) | `manager.py:2386-2406, 4404-4406, 3598-3599` |
| R4 | Liveness = "is something on my port", not "is my process alive" | `manager.py:4153-4161` |
| R5 | Shadow allocator has no reservation set and a TOCTOU gap (`_free_port` closes its probe socket before PocketBase binds) | `provisioner.py:239-248` |
| R6 | Shadow ports are never tracked or released; "release" = process death, unverified | provisioner (whole) |
| R7 | Stale staging records linger (5-month-old `_staging/project` record still claimed 3900) and are matched by port | sidecar `host.json`, `browser_probe.py` |
| R8 | `delete_project` while a shadow runs leaks the shadow process; startup killer only scans 3100-3199 | `manager.py:4416-4523, 2388-2397` |
| R9 | Reap-by-stored-pid => PID-reuse mis-kill after OS restart | `provisioner.py:203,250-265` |
| R10 | Staging records cleared at boot BEFORE confirming the pid died => silent 3900 orphan | `manager.py:2431-2432` |
| R11 | Vestigial `backend_port` still allocated + persisted; marketplace burns 2 ports/app | `manager.py:3685-3686,4624-4637` |
| R12 | External `internal_port` drawn from live pool, not persisted => invisible survivors | `manager.py:196,1470` |
| R13 | `open_dev`/shadow boot takes no per-project lock => same-project double-boot drops a pid (leak); cross-project shadow alloc races | `lifecycle.py:51-148` |
| R14 | Two independent shadow-routing stores must agree: `.lui/shadow.json` (CLI) vs staging-record url (HTTP action) | `provisioner.py:128-144`, `agent_app_actions.py:2040-2048` |
| R15 | Dead state `_next_port` never used; misleading | `manager.py:249` |
| R16 | `taskkill /F` without `/T` in one killer, `/T` in another => orphaned child trees | `manager.py:1157` vs `2354` |

One thing already correct and worth copying: shadow -> real-project aliasing is
done by a random **bridge token**, not by port (`lifecycle.py:112-122` ->
`validate_bridge_token` `manager.py:4336` -> `integration_bridge.py:669`). The
revamp makes the token/id the identity everywhere.

---

## 3. Design principles

1. **Identity is an instance id, never a port.** Every kill, route, probe,
   stamp, and liveness check resolves an *instance* first, then acts on that
   instance's own port/pid. A port collision becomes harmless.
2. **One allocator, one lock, two ranges, reserve-before-return.** Shadow gets
   the same reservation discipline live already has. No TOCTOU.
3. **One registry is the single source of truth for running instances.** It is
   reconciled against the OS at startup (a pid counts as alive only if it is
   alive AND actually owns the recorded port).
4. **Ownership-verified teardown.** Never "kill whatever is on this port."
   Resolve the instance, confirm the port's listener pid equals the instance's
   pid, then kill that pid tree.
5. **One routing truth.** The instance registry is the only place that answers
   "where does traffic for project X go right now" (live url or shadow url).
   `.lui/shadow.json` and the HTTP-action redirect both derive from it.
6. **No migration shims.** Per the project rule, on this schema change the new
   code is the standard: at first startup we reconcile against the OS, kill
   real orphans, and discard old staging/`_staging` records. Live `project.port`
   stays persisted (it is the app's stable address); everything ephemeral is
   rebuilt.

---

## 4. New data model

### 4.1 Instance
One running server process (live OR shadow).

```
@dataclass
class Instance:
    instance_id: str        # unique per boot, e.g. secrets.token_hex(8); THE identity
    project_id: str         # owner
    role: str               # "live" | "shadow"
    port: int               # allocated from the role's range
    pid: Optional[int]      # None until the process is adopted
    token: str              # bridge token (shadow inherits the live project's)
    boot_id: str            # per-boot dir id (shadow); "" for live
    dir: str                # state dir (shadow per-boot; live = project dir)
    public_dir: str
    created_at: float
    # per-boot flags that used to be lost on re-record:
    probed_at: Optional[float] = None
    @property
    def url(self) -> str: return f"http://127.0.0.1:{self.port}"
```

`instance_id` is the key. `port` is an attribute of an instance, not a lookup
key for identity.

### 4.2 PortAllocator (unified, two ranges, atomic)
Replaces the split `_used_ports`/`_allocate_port` (live) and `_free_port`
(shadow) with one object holding one lock and two range definitions.

```
LIVE_RANGE   = (3100, 3199)
SHADOW_RANGE = (3900, 3999)

class PortAllocator:
    _reserved: set[int]         # BOTH ranges, single set
    _lock: asyncio.Lock

    async def reserve(self, role) -> int:
        async with self._lock:
            lo, hi = self._range(role)
            for p in range(lo, hi+1):
                if p in self._reserved: continue
                if not self._bindable(p): continue     # connect_ex + bind probe
                self._reserved.add(p)                  # reserve BEFORE returning
                return p
            raise PortPoolExhausted(role)

    def release(self, port): self._reserved.discard(port)
    def reserve_known(self, port): self._reserved.add(port)   # for load/reconcile
```

Key differences from today:
- Shadow allocation now reserves before returning (closes R5).
- One lock covers both ranges, so concurrent boots (even across projects) cannot
  hand out the same port (closes the cross-project race in R13).
- `reserve_known` lets startup rebuild reservations from the registry + persisted
  live ports.

### 4.3 InstanceRegistry (single source of truth)
Owns all `Instance` objects; the only place that answers routing/liveness.

```
class InstanceRegistry:
    _by_id:     Dict[str, Instance]
    _by_project_role: Dict[(project_id, role), instance_id]   # at most one each
    _by_port:   Dict[int, instance_id]        # reverse lookup ONLY, never identity

    def upsert(inst): ...
    def get(instance_id) -> Instance | None
    def live(project_id) -> Instance | None
    def shadow(project_id) -> Instance | None
    def route(project_id) -> Instance | None   # shadow if present else live
    def remove(instance_id): ...               # also releases the port
```

Persistence: a single `agent_app_instances.json` at the workspace root listing
every live + shadow instance (id, project, role, port, pid, boot_id, token,
probed_at). This replaces:
- the per-project `staging` key in `.factory/host.json` (shadow), and
- the implicit "project.process + project.port + _used_ports" live tracking.

Why one file instead of per-project sidecars: startup reconciliation and orphan
reaping become a single pass over one list, and duplicate-port detection is
trivial. The per-project `.factory/host.json` keeps its non-instance data
(delivered_at, backups, arc pointers).

### 4.4 What stays persisted vs ephemeral
- Persisted and authoritative: `project.port` (live address of the app; user
  facing) and the instance registry file.
- Ephemeral, rebuilt at startup: port reservations, pids, shadow instances,
  `.lui/shadow.json`, HTTP redirect targets. All derived from the registry after
  reconciliation.
- Removed: `backend_port` (R11), `_next_port` (R15). External `internal_port`
  becomes a real shadow-style instance with an id and gets tracked (R12).

---

## 5. Rewriting every identity-by-port site

| Site | Today | After |
|------|-------|-------|
| `browser_probe` probed_at stamp | scan projects, first port match, `break` | resolve the instance by `project_path` -> project_id -> `registry.shadow(project_id)`; assert its port == probed port; set `probed_at` on THAT instance (R1, R7) |
| `probe_pool` sessions | `Dict[int,_Session]` keyed by port | keyed by `instance_id` (or `boot_id`); `drop(instance_id)`; a reused port with a new instance id is a new session (R2) |
| orphan killer (startup) | kill any pid on a tracked live port | for each registry instance: verify pid alive AND owns its port; kill by pid-tree only if it is a known-stale instance; scan BOTH ranges (R3, R8, R10) |
| watchdog liveness | `is_port_in_use(project.port)` | `registry.live(project_id)` pid alive AND owns port (R4) |
| stop / adopt / relaunch kill | `_kill_process_on_port(port)` | resolve instance, kill its pid-tree (`/F /T`), then release its port (R3, R16) |
| shadow teardown drop | `probe_pool.drop(record["port"])` | `probe_pool.drop(instance_id)` (R2) |
| CLI route / HTTP redirect | `.lui/shadow.json` + staging url, written separately | both derived from `registry.route(project_id)`; `.lui/shadow.json` written from the shadow instance and removed when the shadow instance is removed (R14) |
| http_request SSRF allowlist | port-set membership | membership set built from `registry` live ports (unchanged semantics, single source) |

The bridge-token path (`validate_bridge_token`) is kept as-is; the instance
simply carries the same token it already inherits.

---

## 6. Lifecycle flows (port + instance actions)

Legend: A=allocate, B=bind, R=register instance, X=release, K=kill.

- **Build / create** (`create_project`): A live port, persist `project.port`.
  No instance yet (nothing bound). On scaffold failure, X the port.
- **Import (zip/folder/git/marketplace)**: A a fresh live port, rewrite the
  manifest port, persist. Discard donor ports. No dual `backend_port`.
- **notify_ready (boot shadow)** (`open_dev`): take the per-project launch lock
  (closes R13). A shadow port via the unified allocator. Create a shadow
  Instance (id, token=live token, pid=None) and `registry.upsert` BEFORE boot.
  Write `.lui/shadow.json` from the instance. B PocketBase. On success set pid,
  upsert again (same instance_id, so `probed_at` is preserved across the second
  write, closing the per-boot-flag loss). On failure, remove the instance and X
  the port.
- **use (live serving)**: the iframe always loads `registry.live(project).url`.
  Shadow is never shown in the UI (unchanged). Agent/CLI/HTTP traffic routes via
  `registry.route(project)` (shadow if present, else live).
- **walk_verify + promote**: verify against `registry.shadow(project).url`; the
  probe-first gate checks `probed_at` on that shadow instance. On pass, boot the
  live instance (A/B/R live), then remove the shadow instance (K its pid-tree, X
  its port, delete `.lui/shadow.json`). On promote failure, keep the shadow
  instance (unchanged policy) but it is now a first-class registry entry, so it
  cannot become an untracked orphan.
- **stop**: resolve the live instance, K its pid-tree, remove instance. Keep
  `project.port` reserved (project keeps its address across stop/start), or
  release it and re-reserve on next launch (see Open Question OQ1).
- **delete**: stop first (removes live instance), ALSO remove any shadow
  instance (K its pid, X its shadow port, delete shadow dir + `.lui/shadow.json`)
  BEFORE `rmtree`. Closes R8 (no more leaked shadow on delete).
- **modify / evolve**: same as notify_ready + verify + promote; each boot is a
  new shadow instance id, DB rebuilt from migrations (unchanged).

---

## 7. Startup reconciliation (reaper redesign)

Replaces "kill tracked-port pids + clear all staging records" with a
registry-driven, ownership-verified pass:

1. Load `project.port` for every project; `allocator.reserve_known(port)`.
2. Load `agent_app_instances.json`. For each recorded instance:
   - Determine the pid actually LISTENING on `instance.port` (one netstat/lsof).
   - If that pid == `instance.pid` and the process command looks like ours:
     - live role and project.auto_launch: keep/adopt (or plan a clean relaunch).
     - shadow role: it should not be alive at boot; kill the pid-tree, X the
       port, drop the instance. (Verified kill, closes R9/R10.)
   - If the port's pid != `instance.pid`: the recorded process is gone; do NOT
     kill the current holder (it is someone else). Drop the stale instance,
     leave the port to normal allocation.
3. Scan BOTH ranges (3100-3199 and 3900-3999) for LISTENERS that match no
   registry instance and whose command matches our server signature: these are
   true orphans from an unclean shutdown; kill the pid-tree. (Closes R8: shadow
   orphans are now covered.) Non-matching processes are never touched.
4. Discard any legacy per-project `staging` keys and `_staging/project` dirs
   (no shims). Their processes, if any, are caught by step 3's signature scan.
5. Rewrite `agent_app_instances.json` from the reconciled set.

Ownership signature: match on the process command line containing the project
dir / boot dir / an env marker we already inject (`CRAFTBOT_APP_ENV`,
`CRAFTBOT_APP_PORT`, `runner.py:466,477-478`). This is what makes "kill by
signature" safe instead of "kill whatever holds the port."

---

## 8. Probe pool redesign

- Key sessions by `instance_id` (or `boot_id`), not port: `Dict[str,_Session]`.
- `probe(instance)` uses `instance.url` for navigation but caches under
  `instance_id`, so a reused port with a new boot never serves a stale page (R2).
- `drop(instance_id)` on teardown. `kill()`/`promote`/`stop` drop by id.
- Optional hardening: the session records the `boot_id` it was spawned for and
  refuses to serve if the registry's current instance on that project has a
  different `boot_id`.

---

## 9. CLI + HTTP routing unification

Both routing consumers derive from `registry.route(project_id)`:
- HTTP action redirect (`agent_app_actions.py:2035-2095`): read the shadow/live
  instance url from the registry instead of the sidecar staging key.
- `.lui/shadow.json`: still written (the CLI is a separate process and reads a
  file), but it is written from the shadow instance at boot and deleted the
  moment the shadow instance is removed (promote, stop, delete). Because both the
  file and the HTTP redirect now come from one registry event, they cannot
  desync (R14). If the shadow instance is gone, there is no `shadow.json`.

Also rewrite the live manifest `port` whenever `project.port` changes so the
CLI's live fallback cannot go stale (R14/Q5).

---

## 10. Removals

- `backend_port`: stop allocating/persisting; `_serving_port` becomes just
  `project.port`. Migrating installs: ignore any persisted `backendPort`
  (discard, no shim). Frees ~1 port/app; marketplace stops burning 2 (R11).
- `_next_port`: delete (R15).
- Legacy `_staging/project` handling: discard dirs/records at startup; remove
  the port-scan matching that relied on them (R7).
- Unify `taskkill` to `/F /T` (pid-tree) everywhere (R16).

---

## 11. Edge-case coverage matrix

| Edge case | Handled by |
|-----------|-----------|
| Two projects both assigned 3900 sequentially | id identity: routing/stamp/kill act on the instance, not the port |
| Two shadow boots race for a port | unified allocator lock + reserve-before-return |
| Same-project double `open_dev` | per-project launch lock on open_dev |
| Stale 5-month record claims a live port | startup reconciliation drops non-owning records; no port-scan identity |
| Zombie holds a port (Windows lock) | allocator skips it; signature scan kills only our orphans; never blind-kills the holder |
| PID reuse after OS restart | kill only when port's listener pid == recorded pid AND signature matches |
| delete while shadow up | delete removes the shadow instance (kill+release) before rmtree |
| Promote fails | shadow instance retained as a registry entry (not an untracked orphan) |
| Boot fails after first record | instance removed + port released on failure; no `pid:None` ghost advertising a url |
| External internal port survivor | internal port is a tracked instance; reconciled/killed like any other |
| Pool exhaustion | one `PortPoolExhausted` type; all allocation call sites catch and surface a clean error; reconciliation reclaims leaked ports first |
| CLI vs HTTP route desync | both derive from one registry; shadow.json exists iff shadow instance exists |
| iframe refresh vs port change | live port is sticky across promote; if it ever changes, a fresh `agent_app_ready` (new readyAt) re-navigates; manifest rewritten |

---

## 12. Migration (no shims)

Per the repo rule (no fallback/migration code): the new code is the standard.
- First boot after deploy: `agent_app_instances.json` does not exist yet ->
  treated as empty. Reconciliation (Section 7) scans the OS, kills our orphans
  by signature, discards legacy `staging`/`_staging` records, and writes a fresh
  registry. Live apps auto-launch as usual and register live instances.
- `project.port` is preserved (persisted). `backendPort` in old JSON is ignored.
- No conversion function is written; stale state is discarded and reseeded.

---

## 13. Testing plan

Unit/behavioral (extend the existing `test_phase*.py` / `test_data_safety.py`
harness style):
- Allocator: reserve-before-return, no duplicate across concurrent reserves,
  exhaustion raises, release re-hands the lowest port.
- Registry: route() returns shadow-then-live; remove() releases the port;
  duplicate (project,role) impossible.
- Identity: probe stamps the correct instance when two instances share a port
  (the exact 2026-09-10 scenario as a regression test).
- Teardown: kill only when pid owns the port; PID-reuse simulation does not
  mis-kill.
- Lifecycle: build/import/notify_ready/promote/stop/delete/evolve each leave the
  registry and reservations consistent (no leaked ports, no orphan instances).
- Startup reconciliation: stale record + live orphan on a shadow port ->
  orphan killed, registry clean, no false kill of an unrelated process.

Live smoke: rerun the brainstorm_graph flow end to end (build -> modify ->
probe -> walk_verify -> promote) and confirm no deadlock.

---

## 14. Phased rollout

1. Introduce `PortAllocator` + `Instance` + `InstanceRegistry` (new module),
   fully unit-tested, not yet wired.
2. Route shadow boot (`open_dev`) and `browser_probe` stamping through the
   registry (fixes the reported bug first, behind the new model).
3. Move probe_pool to id keying.
4. Move live launch/stop/delete/watchdog/orphan-killer onto the registry;
   remove `_used_ports`/`_next_port`/staging sidecar key.
5. Unify routing (HTTP redirect + shadow.json) and remove `backend_port`.
6. Startup reconciliation replaces the old reaper.
7. Delete dead code and legacy `_staging` handling.

Each phase is independently shippable and testable; phase 2 alone closes the
production deadlock.

---

## Open questions

- OQ1: On `stop`, keep the live port reserved (sticky address, current behavior)
  or release and re-reserve on next launch? Sticky is simpler for the UI/CLI
  fallback and tunnels; recommend keep sticky.
- OQ2: Single registry file vs keeping per-project sidecar entries keyed by
  instance_id. Recommend single file for O(1) startup reconciliation; the
  per-project `.factory/host.json` keeps non-instance data.
- OQ3: Instance id scheme: random `token_hex(8)` (opaque) vs
  `f"{role}-{project}-{boot_seq}"` (debuggable). Recommend the readable form for
  logs, with uniqueness guaranteed by boot_seq.
