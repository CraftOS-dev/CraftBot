import { useCallback, useMemo, type Dispatch, type SetStateAction } from 'react'
import type { UiStateDescriptor } from '../store/uiState'
import { usePersistedState } from './usePersistedState'

/**
 * A persisted `Set<string>` — expanded folders, selected rows, open cards.
 * Stored as an array (JSON has no sets); exposed as a Set with the same
 * setter contract as `useState<Set<string>>`, plus a `toggle` shortcut.
 */
export function usePersistedSet(
  descriptor: UiStateDescriptor<string[]>,
): [Set<string>, Dispatch<SetStateAction<Set<string>>>, (id: string) => void] {
  const [items, setItems] = usePersistedState(descriptor)
  const set = useMemo(() => new Set(items), [items])

  const setSet = useCallback((next: SetStateAction<Set<string>>) => {
    setItems(previous => {
      const resolved = typeof next === 'function' ? next(new Set(previous)) : next
      return Array.from(resolved)
    })
  }, [setItems])

  const toggle = useCallback((id: string) => {
    setItems(previous => (
      previous.includes(id) ? previous.filter(item => item !== id) : [...previous, id]
    ))
  }, [setItems])

  return [set, setSet, toggle]
}
