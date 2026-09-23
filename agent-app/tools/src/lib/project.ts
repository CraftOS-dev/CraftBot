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

/** While a SHADOW environment is up, the host writes `.agent-app/shadow.json`
 *  ({"port": n}) into the project and removes it at promote/teardown. All
 *  agent-facing CLI traffic (ops/run/data) then targets the shadow instance
 *  — the same routing rule the host applies to its own HTTP action. Without
 *  this, CLI calls during a build/modify would hit the LIVE app and write
 *  test records into real user data. */
function shadowPort(dir: string): number | null {
  // TODO(lui-compat): the host now writes .agent-app/shadow.json; shadows
  // created before the rename wrote .lui/shadow.json. Read the new path first,
  // fall back to the legacy one. Remove the fallback once no live shadow
  // predates the rename.
  for (const metaDir of ['.agent-app', '.lui']) {
    try {
      const raw = JSON.parse(readFileSync(join(dir, metaDir, 'shadow.json'), 'utf8')) as {
        port?: number;
      };
      if (typeof raw.port === 'number') return raw.port;
    } catch {
      /* try next location */
    }
  }
  return null;
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
    const port = shadowPort(dir) ?? manifest.port;
    return {
      dir,
      name: manifest.name,
      id: manifest.id,
      port,
      baseUrl: `http://127.0.0.1:${port}`,
    };
  }
  // EXTERNAL (adopted third-party) projects have no manifest.json — the
  // CraftBot config lives in craftbot.json, and the A2App proxy on `port`
  // serves the same ops surface, so `agent-app ops` / `agent-app run` work unchanged.
  // (`agent-app data` does not apply: external describe carries no entities.)
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
    `Not a Agent App project (no manifest.json, no external craftbot.json): ${dir}`,
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
  // TODO(lui-compat): honour the legacy LUI_AGENT env and emit the legacy
  // X-LUI-Agent header so apps not yet re-vendored still attribute the write.
  // Remove the LUI_AGENT read and the X-LUI-Agent header once every app speaks
  // the X-A2App-* signature.
  const agentId = process.env['A2APP_AGENT'] ?? process.env['LUI_AGENT'] ?? 'a2app-cli';
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-A2App-Agent': agentId,
    'X-LUI-Agent': agentId,
  };
  // Agent token (spec Phase 2 C4): the credential a non-browser client presents
  // to write. Absent on projects that predate it — the app then does not
  // require one, so this stays backwards compatible.
  const agentToken = readAgentToken(project);
  if (agentToken !== null) {
    headers['X-A2App-Token'] = agentToken;
    // TODO(lui-compat): mirror onto the legacy header for un-re-vendored apps.
    headers['X-LUI-Token'] = agentToken;
  }
  const token = await authToken(project);
  if (token !== null) headers['Authorization'] = token;
  if (extraHeaders !== undefined) Object.assign(headers, extraHeaders);
  const init: RequestInit = { method, headers };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await fetch(`${project.baseUrl}${path}`, init);
  return { status: res.status, body: await res.text() };
}
