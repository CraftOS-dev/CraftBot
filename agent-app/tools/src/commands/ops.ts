/**
 * agent-app ops <project-dir> [area]: the app's declared verb surface (spec O1/O4).
 * The agent-facing capability card: what this app can DO. With an area (an op
 * name or the part before its last dot, e.g. `notes` or `notes.create`) it lists
 * only those ops, each param with its description, so an agent can look up
 * one area of a large app without reading every op.
 */
import { log } from '../lib/log.ts';
import { loadOps, loadProject } from '../lib/project.ts';

export async function run(args: string[]): Promise<number> {
  const [dirArg, area] = args.filter((a) => !a.startsWith('--'));
  if (dirArg === undefined) {
    log.error('Usage: agent-app ops <project-dir> [area]');
    return 1;
  }
  const project = loadProject(dirArg);
  const all = loadOps(project);
  const ops = area === undefined ? all : all.filter((o) => o.name === area || o.name.startsWith(area + '.'));
  if (ops.length === 0) {
    const areas = [...new Set(all.map((o) => o.name.slice(0, Math.max(o.name.lastIndexOf('.'), 0)) || o.name))];
    log.error(`No op matches "${area}". Areas: ${areas.join(', ')}`);
    return 1;
  }

  log.raw(`${project.name} (${project.id}) — ${project.baseUrl}\n`);
  for (const op of ops) {
    const params = Object.entries(op.params ?? {})
      .map(([k, v]) => `--${k} <${v.enum ? v.enum.join('|') : v.type}>${v.required ? '' : '?'}`)
      .join(' ');
    const flags = [op.system ? 'system' : '', op.destructive ? 'DESTRUCTIVE' : '']
      .filter(Boolean)
      .join(', ');
    log.raw(`  ${op.name}${params ? ' ' + params : ''}${flags ? `  [${flags}]` : ''}`);
    log.raw(`      ${op.description}`);
    if (area !== undefined) {
      for (const [k, v] of Object.entries(op.params ?? {})) {
        if (v.description) log.raw(`        --${k}: ${v.description}`);
      }
    }
  }
  log.raw(`\nRun one:  agent-app run ${dirArg} <op-name> [--param value ...]`);
  const example = ops.find((o) => !o.system)?.name;
  if (area === undefined && example !== undefined) {
    log.raw(`Details:  agent-app ops ${dirArg} <area>   (each param explained, e.g. ${example.slice(0, example.lastIndexOf('.'))})`);
  }
  log.raw(`Data:     agent-app data ${dirArg} <collection> [list|get <id>|create|update <id>|delete <id>] [--json '{...}'] [--filter '...']`);
  return 0;
}
