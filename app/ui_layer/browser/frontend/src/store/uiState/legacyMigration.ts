import { UI_STATE } from './catalog'
import { isDefaultUiValue, type UiStateDescriptor } from './defineUiState'
import type { UiStorage } from './UiStorage'

/**
 * One-time move of UI state saved before the shared uiState layer existed,
 * when each component wrote its own ad-hoc localStorage key.
 *
 * A legacy value is copied only when its new key is still unset, and the
 * legacy key is always removed afterwards. That makes the migration
 * idempotent: after the first boot it finds nothing to do.
 */

interface LegacyRule {
  /** The descriptor a legacy key maps to, or null when this rule doesn't apply. */
  target(legacyKey: string): UiStateDescriptor<unknown> | null
  /** Raw legacy string → new value; undefined discards it. */
  convert(raw: string): unknown
}

const exactKey = (
  legacyKey: string,
  descriptor: UiStateDescriptor<unknown>,
  convert: (raw: string) => unknown,
): LegacyRule => ({
  target: key => (key === legacyKey ? descriptor : null),
  convert,
})

const keyPrefix = (
  prefix: string,
  family: (id: string) => UiStateDescriptor<unknown>,
  convert: (raw: string) => unknown,
): LegacyRule => ({
  target: key => (key.startsWith(prefix) ? family(key.slice(prefix.length)) : null),
  convert,
})

const flag = (raw: string) => raw === '1'
const asIs = (raw: string) => raw
const json = (raw: string) => {
  try {
    return JSON.parse(raw)
  } catch {
    return undefined
  }
}

const LEGACY_RULES: LegacyRule[] = [
  exactKey('craftbot-theme', UI_STATE.theme, asIs),
  exactKey('craftbot.sidebar.collapsed', UI_STATE.sidebar.collapsed, flag),
  // Only the collapsed state used to be stored ('1'); expanded meant "no key".
  exactKey('sidebarGroupCollapsed.chats', UI_STATE.nav.chatsExpanded, raw => raw !== '1'),
  exactKey('sidebarGroupCollapsed.agentapp', UI_STATE.nav.agentAppExpanded, raw => raw !== '1'),
  exactKey('craftbot.dashboard.layouts', UI_STATE.dashboard.layouts, json),
  exactKey('craftbot.dashboard.activeLayoutId', UI_STATE.dashboard.activeLayoutId, asIs),
  keyPrefix('craftbot.tour.completed.', UI_STATE.tour.completed, flag),
]

export function migrateLegacyUiStorage(
  target: UiStorage,
  resolveLegacyArea: () => Storage = () => window.localStorage,
): void {
  try {
    const area = resolveLegacyArea()
    // Snapshot the keys first: the loop removes entries as it goes.
    const legacyKeys = Array.from({ length: area.length }, (_, i) => area.key(i))
    for (const legacyKey of legacyKeys) {
      if (legacyKey === null) continue
      const rule = LEGACY_RULES.find(r => r.target(legacyKey) !== null)
      const descriptor = rule?.target(legacyKey)
      if (!rule || !descriptor) continue

      const raw = area.getItem(legacyKey)
      const value = raw === null ? undefined : rule.convert(raw)
      const worthKeeping = value !== undefined
        && descriptor.isValid(value)
        && !isDefaultUiValue(descriptor, value)
      if (worthKeeping && target.read(descriptor.key) === undefined) {
        target.write(descriptor.key, value)
      }
      area.removeItem(legacyKey)
    }
  } catch {
    // Storage unavailable — nothing to migrate.
  }
}
