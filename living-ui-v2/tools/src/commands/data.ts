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

// Reserved flags that control the query/body, never treated as record fields.
const CONTROL_FLAGS = new Set(['json', 'filter', 'sort', 'limit']);

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
 *  A flag with no following value (or followed by another flag) becomes true. */
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
      out[key] = true; // bare flag
    } else {
      out[key] = coerceScalar(next);
      i++;
    }
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
  const base = `/api/collections/${collection}/records`;
  const body = buildBody(args);

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
      res = await request(project, 'POST', base, body);
      break;
    case 'update':
      if (id === undefined) return usageError('update needs an <id>');
      if (body === undefined)
        return usageError("update needs fields (e.g. --status \"…\") or --json '{...}'");
      res = await request(project, 'PATCH', `${base}/${id}`, body);
      break;
    case 'delete':
      if (id === undefined) return usageError('delete needs an id');
      res = await request(project, 'DELETE', `${base}/${id}`);
      break;
    default:
      return usageError(`unknown verb "${verb}"`);
  }
  log.raw(res.body || `(HTTP ${res.status}${res.status < 300 ? ', ok' : ''})`);
  return res.status < 300 ? 0 : 1;

  function usageError(msg: string): number {
    log.error(msg);
    return 1;
  }
}
