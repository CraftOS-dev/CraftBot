/** Workspace path resolution — single source of truth for where things live. */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/** The living-ui workspace root (this file is tools/src/lib/paths.ts). */
export function workspaceRoot(): string {
  return dirname(dirname(dirname(dirname(fileURLToPath(import.meta.url)))));
}

export function kitDir(): string {
  return join(workspaceRoot(), 'kit');
}

export function blueprintDir(): string {
  return join(workspaceRoot(), 'blueprint');
}

export function examplesDir(): string {
  return join(workspaceRoot(), 'examples');
}

/** Exact PocketBase version pinned by the spec (D9). */
export function pinnedPbVersion(): string {
  const file = join(workspaceRoot(), 'spec', 'pocketbase.version');
  if (!existsSync(file)) {
    throw new Error(`Missing ${file} — the PB pin is required (spec B1).`);
  }
  return readFileSync(file, 'utf8').trim();
}
