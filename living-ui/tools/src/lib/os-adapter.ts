/**
 * OSAdapter — the single home for platform-specific behavior (spec W5/D14).
 * Commands never branch on process.platform; they ask the adapter.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

export type Platform = 'darwin' | 'linux' | 'win32';

export class OSAdapter {
  readonly platform: Platform;
  readonly arch: 'amd64' | 'arm64';

  constructor(platform: NodeJS.Platform = process.platform, arch: string = process.arch) {
    if (platform !== 'darwin' && platform !== 'linux' && platform !== 'win32') {
      throw new Error(`Unsupported platform: ${platform}`);
    }
    this.platform = platform;
    this.arch = arch === 'arm64' ? 'arm64' : 'amd64';
  }

  /** Central per-host PocketBase binary cache, versioned (spec B1). */
  pbCacheDir(version: string): string {
    const override = process.env['LIVING_UI_PB_CACHE'];
    const base =
      override ??
      {
        darwin: join(homedir(), 'Library', 'Caches', 'craftos-living-ui', 'pb'),
        linux: join(homedir(), '.cache', 'craftos-living-ui', 'pb'),
        win32: join(process.env['LOCALAPPDATA'] ?? join(homedir(), 'AppData', 'Local'), 'craftos-living-ui', 'pb'),
      }[this.platform];
    const dir = join(base, version);
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

  /**
   * Extract a zip without npm deps: bsdtar handles zip on macOS and Windows 10+;
   * on Linux prefer unzip, fall back to bsdtar.
   */
  extractZip(zipPath: string, destDir: string): void {
    if (this.platform === 'linux') {
      try {
        execFileSync('unzip', ['-o', zipPath, '-d', destDir], { stdio: 'pipe' });
        return;
      } catch {
        // fall through to tar
      }
    }
    execFileSync('tar', ['-xf', zipPath, '-C', destDir], { stdio: 'pipe' });
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
