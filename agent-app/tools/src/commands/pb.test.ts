import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { zipSync, strToU8 } from 'fflate';
import { OSAdapter } from '../lib/os-adapter.ts';
import { acquireDownloadLock, binaryReady, downloadArchive, ensurePbBinary } from './pb.ts';

test('npm is invoked as a JS entry point with the selected Node, including special paths', () => {
  const root = mkdtempSync(join(tmpdir(), 'node & caf\u00e9-'));
  try {
    const node = join(root, 'node');
    writeFileSync(node, 'placeholder');
    const adapter = new OSAdapter();
    assert.throws(() => adapter.npmCommand(node), /Matching npm is missing/);
    const directory = join(root, 'node_modules/npm/bin');
    mkdirSync(directory, { recursive: true });
    const cli = join(directory, 'npm-cli.js');
    writeFileSync(cli, 'placeholder');
    assert.deepEqual(adapter.npmCommand(node), [realpathSync(node), realpathSync(cli)]);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('npm discovery supports distro symlinks', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(join(tmpdir(), 'node-distro-'));
  try {
    mkdirSync(join(root, 'bin'));
    mkdirSync(join(root, 'share/npm/bin'), { recursive: true });
    const node = join(root, 'bin/node');
    const cli = join(root, 'share/npm/bin/npm-cli.js');
    writeFileSync(node, 'placeholder');
    writeFileSync(cli, 'placeholder');
    symlinkSync(cli, join(root, 'bin/npm'));
    assert.deepEqual(new OSAdapter().npmCommand(node), [realpathSync(node), realpathSync(cli)]);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('extracts ZIP on each platform without tools, including Unicode and spaces', () => {
  const root = mkdtempSync(join(tmpdir(), 'pb-zip-'));
  const oldPath = process.env.PATH;
  try {
    const zip = join(root, 'input.zip');
    writeFileSync(zip, zipSync({ 'folder/hello.txt': strToU8('hello') }));
    process.env.PATH = join(root, 'no-tools');
    for (const platform of ['win32', 'darwin', 'linux'] as const) {
      const dest = join(root, platform, 'User Name & caf\u00e9 \u6587\u4ef6');
      new OSAdapter(platform, 'x64').extractZip(zip, dest);
      assert.equal(readFileSync(join(dest, 'folder/hello.txt'), 'utf8'), 'hello');
    }
  } finally {
    process.env.PATH = oldPath;
    rmSync(root, { recursive: true, force: true });
  }
});

test('rejects escaping ZIP entries before writing outside staging', () => {
  const root = mkdtempSync(join(tmpdir(), 'pb-unsafe-'));
  try {
    for (const name of ['../outside', '..\\outside', '/absolute', 'C:/absolute']) {
      const zip = join(root, 'input.zip');
      writeFileSync(zip, zipSync({ [name]: strToU8('bad') }));
      assert.throws(() => new OSAdapter().extractZip(zip, join(root, 'out')), /Unsafe ZIP/);
      assert.equal(existsSync(join(root, 'outside')), false);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('rejects truncated ZIP data', () => {
  const root = mkdtempSync(join(tmpdir(), 'pb-truncated-'));
  try {
    const zip = join(root, 'input.zip');
    writeFileSync(zip, zipSync({ hello: strToU8('hello') }).subarray(0, 10));
    assert.throws(() => new OSAdapter().extractZip(zip, join(root, 'out')));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('unsupported architectures cannot silently select x64', () => {
  assert.throws(() => new OSAdapter('linux', 'riscv64'), /Unsupported CPU/);
  assert.throws(() => new OSAdapter('win32', 'ia32'), /Unsupported CPU/);
});

test('cached binaries must run and report the expected version', () => {
  const root = mkdtempSync(join(tmpdir(), 'pb-binary-'));
  try {
    const broken = join(root, 'pocketbase.exe');
    writeFileSync(broken, '');
    assert.equal(binaryReady(broken, '0.39.7'), false);
    assert.equal(binaryReady(process.execPath, process.version), true);
    assert.equal(binaryReady(process.execPath, '0.39.7'), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('readiness check never fetches missing PocketBase', async () => {
  const root = mkdtempSync(join(tmpdir(), 'pb-check-'));
  const cache = process.env.AGENT_APP_PB_CACHE;
  const fetch = globalThis.fetch;
  try {
    process.env.AGENT_APP_PB_CACHE = root;
    globalThis.fetch = async () => { throw new Error('unexpected download'); };
    await assert.rejects(ensurePbBinary(false), /missing or damaged/);
  } finally {
    globalThis.fetch = fetch;
    if (cache === undefined) delete process.env.AGENT_APP_PB_CACHE;
    else process.env.AGENT_APP_PB_CACHE = cache;
    rmSync(root, { recursive: true, force: true });
  }
});

test('download checks the pinned digest', async () => {
  const root = mkdtempSync(join(tmpdir(), 'pb-download-'));
  const fetch = globalThis.fetch;
  try {
    const data = Buffer.from('archive');
    globalThis.fetch = async () => new Response(data);
    await downloadArchive('https://example.test/pb.zip', join(root, 'ok'), createHash('sha256').update(data).digest('hex'));
    await assert.rejects(downloadArchive('https://example.test/pb.zip', join(root, 'bad'), '0'.repeat(64)), /SHA-256/);
  } finally { globalThis.fetch = fetch; rmSync(root, { recursive: true, force: true }); }
});

test('simultaneous downloads serialize across lock owners', async () => {
  const root = mkdtempSync(join(tmpdir(), 'pb-lock-'));
  try {
    const lock = join(root, '.lock');
    const release = await acquireDownloadLock(lock);
    let entered = false;
    const next = acquireDownloadLock(lock).then((unlock) => { entered = true; return unlock; });
    await new Promise((resolve) => setTimeout(resolve, 150));
    assert.equal(entered, false);
    release();
    const unlock = await next;
    assert.equal(entered, true);
    unlock();
    assert.equal(existsSync(lock), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('empty lock left by an interrupted writer can be recovered', async () => {
  const { utimesSync } = await import('node:fs');
  const root = mkdtempSync(join(tmpdir(), 'pb-stale-'));
  try {
    const lock = join(root, '.lock');
    writeFileSync(lock, '');
    utimesSync(lock, new Date(0), new Date(0));
    const release = await acquireDownloadLock(lock);
    release();
    assert.equal(existsSync(lock), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
