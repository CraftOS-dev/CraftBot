/** Pinned PocketBase downloads shared by setup, repair and app imports. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, closeSync, createReadStream, createWriteStream, existsSync, mkdirSync, mkdtempSync, openSync, readFileSync, renameSync, rmSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { Readable, Transform } from 'node:stream';
import type { ReadableStream as WebReadableStream } from 'node:stream/web';
import { pipeline } from 'node:stream/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { log } from '../lib/log.ts';
import { osAdapter } from '../lib/os-adapter.ts';
import { pinnedPbVersion, workspaceRoot } from '../lib/paths.ts';

const RELEASE_BASE = 'https://github.com/pocketbase/pocketbase/releases/download';

export function binaryReady(bin: string, version: string): boolean {
  try {
    if (!existsSync(bin) || statSync(bin).size === 0) return false;
    const reported = execFileSync(bin, ['--version'], { encoding: 'utf8', timeout: 15000, windowsHide: true, stdio: 'pipe' }).trim();
    return reported.split(/\s+/).at(-1) === version;
  } catch { return false; }
}

/** Exclusive across CLI processes. Dead owners are recoverable after a crash. */
export async function acquireDownloadLock(path: string): Promise<() => void> {
  const token = `${process.pid}:${Date.now()}:${Math.random()}`;
  const deadline = Date.now() + 300000;
  while (true) {
    try {
      const fd = openSync(path, 'wx');
      try { writeFileSync(fd, token); } finally { closeSync(fd); }
      return () => {
        try { if (readFileSync(path, 'utf8') === token) unlinkSync(path); } catch { /* already gone */ }
      };
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== 'EEXIST') throw err;
    }
    try {
      const owner = readFileSync(path, 'utf8');
      const pid = Number(owner.split(':')[0]);
      let dead = false;
      if (Number.isInteger(pid) && pid > 0) {
        try { process.kill(pid, 0); }
        catch (err) { dead = (err as NodeJS.ErrnoException).code === 'ESRCH'; }
      } else {
        // A process could die between creating the file and writing its PID.
        dead = Date.now() - statSync(path).mtimeMs > 10000;
      }
      if (dead && readFileSync(path, 'utf8') === owner) { unlinkSync(path); continue; }
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === 'ENOENT') continue;
      throw err;
    }
    if (Date.now() >= deadline) throw new Error('Another PocketBase download is still running. Retry when it finishes.');
    await delay(100);
  }
}

export async function downloadArchive(url: string, dest: string, expectedHash: string): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt++) {
    const controller = new AbortController();
    let idle = setTimeout(() => controller.abort(), 120000);
    try {
      const res = await fetch(url, { redirect: 'follow', signal: controller.signal });
      if (!res.ok || res.body === null) {
        throw new Error(`PocketBase download failed (HTTP ${res.status}): ${url}`);
      }
      // Bound inactivity rather than total transfer time: slow links can still finish.
      const watchdog = new Transform({
        transform(chunk, _encoding, done) {
          clearTimeout(idle);
          idle = setTimeout(() => controller.abort(), 120000);
          done(null, chunk);
        },
      });
      await pipeline(Readable.fromWeb(res.body as unknown as WebReadableStream<Uint8Array>), watchdog, createWriteStream(dest));
      break;
    } catch (err) {
      if (attempt === 2 || /HTTP 4(?!08|29)/.test(String(err))) throw err;
      log.step(`PocketBase download interrupted; retrying (${attempt + 2}/3)…`);
      await delay(1000 * (attempt + 1));
    } finally {
      clearTimeout(idle);
    }
  }
  const digest = createHash('sha256');
  for await (const chunk of createReadStream(dest)) digest.update(chunk as Buffer);
  if (digest.digest('hex') !== expectedHash) throw new Error('PocketBase download failed SHA-256 verification; no executable was installed.');
}

export async function ensurePbBinary(download = true): Promise<string> {
  const version = pinnedPbVersion();
  const cacheDir = osAdapter.pbCacheDir(version);
  const binPath = join(cacheDir, osAdapter.pbBinaryName());
  if (binaryReady(binPath, version)) return binPath;
  if (!download) throw new Error(`PocketBase ${version} is missing or damaged. Run setup or Repair.`);

  const release = await acquireDownloadLock(join(cacheDir, '.download.lock'));
  let staging: string | undefined;
  try {
    if (binaryReady(binPath, version)) return binPath;
    const asset = osAdapter.pbAssetName(version);
    const hashes = JSON.parse(readFileSync(join(workspaceRoot(), 'spec', 'pocketbase-checksums.json'), 'utf8')) as Record<string, string>;
    const expected = hashes[asset];
    if (!expected || !/^[a-f0-9]{64}$/.test(expected)) throw new Error(`No approved PocketBase checksum for ${asset}`);
    staging = mkdtempSync(join(cacheDir, '.download-'));
    const zip = join(staging, asset);
    log.step(`Downloading PocketBase v${version} (${asset})…`);
    await downloadArchive(`${RELEASE_BASE}/v${version}/${asset}`, zip, expected);
    const unpacked = join(staging, 'unpacked');
    mkdirSync(unpacked);
    log.step('Extracting PocketBase…');
    osAdapter.extractZip(zip, unpacked);
    const candidate = join(unpacked, osAdapter.pbBinaryName());
    if (osAdapter.platform !== 'win32' && existsSync(candidate)) chmodSync(candidate, 0o755);
    if (!binaryReady(candidate, version)) throw new Error(`PocketBase ${version} failed its execution check on ${osAdapter.platform}/${osAdapter.arch}`);
    renameSync(candidate, binPath);
    log.ok(`Cached ${binPath} (version ${version})`);
    return binPath;
  } finally {
    try { if (staging) rmSync(staging, { recursive: true, force: true }); }
    finally { release(); }
  }
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
    case 'check': {
      log.raw(await ensurePbBinary(false));
      return 0;
    }
    case 'version': {
      log.raw(pinnedPbVersion());
      return 0;
    }
    default:
      log.error(`Unknown subcommand: pb ${sub}`);
      log.raw('Try: agent-app pb fetch | path | check | version');
      return 1;
  }
}
