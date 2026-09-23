/** Prefix for every persisted UI state key, e.g. `craftbot.ui.sidebar.collapsed`. */
export const UI_STORAGE_NAMESPACE = 'craftbot.ui.'

/**
 * Namespaced JSON access to one Web Storage area (localStorage or
 * sessionStorage).
 *
 * Every operation is guarded: storage can be unavailable (private mode,
 * sandboxed frames), over quota, or hold corrupt values from an older build.
 * Failures degrade to "nothing persisted" instead of throwing into the UI.
 */
export class UiStorage {
  constructor(
    private readonly resolveArea: () => Storage,
    private readonly namespace: string = UI_STORAGE_NAMESPACE,
  ) {}

  /** The stored value, or undefined when missing or unreadable. */
  read(key: string): unknown {
    return this.parse(this.withArea(area => area.getItem(this.namespace + key), null))
  }

  write(key: string, value: unknown): void {
    this.withArea(area => area.setItem(this.namespace + key, JSON.stringify(value)), undefined)
  }

  remove(key: string): void {
    this.withArea(area => area.removeItem(this.namespace + key), undefined)
  }

  /** Every readable value under the namespace, keyed without the prefix. */
  readAll(): Record<string, unknown> {
    return this.withArea(area => {
      const values: Record<string, unknown> = {}
      for (let i = 0; i < area.length; i++) {
        const storageKey = area.key(i)
        if (!storageKey?.startsWith(this.namespace)) continue
        const value = this.parse(area.getItem(storageKey))
        if (value !== undefined) values[storageKey.slice(this.namespace.length)] = value
      }
      return values
    }, {})
  }

  /**
   * The un-prefixed key a `storage` event (a write from another tab) refers
   * to, or null when the event is for a different area or namespace.
   */
  keyOf(event: StorageEvent): string | null {
    const area = this.withArea<Storage | null>(a => a, null)
    if (!area || event.storageArea !== area || !event.key?.startsWith(this.namespace)) return null
    return event.key.slice(this.namespace.length)
  }

  /** Parses a raw stored string; missing or corrupt input reads as undefined. */
  parse(raw: string | null): unknown {
    if (raw === null) return undefined
    try {
      return JSON.parse(raw)
    } catch {
      return undefined
    }
  }

  private withArea<R>(operation: (area: Storage) => R, fallback: R): R {
    try {
      return operation(this.resolveArea())
    } catch {
      return fallback
    }
  }
}
