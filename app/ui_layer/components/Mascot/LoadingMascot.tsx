import { useEffect, useRef } from 'react'
import { CraftBotMascot } from './CraftBotMascot'
import {
  JUMP_IN_PLACE_DURATION_MS,
  buildJumpInPlaceKeyframes,
  pickJumpRest,
} from './mascotEngine'
import styles from './Mascot.module.css'

// LoadingMascot — a loading indicator: the CraftBot mascot jumping in place
// on a loop. It reuses the exact squash-and-stretch jump beats the engine
// plays during its `waitingJump` phase (buildJumpInPlaceKeyframes), so it
// reads as the same character — just standing in for a spinner.
//
// Deliberately minimal: no wander, no sleep, no eye tracking, no engine FSM.
// It can render before the app is interactive (boot splash), so it must not
// depend on WebSocket state or any store.
interface Props {
  /** Pixel size of the mascot SVG. */
  size?: number
}

export function LoadingMascot({ size = 88 }: Props) {
  const bodyRef = useRef<HTMLDivElement>(null)

  // Loop: jump in place → short random rest → jump again. Mirrors the
  // waitingJump loop in useMascotBehavior (a `cancelled` closure flag stops
  // every async continuation before it schedules the next step).
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    // Reduced motion: hold the mascot still rather than looping the jump.
    if (
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return
    }

    let cancelled = false
    let restTimer: number | undefined
    let anim: Animation | null = null

    const jump = () => {
      if (cancelled || !bodyRef.current) return
      anim = el.animate(buildJumpInPlaceKeyframes(), {
        duration: JUMP_IN_PLACE_DURATION_MS,
        easing: 'ease-in-out', // same curve as the hop — linear reads floaty
        fill: 'forwards',
      })
      anim.onfinish = () => {
        if (cancelled) return
        restTimer = window.setTimeout(jump, pickJumpRest())
      }
    }

    jump()
    return () => {
      cancelled = true
      window.clearTimeout(restTimer)
      try { anim?.cancel() } catch { /* already gone */ }
    }
  }, [])

  return (
    <div className={styles.draftStage}>
      <div ref={bodyRef} className={styles.draftBody} style={{ cursor: 'default' }}>
        <CraftBotMascot state="resting" size={size} />
      </div>
    </div>
  )
}
