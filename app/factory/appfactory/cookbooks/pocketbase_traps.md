# PocketBase 0.39 — the traps that break every guessed API (copy-adapt)
- Handlers run in ISOLATED VMs: file-level consts/functions are INVISIBLE in
  routerAdd/cronAdd callbacks. Share code via a plain .js module +
  `require(`${__hooks}/mod.js`)` INSIDE each callback.
- `res.json` is the ONLY body accessor for $http.send responses.
  `JSON.parse(String(res.body))` throws (body is a Go byte slice).
- find helpers THROW on no rows (never return null): wrap in try/catch or use
  `findRecordsByFilter(col, filter, sort, LIMIT, OFFSET)` and check .length.
  A 404 from a route you declared = your handler threw, NOT a missing route.
- Signature: findRecordsByFilter(collection, filter, SORT, LIMIT, OFFSET).
- `new Record(collectionOBJECT)` — an id string nil-panics the process.
- Migrations: `migrate(upFn, downFn)` only (no global rollback); `fields:` not
  `schema:`; NEVER edit/rename an applied migration — add a NEW file.
- `required: true` on number fields REJECTS 0 — measurements must be optional.
- No setTimeout at top level (undefined); scheduled work = cronAdd.
- Current API: e.app.save/delete/findRecordsByFilter — `$app.dao()` does not exist.
