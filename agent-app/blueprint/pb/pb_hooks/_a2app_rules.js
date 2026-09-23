/**
 * A2APP validation rules — PURE. No PocketBase, no Node, no I/O, no globals.
 *
 * This module is shared verbatim by every A2APP adapter so that a PocketBase
 * app and a Django app enforce IDENTICAL rules (spec A2APP-PLAN §10b). It is
 * the reason the guard can move to the Phase 4 runtime without being rewritten.
 *
 * An adapter's only jobs are:
 *   1. map its backend's field types onto the protocol vocabulary below
 *   2. call validate() / divergences()
 *   3. render the returned violations as its transport's error
 *
 * It deliberately RETURNS violations rather than throwing: throwing requires a
 * transport-specific error class (BadRequestError in PocketBase, an HTTP
 * response in the runtime), which is exactly the coupling this file avoids.
 *
 * ── Protocol type vocabulary (spec A2APP-PLAN §5.2) ──
 *   string · number · boolean · datetime · duration · enum · ref
 *   list<enum> · list<ref> · json · binary
 *
 * ── Normalised field contract expected by validate() ──
 *   { name, type, required?, readOnly?, writeOnly?, max?, values?, target?, dayKey? }
 */

var RULES_VERSION = '1.0.0';

/* ------------------------------------------------------------------ helpers */

function isBlank(v) {
  return v === null || v === undefined || v === '';
}

/** Regex alone accepts 2026-13-45, so check the calendar too. */
function isValidYmd(y, m, d) {
  if (m < 1 || m > 12 || d < 1) return false;
  var lengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  var max = lengths[m - 1];
  if (m === 2 && y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)) max = 29;
  return d <= max;
}

function looksLikeDate(v) {
  if (typeof v !== 'string') return false;
  var m = v.match(/^(\d{4})-(\d{2})-(\d{2})([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$/);
  return !!m && isValidYmd(Number(m[1]), Number(m[2]), Number(m[3]));
}

function isDayKeyValue(v) {
  if (typeof v !== 'string') return false;
  var m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return !!m && isValidYmd(Number(m[1]), Number(m[2]), Number(m[3]));
}

/**
 * Day-keys stored as plain text to dodge timezone drift — e.g.
 * crm-system.tasks.due and habit-tracker.entries.day are `text, max 10` with
 * the comment "Day key as plain text YYYY-MM-DD".
 *
 * No type check can protect these: writing "tomorrow" stores it verbatim, the
 * field LOOKS populated, and because comparison is lexical the row is
 * permanently invisible to `due <= "2026-07-29"` ("t" > "2"). Strictly worse
 * than the empty string. Hence a name+width convention (spec D3).
 */
function isDayKeyField(field) {
  if (field.type !== 'string') return false;
  var max = field.max || 0;
  if (max <= 0 || max > 12) return false;
  return /^(due|day|date)$|_(date|day)$/i.test(field.name);
}

function fieldMap(fields) {
  var m = {};
  for (var i = 0; i < fields.length; i++) m[fields[i].name] = fields[i];
  return m;
}

function writableNames(fields) {
  var out = [];
  for (var i = 0; i < fields.length; i++) {
    if (!fields[i].readOnly) out.push(fields[i].name);
  }
  return out;
}

/* --------------------------------------------------------------- validation */

function violation(code, field, expected, got) {
  return { code: code, field: field, expected: expected, got: got === undefined ? null : got };
}

/**
 * Validate a RAW request body against normalised fields.
 *
 * IMPORTANT: the body must be raw — the values as the client sent them. Any
 * backend that coerces before validation defeats this entirely. (PocketBase
 * coerces before its record hooks run, which is why its adapter validates in
 * router middleware instead. See spec §3.15.)
 *
 * opts.allow — extra keys accepted without being fields (e.g. 'id', auth fields)
 *
 * Returns [] when the body is acceptable.
 */
function validate(fields, body, opts) {
  var options = opts || {};
  var allow = options.allow || {};
  var map = fieldMap(fields);
  var writable = writableNames(fields);
  var out = [];

  var keys = Object.keys(body);
  for (var k = 0; k < keys.length; k++) {
    var key = keys[k];
    if (allow[key]) continue;

    var field = map[key];

    // Silently dropped by most backends, and absent from the response, so the
    // caller cannot tell it was ignored.
    if (!field) {
      out.push(violation('unknown_field', key, 'one of: ' + writable.join(', '), body[key]));
      continue;
    }
    if (field.readOnly) {
      out.push(violation('read_only_field', key, 'not writable (server-managed)', body[key]));
      continue;
    }

    var value = body[key];
    // Blank means "clear this field" — a legitimate operation. Only
    // distinguishable from garbage because we see the raw value.
    if (isBlank(value)) continue;

    if (field.type === 'datetime' && !looksLikeDate(value)) {
      out.push(violation('invalid_date', key, 'an ISO 8601 date', value));
      continue;
    }
    if (field.dayKey && !isDayKeyValue(value)) {
      out.push(violation('invalid_daykey', key, 'a day key "YYYY-MM-DD"', value));
      continue;
    }
    // A boolean or number landing in a text field. Sounds unlikely; it happened
    // on the first day: the agent wrote `--color #ff6b35`, the SHELL treated
    // `#` as a comment and dropped the value, the CLI saw a bare `--color` and
    // sent `true`, and PocketBase stored the string "true" as the colour. Every
    // other type was checked, so the one unchecked type is where it landed.
    if (field.type === 'string' && typeof value !== 'string') {
      out.push(violation('invalid_string', key, 'text', value));
      continue;
    }
    if (field.type === 'number' && typeof value !== 'number') {
      if (typeof value !== 'string' || value.trim() === '' || isNaN(Number(value))) {
        out.push(violation('invalid_number', key, 'a number', value));
        continue;
      }
    }
    if (field.type === 'boolean' && typeof value !== 'boolean') {
      if (value !== 'true' && value !== 'false') {
        out.push(violation('invalid_boolean', key, 'true or false', value));
        continue;
      }
    }
    if (field.type === 'enum' && field.values && field.values.length) {
      var found = false;
      for (var v = 0; v < field.values.length; v++) {
        if (String(field.values[v]) === String(value)) found = true;
      }
      if (!found) {
        out.push(violation('invalid_enum', key, 'one of: ' + field.values.join(' | '), value));
        continue;
      }
    }
  }
  return out;
}

/**
 * Backstop: which non-blank requested values failed to land?
 *
 * `read(name)` returns the stored value for a field. Deliberately conservative
 * — only flags "asked for something, stored nothing" — so it never
 * false-positives on a legitimate false/0/"" write, nor on a backend
 * normalising 2026-07-30T00:00:00+01:00 to 2026-07-29T23:00:00Z.
 */
function divergences(fields, body, read) {
  var map = fieldMap(fields);
  var out = [];
  var keys = Object.keys(body);
  for (var i = 0; i < keys.length; i++) {
    var key = keys[i];
    var field = map[key];
    if (!field || field.readOnly) continue;
    var requested = body[key];
    if (isBlank(requested) || String(requested) === '') continue;
    var stored;
    try {
      stored = read(key);
    } catch {
      stored = null;
    }
    if (isBlank(stored) || String(stored) === '') {
      out.push({ field: key, type: field.type, stored: String(stored) });
    }
  }
  return out;
}

/* ----------------------------------------------------------------- messages */

/** One human+machine readable sentence. Adapters should not invent their own —
 *  identical rules must produce identical text on every backend.
 *  NOTE: starts with a capitalised word on purpose; PocketBase capitalises the
 *  first letter of error messages, which silently breaks prefix matching. */
function describeViolation(v, serverNow) {
  var msg =
    'Rejected by a2app (' +
    v.code +
    '): field "' +
    v.field +
    '" expects ' +
    v.expected +
    '; got ' +
    JSON.stringify(v.got);
  if (v.code === 'invalid_date' || v.code === 'invalid_daykey') {
    if (serverNow) msg += '. Example: "' + String(serverNow).slice(0, 10) + '"';
  }
  if (serverNow) msg += '. Server time is ' + serverNow;
  return msg + '.';
}

function describeIncomplete(lost) {
  var names = [];
  for (var i = 0; i < lost.length; i++) names.push(lost[i].field);
  return (
    'Rejected by a2app (write_incomplete): the database did not store ' +
    names.join(', ') +
    '. Do NOT report this as done.'
  );
}

module.exports = {
  RULES_VERSION: RULES_VERSION,
  isBlank: isBlank,
  isValidYmd: isValidYmd,
  looksLikeDate: looksLikeDate,
  isDayKeyValue: isDayKeyValue,
  isDayKeyField: isDayKeyField,
  validate: validate,
  divergences: divergences,
  describeViolation: describeViolation,
  describeIncomplete: describeIncomplete,
};
