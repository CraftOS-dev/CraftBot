import { useLayoutEffect, useRef } from 'react'

const ANIMATION_DURATION_MS = 250

/**
 * Animates task row position changes using the FLIP technique. When a task
 * moves between the active and ended sections (or shifts within a section as
 * other tasks arrive / depart), it slides from its previous position to the
 * new one instead of teleporting.
 *
 * Returns a `setRef(id)` factory the parent attaches to each row's outer
 * element. The hook keys positions by task id, so siblings reordering inside
 * the same scroll container animate cleanly without re-mounting.
 *
 * Implementation notes:
 * - Uses `offsetTop` (container-relative) rather than `getBoundingClientRect`
 *   so user scrolling doesn't trigger spurious animations.
 * - Forces a synchronous reflow between Invert and Play so the inverted
 *   transform commits in the same frame as it was applied — no flicker.
 */
export function useTaskListFLIP() {
  const elementsRef = useRef<Map<string, HTMLElement>>(new Map())
  const prevPositionsRef = useRef<Map<string, number>>(new Map())

  const setRef = (id: string) => (el: HTMLElement | null) => {
    if (el) elementsRef.current.set(id, el)
    else elementsRef.current.delete(id)
  }

  useLayoutEffect(() => {
    const newPositions = new Map<string, number>()
    elementsRef.current.forEach((el, id) => {
      newPositions.set(id, el.offsetTop)
    })

    elementsRef.current.forEach((el, id) => {
      const prev = prevPositionsRef.current.get(id)
      const next = newPositions.get(id)
      if (prev == null || next == null) return
      const dy = prev - next
      if (Math.abs(dy) < 1) return

      el.style.transition = 'none'
      el.style.transform = `translateY(${dy}px)`
      // Force a reflow so the inverted state commits before the transition
      // kicks in. Without this, the browser batches and the user sees a jump.
      void el.offsetHeight
      el.style.transition = `transform ${ANIMATION_DURATION_MS}ms ease`
      el.style.transform = ''
    })

    prevPositionsRef.current = newPositions
  })

  return setRef
}
