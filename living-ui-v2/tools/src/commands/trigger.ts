/**
 * lui trigger <project-dir> <name> [--param value ...]
 *
 * Fire a declared trigger of the RUNNING app — the same path the app itself
 * uses (a POST into agent_requests through the in-app guard), not a side
 * door: the fire proves the guard, the cooldown, and — when a CraftBot host
 * is attached and has approved the app — the agent dispatch, end to end.
 * Spec TRIGGERS-PLAN: "test each trigger after launch".
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { log } from '../lib/log.ts';
import { loadProject, request } from '../lib/project.ts';

interface TriggerParamSpec {
  type?: string;
  required?: boolean;
  default?: unknown;
  enum?: unknown[];
}

interface TriggerDef {
  description?: string;
  instruction?: string;
  params?: Record<string, TriggerParamSpec>;
  cooldown_seconds?: number;
}

function loadDeclared(dir: string): Record<string, TriggerDef> {
  const file = join(dir, 'triggers.json');
  if (!existsSync(file)) return {};
  const parsed = JSON.parse(readFileSync(file, 'utf8')) as {
    triggers?: Record<string, TriggerDef>;
  };
  return parsed.triggers ?? {};
}

/** --key value pairs → params, coerced by the DECLARED type (the client owns
 *  coercion in this architecture — the app only validates). A valueless
 *  --flag errors rather than becoming `true`, same rule as `lui data`. */
function parseParams(
  args: string[],
  spec: Record<string, TriggerParamSpec>,
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (let i = 0; i < args.length; i++) {
    const arg = args[i] ?? '';
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const value = args[i + 1];
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`--${key} needs a value`);
    }
    i++;
    const declared = spec[key];
    if (declared?.type === 'number') {
      const n = Number(value);
      if (Number.isNaN(n)) throw new Error(`--${key} must be a number, got "${value}"`);
      params[key] = n;
    } else if (declared?.type === 'boolean') {
      if (value !== 'true' && value !== 'false') {
        throw new Error(`--${key} must be true or false, got "${value}"`);
      }
      params[key] = value === 'true';
    } else {
      params[key] = value;
    }
  }
  return params;
}

export async function run(args: string[]): Promise<number> {
  const projectDir = args[0];
  const name = args[1];
  if (projectDir === undefined || name === undefined || name.startsWith('--')) {
    log.error('Usage: lui trigger <project-dir> <name> [--param value ...]');
    return 1;
  }
  const project = loadProject(projectDir);

  const declared = loadDeclared(project.dir);
  const names = Object.keys(declared).sort();
  const def = declared[name];
  if (def === undefined) {
    log.error(
      `Trigger "${name}" is not declared in triggers.json. Declared: ${names.join(', ') || '(none)'}`,
    );
    return 1;
  }

  let params: Record<string, unknown>;
  try {
    params = parseParams(args.slice(2), def.params ?? {});
  } catch (err) {
    log.error(err instanceof Error ? err.message : String(err));
    return 1;
  }

  const res = await request(project, 'POST', '/api/collections/agent_requests/records', {
    trigger: name,
    params,
    status: 'pending',
    fired_by: 'cli',
  });
  if (res.status !== 200) {
    log.error(`Fire rejected (HTTP ${res.status}): ${res.body.slice(0, 400)}`);
    return 1;
  }
  const row = JSON.parse(res.body) as { id: string };
  log.ok(`Fired "${name}" — request ${row.id} is pending.`);
  log.raw(
    `Watch it: node tools/src/cli.ts requests ${project.dir}\n` +
      'If a CraftBot host is attached (and has approved this app), the agent claims the row and writes result/status.',
  );
  return 0;
}
