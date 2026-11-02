# Included Kanban Board

New CraftBot installations include the existing Kanban Board as a normal
installed Agent App. It appears in Agent Apps, with auto-launch enabled.
CraftBot's usual startup launches it; the starting screen does not change.
There is no first-run wizard, generated app, build mission, or automatic
approval of agent triggers. Existing installations do not acquire a board
when they upgrade or repair.

## Installation

`install.py` captures whether this is a fresh installation before saving
configuration. The legacy frozen installer does the same before extracting
its payload. Both use `app.provision.default_agent_app`, through the shared
provisioning pipeline. The native launcher already delegates to `install.py`.

Existing installation metadata, a workspace (even one with no Agent Apps),
settings in a separate runtime directory, or the source install's `config.json`
exclude an existing installation. A checkout's tracked `settings.json` is a
shipped default and does not count as a previous installation. This deliberately
errs toward leaving existing users alone.

A fresh installation writes `.default-agent-app.json` under `STATE_ROOT`
with status `pending`. The install stage runs under the provisioned service
Python, using the installed code tree and the explicit state root. It checks
the bundled archive's SHA-256 and calls `AgentAppManager.import_project_source`.
The normal importer owns extraction, placeholder substitution, identity, port,
kit synchronization, delivered registration, and persistence. The stage neither
launches a server nor queues an agent run.

Completion records the project ID with status `installed`. A retry after
registration reuses the `marketplaceAppId: kanban-board` project rather than
importing another one. Pending installation survives failures in later install
attempts. A completed receipt remains authoritative if the user deletes Kanban;
repair must not restore it or change the user's auto-launch preference.

Normal startup uses the existing `auto_launch_projects` flow. There is no new
startup hook, WebSocket message, UI page, or process manager. Code and user
data stay separate: the runner's tools come from `CODE_ROOT/agent-app` and
the installed board lives under `STATE_ROOT/agent_file_system/workspace`.

## Bundled source

`app/data/default_agent_app/kanban-board.zip` contains the published app's
source, lockfile, hooks, migrations, operations, guidance, and upstream license.
It excludes databases, credentials, dependencies, and machine lifecycle state.
`source.json` records its upstream repository, full revision, and archive hash.
The only manifest addition is the existing marketplace provenance marker.

To deliberately refresh the included version, update `REVISION` in
`scripts/bundle_default_agent_app.py` and run:

```powershell
python scripts/bundle_default_agent_app.py
```

Review and test the resulting bundle and provenance together. Bundling is a
maintainer operation; users do not download marketplace source during install.
Node, npm dependencies, and PocketBase retain their usual runtime requirements;
including app source does not make a full CraftBot installation offline.
The source packager requires both bundle files to be present in its payload.
An updated bundle affects future new installations, not existing user boards.

## Verification

```powershell
python -m pytest tests/test_default_agent_app.py tests/test_marketplace_source.py tests/test_agent_app_launch_lock.py tests/test_agent_app_undeployed.py tests/test_craftbot_service.py -q
```

Tests cover eligibility, retries, deletion, interpreter/state isolation,
read-only diagnosis, bundle integrity and contents, normal importer persistence,
and tools resolution with separate code and state roots. Before shipping a
changed bundle, use disposable `CRAFTBOT_HOME` state to run the installation
stage and normal auto-launch; check the health endpoint, built frontend and
starter board/columns, then stop the project. Never use an existing user's
state for this check.
