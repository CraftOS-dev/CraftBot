/**
 * lui data <project-dir> <collection> [list|get <id>|create|update <id>|delete <id>]
 *          [--json '{...}'] [--filter '...'] [--sort '...'] [--limit N]
 * Generic collection access against the RUNNING app (superuser-authed when
 * the project has a .superuser file).
 */
import { log } from '../lib/log.ts';
import { loadProject, request } from '../lib/project.ts';

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : undefined;
}

export async function run(args: string[]): Promise<number> {
  const positional = args.filter((a, i) => !a.startsWith('--') && !(args[i - 1] ?? '').startsWith('--'));
  const [dirArg, collection, verb = 'list', id] = positional;
  if (dirArg === undefined || collection === undefined) {
    log.error(
      "Usage: lui data <project-dir> <collection> [list|get <id>|create|update <id>|delete <id>] [--json '{...}'] [--filter '...'] [--sort '...'] [--limit N]",
    );
    return 1;
  }
  const project = loadProject(dirArg);
  const base = `/api/collections/${collection}/records`;
  const jsonBody = flag(args, 'json');
  const body = jsonBody === undefined ? undefined : JSON.parse(jsonBody);

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
      if (body === undefined) return usageError("create needs --json '{...}'");
      res = await request(project, 'POST', base, body);
      break;
    case 'update':
      if (id === undefined || body === undefined) return usageError("update needs <id> and --json '{...}'");
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
