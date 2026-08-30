/**
 * lui run <project-dir> <op-name> [--param value ...]
 * Execute a declared operation against the RUNNING app (spec O2 executors).
 */
import { log } from '../lib/log.ts';
import { loadOps, loadProject, request, type Operation } from '../lib/project.ts';

function collectParams(args: string[]): Record<string, string> {
  const params: Record<string, string> = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a !== undefined && a.startsWith('--')) {
      const value = args[i + 1];
      if (value !== undefined && !value.startsWith('--')) {
        params[a.slice(2)] = value;
        i++;
      } else {
        params[a.slice(2)] = 'true';
      }
    }
  }
  return params;
}

export async function run(args: string[]): Promise<number> {
  const positional = args.filter((a, i) => !a.startsWith('--') && (i === 0 || !(args[i - 1] ?? '').startsWith('--')));
  const [dirArg, opName] = positional;
  if (dirArg === undefined || opName === undefined) {
    log.error('Usage: lui run <project-dir> <op-name> [--param value ...]');
    return 1;
  }
  const project = loadProject(dirArg);
  const op: Operation | undefined = loadOps(project).find((o) => o.name === opName);
  if (op === undefined) {
    log.error(`Unknown op "${opName}". Try: lui ops ${dirArg}`);
    return 1;
  }

  const params = collectParams(args.slice(2));
  const missing = Object.entries(op.params ?? {})
    .filter(([k, v]) => v.required === true && !(k in params))
    .map(([k]) => k);
  if (missing.length > 0) {
    log.error(`Missing required param(s): ${missing.join(', ')}`);
    return 1;
  }

  const exec = op.executor;
  if (exec.type === 'http' || exec.type === 'job') {
    const method = exec.method ?? 'POST';
    let path = exec.path ?? '';
    let body: unknown;
    if (method === 'GET' || method === 'DELETE') {
      const qs = new URLSearchParams(params).toString();
      if (qs) path += (path.includes('?') ? '&' : '?') + qs;
    } else {
      body = params;
    }
    const res = await request(project, method, path, body);
    log.raw(res.body || `(HTTP ${res.status}, empty body)`);
    return res.status >= 200 && res.status < 300 ? 0 : 1;
  }
  if (exec.type === 'crud') {
    const collection = exec.collection ?? '';
    const action = exec.action ?? 'list';
    if (action === 'list') {
      const res = await request(project, 'GET', `/api/collections/${collection}/records`);
      log.raw(res.body);
      return res.status < 300 ? 0 : 1;
    }
    log.error(`crud action "${action}" not supported via run — use: lui data ${dirArg} ${collection} ...`);
    return 1;
  }
  log.error(`Unsupported executor type: ${exec.type}`);
  return 1;
}
