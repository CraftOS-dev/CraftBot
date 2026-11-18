/**
 * A Web Storage area kept in one JSON file.
 *
 * The browser store persists remembered UI state (read receipts, drafts,
 * preferences) in localStorage. The terminal gives it this instead: the same
 * synchronous API, saved under the CraftBot state directory so a restart
 * remembers what the last session did. Writes are debounced and flushed on
 * exit; a missing or unreadable file starts empty.
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

export class FileStorage implements Storage {
  private data = new Map<string, string>()
  private timer: NodeJS.Timeout | null = null

  constructor(private readonly path: string | null) {
    if (!path) return
    try {
      const parsed = JSON.parse(readFileSync(path, 'utf8')) as Record<string, unknown>
      for (const [key, value] of Object.entries(parsed)) {
        if (typeof value === 'string') this.data.set(key, value)
      }
    } catch {
      // First run, or a damaged file: start empty.
    }
  }

  get length(): number {
    return this.data.size
  }

  key(index: number): string | null {
    return Array.from(this.data.keys())[index] ?? null
  }

  getItem(key: string): string | null {
    return this.data.has(key) ? (this.data.get(key) as string) : null
  }

  setItem(key: string, value: string): void {
    this.data.set(key, String(value))
    this.schedule()
  }

  removeItem(key: string): void {
    if (this.data.delete(key)) this.schedule()
  }

  clear(): void {
    this.data.clear()
    this.schedule()
  }

  /** Write pending changes now (called on exit). */
  flush(): void {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    if (!this.path) return
    try {
      mkdirSync(dirname(this.path), { recursive: true })
      const tmp = `${this.path}.tmp`
      writeFileSync(tmp, JSON.stringify(Object.fromEntries(this.data)), 'utf8')
      renameSync(tmp, this.path)
    } catch {
      // Remembered UI state is a convenience; never crash over it.
    }
  }

  private schedule(): void {
    if (!this.path || this.timer) return
    this.timer = setTimeout(() => this.flush(), 500)
    this.timer.unref()
  }
}
