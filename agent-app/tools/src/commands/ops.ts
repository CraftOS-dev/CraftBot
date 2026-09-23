/**
 * agent-app ops <project-dir> — the app's declared verb surface (spec O1/O4).
 * The agent-facing capability card: what this app can DO.
 */
import { log } from '../lib/log.ts';
import { loadOps, loadProject } from '../lib/project.ts';

export async function run(args: string[]): Promise<number> {
  const dirArg = args.find((a) => !a.startsWith('--'));
  if (dirArg === undefined) {
    log.error('Usage: agent-app ops <project-dir>');
    return 1;
  }
  const project = loadProject(dirArg);
  const ops = loadOps(project);

  log.raw(`${project.name} (${project.id}) — ${project.baseUrl}\n`);
  for (const op of ops) {
    const params = Object.entries(op.params ?? {})
      .map(([k, v]) => `--${k} <${v.type}>${v.required ? '' : '?'}`)
      .join(' ');
    const flags = [op.system ? 'system' : '', op.destructive ? 'DESTRUCTIVE' : '']
      .filter(Boolean)
      .join(', ');
    log.raw(`  ${op.name}${params ? ' ' + params : ''}${flags ? `  [${flags}]` : ''}`);
    log.raw(`      ${op.description}`);
  }
  log.raw(`\nRun one:  agent-app run ${dirArg} <op-name> [--param value ...]`);
  log.raw(`Data:     agent-app data ${dirArg} <collection> [list|get <id>|create|update <id>|delete <id>] [--json '{...}'] [--filter '...']`);
  return 0;
}
