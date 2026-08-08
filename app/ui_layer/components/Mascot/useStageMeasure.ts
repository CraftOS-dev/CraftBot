import { useEffect, useLayoutEffect, useState, type RefObject } from 'react'
import { STAGE_EDGE_PADDING_PX } from './mascotEngine'

export interface StageSize {
  width: number
  height: number
}

/** Tracks the content-area size of a measured container.
 *
 *  - Synchronous initial measurement via useLayoutEffect so the first
 *    render has a real number (no zero-then-resize jump).
 *  - ResizeObserver for ongoing updates so the wander range follows the
 *    chat panel as the user drags the resize handle.
 *
 *  Returns the *content* box (= client size − 2 × padding). Width drives the
 *  wander amplitude; height drives the mascot's own size, because that's the
 *  dimension the background scene is anchored to (see MASCOT_SIZE_RATIO).
 */
export function useStageMeasure(
  ref: RefObject<HTMLElement>,
  paddingPx: number = STAGE_EDGE_PADDING_PX,
): StageSize {
  const [size, setSize] = useState<StageSize>({ width: 0, height: 0 })

  useLayoutEffect(() => {
    const el = ref.current
    if (el) {
      setSize({
        width: el.clientWidth - 2 * paddingPx,
        height: el.clientHeight - 2 * paddingPx,
      })
    }
  }, [ref, paddingPx])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(entries => {
      const rect = entries[0]?.contentRect
      if (!rect) return
      // contentRect is already the content box, so no padding subtraction here.
      setSize(prev => (
        prev.width === rect.width && prev.height === rect.height
          ? prev
          : { width: rect.width, height: rect.height }
      ))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])

  return size
}
