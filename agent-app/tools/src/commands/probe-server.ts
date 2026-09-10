/**
 * lui probe-server — long-lived headless-browser probe service.
 *
 * One Chromium for the whole session, one PAGE PER ORIGIN kept alive
 * between requests (so multi-step flows can be probed incrementally and
 * repeat probes skip the 2-4s browser cold start that a one-shot `lui
 * probe` pays every call).
 *
 * Protocol: line-delimited JSON over stdio.
 *   startup  → {"ready":true}                      (or {"fatal":"..."} + exit 2)
 *   request  → {"id":"r1","url":"http://127.0.0.1:3902","steps":[...],"outDir":"..."}
 *   response → {"id":"r1","steps":[{op,ok,detail}],"consoleErrors":[...]}
 *   control  → {"id":"p","op":"ping"} → {"id":"p","ok":true}
 *              {"id":"r","op":"reset","url":"..."} → drops that origin's page
 *              {"id":"s","op":"shutdown"} → close browser, exit 0
 *
 * The host (app/agent_app/probe_pool.py) owns process lifecycle: it spawns
 * one server per app port and kills it when the environment it targeted is
 * torn down, which is what guarantees no page ever outlives the build it
 * rendered.
 */
import { createInterface } from 'node:readline';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { Browser, Page } from 'playwright';

interface Step {
  op: 'goto' | 'click' | 'type' | 'read' | 'wait' | 'screenshot' | 'mounted';
  selector?: string;
  value?: string;
}

interface ProbeRequest {
  id: string;
  op?: 'ping' | 'reset' | 'shutdown';
  url?: string;
  steps?: Step[];
  outDir?: string;
}

interface PageEntry {
  page: Page;
  // Drained per request: each probe reports only the errors ITS steps caused
  // (plus anything the app emitted since the previous probe, which is signal
  // too — a background poller that started failing belongs in the report).
  errors: string[];
}

function emit(payload: unknown): void {
  process.stdout.write(JSON.stringify(payload) + '\n');
}

export async function run(_args: string[]): Promise<number> {
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    emit({ fatal: 'playwright not installed' });
    return 2;
  }

  let browser: Browser;
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
    emit({ fatal: `browser unavailable: ${reason}` });
    return 2;
  }

  const pages = new Map<string, PageEntry>();

  async function pageFor(origin: string): Promise<PageEntry> {
    const existing = pages.get(origin);
    if (existing !== undefined && !existing.page.isClosed()) return existing;
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const entry: PageEntry = { page, errors: [] };
    page.on('console', (m) => {
      if (m.type() === 'error') entry.errors.push(m.text().slice(0, 300));
    });
    page.on('requestfailed', (req) => {
      const failure = req.failure()?.errorText ?? 'request failed';
      entry.errors.push(
        `REQUEST FAILED: ${req.method()} ${req.url().slice(0, 200)} — ${failure}`,
      );
    });
    page.on('response', (res) => {
      if (res.status() < 400) return;
      // The status alone starves the fixing agent: a 502 whose body says
      // what threw is diagnosable, a bare "HTTP 502" is a wall. Attach the
      // body asynchronously; the entry buffer is drained at request end.
      void res
        .text()
        .then((body) => {
          const excerpt = body.replace(/\s+/g, ' ').trim().slice(0, 300);
          entry.errors.push(
            `HTTP ${res.status()}: ${res.request().method()} ${res
              .url()
              .slice(0, 200)}${excerpt ? ` — ${excerpt}` : ''}`,
          );
        })
        .catch(() => {
          entry.errors.push(
            `HTTP ${res.status()}: ${res.request().method()} ${res.url().slice(0, 200)}`,
          );
        });
    });
    page.on('pageerror', (e) => entry.errors.push(`pageerror: ${e.message.slice(0, 300)}`));
    pages.set(origin, entry);
    return entry;
  }

  async function executeSteps(
    entry: PageEntry,
    baseUrl: string,
    steps: Step[],
    outDir: string,
  ): Promise<Array<{ op: string; ok: boolean; detail: string }>> {
    const { page } = entry;
    const results: Array<{ op: string; ok: boolean; detail: string }> = [];
    for (const step of steps.slice(0, 40)) {
      try {
        switch (step.op) {
          case 'goto':
            // Resolve the step value against the base URL: a relative path
            // ("/", "/foo") joins onto the origin, while an absolute URL the
            // agent may pass ("http://127.0.0.1:3902") is used as-is instead
            // of being concatenated into "http://…3902http://…3902" (an
            // invalid URL whose failed goto left every later selector step to
            // hang for its full timeout — observed 2026-09-09).
            await page.goto(new URL(step.value ?? '/', baseUrl).href, {
              waitUntil: 'load',
              timeout: 15000,
            });
            await page.waitForTimeout(800);
            results.push({ op: 'goto', ok: true, detail: page.url() });
            break;
          case 'click':
            await page.click(step.selector ?? '', { timeout: 5000 });
            await page.waitForTimeout(500);
            results.push({ op: 'click', ok: true, detail: step.selector ?? '' });
            break;
          case 'type':
            await page.fill(step.selector ?? '', step.value ?? '', { timeout: 5000 });
            results.push({ op: 'type', ok: true, detail: step.selector ?? '' });
            break;
          case 'read': {
            const text = step.selector
              ? await page.innerText(step.selector, { timeout: 5000 })
              : await page.innerText('body');
            results.push({ op: 'read', ok: true, detail: text.slice(0, 1500) });
            break;
          }
          case 'wait':
            await page.waitForTimeout(Math.min(Number(step.value ?? 500), 5000));
            results.push({ op: 'wait', ok: true, detail: step.value ?? '500' });
            break;
          case 'screenshot': {
            mkdirSync(outDir, { recursive: true });
            const file = join(outDir, `${step.value ?? 'shot'}-${Date.now()}.png`);
            await page.screenshot({ path: file });
            results.push({ op: 'screenshot', ok: true, detail: file });
            break;
          }
          case 'mounted': {
            // The boot smoke's structural check: #root rendered real content.
            const text = (await page.innerText('#root', { timeout: 5000 })).trim();
            results.push({
              op: 'mounted',
              ok: text.length > 0,
              detail: text.length > 0 ? `#root has content (${text.length} chars)` : '#root is empty',
            });
            break;
          }
        }
      } catch (e) {
        results.push({
          op: step.op,
          ok: false,
          detail: e instanceof Error ? e.message.slice(0, 300) : String(e),
        });
      }
    }
    return results;
  }

  emit({ ready: true });

  const rl = createInterface({ input: process.stdin });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (trimmed === '') continue;
    let req: ProbeRequest;
    try {
      req = JSON.parse(trimmed) as ProbeRequest;
    } catch {
      emit({ error: 'unparseable request line' });
      continue;
    }
    if (req.op === 'shutdown') {
      break;
    }
    if (req.op === 'ping') {
      emit({ id: req.id, ok: true });
      continue;
    }
    if (req.op === 'reset') {
      const origin = req.url !== undefined ? new URL(req.url).origin : '';
      const entry = pages.get(origin);
      if (entry !== undefined) {
        pages.delete(origin);
        await entry.page.close().catch(() => undefined);
      }
      emit({ id: req.id, ok: true });
      continue;
    }
    if (req.url === undefined || !Array.isArray(req.steps) || req.steps.length === 0) {
      emit({ id: req.id, error: 'url and a non-empty steps array are required' });
      continue;
    }
    try {
      const origin = new URL(req.url).origin;
      const entry = await pageFor(origin);
      const results = await executeSteps(
        entry,
        req.url,
        req.steps,
        req.outDir ?? join(process.cwd(), 'lui-probe'),
      );
      // Give in-flight response-body captures a beat to land in the buffer.
      await new Promise((resolve) => setTimeout(resolve, 150));
      const consoleErrors = entry.errors.splice(0, entry.errors.length).slice(0, 10);
      emit({ id: req.id, steps: results, consoleErrors });
    } catch (e) {
      emit({
        id: req.id,
        error: e instanceof Error ? e.message.slice(0, 300) : String(e),
      });
    }
  }

  await browser.close().catch(() => undefined);
  return 0;
}
