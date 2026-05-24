import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  type RefObject,
} from 'react'
import {
  HAPPY_DURATION_MS,
  HOP_DURATION_MS,
  INITIAL_STATE,
  SETTLE_DURATION_MS,
  WANDER_WARMUP_MS,
  buildHopKeyframes,
  buildSettleKeyframes,
  pickPostHopRest,
  readCurrentTranslateX,
  transition,
  type EngineState,
  type Phase,
} from './mascotEngine'

export interface BehaviorInputs {
  /** Whether the mascot is free to wander. False when the agent is
   *  sleeping, an action card is pinned, or the panel is collapsed. */
  isActive: boolean
  /** Click guard: when false (panel collapsed or pinned by an action),
   *  clicks on the mascot are ignored entirely. Distinct from `isActive`
   *  because a sleeping (asleep but not pinned) mascot should still wake
   *  on click. */
  isClickable: boolean
  /** Whether the mascot is currently in its "needs to be woken" state.
   *  When true, a click also fires `onWakeFromSleep` before reacting. */
  isAsleep: boolean
  /** Maximum X-amplitude the mascot's center can drift from stage
   *  midpoint (computed from stage width + mascot size). */
  maxAmplitude: number
  /** External wake-up trigger — typically `resetIdleTimer` from
   *  useMascotState. Called on click when the mascot is asleep. */
  onWakeFromSleep: () => void
}

export interface BehaviorOutputs {
  /** Ref to attach to the element that gets the hop animations. */
  wanderRef: RefObject<HTMLDivElement>
  /** Current FSM phase — drives renderer conditional logic. */
  phase: Phase
  /** Visual orientation matching the last hop's direction of travel. */
  facing: 'left' | 'right'
  /** True iff in the 'reacting' phase. Passed down to CraftBotMascot
   *  to render > < eyes + light rays. */
  isReacting: boolean
  /** Onclick callback for the mascot wrapper. */
  handleClick: () => void
}

/** React integration layer for the mascot FSM. Owns:
 *
 *  - The reducer state (`useReducer` over the pure transition function).
 *  - Refs to the latest input values (so timer callbacks see fresh data).
 *  - One effect per phase that applies the corresponding side effect
 *    (wander timer → WANDER_TICK, hop animation → HOP_DONE, settle
 *    animation back to center on inactive, reaction timer → REACTION_DONE).
 *  - The click handler, which does the synchronous DOM snap to avoid
 *    a one-frame flicker before the reaction effect runs.
 */
export function useMascotBehavior(inputs: BehaviorInputs): BehaviorOutputs {
  const [state, dispatch] = useReducer(transition, INITIAL_STATE)
  const wanderRef = useRef<HTMLDivElement>(null)

  // The wander timer's callback closes over inputs.maxAmplitude. To make
  // sure resize events propagate into the next-scheduled tick without
  // tearing down the timer every render, mirror it into a ref.
  const maxAmpRef = useRef(inputs.maxAmplitude)
  useEffect(() => {
    maxAmpRef.current = inputs.maxAmplitude
  }, [inputs.maxAmplitude])

  // Tracks the WAAPI animation currently driving the wander element, if
  // any. Used so the click handler can cancel an in-flight hop and so
  // each new phase's effect can supersede the previous animation.
  const currentAnimRef = useRef<Animation | null>(null)

  // Tracks the phase from the prior render — lets the wander effect
  // distinguish "we just landed a hop" (full random rest) from "we just
  // woke up / reaction ended" (short warmup). Without this distinction
  // the mascot feels sluggish after wake events.
  const prevPhaseRef = useRef<Phase>(INITIAL_STATE.phase)

  // ─── Sync: external isActive → SET_ACTIVE event ─────────────────────
  // Single source of truth for "should we be wandering" — flows through
  // the FSM rather than being checked in every effect.
  useEffect(() => {
    dispatch({ type: 'SET_ACTIVE', active: inputs.isActive })
  }, [inputs.isActive])

  // ─── Effect: wander timer (resting → hopping) ────────────────────────
  // Fires WANDER_TICK after a delay. Warmup is used for the first
  // resting tick after waking/reaction; full random rest is used after
  // hops so the rhythm matches the old hop+rest cycle (1300–5500ms total).
  useEffect(() => {
    const prevPhase = prevPhaseRef.current
    prevPhaseRef.current = state.phase

    if (state.phase !== 'resting') return

    const delay = prevPhase === 'hopping' ? pickPostHopRest() : WANDER_WARMUP_MS
    const id = window.setTimeout(() => {
      dispatch({ type: 'WANDER_TICK', maxAmp: maxAmpRef.current })
    }, delay)
    return () => window.clearTimeout(id)
  }, [state.phase])

  // ─── Effect: hop animation (drives HOP_DONE) ─────────────────────────
  // When the FSM enters 'hopping', start the WAAPI keyframe sequence
  // from state.position → state.hopTarget. onfinish dispatches HOP_DONE
  // which the reducer turns into 'resting' with the new position.
  //
  // IMPORTANT: no cleanup function here. Returning `() => anim.cancel()`
  // looks defensive but it teleports — cleanup runs on every dep change
  // including the natural HOP_DONE → 'resting' transition, and cancel()
  // on a finished+fill:forwards animation REMOVES the fill effect,
  // snapping the element back to its un-animated style (translateX(0)).
  // Instead we let each animation run to completion (its onfinish fires
  // HOP_DONE) or be overridden by the next phase's animation (WAAPI
  // composites; the newer animation wins on the same property).
  // Interruptions that need an explicit cancel are owned by the *next*
  // setup (settle pre-cancel) or by the click handler.
  useEffect(() => {
    if (state.phase !== 'hopping') return
    const el = wanderRef.current
    if (!el) return

    const anim = el.animate(
      buildHopKeyframes(state.position, state.hopTarget),
      { duration: HOP_DURATION_MS, easing: 'ease-in-out', fill: 'forwards' },
    )
    currentAnimRef.current = anim
    anim.onfinish = () => {
      if (currentAnimRef.current === anim) currentAnimRef.current = null
      dispatch({ type: 'HOP_DONE' })
    }
    anim.oncancel = () => {
      if (currentAnimRef.current === anim) currentAnimRef.current = null
    }
  }, [state.phase, state.position, state.hopTarget])

  // ─── Effect: settle to center on 'inactive' ──────────────────────────
  // When the mascot has to stop wandering (action arrives, panel
  // collapses, agent goes to sleep), animate the body smoothly back to
  // position 0. The CSS layer separately switches between mascotLeft and
  // mascotCenter; this only handles the within-layer translateX reset.
  useEffect(() => {
    if (state.phase !== 'inactive') return
    const el = wanderRef.current
    if (!el) return

    const currentX = readCurrentTranslateX(el)
    if (Math.abs(currentX) < 1) {
      // Already at center. Clear any leftover inline transform so future
      // animations have a clean starting state.
      el.style.transform = ''
      return
    }

    // If a hop was in flight, commit its current visual state to inline
    // style before canceling. Without commitStyles, cancel removes the
    // animation's fill effect and snaps the element back to its
    // un-animated style — which would then disagree with the settle
    // keyframes' starting position and cause a one-frame snap.
    if (currentAnimRef.current) {
      try { currentAnimRef.current.commitStyles() } catch { /* noop */ }
      currentAnimRef.current.cancel()
      currentAnimRef.current = null
    }

    const anim = el.animate(
      buildSettleKeyframes(currentX, 0),
      { duration: SETTLE_DURATION_MS, easing: 'ease-in-out', fill: 'forwards' },
    )
    currentAnimRef.current = anim
    const clear = () => {
      if (currentAnimRef.current === anim) currentAnimRef.current = null
    }
    anim.onfinish = clear
    anim.oncancel = clear
  }, [state.phase])

  // ─── Effect: reaction timer (reacting → resting) ─────────────────────
  // The snap-to-ground inline-style write happens *synchronously* in the
  // click handler below to avoid a one-frame flicker; this effect only
  // schedules the timeout that ends the reaction.
  useEffect(() => {
    if (state.phase !== 'reacting') return
    const id = window.setTimeout(() => {
      dispatch({ type: 'REACTION_DONE' })
    }, HAPPY_DURATION_MS)
    return () => window.clearTimeout(id)
  }, [state.phase])

  // ─── Click handler ──────────────────────────────────────────────────
  // Synchronous DOM work happens here (cancel anim, snap inline style)
  // rather than in a useEffect, so the body settles in the same frame
  // as the click event. The dispatch then notifies the FSM, which on
  // next render drives the reaction effect's timer.
  const handleClick = useCallback(() => {
    if (!inputs.isClickable) return
    if (state.phase === 'reacting') return

    const el = wanderRef.current
    if (!el) return

    // Snapshot the on-screen position BEFORE we touch anything — if
    // we're mid-hop, this is what stops the reaction from snapping the
    // body to the canceled hop's destination.
    const currentX = readCurrentTranslateX(el)
    // Capture the current full transform (matrix form including scale +
    // Y offset from the in-flight hop) so the settle animation below
    // can start from exactly the visual state at click time.
    const computedTransform = window.getComputedStyle(el).transform
    const startTransform =
      !computedTransform || computedTransform === 'none'
        ? 'matrix(1, 0, 0, 1, 0, 0)'
        : computedTransform

    // Commit the in-flight animation's current frame to inline style
    // BEFORE canceling, so the cancel doesn't yank the element back to
    // its un-animated style. The settle animation below then animates
    // FROM that committed state TO the ground pose.
    if (currentAnimRef.current) {
      try { currentAnimRef.current.commitStyles() } catch { /* noop */ }
      currentAnimRef.current.cancel()
      currentAnimRef.current = null
    }

    // Instead of an instant snap to ground, run a short ease-out from
    // the click-moment pose to the standing pose. Mid-hop, the body has
    // a non-zero Y (up to −22px at peak) and non-unit scale; an instant
    // snap to translate(currentX, 0) scale(1, 1) jumps the body up to
    // 25px vertically + visibly resizes it, which reads as a teleport.
    // 150ms is short enough that the reaction's > < eyes and ray burst
    // still feel instantly responsive, but long enough that the body
    // motion is perceived as a deliberate settle.
    //
    // Visual X stays constant throughout the interpolation because both
    // keyframes resolve to the same on-screen X (readCurrentTranslateX
    // already accounts for the scale × transform-origin offset, so the
    // ground keyframe's matrix has the same effective X as the source).
    const settleAnim = el.animate(
      [
        { transform: startTransform, offset: 0 },
        { transform: `matrix(1, 0, 0, 1, ${currentX}, 0)`, offset: 1 },
      ],
      { duration: 150, easing: 'ease-out', fill: 'forwards' },
    )
    currentAnimRef.current = settleAnim
    const clearSettle = () => {
      if (currentAnimRef.current === settleAnim) currentAnimRef.current = null
    }
    settleAnim.onfinish = clearSettle
    settleAnim.oncancel = clearSettle

    // Wake from sleep if needed. The external resetIdleTimer triggers
    // a state update; the SET_ACTIVE sync effect will then transition
    // the FSM out of 'inactive' on the next render. Our CLICK dispatch
    // below also lifts the FSM into 'reacting' even from 'inactive',
    // so the reaction starts immediately without waiting for the wake.
    if (inputs.isAsleep) {
      inputs.onWakeFromSleep()
    }

    dispatch({ type: 'CLICK', currentVisualX: currentX })
  }, [state.phase, inputs])

  return {
    wanderRef,
    phase: state.phase,
    facing: (state as EngineState).facing,
    isReacting: state.phase === 'reacting',
    handleClick,
  }
}
