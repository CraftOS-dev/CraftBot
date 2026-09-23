/**
 * Typed descriptors for persisted UI state.
 *
 * A descriptor names one piece of UI state: its storage key, its default and
 * how long it lives. Components never handle storage keys themselves — they
 * pass a descriptor from `catalog.ts` to `usePersistedState` (or one of the
 * hooks built on it).
 */

/**
 * - `preference`: a choice the user made that should survive reloads (panel
 *   sizes, open/closed sections, filters, the active tab). localStorage.
 * - `session`: a view position that only matters while this browser tab is
 *   open (scroll offsets, search text, selection). sessionStorage.
 *
 * Both survive navigating between pages.
 */
export type UiStateLifetime = 'preference' | 'session'

export interface UiStateDescriptor<T> {
  readonly key: string
  readonly defaultValue: T
  readonly lifetime: UiStateLifetime
  /** Accepts a value read back from storage; rejected values fall back to the default. */
  readonly isValid: (value: unknown) => boolean
}

export interface UiStateOptions {
  /** Defaults to "same shape as the default value" (see `matchesShapeOf`). */
  isValid?: (value: unknown) => boolean
}

export function defineUiState<T>(
  key: string,
  defaultValue: T,
  lifetime: UiStateLifetime,
  options: UiStateOptions = {},
): UiStateDescriptor<T> {
  return Object.freeze({
    key,
    defaultValue,
    lifetime,
    isValid: options.isValid ?? matchesShapeOf(defaultValue),
  })
}

/**
 * One descriptor per instance — per chat session, per widget, per picker.
 * Descriptors are cached per id so hooks see a stable identity across renders.
 */
export function defineUiStateFamily<T>(
  keyPrefix: string,
  defaultValue: T,
  lifetime: UiStateLifetime,
  options: UiStateOptions = {},
): (id: string) => UiStateDescriptor<T> {
  const cache = new Map<string, UiStateDescriptor<T>>()
  return (id: string) => {
    let descriptor = cache.get(id)
    if (!descriptor) {
      descriptor = defineUiState(`${keyPrefix}.${id}`, defaultValue, lifetime, options)
      cache.set(id, descriptor)
    }
    return descriptor
  }
}

/** Validator for a closed set of literal values. */
export const oneOf = (values: readonly unknown[]) => (value: unknown): boolean => values.includes(value)

const mergedWithDefaults = new WeakMap<object, object>()

/**
 * The effective value for a descriptor given what the store holds.
 *
 * Missing or invalid values fall back to the default. Object values are laid
 * over the default so fields added by a later build still get their
 * defaults; the merge is cached per stored object, keeping selector results
 * referentially stable.
 */
export function resolveUiState<T>(descriptor: UiStateDescriptor<T>, stored: unknown): T {
  if (stored === undefined || !descriptor.isValid(stored)) return descriptor.defaultValue
  const defaults = descriptor.defaultValue
  if (isPlainObject(defaults) && isPlainObject(stored)) {
    if (Object.keys(defaults).every(field => field in stored)) return stored as T
    let merged = mergedWithDefaults.get(stored)
    if (!merged) {
      merged = { ...defaults, ...stored }
      mergedWithDefaults.set(stored, merged)
    }
    return merged as T
  }
  return stored as T
}

/**
 * Whether a value equals the descriptor's default. Default values are not
 * stored at all, which keeps storage lean and makes "reset" a removal.
 */
export function isDefaultUiValue<T>(descriptor: UiStateDescriptor<T>, value: T): boolean {
  const defaults: unknown = descriptor.defaultValue
  if (Object.is(value, defaults)) return true
  return Array.isArray(defaults) && Array.isArray(value) && defaults.length === 0 && value.length === 0
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function matchesShapeOf(defaultValue: unknown): (value: unknown) => boolean {
  if (defaultValue === null) return value => value !== undefined
  if (Array.isArray(defaultValue)) return value => Array.isArray(value)
  if (isPlainObject(defaultValue)) return isPlainObject
  const type = typeof defaultValue
  return value => typeof value === type
}
