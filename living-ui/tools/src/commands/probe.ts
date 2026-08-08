/**
 * lui probe --url <base> --steps '<json>' [--out <dir>]
 * Scripted headless-browser walk (walk-verify's hands). Steps:
 *   {"op":"goto","value":"/"} | {"op":"click","selector":"..."} |
 *   {"op":"type","selector":"...","value":"..."} | {"op":"read","selector":"..."} |
 *   {"op":"wait","value":"800"} | {"op":"screenshot","value":"name"}
 * Output: one JSON line {steps:[{op,ok,detail}], consoleErrors:[...]}.
 */
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { log } from '../lib/log.ts';

interface Step {
  op: 'goto' | 'click' | 'type' | 'read' | 'wait' | 'screenshot';
  selector?: string;
  value?: string;
}

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : undefined;
}

export async function run(args: string[]): Promise<number> {
  const url = argValue(args, '--url');
  const stepsRaw = argValue(args, '--steps');
  const outDir = argValue(args, '--out') ?? '/tmp/lui-probe';
  if (url === undefined || stepsRaw === undefined) {
    log.error("Usage: lui probe --url http://127.0.0.1:<port> --steps '[{\"op\":\"goto\",\"value\":\"/\"}]' [--out dir]");
    return 1;
  }
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    log.raw(JSON.stringify({ error: 'playwright not installed' }));
    return 2;
  }
  const steps = JSON.parse(stepsRaw) as Step[];
  mkdirSync(outDir, { recursive: true });

  const consoleErrors: string[] = [];
  const results: Array<{ op: string; ok: boolean; detail: string }> = [];
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300));
    });
    page.on('requestfailed', (req) => {
      const failure = req.failure()?.errorText ?? 'request failed';
      consoleErrors.push(`REQUEST FAILED: ${req.method()} ${req.url().slice(0, 200)} — ${failure}`);
    });
    page.on('response', (res) => {
      if (res.status() >= 400) consoleErrors.push(`HTTP ${res.status()}: ${res.request().method()} ${res.url().slice(0, 200)}`);
    });
    page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message.slice(0, 300)}`));

    for (const step of steps.slice(0, 40)) {
      try {
        switch (step.op) {
          case 'goto':
            await page.goto(url + (step.value ?? '/'), { waitUntil: 'load', timeout: 15000 });
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
            const file = join(outDir, `${step.value ?? 'shot'}-${Date.now()}.png`);
            await page.screenshot({ path: file });
            results.push({ op: 'screenshot', ok: true, detail: file });
            break;
          }
        }
      } catch (e) {
        results.push({ op: step.op, ok: false, detail: e instanceof Error ? e.message.slice(0, 300) : String(e) });
      }
    }
  } finally {
    await browser.close();
  }
  log.raw(JSON.stringify({ steps: results, consoleErrors: consoleErrors.slice(0, 10) }));
  return 0;
}
