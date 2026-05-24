import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { CraftBotMascot } from './CraftBotMascot'
import { MascotBackground } from './MascotBackground'
import { SpeechBubble } from './SpeechBubble'
import { useMascotState } from './useMascotState'
import { useMascotNarration } from './useMascotNarration'
import { useStageMeasure } from './useStageMeasure'
import { useMascotBehavior } from './useMascotBehavior'
import { useCursorEyeTracking } from './useCursorEyeTracking'
import { computeMaxAmplitude } from './mascotEngine'
import styles from './Mascot.module.css'

interface Props {
  /** Optional pixel size for the mascot SVG. Defaults to 120. */
  mascotSize?: number
}

// Zoom bounds + per-tick step for the stage's scroll-to-zoom interaction.
// Multiplicative steps (rather than additive) give an even perceptual feel
// at any current zoom level — 10% bigger / 10% smaller per wheel notch.
// ZOOM_MAX is 1 so the default is the largest size — the user can only
// scroll to shrink the mascot, not enlarge past the design baseline.
const ZOOM_MIN = 0.40
const ZOOM_MAX = 1
const ZOOM_STEP = 0.1

export function MascotDisplay({ mascotSize = 80 }: Props) {
  const {
    state,
    completedCount,
    successTaskCount,
    abortedTaskCount,
    resetIdleTimer,
  } = useMascotState()
  const { bubble } = useMascotNarration({ mascotState: state })
  const [zoom, setZoom] = useState(1)

  // Sleeping states (idle = 30-min idle, stopped/error = external).
  // Only 'idle' is recoverable by clicking; the others stay sleeping.
  const isSleeping = state === 'idle' || state === 'stopped' || state === 'error'
  const canBeWoken = state === 'idle'

  // ── Stage measurement → wander amplitude ───────────────────────────
  const stageRef = useRef<HTMLDivElement>(null)
  const stageContentWidth = useStageMeasure(stageRef)
  const maxAmplitude = computeMaxAmplitude(stageContentWidth, mascotSize)

  // ── Behavior FSM ───────────────────────────────────────────────────
  // The mascot is free to wander any time the agent isn't sleeping;
  // clicks are always allowed (sleeping mascots accept clicks so the
  // user can wake them). `isWaiting` flips the FSM into the in-place
  // jump phase whenever the agent reports it's waiting on a user reply.
  const { wanderRef, facing, reaction, bubbleSide, isEyeTracking, handleClick } = useMascotBehavior({
    isActive: !isSleeping,
    isClickable: true,
    isAsleep: canBeWoken,
    maxAmplitude,
    onWakeFromSleep: resetIdleTimer,
    successTaskCount,
    abortedTaskCount,
    isWaiting: state === 'waiting',
  })

  // ── Stage scroll-to-zoom ───────────────────────────────────────────
  // Wheel inside the stage adjusts the mascot's visual scale. We bind
  // via addEventListener (not React's onWheel) with passive:false so
  // preventDefault() actually stops the page-level scroll — React's
  // built-in wheel handler is passive by default and can't block it.
  // Plain wheel (no Ctrl) so it doesn't collide with browser zoom.
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      setZoom(z => {
        // Multiplicative step keeps the perceptual delta consistent
        // across the zoom range (zooming in from 2.0 feels the same as
        // from 0.5).
        const factor = e.deltaY < 0 ? 1 + ZOOM_STEP : 1 / (1 + ZOOM_STEP)
        return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z * factor))
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // ── Cursor eye tracking ────────────────────────────────────────────
  // The hook writes the eye group's transform attribute directly (no
  // React state churn). It activates only during the 'track' idle
  // mode the FSM cycles into periodically — the rest of the time the
  // eyes do their normal blink/closed animations.
  const eyeGroupRef = useRef<SVGGElement>(null)
  useCursorEyeTracking(wanderRef, eyeGroupRef, {
    enabled: isEyeTracking,
    facing,
  })

  return (
    <div className={styles.display}>
      <div
        ref={stageRef}
        className={styles.stage}
        // --mascot-zoom is the user's wheel-zoom value. Read by the
        // mascot's .zoomLayer to scale the character. The background
        // intentionally does NOT scale (see Mascot.module.css), so it
        // ignores this variable.
        style={{ '--mascot-zoom': zoom } as CSSProperties}
      >
        {/* Decorative scene behind the mascot. z-index:0 (mascotLayer
            is z-index:2) + pointer-events:none so it doesn't interfere
            with clicks or the wheel-to-zoom handler on the stage. */}
        <MascotBackground />
        <div
          className={`${styles.mascotLayer} ${styles.mascotCenter}`}
          style={{ width: mascotSize, height: mascotSize }}
        >
          <div
            ref={wanderRef}
            className={styles.wander}
            onClick={handleClick}
            role="button"
            tabIndex={0}
            aria-label="Pet the mascot"
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                handleClick()
              }
            }}
          >
            {/* Zoom wrapper inside .wander so the scale's pivot is the
                mascot's current visual center — wander's hop translateX
                has already shifted the wrapper to the mascot's live
                position, and scaling that wrapper keeps the mascot in
                place rather than drifting toward stage center.
                The scale itself is applied via CSS reading the shared
                --mascot-zoom variable on .stage. */}
            <div className={styles.zoomLayer}>
              <CraftBotMascot
                state={state}
                size={mascotSize}
                completedCount={completedCount}
                facing={facing}
                reaction={reaction}
                eyeGroupRef={eyeGroupRef}
              />
              <SpeechBubble content={bubble} side={bubbleSide} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
