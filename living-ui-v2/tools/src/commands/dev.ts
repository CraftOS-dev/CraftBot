/**
 * lui dev <project> — development mode: PocketBase (backend, hooks, data) +
 * Vite dev server (HMR frontend) pointing at it. Ctrl+C stops both.
 */
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { log } from '../lib/log.ts';
import { osAdapter } from '../lib/os-adapter.ts';
import { ensurePbBinary } from './pb.ts';

export async function run(args: string[]): Promise<number> {
  const projectDir = args[0];
  if (projectDir === undefined || !existsSync(join(projectDir, 'manifest.json'))) {
    log.error('Usage: lui dev <project-dir>   (must contain manifest.json)');
    return 1;
  }

  const manifest = JSON.parse(readFileSync(join(projectDir, 'manifest.json'), 'utf8')) as {
    port: number;
    name: string;
  };
  const pbPort = manifest.port;
  const vitePort = pbPort + 1;
  const pbBin = await ensurePbBinary();
  const pbDir = join(projectDir, 'pb');
  mkdirSync(join(pbDir, 'pb_data'), { recursive: true });

  log.info(`${manifest.name}: PocketBase on :${pbPort}, Vite on :${vitePort}`);

  const children: ChildProcess[] = [];
  const stop = (): void => {
    for (const child of children) {
      if (child.pid !== undefined) osAdapter.terminate(child.pid);
    }
  };
  process.on('SIGINT', () => {
    stop();
    process.exit(0);
  });
  process.on('SIGTERM', () => {
    stop();
    process.exit(0);
  });

  const pb = spawn(
    pbBin,
    [
      'serve',
      `--http=127.0.0.1:${pbPort}`,
      '--dir',
      join(pbDir, 'pb_data'),
      '--hooksDir',
      join(pbDir, 'pb_hooks'),
      '--migrationsDir',
      join(pbDir, 'pb_migrations'),
      '--publicDir',
      join(pbDir, 'pb_public'),
    ],
    { stdio: 'inherit' },
  );
  children.push(pb);

  // Windows: npm is npm.cmd, which Node refuses to spawn without a shell.
  const isWin = process.platform === 'win32';
  const vite = spawn(isWin ? 'npm.cmd' : 'npm', ['run', 'dev'], {
    cwd: join(projectDir, 'frontend'),
    stdio: 'inherit',
    shell: isWin,
    env: {
      ...process.env,
      VITE_PB_URL: `http://127.0.0.1:${pbPort}`,
      LUI_DEV_PORT: String(vitePort),
    },
  });
  children.push(vite);

  return new Promise<number>((resolve) => {
    let exited = 0;
    for (const child of children) {
      child.on('exit', () => {
        exited += 1;
        if (exited === 1) stop();
        if (exited === children.length) resolve(0);
      });
    }
  });
}
