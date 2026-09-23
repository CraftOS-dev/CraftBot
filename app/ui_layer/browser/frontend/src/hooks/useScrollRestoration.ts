import { useEffect, type RefObject } from 'react'
import { useStore } from 'react-redux'
import type { RootState } from '../store'
import { useAppDispatch } from '../store/hooks'
import { selectUiState } from '../store/selectors/ui'
import { setUiState } from '../store/slices/uiSlice'
import type { UiStateDescriptor } from '../store/uiState'

// Content usually arrives after mount (socket data, measured grids), so a
// restore keeps retrying until the saved offset is reachable — for at most
// this long.
const RESTORE_TIMEOUT_MS = 1500

// Any of these means the user is scrolling on their own: stop restoring.
const USER_SCROLL_EVENTS = ['wheel', 'touchstart', 'pointerdown', 'keydown'] as const

/**
 * Remembers a scroll container's position under `descriptor`.
 *
 * Saves `scrollTop` as the user scrolls and restores it whenever the
 * container mounts, the descriptor changes (e.g. a different tab shares the
 * container) or `enabled` turns true (e.g. a list finished loading). Saving
 * pauses while a restore is in flight, so an offset clamped by
 * not-yet-loaded content never overwrites the real one.
 */
export function useScrollRestoration(
  descriptor: UiStateDescriptor<number>,
  ref: RefObject<HTMLElement>,
  enabled = true,
): void {
  const dispatch = useAppDispatch()
  const store = useStore<RootState>()

  useEffect(() => {
    const element = ref.current
    if (!element || !enabled) return

    const target = selectUiState(store.getState(), descriptor)
    const startedAt = performance.now()
    let restoring = true
    let restoreFrame = 0
    let saveFrame = 0

    const stopRestoring = () => {
      restoring = false
      cancelAnimationFrame(restoreFrame)
    }

    const restore = () => {
      element.scrollTop = target
      const reached = Math.abs(element.scrollTop - target) <= 1
      if (reached || performance.now() - startedAt > RESTORE_TIMEOUT_MS) {
        stopRestoring()
      } else {
        restoreFrame = requestAnimationFrame(restore)
      }
    }

    const save = () => {
      if (restoring) return
      cancelAnimationFrame(saveFrame)
      saveFrame = requestAnimationFrame(() => {
        dispatch(setUiState(descriptor, Math.round(element.scrollTop)))
      })
    }

    restore()
    element.addEventListener('scroll', save, { passive: true })
    USER_SCROLL_EVENTS.forEach(type => element.addEventListener(type, stopRestoring, { passive: true }))
    return () => {
      stopRestoring()
      cancelAnimationFrame(saveFrame)
      element.removeEventListener('scroll', save)
      USER_SCROLL_EVENTS.forEach(type => element.removeEventListener(type, stopRestoring))
    }
  }, [descriptor, dispatch, enabled, ref, store])
}
