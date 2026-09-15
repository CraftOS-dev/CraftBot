import { useCallback, type Dispatch, type SetStateAction } from 'react'
import { useStore } from 'react-redux'
import type { RootState } from '../store'
import { useAppDispatch, useAppSelector } from '../store/hooks'
import { selectUiState } from '../store/selectors/ui'
import { setUiState } from '../store/slices/uiSlice'
import type { UiStateDescriptor } from '../store/uiState'

/**
 * `useState` for UI state that must outlive the component.
 *
 * The value lives in the Redux `ui` slice, so it survives navigating away
 * and back, and is written to storage according to the descriptor's lifetime.
 * Every component using the same descriptor shares one value.
 *
 * @example
 *   const [width, setWidth] = usePersistedState(UI_STATE.memory.panelWidth)
 */
export function usePersistedState<T>(
  descriptor: UiStateDescriptor<T>,
): [T, Dispatch<SetStateAction<T>>] {
  const value = useAppSelector(state => selectUiState(state, descriptor))
  const dispatch = useAppDispatch()
  const store = useStore<RootState>()

  const setValue = useCallback((next: SetStateAction<T>) => {
    // Updaters read the store, not a render closure, so rapid successive
    // updates (pointer moves, key repeats) never build on a stale value.
    const resolved = typeof next === 'function'
      ? (next as (previous: T) => T)(selectUiState(store.getState(), descriptor))
      : next
    dispatch(setUiState(descriptor, resolved))
  }, [descriptor, dispatch, store])

  return [value, setValue]
}
