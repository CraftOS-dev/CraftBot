/// <reference path="../pb_data/types.d.ts" />
/**
 * SYSTEM MODULE — managed by tooling, never edited by agents (spec P1).
 * Trigger plane (spec TRIGGERS-PLAN, OVERVIEW §6.2): the app fires the agent.
 *
 * Operations are verbs an AGENT calls on the app. Triggers are the reverse:
 * the app asks an agent to act, by inserting a row into the `agent_requests`
 * queue collection. A queue, not a webhook, because any agent can poll REST
 * or subscribe to PocketBase realtime, and almost none can receive a push.
 *
 * Trust model: `triggers.json` (project root, agent-authored at build time)
 * declares every trigger this app may fire. A fire carries only the trigger
 * NAME and validated PARAMS — the instruction an agent executes is read from
 * triggers.json by whoever reacts, never from the request. An undeclared
 * name or invalid params are rejected here, in-app, before any agent exists.
 *
 * Require inside handlers (isolated-VM rule — never reference file scope):
 *
 *   const trig = require(`${__hooks}/_triggers_lib.js`);
 *   trig.fire(e.app, 'restock_needed', { item_id: 42 }, 'hook');
 *
 * `fire()` exists because programmatic saves (`e.app.save()`) bypass router
 * middleware entirely — an ops handler that inserted the row directly would
 * skip every check below. It runs the same validation + cooldown, then saves.
 */

var TRIGGER_COLLECTION = 'agent_requests';
var TRIGGERS_FILE = 'triggers.json';
var REQUESTS_PATH = /^\/api\/collections\/agent_requests\/records(\/([^\/?]+))?$/;

// Floor between two fires of the same trigger; `cooldown_seconds` in the
// manifest can only RAISE it. The agent's reaction to a fire often writes
// data, which could otherwise re-fire the same trigger forever — and a buggy
// button must not machine-gun the agent.
var COOLDOWN_FLOOR_SECONDS = 10;
var MAX_FIRES_PER_HOUR = 30;

var STATUSES = ['pending', 'claimed', 'done', 'rejected'];
var FIRED_BY = ['ui', 'hook', 'cli'];
// The queue is append-only state, not app data: rows may only move forward.
var TRANSITIONS = {
  pending: { claimed: 1, rejected: 1 },
  claimed: { done: 1, rejected: 1 },
};
// Immutable after create — a claimed request whose params silently change
// under the agent is a lie in the making.
var FROZEN_FIELDS = ['trigger', 'params', 'fired_by'];

/* ---------------------------------------------------------------- manifest */

/** Load declared triggers. Missing file → {} (no triggers declared).
 *  Invalid JSON → null (fail CLOSED: a manifest we cannot read must not
 *  become "everything is allowed" or silently "nothing fires"). */
function loadTriggers() {
  var raw;
  try {
    raw = toString($os.readFile($filepath.join(__hooks, '..', '..', TRIGGERS_FILE)));
  } catch {
    return {}; // no manifest — nothing is declared
  }
  try {
    var parsed = JSON.parse(raw);
    var triggers = parsed && parsed.triggers;
    if (!triggers || typeof triggers !== 'object' || Array.isArray(triggers)) return {};
    return triggers;
  } catch {
    return null;
  }
}

/** Public shape for `describe`: name → description/params/cooldown, WITHOUT
 *  the instruction. The instruction is for whoever REACTS to a fire; serving
 *  it on a public endpoint invites imitation without adding any capability. */
function describeTriggers() {
  var declared = loadTriggers();
  if (!declared) return {};
  var out = {};
  for (var name in declared) {
    var def = declared[name] || {};
    var entry = { description: String(def.description || '') };
    if (def.params && typeof def.params === 'object') entry.params = def.params;
    if (def.cooldown_seconds) entry.cooldownSeconds = Number(def.cooldown_seconds);
    out[name] = entry;
  }
  return out;
}

/* -------------------------------------------------------- param validation */

/** Validate params against a declared spec (operations.json param shape:
 *  {type: string|number|boolean, required, default, enum, description}).
 *  Returns violations in the a2app shape. Defaults are NOT filled here —
 *  middleware cannot rewrite the request body; readers fill them (documented
 *  in the spec) so the stored row stays exactly what the app sent. */
function validateParams(spec, params) {
  var violations = [];
  spec = spec && typeof spec === 'object' ? spec : {};
  params = params && typeof params === 'object' && !Array.isArray(params) ? params : {};

  for (var sent in params) {
    if (!Object.prototype.hasOwnProperty.call(spec, sent)) {
      violations.push({
        field: sent,
        code: 'unknown_param',
        expected: 'one of: ' + (Object.keys(spec).join(', ') || '(none)'),
        got: sent,
      });
    }
  }

  for (var name in spec) {
    var p = spec[name] || {};
    var has = Object.prototype.hasOwnProperty.call(params, name);
    if (!has) {
      if (p.required && p.default === undefined) {
        violations.push({ field: name, code: 'missing_param', expected: String(p.type || 'string'), got: 'nothing' });
      }
      continue;
    }
    var value = params[name];
    var type = String(p.type || 'string');
    var ok =
      (type === 'string' && typeof value === 'string') ||
      (type === 'number' && typeof value === 'number' && isFinite(value)) ||
      (type === 'boolean' && typeof value === 'boolean');
    if (!ok) {
      violations.push({ field: name, code: 'invalid_type', expected: type, got: typeof value });
      continue;
    }
    if (Array.isArray(p.enum) && p.enum.length && p.enum.indexOf(value) < 0) {
      violations.push({ field: name, code: 'invalid_enum_value', expected: p.enum.join(' | '), got: String(value) });
    }
  }
  return violations;
}

/* ------------------------------------------------------- cooldown and caps */

/** $app.store() survives across requests in-process (same store the a2app
 *  idempotency ledger uses); lost on restart, which for a cooldown is fine. */
function cooldownState(name) {
  try {
    return $app.store().get('trig_rate:' + name) || null;
  } catch {
    return null;
  }
}

function checkRate(name, def) {
  var now = Date.now();
  var cooldownS = Math.max(COOLDOWN_FLOOR_SECONDS, Number((def && def.cooldown_seconds) || 0));
  var state = cooldownState(name) || { last: 0, windowStart: now, count: 0 };

  if (now - Number(state.last || 0) < cooldownS * 1000) {
    var retry = Math.ceil((cooldownS * 1000 - (now - Number(state.last))) / 1000);
    return { code: 'cooldown', retryAfterSeconds: retry, message: 'fired too recently — retry in ' + retry + 's' };
  }
  if (now - Number(state.windowStart || 0) > 3600 * 1000) {
    state.windowStart = now;
    state.count = 0;
  }
  if (Number(state.count || 0) >= MAX_FIRES_PER_HOUR) {
    return {
      code: 'rate_capped',
      retryAfterSeconds: Math.ceil((Number(state.windowStart) + 3600 * 1000 - now) / 1000),
      message: 'hourly cap reached (' + MAX_FIRES_PER_HOUR + ' fires/hour)',
    };
  }
  return null;
}

function recordFire(name) {
  try {
    var now = Date.now();
    var state = cooldownState(name) || { last: 0, windowStart: now, count: 0 };
    if (now - Number(state.windowStart || 0) > 3600 * 1000) {
      state.windowStart = now;
      state.count = 0;
    }
    state.last = now;
    state.count = Number(state.count || 0) + 1;
    $app.store().set('trig_rate:' + name, state);
  } catch {
    /* bookkeeping must never break a fire */
  }
}

/* ---------------------------------------------------------------- validate */

/** Full fire validation. Returns null when the fire may proceed, or an error
 *  object {status, code, message, violations?} in the a2app envelope. */
function validateFire(body) {
  var declared = loadTriggers();
  if (declared === null) {
    return { status: 400, code: 'invalid_manifest', message: 'triggers.json is not valid JSON — no trigger can fire until it is fixed.' };
  }
  var name = String((body && body.trigger) || '');
  var def = declared[name];
  if (!name || def === undefined) {
    return {
      status: 400,
      code: 'undeclared_trigger',
      message:
        "Trigger '" + name + "' is not declared in triggers.json. Declared: " +
        (Object.keys(declared).sort().join(', ') || '(none)') + '.',
    };
  }
  if (body.status !== undefined && String(body.status) !== 'pending') {
    return { status: 400, code: 'invalid_status_on_create', message: "A new request must start at status 'pending' (or omit status)." };
  }
  var firedBy = String((body && body.fired_by) || '');
  if (FIRED_BY.indexOf(firedBy) < 0) {
    return { status: 400, code: 'invalid_fired_by', message: "fired_by must be one of: " + FIRED_BY.join(', ') + '.' };
  }
  var violations = validateParams(def.params, body.params);
  if (violations.length) {
    return {
      status: 400,
      code: violations[0].code,
      message:
        "Params for trigger '" + name + "' were rejected: " +
        violations.map(function (v) { return v.field + ' (' + v.code + ', expected ' + v.expected + ')'; }).join('; ') + '.',
      violations: violations,
    };
  }
  var rate = checkRate(name, def);
  if (rate) {
    return { status: 429, code: rate.code, message: "Trigger '" + name + "' " + rate.message + '.', retryAfterSeconds: rate.retryAfterSeconds };
  }
  return null;
}

/* ------------------------------------------------------------- entry points */

function respond(e, err) {
  var payload = { a2app: true, ok: false, plane: 'triggers', code: err.code, message: 'Rejected by a2app (' + err.code + '): ' + err.message };
  if (err.violations) payload.violations = err.violations;
  if (err.retryAfterSeconds) payload.retryAfterSeconds = err.retryAfterSeconds;
  return e.json(err.status, payload);
}

/** Middleware guard for HTTP writes to the queue collection. RETURNS error
 *  responses rather than throwing — PocketBase recursively normalises the
 *  data map of thrown errors, so a machine code cannot survive a throw. */
function guardTriggerRequest(e) {
  var method, path;
  try {
    method = String(e.request.method || '').toUpperCase();
    path = String((e.request.url && e.request.url.path) || '');
  } catch {
    return e.next();
  }
  var m = path.match(REQUESTS_PATH);
  if (!m) return e.next();

  if (method === 'DELETE') {
    return respond(e, { status: 403, code: 'append_only', message: 'agent_requests rows are never deleted — the queue is the audit trail.' });
  }
  if (method !== 'POST' && method !== 'PATCH' && method !== 'PUT') return e.next();

  var body;
  try {
    body = e.requestInfo().body;
  } catch {
    return e.next(); // unparseable body — let PocketBase answer
  }
  if (!body || typeof body !== 'object' || Array.isArray(body)) return e.next();

  try {
    if (method === 'POST') {
      var err = validateFire(body);
      if (err) return respond(e, err);
      // Cooldown is recorded by the after-create-success hook, not here — a
      // fire PocketBase goes on to reject must not burn the cooldown.
      return e.next();
    }

    // PATCH/PUT: enforce the status state machine + immutability.
    var recordId = m[2] || '';
    var current = null;
    try {
      current = e.app.findRecordById(TRIGGER_COLLECTION, recordId);
    } catch {
      return e.next(); // unknown id — PocketBase's 404 is the right answer
    }
    for (var i = 0; i < FROZEN_FIELDS.length; i++) {
      var f = FROZEN_FIELDS[i];
      if (body[f] !== undefined && JSON.stringify(body[f]) !== JSON.stringify(current.get(f))) {
        return respond(e, { status: 400, code: 'immutable_field', message: "'" + f + "' cannot change after create." });
      }
    }
    if (body.status !== undefined) {
      var from = String(current.get('status') || '');
      var to = String(body.status);
      if (STATUSES.indexOf(to) < 0 || !(TRANSITIONS[from] && TRANSITIONS[from][to])) {
        return respond(e, {
          status: 400,
          code: 'invalid_transition',
          message: "status '" + from + "' → '" + to + "' is not allowed (pending→claimed|rejected, claimed→done|rejected).",
        });
      }
    }
    return e.next();
  } catch (unexpected) {
    // A guard must never take the queue down: log and let PocketBase decide.
    console.log('[triggers] guard skipped on ' + path + ': ' + (unexpected && unexpected.message));
    return e.next();
  }
}

/** Programmatic fire for backend hooks — the ONLY correct way to fire from
 *  ops handlers, because `e.app.save()` bypasses router middleware and would
 *  skip every check above. Returns {ok: true, id} or {ok: false, code,
 *  message}; never throws (business logic must degrade when a fire is
 *  refused, exactly as it must when running standalone). */
function fire(app, name, params, firedBy) {
  try {
    var body = { trigger: String(name || ''), params: params || {}, fired_by: firedBy || 'hook', status: 'pending' };
    var err = validateFire(body);
    if (err) return { ok: false, code: err.code, message: err.message };
    var collection = app.findCollectionByNameOrId(TRIGGER_COLLECTION);
    var record = new Record(collection);
    record.set('trigger', body.trigger);
    record.set('params', body.params);
    record.set('status', 'pending');
    record.set('fired_by', body.fired_by);
    app.save(record); // cooldown recorded by the after-create-success hook
    return { ok: true, id: String(record.id) };
  } catch (e2) {
    return { ok: false, code: 'fire_failed', message: String((e2 && e2.message) || e2) };
  }
}

module.exports = {
  TRIGGER_COLLECTION: TRIGGER_COLLECTION,
  loadTriggers: loadTriggers,
  describeTriggers: describeTriggers,
  validateParams: validateParams,
  validateFire: validateFire,
  guardTriggerRequest: guardTriggerRequest,
  recordFire: recordFire,
  fire: fire,
};
