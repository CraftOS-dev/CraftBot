/** Kit vendoring — wholesale copy, never merge (spec V2/D6). */
import { cpSync, readFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { kitDir } from './paths.ts';

export function kitVersion(): string {
  const meta = JSON.parse(readFileSync(join(kitDir(), 'kit.json'), 'utf8')) as { version: string };
  return meta.version;
}

/**
 * Vendor the kit into a project: replace frontend/src/kit entirely with the
 * workspace kit source + its version marker. Safe because the folder is
 * system-managed — no agent edits can live there (spec P1).
 */
export function vendorKitInto(projectDir: string): string {
  const dest = join(projectDir, 'frontend', 'src', 'kit');
  rmSync(dest, { recursive: true, force: true });
  cpSync(join(kitDir(), 'src'), dest, { recursive: true });
  cpSync(join(kitDir(), 'kit.json'), join(dest, 'kit.json'));
  return kitVersion();
}
