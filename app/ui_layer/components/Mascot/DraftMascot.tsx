import { useEffect, useRef, useState, type RefObject } from 'react'
import { CraftBotMascot } from './CraftBotMascot'
import { useCursorEyeTracking } from './useCursorEyeTracking'
import {
  HOP_DURATION_MS,
  HAPPY_DURATION_MS,
  buildHopKeyframes,
  computeMaxAmplitude,
  pickPostHopRest,
  pickRandomHopTarget,
  readCurrentTranslateX,
  type ReactionKind,
} from './mascotEngine'
import styles from './Mascot.module.css'

// Lightweight mascot for the New Chat hero — no stage scene, no zoom, no
// narration, no engine FSM. Just the character with four simple behaviors
// driven by plain timers:
//   - wanders with hops across the dock's width
//   - eyes follow the cursor while awake ("looking around")
//   - falls asleep after the user goes idle; any activity wakes it
//   - happy reaction when clicked
interface Props {
  /** Pixel size of the mascot SVG. */
  size?: number
  /** When true, plays the exit animation: crouch → spring up → dive down
   *  behind the input shell (which paints above the mascot). The parent
   *  unmounts the component after DRAFT_MASCOT_EXIT_MS. */
  leaving?: boolean
}

/** User inactivity (no pointer/keyboard anywhere) before the mascot naps. */
const SLEEP_AFTER_IDLE_MS = 60_000

/** Exit ("dive into the input box") animation length. The parent should
 *  keep the component mounted this long after setting `leaving`. */
export const DRAFT_MASCOT_EXIT_MS = 1000

/** How far the exit dive drops — enough to fully disappear behind the
 *  input shell for any mascot size this dock uses. */
const EXIT_DROP_PX = 90

export function DraftMascot({ size = 88, leaving = false }: Props) {
  const stageRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const eyeGroupRef = useRef<SVGGElement>(null)

  const [sleeping, setSleeping] = useState(false)
  const [reaction, setReaction] = useState<ReactionKind | null>(null)
  const [facing, setFacing] = useState<'left' | 'right'>('right')

  // Timer-loop mirrors (the wander loop lives outside React renders).
  const posRef = useRef(0)
  const reactionRef = useRef<ReactionKind | null>(null)
  reactionRef.current = reaction

  const reducedMotionRef = useRef(
    typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  // ── Exit: crouch → spring up → dive down behind the input shell ────
  useEffect(() => {
    if (!leaving) return
    const el = bodyRef.current
    if (!el || reducedMotionRef.current) return
    // Start from wherever the body actually is (even mid-hop).
    const x = readCurrentTranslateX(el)
    // Per-SEGMENT easing (each keyframe's `easing` shapes the leg that
    // leaves it). One global curve over a multi-beat sequence averages
    // out to near-linear motion — the crouch, launch, and fall each need
    // their own physics.
    const anim = el.animate(
      [
        // Settle into the crouch — decelerating sink.
        { transform: `translate(${x}px, 0) scale(1, 1)`, offset: 0, easing: 'ease-in-out' },
        // Launch — explosive push-off that decelerates into the apex.
        { transform: `translate(${x}px, 4px) scale(1.18, 0.82)`, offset: 0.35, easing: 'cubic-bezier(0.2, 0.9, 0.35, 1)' },
        // Hang — near-still float at the top of the arc.
        { transform: `translate(${x}px, -28px) scale(0.9, 1.12)`, offset: 0.6, easing: 'linear' },
        // Gravity — accelerating dive behind the input shell.
        { transform: `translate(${x}px, -26px) scale(0.94, 1.06)`, offset: 0.68, easing: 'cubic-bezier(0.55, 0, 0.85, 0.36)' },
        { transform: `translate(${x}px, ${EXIT_DROP_PX}px) scale(0.95, 1.02)`, offset: 1 },
      ],
      { duration: DRAFT_MASCOT_EXIT_MS - 20, fill: 'forwards' },
    )
    return () => { try { anim.cancel() } catch { /* already gone */ } }
  }, [leaving])

  // ── Wander: hop → rest → hop, paused while sleeping/reacting ───────
  useEffect(() => {
    if (sleeping || leaving || reducedMotionRef.current) return
    let cancelled = false
    let timer: number | undefined
    let anim: Animation | null = null

    const scheduleNext = (delay: number) => {
      timer = window.setTimeout(hop, delay)
    }

    const hop = () => {
      if (cancelled) return
      const el = bodyRef.current
      const stage = stageRef.current
      // Skip beats while hidden, mid-reaction, or unmeasurable — check
      // again soon rather than dropping the loop.
      if (!el || !stage || document.hidden || reactionRef.current) {
        scheduleNext(1000)
        return
      }
      const maxAmp = computeMaxAmplitude(stage.clientWidth, size)
      const target = pickRandomHopTarget(posRef.current, maxAmp)
      setFacing(target < posRef.current ? 'left' : 'right')
      anim = el.animate(buildHopKeyframes(posRef.current, target), {
        duration: HOP_DURATION_MS,
        easing: 'ease-in-out', // same curve as useMascotBehavior — linear reads floaty
        fill: 'forwards',
      })
      anim.onfinish = () => {
        // Commit the landing spot as inline style, then release the fill
        // so future inline writes aren't overridden by the animation.
        el.style.transform = `translate(${target}px, 0)`
        try { anim?.cancel() } catch { /* already gone */ }
        posRef.current = target
        if (!cancelled) scheduleNext(pickPostHopRest())
      }
    }

    scheduleNext(pickPostHopRest())
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      try { anim?.cancel() } catch { /* already gone */ }
    }
  }, [sleeping, leaving, size])

  // ── Idle → sleep; any user activity wakes and re-arms ──────────────
  useEffect(() => {
    let timer: number | undefined
    const arm = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setSleeping(true), SLEEP_AFTER_IDLE_MS)
    }
    const onActivity = () => {
      setSleeping(false)
      arm()
    }
    arm()
    window.addEventListener('pointermove', onActivity, { passive: true })
    window.addEventListener('pointerdown', onActivity, { passive: true })
    window.addEventListener('keydown', onActivity)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointermove', onActivity)
      window.removeEventListener('pointerdown', onActivity)
      window.removeEventListener('keydown', onActivity)
    }
  }, [])

  // ── Click → wake + happy burst ──────────────────────────────────────
  const reactionTimerRef = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(reactionTimerRef.current), [])
  const handleClick = () => {
    if (leaving) return
    setSleeping(false)
    setReaction('happy')
    window.clearTimeout(reactionTimerRef.current)
    reactionTimerRef.current = window.setTimeout(() => setReaction(null), HAPPY_DURATION_MS)
  }

  // ── Eyes follow the cursor while awake and not mid-reaction ────────
  useCursorEyeTracking(bodyRef as RefObject<HTMLElement>, eyeGroupRef, {
    enabled: !sleeping && !reaction && !leaving,
    facing,
  })

  return (
    <div ref={stageRef} className={styles.draftStage}>
      <div
        ref={bodyRef}
        className={styles.draftBody}
        onClick={handleClick}
        title="CraftBot"
      >
        <CraftBotMascot
          state={sleeping ? 'idle' : 'resting'}
          size={size}
          facing={facing}
          reaction={reaction}
          eyeGroupRef={eyeGroupRef}
        />
      </div>
    </div>
  )
}
