/** Operate-command helpers: resolve a project, its port, ops, and auth. */
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

export interface ProjectRef {
  dir: string;
  name: string;
  id: string;
  port: number;
  baseUrl: string;
}

export function loadProject(projectDir: string): ProjectRef {
  const dir = resolve(projectDir);
  const manifestPath = join(dir, 'manifest.json');
  if (existsSync(manifestPath)) {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as {
      name: string;
      id: string;
      port: number;
    };
    return {
      dir,
      name: manifest.name,
      id: manifest.id,
      port: manifest.port,
      baseUrl: `http://127.0.0.1:${manifest.port}`,
    };
  }
  // EXTERNAL (adopted third-party) projects have no manifest.json — the
  // CraftBot config lives in craftbot.json, and the A2App proxy on `port`
  // serves the same ops surface, so `lui ops` / `lui run` work unchanged.
  // (`lui data` does not apply: external describe has no entities in v1.)
  const craftbotPath = join(dir, 'craftbot.json');
  if (existsSync(craftbotPath)) {
    const cfg = JSON.parse(readFileSync(craftbotPath, 'utf8')) as {
      name?: string;
      id?: string;
      port?: number;
      external?: boolean;
    };
    if (cfg.external === true && typeof cfg.port === 'number') {
      return {
        dir,
        name: cfg.name ?? dir,
        id: cfg.id ?? '',
        port: cfg.port,
        baseUrl: `http://127.0.0.1:${cfg.port}`,
      };
    }
  }
  throw new Error(
    `Not a Living UI project (no manifest.json, no external craftbot.json): ${dir}`,
  );
}

export interface Operation {
  name: string;
  description: string;
  system?: boolean;
  destructive?: boolean;
  params?: Record<string, { type: string; description?: string; required?: boolean }>;
  executor: { type: string; method?: string; path?: string; collection?: string; action?: string };
}

export function loadOps(project: ProjectRef): Operation[] {
  const raw = JSON.parse(readFileSync(join(project.dir, 'operations.json'), 'utf8')) as {
    operations: Operation[];
  };
  return raw.operations ?? [];
}

/** The project's agent token, or null when the project predates it. */
export function readAgentToken(project: ProjectRef): string | null {
  const file = join(project.dir, '.agent-token');
  if (!existsSync(file)) return null;
  const value = readFileSync(file, 'utf8').trim();
  return value === '' ? null : value;
}

/** Superuser token via the project-local .superuser file (absent on imports). */
export async function authToken(project: ProjectRef): Promise<string | null> {
  const credFile = join(project.dir, '.superuser');
  if (!existsSync(credFile)) return null;
  const { email, password } = JSON.parse(readFileSync(credFile, 'utf8'));
  const res = await fetch(`${project.baseUrl}/api/collections/_superusers/auth-with-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ identity: email, password }),
  });
  if (!res.ok) return null;
  return ((await res.json()) as { token: string }).token;
}

export async function request(
  project: ProjectRef,
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<{ status: number; body: string }> {
  // Attribution: the app records this against every write (spec Phase 1 B6).
  // Self-asserted and worthless against malice — exactly right against
  // confusion, which is the real problem when several agents share one app.
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-LUI-Agent': process.env['LUI_AGENT'] ?? 'lui-cli',
  };
  // Agent token (spec Phase 2 C4): the credential a non-browser client presents
  // to write. Absent on projects that predate it — the app then does not
  // require one, so this stays backwards compatible.
  const agentToken = readAgentToken(project);
  if (agentToken !== null) headers['X-LUI-Token'] = agentToken;
  const token = await authToken(project);
  if (token !== null) headers['Authorization'] = token;
  if (extraHeaders !== undefined) Object.assign(headers, extraHeaders);
  const init: RequestInit = { method, headers };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await fetch(`${project.baseUrl}${path}`, init);
  return { status: res.status, body: await res.text() };
}
