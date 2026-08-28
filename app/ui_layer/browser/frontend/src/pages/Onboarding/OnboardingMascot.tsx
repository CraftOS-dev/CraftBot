import { useEffect, useRef, useState } from 'react'
import { CraftBotMascot, useCursorEyeTracking } from '@mascot'
import styles from './OnboardingPage.module.css'

// Outro phases, driven by OnboardingPage once onboarding finishes.
export type OutroPhase = 'idle' | 'message' | 'fade' | 'center' | 'jump'

interface Props {
  /** Current step index - a change triggers a celebratory wiggle. */
  stepIndex?: number
  /** Finishing-sequence phase. 'center' slides the mascot to screen centre;
   *  'jump' plays the crouch + launch that flings it off the top. */
  outroPhase?: OutroPhase
}

// A stationary companion for the onboarding wizard. Unlike the dashboard
// mascot it never wanders, jumps, or floats (no useMascotBehavior) - it stays
// pinned, breathes/blinks, celebrates each step, and its eyes follow the
// user's cursor. During the finishing outro it slides to centre and launches.
export function OnboardingMascot({ stepIndex, outroPhase = 'idle' }: Props) {
  const mascotRef = useRef<HTMLDivElement>(null)
  const jumpRef = useRef<HTMLDivElement>(null)
  const eyeGroupRef = useRef<SVGGElement>(null)

  // Eyes track the cursor for the whole wizard, but not once the outro starts.
  useCursorEyeTracking(mascotRef, eyeGroupRef, {
    enabled: outroPhase === 'idle',
    facing: 'right',
  })

  // Celebrate (wiggle) whenever the user advances a step - but not on mount.
  const [completedCount, setCompletedCount] = useState(0)
  const mounted = useRef(false)
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true
      return
    }
    setCompletedCount(c => c + 1)
  }, [stepIndex])

  // Slide the existing mascot from its spot to the centre of the viewport.
  // It's pinned with position:fixed first so it can travel freely (and later
  // fly off-screen) without being clipped by the wizard's overflow.
  useEffect(() => {
    if (outroPhase !== 'center') return
    const el = mascotRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const dx = window.innerWidth / 2 - (rect.left + rect.width / 2)
    const dy = window.innerHeight / 2 - (rect.top + rect.height / 2)
    el.style.position = 'fixed'
    el.style.left = `${rect.left}px`
    el.style.top = `${rect.top}px`
    el.style.width = `${rect.width}px`
    el.style.height = `${rect.height}px`
    el.style.margin = '0'
    el.style.zIndex = '50'
    el.style.transition = 'transform 520ms cubic-bezier(0.4, 0, 0.2, 1)'
    // Next frame so the transition has a start value to animate from.
    const id = requestAnimationFrame(() => {
      el.style.transform = `translate(${dx}px, ${dy}px)`
    })
    return () => cancelAnimationFrame(id)
  }, [outroPhase])

  // Crouch, hold, then jump off the top of the screen. Timeline (820ms):
  // squash into a deep crouch and HOLD it for ~0.5s (anticipation); then the
  // body starts stretching in place, and once it's past halfway through the
  // stretch the launch kicks in - so the rest of the stretch and the upward
  // flight happen at the same time, then it rockets off the top. Origin is the
  // feet (set in CSS) so the squash reads as a crouch, not a shrink.
  useEffect(() => {
    if (outroPhase !== 'jump') return
    const el = jumpRef.current
    if (!el) return
    const offscreen = -(window.innerHeight * 0.85 + 240)
    const anim = el.animate(
      [
        { transform: 'translateY(0px) scale(1, 1)', offset: 0, easing: 'cubic-bezier(0.3, 0, 0.4, 1)' },
        // Crouch reached (~0.33s) and held (~0.46s total).
        { transform: 'translateY(6px) scale(1.24, 0.76)', offset: 0.6, easing: 'linear' },
        { transform: 'translateY(6px) scale(1.24, 0.76)', offset: 0.76, easing: 'cubic-bezier(0.2, 0.7, 0.4, 1)' },
        // Stretch begins in place (past halfway un-squashed, barely risen).
        { transform: 'translateY(2px) scale(1.05, 0.99)', offset: 0.8, easing: 'cubic-bezier(0.5, 0, 1, 1)' },
        // Launch: finish the stretch WHILE rocketing off the top.
        { transform: `translateY(${offscreen}px) scale(0.9, 1.12)`, offset: 1 },
      ],
      { duration: 820, fill: 'forwards' },
    )
    return () => { try { anim.cancel() } catch { /* already gone */ } }
  }, [outroPhase])

  return (
    <div ref={mascotRef} className={styles.mascotCol} aria-hidden="true">
      <div ref={jumpRef} className={styles.mascotJump}>
        <CraftBotMascot
          state="resting"
          size={132}
          facing="right"
          eyeGroupRef={eyeGroupRef}
          completedCount={completedCount}
        />
      </div>
    </div>
  )
}
