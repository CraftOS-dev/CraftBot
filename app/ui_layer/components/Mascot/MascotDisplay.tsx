import { useRef, type CSSProperties } from 'react'
import { CraftBotMascot } from './CraftBotMascot'
import { MascotBackground } from './MascotBackground'
import { SpeechBubble } from './SpeechBubble'
import { useMascotState } from './useMascotState'
import { useMascotNarration } from './useMascotNarration'
import { useStageMeasure } from './useStageMeasure'
import { useMascotBehavior } from './useMascotBehavior'
import { useCursorEyeTracking } from './useCursorEyeTracking'
import { useWheelZoom } from './useWheelZoom'
import { computeMaxAmplitude } from './mascotEngine'
import styles from './Mascot.module.css'

interface Props {
  /** Optional pixel size for the mascot SVG. Defaults to 120. */
  mascotSize?: number
}

// Zoom configuration for the stage's scroll-to-zoom interaction.
//   - max=1 caps zoom-in at the design baseline (user can only scroll
//     to shrink, not enlarge past the intended scene scale).
//   - initial < max so the scene starts slightly pulled-back, giving
//     the mascot some breathing room against the background on first
//     paint. The user can still wheel up to max=1 for the baseline view.
const STAGE_ZOOM = {
  min: 0.40,
  max: 1,
  step: 0.1,
  initial: 0.8,
} as const

export function MascotDisplay({ mascotSize = 80 }: Props) {
  const {
    state,
    completedCount,
    successTaskCount,
    abortedTaskCount,
    resetIdleTimer,
  } = useMascotState()
  const { bubble } = useMascotNarration({ mascotState: state })

  // Sleeping states (idle = 30-min idle, stopped/error = external).
  // Only 'idle' is recoverable by clicking; the others stay sleeping.
  const isSleeping = state === 'idle' || state === 'stopped' || state === 'error'
  const canBeWoken = state === 'idle'

  // ── Stage measurement → wander amplitude ───────────────────────────
  const stageRef = useRef<HTMLDivElement>(null)
  const stageContentWidth = useStageMeasure(stageRef)
  const maxAmplitude = computeMaxAmplitude(stageContentWidth, mascotSize)

  // ── Stage scroll-to-zoom ───────────────────────────────────────────
  // useWheelZoom binds the wheel listener (non-passive) and clamps the
  // returned zoom value to STAGE_ZOOM's bounds. Multiplicative stepping
  // and bound enforcement live inside the hook.
  const zoom = useWheelZoom(stageRef, STAGE_ZOOM)

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
