import type { Middleware } from '@reduxjs/toolkit'
import { uiStateChanged, uiStateSynced, type UiSliceState } from '../slices/uiSlice'
import type { UiStateLifetime } from './defineUiState'
import { migrateLegacyUiStorage } from './legacyMigration'
import { UiStorage } from './UiStorage'

export type UiStorages = Readonly<Record<UiStateLifetime, UiStorage>>

/** Where each lifetime is stored. */
export const uiStorages: UiStorages = {
  preference: new UiStorage(() => window.localStorage),
  session: new UiStorage(() => window.sessionStorage),
}

// Upper bound on how stale storage can be during a continuous change (a
// panel drag, scrolling). The store itself always updates immediately.
const WRITE_INTERVAL_MS = 300

/**
 * Coalesces rapid changes into at most one storage write per key per
 * interval. `flush` writes everything pending right away.
 */
export class UiStatePersister {
  private readonly pending = new Map<string, { lifetime: UiStateLifetime; value: unknown }>()
  private timer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly storages: UiStorages,
    private readonly intervalMs = WRITE_INTERVAL_MS,
  ) {}

  enqueue(key: string, lifetime: UiStateLifetime, value: unknown): void {
    this.pending.set(key, { lifetime, value })
    if (this.timer === null) {
      this.timer = setTimeout(() => this.flush(), this.intervalMs)
    }
  }

  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer)
      this.timer = null
    }
    for (const [key, { lifetime, value }] of this.pending) {
      const storage = this.storages[lifetime]
      if (value === undefined) storage.remove(key)
      else storage.write(key, value)
    }
    this.pending.clear()
  }
}

/**
 * Initial `ui` slice state: legacy keys are migrated first, then both
 * storage areas are read.
 */
export function loadPersistedUiState(storages: UiStorages = uiStorages): UiSliceState {
  migrateLegacyUiStorage(storages.preference)
  return {
    values: { ...storages.preference.readAll(), ...storages.session.readAll() },
  }
}

/** Writes `uiStateChanged` actions to storage and mirrors other tabs' preference writes. */
export function createUiPersistenceMiddleware(storages: UiStorages = uiStorages): Middleware {
  return (store) => {
    const persister = new UiStatePersister(storages)

    // Last chances to write before the tab is closed or backgrounded (mobile
    // browsers may discard a hidden tab without ever firing pagehide).
    window.addEventListener('pagehide', () => persister.flush())
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') persister.flush()
    })

    // Preferences changed in another tab (e.g. the theme) apply here too.
    window.addEventListener('storage', (event) => {
      const key = storages.preference.keyOf(event)
      if (key !== null) {
        store.dispatch(uiStateSynced({ key, value: storages.preference.parse(event.newValue) }))
      }
    })

    return (next) => (action) => {
      const result = next(action)
      if (uiStateChanged.match(action)) {
        const { key, lifetime, value } = action.payload
        persister.enqueue(key, lifetime, value)
      }
      return result
    }
  }
}
