/**
 * lui kit-sync <project> — re-vendor the kit (wholesale replace, spec V2).
 * Used by hosts on launch (auto for patch/minor) and opt-in externally (D8).
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { writeSystemHashes } from '../lib/hashes.ts';
import { vendorKitInto } from '../lib/kit.ts';
import { log } from '../lib/log.ts';

export async function run(args: string[]): Promise<number> {
  const projectDir = args[0];
  if (projectDir === undefined || !existsSync(join(projectDir, 'manifest.json'))) {
    log.error('Usage: lui kit-sync <project-dir>   (must contain manifest.json)');
    return 1;
  }

  const version = vendorKitInto(projectDir);

  const manifestPath = join(projectDir, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as { kitVersion?: string };
  const previous = manifest.kitVersion ?? 'unknown';
  manifest.kitVersion = version;
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');

  // Re-canonize: the sync itself is the new legitimate system-file state.
  writeSystemHashes(projectDir);

  log.ok(`Kit ${previous} → ${version} in ${projectDir} (rebuild required)`);
  return 0;
}
