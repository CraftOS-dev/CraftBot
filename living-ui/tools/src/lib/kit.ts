/** Kit vendoring — wholesale copy, never merge (spec D6). */
import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { SYSTEM_PATHS } from './hashes.ts';
import { blueprintDir, kitDir } from './paths.ts';

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

/** The pb_hooks files tooling owns. Derived from SYSTEM_PATHS so the delivery
 *  list and the ownership list can never drift apart. */
function systemHookFiles(): string[] {
  return SYSTEM_PATHS.filter((p) => p.startsWith('pb/pb_hooks/'));
}

/** Adapter version, read from the hook itself so there is one source of truth. */
export function adapterVersion(): string {
  const src = readFileSync(join(blueprintDir(), 'pb', 'pb_hooks', '_a2app_lib.js'), 'utf8');
  return /ADAPTER_VERSION\s*=\s*'([^']+)'/.exec(src)?.[1] ?? '0.0.0';
}

/**
 * Re-vendor the system-managed pb_hooks files from the blueprint.
 *
 * Per-file rather than wholesale, because pb_hooks is otherwise AGENT-owned
 * (spec A1) — `ops.pb.js` and anything the agent wrote must survive. This is
 * what delivers the A2APP write guard to projects that did not come from
 * `create`: both `import_project_zip` and `install_from_marketplace` already
 * call kit-sync, so imported and marketplace apps pick it up on arrival.
 *
 * It also closes a laundering bug: kit-sync re-canonizes hashes for every
 * SYSTEM_PATH, so any system file it did NOT rewrite had its drifted state
 * blessed as canonical. Now every file it re-canonizes is one it just wrote.
 */
export function vendorSystemFilesInto(projectDir: string): string[] {
  const written: string[] = [];
  for (const rel of systemHookFiles()) {
    const src = join(blueprintDir(), rel);
    if (!existsSync(src)) continue;
    const dest = join(projectDir, rel);
    mkdirSync(dirname(dest), { recursive: true });
    copyFileSync(src, dest);
    written.push(rel);
  }
  return written;
}
