import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { CraftBotMascot } from './CraftBotMascot'
import { MascotBackground } from './MascotBackground'
import { SpeechBubble } from './SpeechBubble'
import { useMascotState } from './useMascotState'
import { useMascotNarration } from './useMascotNarration'
import { useStageMeasure } from './useStageMeasure'
import { useMascotBehavior } from './useMascotBehavior'
import { useCursorEyeTracking } from './useCursorEyeTracking'
import { useWheelZoom } from './useWheelZoom'
import { computeMaxAmplitude, STAGE_BODY_SCALE } from './mascotEngine'
import styles from './Mascot.module.css'

interface LocationSpec {
  day_image: string
  night_image: string
  image_grass_y?: string
  ground_line_y?: string
}

export interface MascotPetProps {
  /** Pet stage 1..5 — drives body scale. Stage 5 = mature (no shrink). */
  stage?: number
  /** Pet mood 0..100 — drives idle variant (sad/normal/happy). */
  mood?: number
  /** Pet hunger 0..100 — drives hungry idle variant + sigh overlay. */
  hunger?: number
  /** Resolved body fill color (CSS color string). */
  bodyColor?: string
  /** Resolved accent color (applied to eyes + antenna). */
  accentColor?: string
  /** Antenna variant id. */
  antennaVariant?: string | null
  /** Accessory id. */
  accessory?: string | null
  /** Background location spec. */
  location?: LocationSpec | null
  /** Monotonic nonce: bump from outside to trigger the stage-up celebration. */
  stageUpNonce?: number
  /** Monotonic nonce: bump from outside to trigger the eating animation. */
  fedNonce?: number
  /** Monotonic nonce: bump from outside to trigger the petted blush burst. */
  pettedNonce?: number
  /** Persist callback when the user releases a drag. */
  onDragRelease?: (x: number, y: number) => void
  /** Click callback — fires when the user taps the mascot. Pet panel
   *  wires this to petStroke so clicking = petting. */
  onClick?: () => void
}

interface Props extends MascotPetProps {
  /** Optional pixel size for the mascot SVG. Defaults to 80. */
  mascotSize?: number
  /** 'chat' = no HUD/feed/pickers, drag enabled.
   *  'panel' = larger stage; consumer wraps HUD/pickers around it. */
  variant?: 'chat' | 'panel'
}

const STAGE_ZOOM = {
  min: 0.40,
  max: 1,
  step: 0.1,
  initial: 0.8,
} as const

export function MascotDisplay({
  mascotSize = 80,
  variant = 'chat',
  stage = 5,
  mood = 50,
  hunger = 0,
  bodyColor,
  accentColor,
  antennaVariant = 'antenna_1',
  accessory = null,
  location = null,
  stageUpNonce = 0,
  fedNonce = 0,
  pettedNonce = 0,
  onDragRelease,
  onClick,
}: Props) {
  const {
    state,
    completedCount,
    successTaskCount,
    abortedTaskCount,
    resetIdleTimer,
  } = useMascotState()
  const { bubble } = useMascotNarration({ mascotState: state })

  // Sleeping states (idle = 30-min idle, stopped/error = external).
  const isSleeping = state === 'idle' || state === 'stopped' || state === 'error'
  const canBeWoken = state === 'idle'

  const stageRef = useRef<HTMLDivElement>(null)
  const stageContentWidth = useStageMeasure(stageRef)

  const zoom = useWheelZoom(stageRef, STAGE_ZOOM)
  // Amplitude depends on zoom — at low zoom the mascot has more visible
  // stage to wander/drag across in LOCAL pixels (since each local pixel
  // covers fewer screen pixels). See computeMaxAmplitude in mascotEngine.
  const maxAmplitude = computeMaxAmplitude(stageContentWidth, mascotSize, zoom)

  const {
    wanderRef,
    facing,
    reaction,
    bubbleSide,
    isEyeTracking,
    handleClick,
    handlePointerDown,
    dangleRef,
    idleVariant,
    isEating,
    isStageUp,
    isPetted,
    isDragging,
  } = useMascotBehavior({
    isActive: !isSleeping,
    isClickable: true,
    isAsleep: canBeWoken,
    maxAmplitude,
    onWakeFromSleep: resetIdleTimer,
    successTaskCount,
    abortedTaskCount,
    isWaiting: state === 'waiting',
    mood,
    hunger,
    draggable: true,
    onDragRelease,
    stageUpNonce,
    fedNonce,
    pettedNonce,
    zoom,
    // Pass bodyScale so the dangle rotation pivot can track the body's
    // scaled position at every stage instead of being pinned to a
    // mascotSize-relative %.
    bodyScale: STAGE_BODY_SCALE[stage] ?? 1,
    onClick,
  })

  const eyeGroupRef = useRef<SVGGElement>(null)
  useCursorEyeTracking(wanderRef, eyeGroupRef, {
    enabled: isEyeTracking,
    facing,
  })

  const isPanel = variant === 'panel'

  // ── Scene pan ────────────────────────────────────────────────────
  // Dragging an empty stage area horizontally pans the scene so the
  // user can peek at the left/right edges of the background image.
  // The same offset is applied to both the background AND the mascot
  // layer (via the --scene-pan-x CSS variable) so they move together
  // in lockstep — no more "mascot stays put while scene slides under
  // it" glitch. Only active in the 'panel' variant.
  const [sceneOffsetX, setSceneOffsetX] = useState(0)
  // Image aspect = naturalWidth / naturalHeight, learned from the bg
  // <img> onLoad callback. 16:9 fallback for the first paint.
  const [imageAspect, setImageAspect] = useState(16 / 9)
  const sceneDragRef = useRef<{
    startPointerX: number
    startOffsetX: number
    pointerId: number
  } | null>(null)

  /** Max |pan| in CSS px before the image edge would clear the stage.
   *  The bg image is centered, sized at bg-zoom × stage-height tall and
   *  aspect-wide, then user-zoomed. Whichever side overflows the stage
   *  is the budget we can pan into — split evenly across both sides
   *  because the image starts centered. Returns 0 when the image is
   *  narrower than the stage (nothing to reveal). */
  const computeMaxPan = useCallback((): number => {
    const stage = stageRef.current
    if (!stage) return 0
    // bg-zoom default lives in Mascot.module.css (--bg-zoom: 4). Kept
    // in sync here so the clamp math matches the rendered image size.
    const BG_ZOOM = 4
    const stageH = stage.clientHeight
    const stageW = stage.clientWidth
    const visibleImageWidth = stageH * BG_ZOOM * imageAspect * zoom
    return Math.max(0, (visibleImageWidth - stageW) / 2)
  }, [imageAspect, zoom])

  // Re-clamp when zoom or image aspect changes — zoom-out shrinks the
  // pan budget, and the current offset may now fall outside it.
  useEffect(() => {
    const max = computeMaxPan()
    setSceneOffsetX((prev) => Math.max(-max, Math.min(max, prev)))
  }, [computeMaxPan])

  const handleStagePointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!isPanel) return
      // Mascot owns its own drag — ignore presses that landed on it.
      if (wanderRef.current?.contains(e.target as Node)) return
      sceneDragRef.current = {
        startPointerX: e.clientX,
        startOffsetX: sceneOffsetX,
        pointerId: e.pointerId,
      }
      const onMove = (ev: PointerEvent) => {
        const d = sceneDragRef.current
        if (!d || ev.pointerId !== d.pointerId) return
        const dx = ev.clientX - d.startPointerX
        const max = computeMaxPan()
        const raw = d.startOffsetX + dx
        setSceneOffsetX(Math.max(-max, Math.min(max, raw)))
      }
      const onUp = (ev: PointerEvent) => {
        const d = sceneDragRef.current
        if (!d || ev.pointerId !== d.pointerId) return
        sceneDragRef.current = null
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        window.removeEventListener('pointercancel', onUp)
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      window.addEventListener('pointercancel', onUp)
    },
    [isPanel, sceneOffsetX, wanderRef, computeMaxPan],
  )

  const stageStyle: CSSProperties = {
    '--mascot-zoom': zoom,
    '--scene-pan-x': `${sceneOffsetX}px`,
  } as CSSProperties

  return (
    <div className={`${styles.display} ${isPanel ? styles.displayPanel : ''}`}>
      <div
        ref={stageRef}
        className={`${styles.stage} ${isPanel ? styles.stagePanel : ''}`}
        style={stageStyle}
        onPointerDown={handleStagePointerDown}
      >
        <MascotBackground location={location} onAspectChange={setImageAspect} />
        <div
          className={`${styles.mascotLayer} ${styles.mascotCenter}`}
          style={{ width: mascotSize, height: mascotSize }}
        >
          <div
            ref={wanderRef}
            className={styles.wander}
            onClick={handleClick}
            onPointerDown={handlePointerDown}
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
            <div className={styles.zoomLayer}>
              <div ref={dangleRef} className={styles.dangleWrapper}>
                <CraftBotMascot
                  state={state}
                  size={mascotSize}
                  completedCount={completedCount}
                  facing={facing}
                  reaction={reaction}
                  eyeGroupRef={eyeGroupRef}
                  stage={stage}
                  bodyColor={bodyColor}
                  accentColor={accentColor}
                  antennaVariant={antennaVariant}
                  accessory={accessory}
                  idleVariant={idleVariant}
                  stageUpOverlay={isStageUp}
                  eatingOverlay={isEating}
                  pettedOverlay={isPetted}
                  hungryOverlay={hunger >= 80 && !isEating && !isStageUp}
                  draggedOverlay={isDragging}
                />
              </div>
              {isStageUp && (
                <div className={styles.stageUpLabel}>
                  Level up!
                </div>
              )}
              <SpeechBubble content={bubble} side={bubbleSide} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
