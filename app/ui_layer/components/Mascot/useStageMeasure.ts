import { useEffect, useLayoutEffect, useState, type RefObject } from 'react'
import { STAGE_EDGE_PADDING_PX } from './mascotEngine'

/** Tracks the content-area width of a measured container.
 *
 *  - Synchronous initial measurement via useLayoutEffect so the first
 *    render has a real number (no zero-then-resize jump).
 *  - ResizeObserver for ongoing updates so the wander range follows the
 *    chat panel as the user drags the resize handle.
 *
 *  Returns the *content* width (= clientWidth - 2 × padding). The mascot
 *  layout uses this to compute the wander amplitude and the renderer-
 *  card's max width.
 */
export function useStageMeasure(
  ref: RefObject<HTMLElement>,
  paddingPx: number = STAGE_EDGE_PADDING_PX,
): number {
  const [width, setWidth] = useState(0)

  useLayoutEffect(() => {
    if (ref.current) {
      setWidth(ref.current.clientWidth - 2 * paddingPx)
    }
  }, [ref, paddingPx])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry) setWidth(entry.contentRect.width)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])

  return width
}
