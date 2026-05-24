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
  JUMP_IN_PLACE_DURATION_MS,
  SETTLE_DURATION_MS,
  WANDER_WARMUP_MS,
  buildHopKeyframes,
  buildJumpInPlaceKeyframes,
  buildSettleKeyframes,
  pickIdleCycleDelay,
  pickJumpRest,
  pickPostHopRest,
  readCurrentTranslateX,
  transition,
  type EngineState,
  type Phase,
  type ReactionKind,
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
  /** Monotonic counter — rises by 1 each time a task finishes successfully.
   *  Drives the celebrate (happy) external reaction. */
  successTaskCount?: number
  /** Monotonic counter — rises by 1 each time a task is aborted (status
   *  cancelled or error). Drives the frustrated external reaction. */
  abortedTaskCount?: number
  /** Whether the agent is waiting for a user reply. When true, the
   *  mascot is forced into the waitingJump phase (centers + jumps in
   *  place). Reverts to normal idle when this flips back to false. */
  isWaiting?: boolean
}

export interface BehaviorOutputs {
  /** Ref to attach to the element that gets the hop animations. */
  wanderRef: RefObject<HTMLDivElement>
  /** Current FSM phase — drives renderer conditional logic. */
  phase: Phase
  /** Visual orientation matching the last hop's direction of travel. */
  facing: 'left' | 'right'
  /** Which reaction visual to render. null when phase !== 'reacting'. */
  reaction: ReactionKind | null
  /** Which side of the mascot a peripheral overlay (speech bubble) should
   *  anchor to so it doesn't clip against the stage edges. Derived from
   *  the mascot's target X — bubble sits opposite the mascot's drift. */
  bubbleSide: 'left' | 'right'
  /** True iff the FSM is in 'resting' phase with idleMode === 'track'.
   *  Drives the cursor eye-tracking hook on the consumer side. */
  isEyeTracking: boolean
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
 *  - External reaction triggers fed by the success/aborted task counters.
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

  // ─── Sync: success/aborted task counters → EXTERNAL_REACT ───────────
  // Same pattern as the celebrate-wiggle counter in CraftBotMascot: we
  // remember the prior count and dispatch a reaction when it ticks up.
  // First-mount value is treated as the baseline so we don't fire on
  // initial state hydration.
  useReactionOnIncrease(inputs.successTaskCount, () => {
    dispatch({ type: 'EXTERNAL_REACT', kind: 'happy' })
  })
  useReactionOnIncrease(inputs.abortedTaskCount, () => {
    dispatch({ type: 'EXTERNAL_REACT', kind: 'frustrated' })
  })

  // ─── Sync: isWaiting → SET_WAITING event ────────────────────────────
  // Re-checks on every (input, phase) change so that if a reaction
  // briefly interrupts waitingJump, REACTION_DONE landing in 'resting'
  // immediately re-promotes back to waitingJump while isWaiting is still
  // true. The reducer's SET_WAITING transition is a no-op when the
  // requested phase already matches, so this is safe to fire repeatedly.
  useEffect(() => {
    if (inputs.isWaiting && state.phase !== 'waitingJump') {
      dispatch({ type: 'SET_WAITING', active: true })
    } else if (!inputs.isWaiting && state.phase === 'waitingJump') {
      dispatch({ type: 'SET_WAITING', active: false })
    }
  }, [inputs.isWaiting, state.phase])

  // ─── Effect: idle-mode cycle timer ──────────────────────────────────
  // Self-rescheduling recursive timeout that fires CYCLE_IDLE_MODE on
  // the desired cadence for the *lifetime of the hook*.
  //
  // CRITICAL: this effect runs once on mount and is not redone on phase
  // changes. An earlier version had `[state.phase, state.idleMode]` as
  // deps, but the hop+rest cycle changes phase every 1.3–5.5s, which
  // tore down and rebuilt the 12–20s cycle timer faster than it could
  // ever fire — eye tracking effectively never triggered. Decoupling
  // from phase fixes that.
  //
  // It's safe to fire CYCLE_IDLE_MODE while the FSM is in non-idle
  // phases (reacting / inactive / waitingJump): the reducer's guard
  // short-circuits those into a no-op and the next tick is already
  // scheduled, so cycling resumes naturally once we're back in idle.
  useEffect(() => {
    let timerId: number | null = null
    const schedule = () => {
      timerId = window.setTimeout(() => {
        timerId = null
        dispatch({ type: 'CYCLE_IDLE_MODE' })
        schedule()
      }, pickIdleCycleDelay())
    }
    schedule()
    return () => {
      if (timerId !== null) window.clearTimeout(timerId)
    }
  }, [])

  // ─── Effect: wander timer (resting → hopping) ────────────────────────
  // Fires WANDER_TICK after a delay. Warmup is used for the first
  // resting tick after waking/reaction; full random rest is used after
  // hops so the rhythm matches the old hop+rest cycle (1300–5500ms total).
  //
  // Skipped entirely in track mode — that's the "stand still, eyes
  // follow cursor" idle behavior. The cycle timer above will eventually
  // flip idleMode back to 'wander' and re-arm this effect.
  useEffect(() => {
    const prevPhase = prevPhaseRef.current
    prevPhaseRef.current = state.phase

    if (state.phase !== 'resting') return
    if (state.idleMode === 'track') return

    const delay = prevPhase === 'hopping' ? pickPostHopRest() : WANDER_WARMUP_MS
    const id = window.setTimeout(() => {
      dispatch({ type: 'WANDER_TICK', maxAmp: maxAmpRef.current })
    }, delay)
    return () => window.clearTimeout(id)
  }, [state.phase, state.idleMode])

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

  // ─── Effect: waitingJump animation loop ─────────────────────────────
  // While phase === 'waitingJump', the mascot stands at center and
  // loops vertical jumps. If it entered waitingJump from a non-center
  // X (mid-wander hop, for example), settle to center first, THEN start
  // the loop. The loop schedules each jump with a randomized rest
  // between them so it doesn't feel mechanical.
  //
  // The `cancelled` closure flag (rather than a ref) is what stops the
  // loop on cleanup — every async continuation checks it before
  // scheduling the next step. Animations and timers both get cleaned up.
  useEffect(() => {
    if (state.phase !== 'waitingJump') return
    const el = wanderRef.current
    if (!el) return

    let cancelled = false
    let restTimerId: number | null = null

    const playJump = () => {
      if (cancelled) return
      const node = wanderRef.current
      if (!node) return
      const anim = node.animate(
        buildJumpInPlaceKeyframes(),
        { duration: JUMP_IN_PLACE_DURATION_MS, easing: 'ease-in-out', fill: 'forwards' },
      )
      currentAnimRef.current = anim
      anim.onfinish = () => {
        if (currentAnimRef.current === anim) currentAnimRef.current = null
        if (cancelled) return
        restTimerId = window.setTimeout(playJump, pickJumpRest())
      }
      anim.oncancel = () => {
        if (currentAnimRef.current === anim) currentAnimRef.current = null
      }
    }

    // Settle to center first if needed. Without this, an entry from
    // mid-hop would have the jumps happen at the hop's last X instead
    // of the stage center.
    const currentX = readCurrentTranslateX(el)
    if (Math.abs(currentX) >= 1) {
      if (currentAnimRef.current) {
        try { currentAnimRef.current.commitStyles() } catch { /* noop */ }
        currentAnimRef.current.cancel()
        currentAnimRef.current = null
      }
      const settleAnim = el.animate(
        buildSettleKeyframes(currentX, 0),
        { duration: SETTLE_DURATION_MS, easing: 'ease-in-out', fill: 'forwards' },
      )
      currentAnimRef.current = settleAnim
      settleAnim.onfinish = () => {
        if (currentAnimRef.current === settleAnim) currentAnimRef.current = null
        if (cancelled) return
        playJump()
      }
      settleAnim.oncancel = () => {
        if (currentAnimRef.current === settleAnim) currentAnimRef.current = null
      }
    } else {
      playJump()
    }

    return () => {
      cancelled = true
      if (restTimerId !== null) {
        window.clearTimeout(restTimerId)
        restTimerId = null
      }
    }
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

  // Bubble side derivation. While hopping, we use the hop's destination
  // rather than the (pre-hop) rest position — so when the mascot leaps
  // toward an edge, the bubble pre-switches to the safe side and is
  // already there as the mascot lands. Outside of hopping, state.position
  // is the current rest position.
  const effectiveX = state.phase === 'hopping' ? state.hopTarget : state.position
  // Threshold at 0 (stage midpoint). The mascot's amplitude is symmetric
  // around 0 so any positive X means "right of center" → bubble on the
  // left, and vice versa. No hysteresis needed because hop crossings of
  // center are infrequent and the bubble swap happens during the hop's
  // own motion, masking any visual snap.
  const bubbleSide: 'left' | 'right' = effectiveX > 0 ? 'left' : 'right'

  return {
    wanderRef,
    phase: state.phase,
    facing: (state as EngineState).facing,
    reaction: state.phase === 'reacting' ? state.reactionKind : null,
    bubbleSide,
    isEyeTracking: state.phase === 'resting' && state.idleMode === 'track',
    handleClick,
  }
}

/** Fire `onIncrease` exactly when `counter` ticks up. Mount-time value is
 *  treated as the baseline so initial hydration doesn't spuriously fire.
 *  Used to translate the success/aborted task counters from useMascotState
 *  into one-shot EXTERNAL_REACT dispatches. */
function useReactionOnIncrease(counter: number | undefined, onIncrease: () => void): void {
  const value = counter ?? 0
  const prev = useRef(value)
  // We keep the callback in a ref so consumers can pass an inline arrow
  // without forcing the effect to re-run on every parent render.
  const cb = useRef(onIncrease)
  useEffect(() => { cb.current = onIncrease }, [onIncrease])

  useEffect(() => {
    if (value > prev.current) cb.current()
    prev.current = value
  }, [value])
}
