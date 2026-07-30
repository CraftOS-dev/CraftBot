/**
 * lui data <project-dir> <collection> [list|get <id>|create|update <id>|delete <id>]
 *          [--field value ...] [--json '{...}'] [--filter '...'] [--sort '...'] [--limit N]
 *
 * Generic collection access against the RUNNING app (superuser-authed when
 * the project has a .superuser file).
 *
 * Write bodies: prefer per-field flags — `create --title "Buy milk" --done false`
 * or `update <id> --status "In Progress"`. They avoid the cross-shell JSON
 * quoting that makes `--json '{...}'` fail under PowerShell/cmd. Values are
 * coerced: true/false → boolean, null → null, plain numbers → number, else
 * string. Use `--json '{...}'` only for nested/array values; when both are
 * given, per-field flags override matching keys.
 */
import { log } from '../lib/log.ts';
import { loadProject, request } from '../lib/project.ts';
import { coerceBody, describe, droppedFields, fetchSchema, suggest } from '../lib/schema.ts';

// Reserved flags that control the query/body, never treated as record fields.
const CONTROL_FLAGS = new Set(['json', 'filter', 'sort', 'limit', 'idempotency-key']);

function safeJson(text: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text) as unknown;
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function idempotencyHeaders(key: string | undefined): Record<string, string> | undefined {
  return key === undefined ? undefined : { 'Idempotency-Key': key };
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : undefined;
}

/** Coerce a CLI string into the JSON scalar it most likely represents. */
function coerceScalar(v: string): unknown {
  if (v === 'true') return true;
  if (v === 'false') return false;
  if (v === 'null') return null;
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  return v;
}

/** Collect `--field value` pairs (excluding CONTROL_FLAGS) into a body object.
 *  Every flag must carry a value — a valueless one is an error, not `true`. */
function collectFields(args: string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (let i = 0; i < args.length; i++) {
    const token = args[i];
    if (token === undefined || !token.startsWith('--')) continue;
    const key = token.slice(2);
    if (CONTROL_FLAGS.has(key)) {
      i++; // skip its value
      continue;
    }
    const next = args[i + 1];
    if (next === undefined || next.startsWith('--')) {
      // This used to become `true`, which silently stored a boolean in whatever
      // field was named — a colour field ended up holding "true". The job here
      // is to STOP that write, not to explain how it happened: a valueless flag
      // and a value eaten by shell quoting arrive byte-identically, so any
      // cause we named would be a guess. The note teaches quoting up front;
      // this just refuses.
      throw new Error(`--${key} has no value. Every flag needs one: --${key} "value".`);
    }
    out[key] = coerceScalar(next);
    i++;
  }
  return out;
}

/** Build a write body from --json (base) merged with --field flags (override). */
function buildBody(args: string[]): unknown {
  const jsonBody = flag(args, 'json');
  const fields = collectFields(args);
  if (jsonBody !== undefined) {
    return { ...(JSON.parse(jsonBody) as Record<string, unknown>), ...fields };
  }
  return Object.keys(fields).length > 0 ? fields : undefined;
}

export async function run(args: string[]): Promise<number> {
  const positional = args.filter((a, i) => !a.startsWith('--') && !(args[i - 1] ?? '').startsWith('--'));
  const [dirArg, collection, verb = 'list', id] = positional;
  if (dirArg === undefined || collection === undefined) {
    log.error(
      "Usage: lui data <project-dir> <collection> [list|get <id>|create|update <id>|delete <id>] [--field value ...] [--json '{...}'] [--filter '...'] [--sort '...'] [--limit N]",
    );
    return 1;
  }
  const project = loadProject(dirArg);
  const schema = await fetchSchema(project);

  // `data <dir> schema` — the app's data model, so an agent never has to guess
  // a collection name or a field type (the failure that motivated all of this).
  if (collection === 'schema' && !schema.has('schema')) {
    log.raw(`${project.name} — collections (field(type), * = required):\n${describe(schema)}`);
    return 0;
  }

  // PocketBase answers an unknown collection with a bare 404 that names
  // nothing. Answer it properly instead.
  if (schema.size > 0 && !schema.has(collection)) {
    const hint = suggest(collection, [...schema.keys()]);
    log.error(
      `No collection "${collection}" in ${project.name}${hint !== null ? ` — did you mean "${hint}"?` : ''}`
    );
    log.raw(`Collections (field(type), * = required):\n${describe(schema)}`);
    return 1;
  }

  // Opt-in, not automatic: the CLI does not retry internally, so a generated
  // key would protect nothing. It exists so a caller that DOES retry — an agent
  // loop, an HTTP layer — can make a write safe to repeat.
  const idempotencyKey = flag(args, 'idempotency-key');
  const base = `/api/collections/${collection}/records`;
  let body = buildBody(args) as Record<string, unknown> | undefined;

  // Coerce CLI-side: relative dates and relation labels. The app still
  // validates — this only makes a well-formed request out of human input.
  if (body !== undefined && (verb === 'create' || verb === 'update')) {
    const coerced = await coerceBody(project, schema, collection, body);
    if (coerced.errors.length > 0) {
      for (const message of coerced.errors) log.error(message);
      return 1;
    }
    body = coerced.body;
  }

  let res;
  switch (verb) {
    case 'list': {
      const qs = new URLSearchParams();
      const filter = flag(args, 'filter');
      const sort = flag(args, 'sort');
      const limit = flag(args, 'limit');
      if (filter !== undefined) qs.set('filter', filter);
      if (sort !== undefined) qs.set('sort', sort);
      if (limit !== undefined) qs.set('perPage', limit);
      res = await request(project, 'GET', qs.size ? `${base}?${qs}` : base);
      break;
    }
    case 'get':
      if (id === undefined) return usageError('get needs an id');
      res = await request(project, 'GET', `${base}/${id}`);
      break;
    case 'create':
      if (body === undefined)
        return usageError("create needs fields (e.g. --title \"…\") or --json '{...}'");
      res = await request(project, 'POST', base, body, idempotencyHeaders(idempotencyKey));
      break;
    case 'update':
      if (id === undefined) return usageError('update needs an <id>');
      if (body === undefined)
        return usageError("update needs fields (e.g. --status \"…\") or --json '{...}'");
      res = await request(project, 'PATCH', `${base}/${id}`, body, idempotencyHeaders(idempotencyKey));
      break;
    case 'delete':
      if (id === undefined) return usageError('delete needs an id');
      res = await request(project, 'DELETE', `${base}/${id}`);
      break;
    default:
      return usageError(`unknown verb "${verb}"`);
  }
  // Failure: surface the app's message plainly instead of a wall of JSON, so
  // the reason reaches the caller rather than being buried in a body.
  if (res.status >= 300) {
    const parsed = safeJson(res.body);
    log.error(String(parsed?.['message'] ?? `HTTP ${res.status}`));

    // A2APP rejections list EVERY problem, so show them all — one round trip
    // should be enough for the caller to fix everything.
    const violations = parsed?.['violations'];
    if (Array.isArray(violations) && violations.length > 1) {
      for (const v of violations.slice(1) as { field?: string; expected?: string }[]) {
        log.raw(`  also: --${v.field} expects ${v.expected}`);
      }
    } else {
      // PocketBase's own rejections keep its shape and carry no a2app marker.
      const detail = parsed?.['data'];
      if (detail !== undefined && Object.keys(detail as object).length > 0) {
        log.raw(`  fields: ${JSON.stringify(detail)}`);
      }
    }
    return 1;
  }

  log.raw(res.body || `(HTTP ${res.status}, ok)`);

  // Backstop for apps whose adapter predates the in-app write guard: if a value
  // we asked for is missing from what came back, the write did not do what was
  // asked, and that must not look like success.
  if (body !== undefined && (verb === 'create' || verb === 'update')) {
    const saved = safeJson(res.body);
    if (saved !== null) {
      const dropped = droppedFields(body, saved);
      if (dropped.length > 0) {
        log.error(
          `WRITE INCOMPLETE — the app accepted the request but did not store: ${dropped.join(', ')}. ` +
            `Do NOT report this as done.`
        );
        return 1;
      }
    }
  }
  return 0;

  function usageError(msg: string): number {
    log.error(msg);
    return 1;
  }
}
