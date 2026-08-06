/// <reference path="../pb_data/types.d.ts" />
/**
 * SYSTEM HOOKS — managed by tooling, never edited by agents (spec P1).
 * Trigger plane (spec TRIGGERS-PLAN): the app fires the agent.
 *
 *   onBootstrap   ensure the `agent_requests` queue collection exists —
 *                 hook-created, NOT a migration, so adapter-sync delivers the
 *                 whole plane to every already-installed app
 *   routerUse     fire guard: declared name, param validation, cooldown,
 *                 hourly cap, status state machine (see _triggers_lib.js)
 *
 * IMPORTANT: hook callbacks run in isolated VMs that CANNOT see this file's
 * scope — every callback reaches shared logic through require(). Keep the
 * bodies below trivial.
 */

onBootstrap((e) => {
  e.next();
  try {
    try {
      $app.findCollectionByNameOrId('agent_requests');
      return; // already provisioned
    } catch {
      /* missing — create it */
    }

    // Match the app's own access mode: the frontend must be able to fire and
    // render results. Deletes are locked for everyone (superuser only) — the
    // queue is the audit trail, and the guard 403s DELETE before PocketBase.
    let authRule = '';
    try {
      const manifest = JSON.parse(
        toString($os.readFile($filepath.join(__hooks, '..', '..', 'manifest.json')))
      );
      if (String(manifest.authMode || 'none') === 'multi-user') {
        authRule = '@request.auth.id != ""';
      }
    } catch {
      authRule = '';
    }

    const collection = new Collection({
      type: 'base',
      name: 'agent_requests',
      listRule: authRule,
      viewRule: authRule,
      createRule: authRule,
      updateRule: authRule,
      deleteRule: null,
      fields: [
        { name: 'trigger', type: 'text', required: true, max: 64 },
        { name: 'params', type: 'json' },
        {
          name: 'status',
          type: 'select',
          required: true,
          maxSelect: 1,
          values: ['pending', 'claimed', 'done', 'rejected'],
        },
        {
          name: 'fired_by',
          type: 'select',
          required: true,
          maxSelect: 1,
          values: ['ui', 'hook', 'cli'],
        },
        { name: 'claimed_by', type: 'text', max: 120 },
        { name: 'result', type: 'text', max: 10000 },
        { name: 'error', type: 'text', max: 2000 },
        { name: 'created', type: 'autodate', onCreate: true },
        { name: 'updated', type: 'autodate', onCreate: true, onUpdate: true },
      ],
    });
    $app.save(collection);
    console.log('[triggers] agent_requests collection provisioned');
  } catch (err) {
    // Never block boot: an app without the queue still serves; fires fail
    // with PocketBase's own "missing collection" answer until the next boot.
    console.log('[triggers] could not provision agent_requests: ' + err);
  }
});

routerUse((e) => {
  const trig = require(`${__hooks}/_triggers_lib.js`);
  return trig.guardTriggerRequest(e);
});

// Cooldown bookkeeping on rows that actually LANDED — recording in the guard
// would burn the cooldown on fires PocketBase goes on to reject, and this
// hook also covers programmatic saves (fire() from ops handlers), which never
// pass through router middleware at all.
//
// The same hook NUDGES the CraftBot host (fire-and-forget, no-op standalone):
// the queue stays the agent-agnostic source of truth — any agent can poll or
// subscribe — the nudge only buys the resident agent latency. The payload is
// name + row id ONLY; the instruction is read from triggers.json on the host
// side, so nothing here can steer the agent beyond the build-time manifest.
onRecordAfterCreateSuccess((e) => {
  try {
    const trig = require(`${__hooks}/_triggers_lib.js`);
    trig.recordFire(String(e.record.get('trigger')));
  } catch (err) {
    console.log('[triggers] cooldown bookkeeping failed: ' + err);
  }
  try {
    const bridge = $os.getenv('CRAFTBOT_BRIDGE_URL');
    const token = $os.getenv('CRAFTBOT_BRIDGE_TOKEN');
    if (bridge && token) {
      $http.send({
        url: bridge + '/api/bridge/agent_request',
        method: 'POST',
        body: JSON.stringify({
          request_id: String(e.record.id),
          trigger: String(e.record.get('trigger')),
        }),
        headers: {
          'content-type': 'application/json',
          authorization: 'Bearer ' + token,
        },
        timeout: 8,
      });
    }
  } catch (err) {
    // A refused or unreachable host must never break the fire: the row is
    // pending either way, and polling agents (or the CLI) still see it.
    console.log('[triggers] host nudge failed: ' + err);
  }
  e.next();
}, 'agent_requests');
