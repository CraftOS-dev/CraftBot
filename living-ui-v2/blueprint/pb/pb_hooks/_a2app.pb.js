/// <reference path="../pb_data/types.d.ts" />
/**
 * SYSTEM HOOKS — managed by tooling, never edited by agents (spec P1).
 * A2APP Phase 1 — see spec/A2APP-PLAN.md §6 Phase 1 Track B.
 *
 *   GET /api/_a2app   identity: app id, adapter + schema version, server clock
 *   routerUse         write guard — runs BEFORE PocketBase coerces the body,
 *                     which is the only place bad values are still visible
 *   record hooks      attribution log + "did it actually land" backstop
 *
 * IMPORTANT: hook callbacks run in isolated VMs that CANNOT see this file's own
 * scope — calling a function defined here fails with "ReferenceError: <name> is
 * not defined". Every callback must reach shared logic through require().
 * Keep the bodies below trivial.
 */

routerUse((e) => {
  const a2 = require(`${__hooks}/_a2app_lib.js`);
  return a2.guardRequest(e);
});

routerAdd('GET', '/api/_a2app', (e) => {
  const a2 = require(`${__hooks}/_a2app_lib.js`);
  let manifest = {};
  try {
    manifest = JSON.parse(
      toString($os.readFile($filepath.join(__hooks, '..', '..', 'manifest.json'))),
    );
  } catch {
    manifest = {};
  }
  return e.json(200, {
    a2app: true,
    protocol: '1.0',
    adapterVersion: a2.ADAPTER_VERSION,
    app: {
      id: manifest.id || null,
      name: manifest.name || null,
      livingUIVersion: manifest.livingUIVersion || null,
      kitVersion: manifest.kitVersion || null,
    },
    schemaVersion: a2.schemaVersion(e.app),
    serverNow: a2.serverNowIso(),
    serverTzOffsetMinutes: -new Date().getTimezoneOffset(),
  });
});

/**
 * GET /api/_a2app/describe — the app's data model and verb surface, generated
 * from the LIVE schema so it cannot drift from what the app actually is.
 *
 * This is the endpoint an agent reads instead of guessing collection names or
 * reverse-engineering migrations, which is what the originating incident did
 * for three turns before giving up and reading source.
 */
routerAdd('GET', '/api/_a2app/describe', (e) => {
  const a2 = require(`${__hooks}/_a2app_lib.js`);
  const described = a2.describeApp(e.app);
  return e.json(200, {
    a2app: true,
    protocol: '1.0',
    adapterVersion: a2.ADAPTER_VERSION,
    schemaVersion: a2.schemaVersion(e.app),
    serverNow: a2.serverNowIso(),
    entities: described.entities,
    operations: described.operations,
    conventions: described.conventions,
  });
});

onRecordCreateRequest((e) => {
  const a2 = require(`${__hooks}/_a2app_lib.js`);
  return a2.guardRecord(e, 'create');
});

onRecordUpdateRequest((e) => {
  const a2 = require(`${__hooks}/_a2app_lib.js`);
  return a2.guardRecord(e, 'update');
});
