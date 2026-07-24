/**
 * lui verify <project> --url <base> — headless smoke verification (spec WD11,
 * the deterministic core of walk-verify):
 *   1. app mounts (#root renders real content)
 *   2. zero console errors / page crashes while loading + settling
 *   3. screenshot evidence saved to logs/verify/home.png (WD7)
 * Always invisible: headless chromium, no window, no focus stealing.
 * Output: one JSON verdict line. Exit 0 pass, 1 fail, 2 skipped (no browser).
 */
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { log } from '../lib/log.ts';

interface Verdict {
  status: 'pass' | 'fail' | 'skipped';
  checks: Record<string, boolean>;
  consoleErrors: string[];
  screenshot: string | null;
}

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : undefined;
}

export async function run(args: string[]): Promise<number> {
  const projectDir = args.find((a) => !a.startsWith('--'));
  const url = argValue(args, '--url');
  if (projectDir === undefined || url === undefined || !existsSync(join(projectDir, 'manifest.json'))) {
    log.error('Usage: lui verify <project-dir> --url http://127.0.0.1:<port>');
    return 1;
  }

  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    log.raw(JSON.stringify({ status: 'skipped', reason: 'playwright not installed' }));
    return 2;
  }

  const verifyDir = join(projectDir, 'logs', 'verify');
  mkdirSync(verifyDir, { recursive: true });
  const screenshotPath = join(verifyDir, 'home.png');

  const consoleErrors: string[] = [];
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 500));
    });
    page.on('response', (res) => {
      if (res.status() >= 400) consoleErrors.push(`HTTP ${res.status()}: ${res.request().method()} ${res.url().slice(0, 200)}`);
    });
    page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message.slice(0, 500)}`));

    // NOTE: never wait for 'networkidle' — Living UIs hold a permanent SSE
    // connection (realtime subscriptions), so the network is never idle.
    let loaded = true;
    try {
      await page.goto(url, { waitUntil: 'load', timeout: 20000 });
      await page.waitForTimeout(1500); // let React mount + realtime settle
    } catch {
      loaded = false;
    }

    const mounted = loaded
      ? await page
          .evaluate(() => {
            const root = document.getElementById('root');
            return root !== null && root.childElementCount > 0 && root.innerText.trim().length > 0;
          })
          .catch(() => false)
      : false;

    await page.screenshot({ path: screenshotPath, fullPage: false }).catch(() => {});

    const checks = { loaded, mounted, noConsoleErrors: consoleErrors.length === 0 };
    const verdict: Verdict = {
      status: Object.values(checks).every(Boolean) ? 'pass' : 'fail',
      checks,
      consoleErrors: consoleErrors.slice(0, 10),
      screenshot: existsSync(screenshotPath) ? screenshotPath : null,
    };
    log.raw(JSON.stringify(verdict));
    return verdict.status === 'pass' ? 0 : 1;
  } finally {
    await browser.close();
  }
}
