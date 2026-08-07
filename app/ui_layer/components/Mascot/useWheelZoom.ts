import { useEffect, useState, type RefObject } from 'react'

export interface WheelZoomOptions {
  /** Lower bound (zoomed-out limit). */
  min: number
  /** Upper bound (zoomed-in limit). Usually the design baseline (= 1). */
  max: number
  /** Per-wheel-notch step. 0.1 = 10% bigger or 10% smaller per notch.
   *  Applied multiplicatively (1 + step on zoom-in, 1 / (1 + step) on
   *  zoom-out) so the perceptual delta is the same at any zoom level. */
  step: number
  /** Initial zoom value. Should sit within [min, max]; not clamped here
   *  so passing an out-of-range value is a visible error rather than a
   *  silent surprise. Defaults to `max` (full-baseline view). */
  initial?: number
}

/**
 * Bind wheel events on `ref` to a clamped, multiplicatively-stepping
 * zoom value. Returns the current zoom (a number in `[min, max]`).
 *
 * Implementation notes:
 *
 * - The listener is attached via `addEventListener(..., { passive: false })`
 *   so `preventDefault()` actually stops the page-level scroll. React's
 *   `onWheel` is passive by default — using it would let the browser
 *   keep scrolling the page even while we're zooming inside the ref.
 *
 * - Plain wheel (no Ctrl modifier) so the gesture doesn't collide with
 *   the browser's built-in Ctrl-wheel zoom. The host element is small
 *   enough that there's no ambiguity — wheel on it always means zoom.
 *
 * - Steps are multiplicative (×(1 + step) / ÷(1 + step)) rather than
 *   additive so a "notch" feels equally significant at zoom 0.5 as at
 *   zoom 1.0 — without this, low zooms would feel slow and high zooms
 *   would feel jumpy.
 */
export function useWheelZoom(
  ref: RefObject<HTMLElement>,
  options: WheelZoomOptions,
): number {
  const { min, max, step, initial = max } = options
  const [zoom, setZoom] = useState(initial)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      setZoom(z => {
        const factor = e.deltaY < 0 ? 1 + step : 1 / (1 + step)
        return Math.max(min, Math.min(max, z * factor))
      })
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [ref, min, max, step])

  // Bounds can move at runtime (MascotDisplay raises `min` as the stage
  // gets wider relative to its height). Re-clamp the held value so it
  // never sits outside the current bounds.
  useEffect(() => {
    setZoom(z => Math.max(min, Math.min(max, z)))
  }, [min, max])

  return zoom
}
