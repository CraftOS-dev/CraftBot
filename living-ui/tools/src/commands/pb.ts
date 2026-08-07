/**
 * lui pb — manage the pinned PocketBase binary.
 *
 *   lui pb fetch   download + cache the pinned version for this OS/arch
 *   lui pb path    print the cached binary path (fetches if missing)
 *   lui pb version print the pinned version
 */
import { execFileSync } from 'node:child_process';
import { chmodSync, createWriteStream, existsSync } from 'node:fs';
import { unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import type { ReadableStream as WebReadableStream } from 'node:stream/web';
import { pipeline } from 'node:stream/promises';
import { log } from '../lib/log.ts';
import { osAdapter } from '../lib/os-adapter.ts';
import { pinnedPbVersion } from '../lib/paths.ts';

const RELEASE_BASE = 'https://github.com/pocketbase/pocketbase/releases/download';

export async function ensurePbBinary(): Promise<string> {
  const version = pinnedPbVersion();
  const cacheDir = osAdapter.pbCacheDir(version);
  const binPath = join(cacheDir, osAdapter.pbBinaryName());

  if (existsSync(binPath)) return binPath;

  const asset = osAdapter.pbAssetName(version);
  const url = `${RELEASE_BASE}/v${version}/${asset}`;
  const zipPath = join(cacheDir, asset);

  log.step(`Downloading PocketBase v${version} (${asset})…`);
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok || res.body === null) {
    throw new Error(`Download failed (${res.status}) — ${url}`);
  }
  await pipeline(
    Readable.fromWeb(res.body as unknown as WebReadableStream<Uint8Array>),
    createWriteStream(zipPath),
  );

  log.step('Extracting…');
  osAdapter.extractZip(zipPath, cacheDir);
  await unlink(zipPath);

  if (!existsSync(binPath)) {
    throw new Error(`Extraction did not produce ${binPath}`);
  }
  if (osAdapter.platform !== 'win32') chmodSync(binPath, 0o755);

  const reported = execFileSync(binPath, ['--version'], { encoding: 'utf8' }).trim();
  log.ok(`Cached ${binPath} (${reported})`);
  return binPath;
}

export async function run(args: string[]): Promise<number> {
  const sub = args[0] ?? 'fetch';

  switch (sub) {
    case 'fetch': {
      await ensurePbBinary();
      return 0;
    }
    case 'path': {
      log.raw(await ensurePbBinary());
      return 0;
    }
    case 'version': {
      log.raw(pinnedPbVersion());
      return 0;
    }
    default:
      log.error(`Unknown subcommand: pb ${sub}`);
      log.raw('Try: lui pb fetch | path | version');
      return 1;
  }
}
