/// <reference path="../pb_data/types.d.ts" />
/**
 * AGENT HOOKS — custom verbs beyond CRUD live here (spec B3/D4).
 * Every route here must have a matching entry in operations.json (the gate
 * enforces it) so any agent can discover it via GET /api/_ops.
 */

// READING A REQUEST BODY — the ONLY correct way in PB hooks:
//   const data = e.requestInfo().body;   // pre-parsed object
// NEVER use e.request.body / toString(e.request.body): that is a Go stream
// and reads as EMPTY, so your param checks will 400 on every request.

// items.clear-done — working example op: bulk-delete completed items.
routerAdd('POST', '/api/ops/items/clear-done', (e) => {
  const records = e.app.findRecordsByFilter('items', 'done = true', '', 0, 0);
  for (const record of records) {
    e.app.delete(record);
  }
  return e.json(200, { cleared: records.length });
});
