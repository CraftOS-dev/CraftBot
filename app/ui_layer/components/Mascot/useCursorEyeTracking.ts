import { useEffect, type RefObject } from 'react'

// Eye-track range. Eyes shift at most ±MAX_OFFSET_X px horizontally and
// ±MAX_OFFSET_Y px vertically. The amount is mapped linearly from cursor
// distance, clamped at MAX_DIST (after which the eyes are pinned at the
// extreme — keeps the look believable when the cursor is far off-screen).
const MAX_OFFSET_X = 4
const MAX_OFFSET_Y = 3
const MAX_DIST = 250

interface Options {
  /** When false, the hook detaches its listeners and resets the eye
   *  transform to identity. Driven by useMascotBehavior.isEyeTracking. */
  enabled: boolean
  /** The mascot SVG's facing direction. When 'left', the eyes are
   *  rendered inside a mirrored <g>, so the X axis is flipped — we
   *  invert the cursor-relative X to keep gaze tracking screen-correct. */
  facing: 'left' | 'right'
}

/** Drives the eye-tracking idle animation: while enabled, the mascot's
 *  eyes shift toward the user's cursor position.
 *
 *  Implementation note: this hook deliberately bypasses React state and
 *  writes the SVG `transform` attribute directly. Eye tracking fires on
 *  every mousemove (10s–100s of times per second) and routing each
 *  update through React would re-render the whole mascot subtree for a
 *  tiny visual delta. Direct DOM writes keep the cost at ~one
 *  setAttribute per mousemove with zero virtual-DOM churn.
 *
 *  Trade-off: the JSX must NOT set its own `transform` attribute on the
 *  eyeGroup element — that would clobber the hook's writes on every
 *  React render. The component contract is "give me a ref to a bare g
 *  element and I'll own its transform". */
export function useCursorEyeTracking(
  mascotRef: RefObject<HTMLElement>,
  eyeGroupRef: RefObject<SVGGElement>,
  { enabled, facing }: Options,
): void {
  useEffect(() => {
    const reset = () => {
      const g = eyeGroupRef.current
      if (g) g.setAttribute('transform', 'translate(0 0)')
    }

    if (!enabled) {
      reset()
      return
    }

    // Initial reset — when tracking just turned on, start from center
    // and let the first mousemove pull the eyes toward the cursor. The
    // alternative (waiting for a mousemove before any visible change)
    // can leave stale offsets from a previous tracking session.
    reset()

    const update = (clientX: number, clientY: number) => {
      const el = mascotRef.current
      const g = eyeGroupRef.current
      if (!el || !g) return
      const rect = el.getBoundingClientRect()
      const dx = clientX - (rect.left + rect.width / 2)
      const dy = clientY - (rect.top + rect.height / 2)
      const ox = clamp((dx / MAX_DIST) * MAX_OFFSET_X, -MAX_OFFSET_X, MAX_OFFSET_X)
      const oy = clamp((dy / MAX_DIST) * MAX_OFFSET_Y, -MAX_OFFSET_Y, MAX_OFFSET_Y)
      // Compensate for the SVG mirror group when facing left — that
      // group flips child X, so we pre-flip our offset to cancel it
      // out and keep the gaze tracking the cursor's actual screen X.
      const finalX = facing === 'left' ? -ox : ox
      g.setAttribute('transform', `translate(${finalX} ${oy})`)
    }

    const onMove = (e: MouseEvent) => update(e.clientX, e.clientY)
    window.addEventListener('mousemove', onMove, { passive: true })
    return () => {
      window.removeEventListener('mousemove', onMove)
      reset()
    }
  }, [enabled, facing, mascotRef, eyeGroupRef])
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}
