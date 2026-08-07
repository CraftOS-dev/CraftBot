/**
 * Console relay (spec K8/D12) — the entire agent-observation layer.
 * Captures console.error/warn + uncaught errors/rejections and ships them,
 * batched, to the app's own backend (`POST /api/_console`, a blueprint hook),
 * where they land in a log the build loop reads. Nothing else is captured.
 */

interface RelayEntry {
  level: 'error' | 'warn';
  message: string;
  ts: number;
}

const FLUSH_INTERVAL_MS = 2000;
const MAX_BATCH = 50;

export class ConsoleRelay {
  private queue: RelayEntry[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private restore: Array<() => void> = [];

  start(): void {
    if (this.timer !== null) return;

    for (const level of ['error', 'warn'] as const) {
      const original = console[level].bind(console);
      console[level] = (...args: unknown[]): void => {
        original(...args);
        this.push(level, args.map(stringify).join(' '));
      };
      this.restore.push(() => {
        console[level] = original;
      });
    }

    const onError = (event: ErrorEvent): void => this.push('error', `uncaught: ${event.message}`);
    const onRejection = (event: PromiseRejectionEvent): void =>
      this.push('error', `unhandledrejection: ${stringify(event.reason)}`);
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    this.restore.push(() => window.removeEventListener('error', onError));
    this.restore.push(() => window.removeEventListener('unhandledrejection', onRejection));

    this.timer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    for (const fn of this.restore) fn();
    this.restore = [];
  }

  private push(level: RelayEntry['level'], message: string): void {
    this.queue.push({ level, message: message.slice(0, 4000), ts: Date.now() });
    if (this.queue.length > MAX_BATCH) this.queue = this.queue.slice(-MAX_BATCH);
  }

  private async flush(): Promise<void> {
    if (this.queue.length === 0) return;
    const batch = this.queue.splice(0, MAX_BATCH);
    try {
      await fetch('/api/_console', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entries: batch }),
      });
    } catch {
      // Relay must never create its own error loop; drop on failure.
    }
  }
}

function stringify(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
