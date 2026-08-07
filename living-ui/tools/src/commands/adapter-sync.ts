/**
 * lui adapter-sync <project> — re-vendor ONLY the system pb_hooks files.
 *
 * `kit-sync` does two jobs: it re-vendors `frontend/src/kit` AND the system
 * hooks. When all you need is to push a fixed adapter — a validation bug, a
 * security patch — the kit half is unwanted: it rewrites 168 KB of frontend
 * source per app, which in a source repo that tracks only a `.gitkeep` there
 * is pure noise, and it forces a rebuild the change did not require.
 *
 * This is also the delivery path A2APP-PLAN §3.4 says does not exist: a fix to
 * code shipped inside apps otherwise reaches nothing already installed.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { writeSystemHashes } from '../lib/hashes.ts';
import { adapterVersion, vendorSystemFilesInto } from '../lib/kit.ts';
import { log } from '../lib/log.ts';

export async function run(args: string[]): Promise<number> {
  const projectDir = args[0];
  if (projectDir === undefined || !existsSync(join(projectDir, 'manifest.json'))) {
    log.error('Usage: lui adapter-sync <project-dir>   (must contain manifest.json)');
    return 1;
  }

  const written = vendorSystemFilesInto(projectDir);
  if (written.length === 0) {
    log.error('No system hook files found in the blueprint — nothing to sync.');
    return 1;
  }

  const version = adapterVersion();
  const manifestPath = join(projectDir, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as { adapterVersion?: string };
  const previous = manifest.adapterVersion ?? 'none';
  manifest.adapterVersion = version;
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');

  // Only re-canonize if the kit is actually vendored here; otherwise the hash
  // manifest would record entries for files that are not present.
  if (existsSync(join(projectDir, 'frontend', 'src', 'kit', 'kit.json'))) {
    writeSystemHashes(projectDir);
  }

  log.ok(`Adapter ${previous} → ${version} (${written.length} file(s), no rebuild required)`);
  for (const file of written) log.raw(`  ${file}`);
  return 0;
}
