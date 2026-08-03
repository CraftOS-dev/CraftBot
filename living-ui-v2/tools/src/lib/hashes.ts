/**
 * Ownership hashes (spec §11 step 5 / P1): system-managed files are recorded
 * at scaffold/kit-sync time; the gate detects agent edits by re-hashing.
 * Tooling is the only writer of both the files and the hash manifest.
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const HASH_FILE = join('.lui', 'system-hashes.json');

/** System-managed paths, relative to the project root (files or directories).
 *  Exported because this list is also the delivery manifest: `kit-sync`
 *  re-vendors every system file so the hashes it re-canonizes are hashes of
 *  files it actually just wrote (see vendorSystemFilesInto). */
export const SYSTEM_PATHS = [
  'frontend/src/kit',
  'frontend/src/main.tsx',
  'frontend/src/config.gen.ts',
  'frontend/src/app.css',
  'frontend/index.html',
  'frontend/vite.config.ts',
  'frontend/tsconfig.json',
  'pb/pb_hooks/_system.pb.js',
  'pb/pb_hooks/_craftbot_bridge.js',
  'pb/pb_hooks/_a2app.pb.js',
  'pb/pb_hooks/_a2app_lib.js',
  'pb/pb_hooks/_a2app_rules.js',
  'manifest.json',
];

function sha256(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

function toPosix(p: string): string {
  return p.split(sep).join('/');
}

/** Hash every system file; directories are walked, missing entries skipped. */
export function computeSystemHashes(projectDir: string): Record<string, string> {
  const hashes: Record<string, string> = {};
  const addFile = (abs: string): void => {
    hashes[toPosix(relative(projectDir, abs))] = sha256(abs);
  };

  const stack = SYSTEM_PATHS.map((p) => join(projectDir, p)).filter((p) => existsSync(p));
  while (stack.length > 0) {
    const current = stack.pop() as string;
    if (statSync(current).isDirectory()) {
      for (const name of readdirSync(current)) stack.push(join(current, name));
    } else {
      addFile(current);
    }
  }
  return hashes;
}

/** Record the current state as canonical (called by create and kit-sync). */
export function writeSystemHashes(projectDir: string): void {
  mkdirSync(join(projectDir, '.lui'), { recursive: true });
  const hashes = computeSystemHashes(projectDir);
  writeFileSync(join(projectDir, HASH_FILE), JSON.stringify(hashes, null, 2) + '\n');
}

/** Does `relPath` currently match its recorded canon hash?
 *  true = clean, false = drifted, null = no canon recorded (fresh scaffold
 *  mid-flight, or a path outside the canon). */
export function fileMatchesCanon(projectDir: string, relPath: string): boolean | null {
  const file = join(projectDir, HASH_FILE);
  if (!existsSync(file)) return null;
  const recorded = JSON.parse(readFileSync(file, 'utf8')) as Record<string, string>;
  const want = recorded[toPosix(relPath)];
  if (want === undefined) return null;
  const abs = join(projectDir, relPath);
  if (!existsSync(abs)) return false;
  return sha256(abs) === want;
}

/** Re-record the canon hash for ONE file the tooling itself just wrote
 *  (e.g. the gate refreshing manifest.json's derived `capabilities`).
 *  Never call this for agent-editable paths — it would canonize the edit. */
export function recordFileHash(projectDir: string, relPath: string): void {
  const file = join(projectDir, HASH_FILE);
  if (!existsSync(file)) return; // no canon yet — create/kit-sync records it
  const recorded = JSON.parse(readFileSync(file, 'utf8')) as Record<string, string>;
  recorded[toPosix(relPath)] = sha256(join(projectDir, relPath));
  writeFileSync(file, JSON.stringify(recorded, null, 2) + '\n');
}

export interface OwnershipDrift {
  modified: string[];
  missing: string[];
  added: string[];
}

/** Compare current state to the recorded canon. */
export function verifySystemHashes(projectDir: string): OwnershipDrift {
  const file = join(projectDir, HASH_FILE);
  if (!existsSync(file)) {
    throw new Error(`missing ${HASH_FILE} — run kit-sync to (re)establish system-file canon`);
  }
  const recorded = JSON.parse(readFileSync(file, 'utf8')) as Record<string, string>;
  const current = computeSystemHashes(projectDir);

  const drift: OwnershipDrift = { modified: [], missing: [], added: [] };
  for (const [path, hash] of Object.entries(recorded)) {
    const now = current[path];
    if (now === undefined) drift.missing.push(path);
    else if (now !== hash) drift.modified.push(path);
  }
  for (const path of Object.keys(current)) {
    if (!(path in recorded)) drift.added.push(path);
  }
  return drift;
}
