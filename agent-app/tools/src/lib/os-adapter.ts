/**
 * OSAdapter — the single home for platform-specific behavior (spec W5/D14).
 * Commands never branch on process.platform; they ask the adapter.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve, sep } from 'node:path';
import { unzipSync } from 'fflate';

export type Platform = 'darwin' | 'linux' | 'win32';

export class OSAdapter {
  readonly platform: Platform;
  readonly arch: 'amd64' | 'arm64';

  constructor(platform: NodeJS.Platform = process.platform, arch: string = process.arch) {
    if (platform !== 'darwin' && platform !== 'linux' && platform !== 'win32') {
      throw new Error(`Unsupported platform: ${platform}`);
    }
    this.platform = platform;
    if (arch !== 'x64' && arch !== 'arm64') {
      throw new Error(`Unsupported CPU architecture: ${arch}`);
    }
    this.arch = arch === 'arm64' ? 'arm64' : 'amd64';
  }

  /** Per-user cache root of the agent-app tooling. */
  private cacheRoot(): string {
    return {
      darwin: join(homedir(), 'Library', 'Caches', 'craftos-agent-app'),
      linux: join(homedir(), '.cache', 'craftos-agent-app'),
      win32: join(process.env['LOCALAPPDATA'] ?? join(homedir(), 'AppData', 'Local'), 'craftos-agent-app'),
    }[this.platform];
  }

  /** Central per-host PocketBase binary cache, versioned (spec B1). */
  pbCacheDir(version: string): string {
    const base = process.env['AGENT_APP_PB_CACHE'] ?? join(this.cacheRoot(), 'pb');
    const dir = join(base, version, `${this.platform}-${this.arch}`);
    mkdirSync(dir, { recursive: true });
    return dir;
  }

  /** Where the CLI keeps each app's superuser session between commands. Kept
   *  out of the project folder so it never travels with an exported app. */
  cliSessionDir(): string {
    const dir = join(this.cacheRoot(), 'cli-sessions');
    mkdirSync(dir, { recursive: true });
    return dir;
  }

  /** GitHub release asset name for the pinned version. */
  pbAssetName(version: string): string {
    const os = { darwin: 'darwin', linux: 'linux', win32: 'windows' }[this.platform];
    return `pocketbase_${version}_${os}_${this.arch}.zip`;
  }

  pbBinaryName(): string {
    return this.platform === 'win32' ? 'pocketbase.exe' : 'pocketbase';
  }

  /** Use the npm belonging to this Node; .cmd wrappers require a shell. */
  npmCommand(nodeExecutable: string = process.execPath): [string, string] {
    const node = realpathSync(nodeExecutable);
    const bin = dirname(node);
    const candidates = [join(bin, 'node_modules/npm/bin/npm-cli.js'), join(bin, '../lib/node_modules/npm/bin/npm-cli.js')];
    // Distro packages may link /usr/bin/npm to /usr/share/nodejs/npm/bin/.
    const sibling = join(bin, 'npm');
    if (existsSync(sibling)) candidates.push(join(dirname(realpathSync(sibling)), 'npm-cli.js'));
    const cli = candidates
      .find((candidate) => existsSync(candidate));
    if (!cli) throw new Error('Matching npm is missing. Run CraftBot Repair to restore Node/npm.');
    return [node, cli];
  }

  /** Extract internally: no PATH tools, shell, or platform-specific encodings. */
  extractZip(zipPath: string, destDir: string): void {
    const limit = 128 * 1024 * 1024;
    if (statSync(zipPath).size > limit) throw new Error('ZIP archive exceeds size limit');
    const root = resolve(destDir);
    let total = 0;
    const entries = unzipSync(readFileSync(zipPath), {
      filter: (entry) => {
        total += entry.originalSize;
        const name = entry.name.replaceAll('\\', '/');
        if (total > limit) throw new Error('ZIP contents exceed size limit');
        if (name.startsWith('/') || name.includes(':') || name.split('/').includes('..')) {
          throw new Error(`Unsafe ZIP entry: ${entry.name}`);
        }
        return true;
      },
    });
    for (const [name, contents] of Object.entries(entries)) {
      const output = resolve(root, name.replaceAll('\\', '/'));
      if (output !== root && !output.startsWith(root + sep)) throw new Error(`Unsafe ZIP entry: ${name}`);
      // Never follow an existing symlink while extracting.
      for (let path = output; path !== root; path = dirname(path)) {
        if (existsSync(path) && lstatSync(path).isSymbolicLink()) throw new Error(`Symlink in ZIP destination: ${path}`);
      }
      if (name.endsWith('/')) mkdirSync(output, { recursive: true });
      else {
        mkdirSync(dirname(output), { recursive: true });
        writeFileSync(output, contents);
      }
    }
  }

  /** Terminate a process tree. */
  terminate(pid: number): void {
    if (this.platform === 'win32') {
      execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'pipe' });
      return;
    }
    try {
      process.kill(pid, 'SIGTERM');
    } catch {
      // already gone
    }
  }

  binaryExists(dir: string): boolean {
    return existsSync(join(dir, this.pbBinaryName()));
  }
}

export const osAdapter = new OSAdapter();
