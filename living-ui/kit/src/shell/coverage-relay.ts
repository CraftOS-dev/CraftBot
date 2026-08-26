/**
 * Coverage relay (scoped walk-verify, docs/design/scoped-walk-verify.md).
 *
 * A DEV build is istanbul-instrumented (vite.config.ts, LUI_COVERAGE=1) and
 * exposes `window.__coverage__`. This relay ships the function-hit DELTAS
 * since its last flush to the app's own backend (`POST /api/_coverage`),
 * where they interleave with the verifier's feature marks into a timeline
 * the host folds into "feature → executed functions".
 *
 * Live builds have no `__coverage__`: every flush is a no-op and nothing is
 * ever posted. Failures are dropped — bookkeeping must never touch the app.
 */

interface FnMeta {
  name: string;
  decl?: { start?: { line?: number } };
  loc?: { start?: { line?: number } };
}

interface FileCoverage {
  path: string;
  fnMap: Record<string, FnMeta>;
  f: Record<string, number>;
}

declare global {
  interface Window {
    __coverage__?: Record<string, FileCoverage>;
  }
}

interface FnHit {
  name: string;
  line: number | null;
  hits: number;
}

const FLUSH_INTERVAL_MS = 2000;

export class CoverageRelay {
  private timer: ReturnType<typeof setInterval> | null = null;
  private last = new Map<string, number>(); // "path\0fnId" → counter
  private onVisibility: (() => void) | null = null;

  start(): void {
    if (this.timer !== null) return;
    this.timer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
    this.onVisibility = (): void => {
      if (document.visibilityState === 'hidden') void this.flush();
    };
    document.addEventListener('visibilitychange', this.onVisibility);
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    if (this.onVisibility !== null) {
      document.removeEventListener('visibilitychange', this.onVisibility);
      this.onVisibility = null;
    }
    void this.flush();
  }

  private collect(): Record<string, FnHit[]> {
    const cov = window.__coverage__;
    if (cov === undefined) return {};
    const out: Record<string, FnHit[]> = {};
    for (const file of Object.values(cov)) {
      if (!file || typeof file !== 'object' || !file.f || !file.fnMap) continue;
      const hits: FnHit[] = [];
      for (const [id, count] of Object.entries(file.f)) {
        const key = `${file.path}\0${id}`;
        const prev = this.last.get(key) ?? 0;
        if (count > prev) {
          this.last.set(key, count);
          const meta = file.fnMap[id];
          const line = meta?.decl?.start?.line ?? meta?.loc?.start?.line ?? null;
          hits.push({ name: meta?.name ?? `(anonymous_${id})`, line, hits: count - prev });
        }
      }
      if (hits.length > 0) out[file.path] = hits;
    }
    return out;
  }

  private async flush(): Promise<void> {
    const counters = this.collect();
    if (Object.keys(counters).length === 0) return;
    try {
      await fetch('/api/_coverage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ counters }),
        keepalive: true,
      });
    } catch {
      // Never surface: coverage is bookkeeping, not app behaviour.
    }
  }
}
