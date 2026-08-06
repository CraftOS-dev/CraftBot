/**
 * lui requests <project-dir> [--status pending|claimed|done|rejected]
 *
 * Inspect the RUNNING app's agent_requests queue — trigger fires and what
 * became of them. This is the polling surface an agent WITHOUT realtime
 * uses; for a human it is the debugging view of the app→agent plane.
 */
import { log } from '../lib/log.ts';
import { loadProject, request } from '../lib/project.ts';

interface RequestRow {
  id: string;
  trigger: string;
  status: string;
  fired_by: string;
  claimed_by: string;
  result: string;
  error: string;
  created: string;
}

function age(created: string): string {
  const ms = Date.now() - new Date(created.replace(' ', 'T')).getTime();
  if (Number.isNaN(ms)) return '?';
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

export async function run(args: string[]): Promise<number> {
  const projectDir = args[0];
  if (projectDir === undefined) {
    log.error('Usage: lui requests <project-dir> [--status pending|claimed|done|rejected]');
    return 1;
  }
  const project = loadProject(projectDir);

  const statusIdx = args.indexOf('--status');
  const status = statusIdx >= 0 ? args[statusIdx + 1] : undefined;
  const filter = status !== undefined ? `&filter=(status='${status}')` : '';

  const res = await request(
    project,
    'GET',
    `/api/collections/agent_requests/records?sort=-created&perPage=30${filter}`,
  );
  if (res.status !== 200) {
    log.error(`Could not read the queue (HTTP ${res.status}): ${res.body.slice(0, 300)}`);
    return 1;
  }
  const rows = (JSON.parse(res.body) as { items: RequestRow[] }).items;
  if (rows.length === 0) {
    log.raw(status !== undefined ? `No ${status} requests.` : 'No trigger fires recorded.');
    return 0;
  }
  for (const row of rows) {
    const who = row.claimed_by !== '' ? ` by ${row.claimed_by}` : '';
    const tail =
      row.status === 'done' && row.result !== ''
        ? ` — ${row.result.slice(0, 80)}`
        : row.status === 'rejected' && row.error !== ''
          ? ` — ${row.error.slice(0, 80)}`
          : '';
    log.raw(
      `${row.id}  ${row.trigger.padEnd(24)} ${row.status.padEnd(9)}${who} (${row.fired_by}, ${age(row.created)})${tail}`,
    );
  }
  return 0;
}
