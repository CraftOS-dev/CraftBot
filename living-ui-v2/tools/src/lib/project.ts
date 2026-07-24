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
  if (!existsSync(manifestPath)) {
    throw new Error(`Not a Living UI project (no manifest.json): ${dir}`);
  }
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
): Promise<{ status: number; body: string }> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = await authToken(project);
  if (token !== null) headers['Authorization'] = token;
  const init: RequestInit = { method, headers };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await fetch(`${project.baseUrl}${path}`, init);
  return { status: res.status, body: await res.text() };
}
