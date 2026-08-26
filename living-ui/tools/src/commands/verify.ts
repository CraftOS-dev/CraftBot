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
  // A present `playwright` package with no matching browser binary (fresh
  // npm install, no `npx playwright install`) throws here with Playwright's
  // boxed "Executable doesn't exist" banner. That is the same tooling
  // condition as "not installed" and must never fail a launch (observed
  // live 2026-08-25: a workspace `npm install` flipped every launch from
  // skipped to failed).
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (err) {
    const reason = (err instanceof Error ? err.message : String(err))
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l !== '' && !/^[╔╚║═]+$/.test(l))
      .slice(0, 3)
      .join(' ')
      .slice(0, 300);
    log.raw(JSON.stringify({ status: 'skipped', reason: `browser unavailable: ${reason}` }));
    return 2;
  }
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 500));
    });
    page.on('response', async (res) => {
      if (res.status() < 400) return;
      // The status alone starves the fixing agent: a 502 whose body says
      // "CITIES is not defined" is diagnosable, a bare "HTTP 502" is a wall
      // (observed live — six blind retries). Always attach the body.
      let body = '';
      try {
        body = (await res.text()).replace(/\s+/g, ' ').trim().slice(0, 300);
      } catch {
        /* body unavailable (redirect/aborted) — status alone will have to do */
      }
      consoleErrors.push(
        `HTTP ${res.status()}: ${res.request().method()} ${res.url().slice(0, 200)}` +
          (body !== '' ? ` — response: ${body}` : ''),
      );
    });
    page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message.slice(0, 500)}`));
    // Failed REQUESTS never produce a response: the console shows only
    // "net::ERR_CONNECTION_REFUSED" with NO URL — an agent once diagnosed a
    // nonexistent "Vite dev server" from that blank. Name the URL and cause.
    page.on('requestfailed', (req) => {
      const failure = req.failure()?.errorText ?? 'request failed';
      consoleErrors.push(`REQUEST FAILED: ${req.method()} ${req.url().slice(0, 200)} — ${failure}`);
    });

    // NOTE: never wait for 'networkidle' — Living UIs hold a permanent SSE
    // connection (realtime subscriptions), so the network is never idle.
    // Retry once on (a) load failure or (b) connection-refused RESOURCES
    // during the settle window: both are the signature of PocketBase's
    // hook-watcher restart blip (~1-2s), and a smoke check landing in that
    // window failed healthy apps twice (observed live). A genuinely dead or
    // broken app still fails — both attempts.
    let loaded = false;
    let retried = false;
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt > 0) {
        retried = true;
        consoleErrors.length = 0; // the blip's first paint is not evidence
        await page.waitForTimeout(3000);
      }
      try {
        await page.goto(url, { waitUntil: 'load', timeout: 20000 });
        await page.waitForTimeout(1500); // let React mount + realtime settle
        loaded = true;
      } catch {
        loaded = false;
        continue; // load failed → retry once
      }
      if (
        attempt === 0 &&
        consoleErrors.some((e) => /ERR_CONNECTION_(REFUSED|RESET)/.test(e))
      ) {
        continue; // refused resources on first paint → clean re-check
      }
      break; // clean (or final) attempt — verdict uses what we have
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

    const checks: Record<string, boolean> = {
      loaded,
      mounted,
      noConsoleErrors: consoleErrors.length === 0,
    };
    if (retried) checks.retriedLoad = true; // visible, but never fails the verdict
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
