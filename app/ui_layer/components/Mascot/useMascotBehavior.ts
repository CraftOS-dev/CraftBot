import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react'
import {
  BODY_FEET_X,
  BODY_FEET_Y,
  EATING_DURATION_MS,
  FALLING_DURATION_MS,
  HAPPY_DURATION_MS,
  HOP_DURATION_MS,
  INITIAL_STATE,
  JUMP_IN_PLACE_DURATION_MS,
  PETTED_DURATION_MS,
  SETTLE_DURATION_MS,
  STAGE_UP_DURATION_MS,
  WANDER_WARMUP_MS,
  buildFallKeyframes,
  buildHopKeyframes,
  buildJumpInPlaceKeyframes,
  buildSettleKeyframes,
  buildStageUpKeyframes,
  pickIdleCycleDelay,
  pickIdleVariant,
  pickJumpRest,
  pickPostHopRest,
  readCurrentTranslateX,
  transition,
  type EngineState,
  type IdleVariant,
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
  /** Pet-system inputs. */
  mood?: number      // 0..100, drives idle variant pick
  hunger?: number    // 0..100, drives hungry idle variant
  /** Whether drag-to-move is enabled. */
  draggable?: boolean
  /** Persist callback fired on drag release (panel uses it to save position). */
  onDragRelease?: (x: number, y: number) => void
  /** Stage-up nonce — rising value triggers the stageUp phase. */
  stageUpNonce?: number
  /** Feed nonce — rising value triggers the eating phase. */
  fedNonce?: number
  /** Petted nonce — rising value triggers the petted phase. */
  pettedNonce?: number
  /** Current CSS zoom on the mascot's parent layer. The drag handler
   *  divides cursor deltas by this so the mascot tracks the cursor 1:1
   *  in screen pixels regardless of zoom. */
  zoom?: number
  /** Body silhouette scale (1.0 = mature, smaller at lower stages).
   *  Used by the dangle code to keep the rotation pivot on the visible
   *  body — the body shrinks around its feet, so the pivot has to shrink
   *  with it. */
  bodyScale?: number
  /** Fires after every successful click on the mascot (taps that aren't
   *  drags, that aren't blocked by the reacting guard). The pet panel
   *  wires this to petStroke so clicking the mascot = petting. */
  onClick?: () => void
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
  /** Pointer-down handler — start dragging if draggable=true. */
  handlePointerDown: (e: ReactPointerEvent<HTMLDivElement>) => void
  /** Ref to attach to a wrapper around the mascot SVG. During drag the
   *  hook writes a `rotate(...)` transform onto this element to make the
   *  mascot dangle/swing with pendulum physics. */
  dangleRef: RefObject<HTMLDivElement>
  /** Mood-driven idle variant for renderer hints (slumped/excited/hungry). */
  idleVariant: IdleVariant
  /** True while the mascot is in the eating phase — renderer overlays battery sprite. */
  isEating: boolean
  /** True while the stage-up celebration is playing — renderer shows sparkle. */
  isStageUp: boolean
  /** True while the petted reaction is playing — renderer shows blush burst. */
  isPetted: boolean
  /** True while the mascot is being dragged. */
  isDragging: boolean
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

  // Same pattern for zoom — drag handler reads the latest value when a
  // pointerdown happens, so wheel-zoom changes between drags propagate.
  const zoomRef = useRef(inputs.zoom ?? 1)
  useEffect(() => {
    zoomRef.current = inputs.zoom ?? 1
  }, [inputs.zoom])

  // Body silhouette scale (1 = mature). Used by the dangle pivot math
  // so the rotation origin tracks the body as it shrinks per-stage.
  const bodyScaleRef = useRef(inputs.bodyScale ?? 1)
  useEffect(() => {
    bodyScaleRef.current = inputs.bodyScale ?? 1
  }, [inputs.bodyScale])

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
  //
  // state.phase is in the deps so the dispatch re-fires when the FSM
  // leaves a STICKY phase (drag/fall/stage-up). The reducer bails on
  // those phases (see mascotEngine SET_ACTIVE), and the bail is what
  // makes the drag follow the cursor without being yanked by a
  // late-arriving isActive=false (e.g. from the agent going idle
  // mid-drag). When the drag/fall ends, this effect re-fires with the
  // latest isActive and the reducer applies it.
  useEffect(() => {
    dispatch({ type: 'SET_ACTIVE', active: inputs.isActive })
  }, [inputs.isActive, state.phase])

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
  // While phase === 'waitingJump', the mascot loops vertical jumps in
  // place at WHATEVER X it's currently at — there's no settle-to-
  // center anymore. The user wants their drag/wander positioning
  // preserved through the wait state. Each jump's keyframes are
  // re-built with the current X baked in so the jump arc lands back at
  // the same spot every cycle.
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
      // Re-read X each cycle so if some other mechanism nudges it the
      // next jump still lands at the right spot. Bake it into the
      // jump keyframes (they're authored at X=0) via the same
      // string-replace pattern the falling effect uses.
      const currentX = readCurrentTranslateX(node)
      const kfs = buildJumpInPlaceKeyframes().map((kf) => ({
        ...kf,
        transform: (kf.transform as string).replace(
          /translate\(0px, /,
          `translate(${currentX}px, `,
        ),
      }))
      const anim = node.animate(
        kfs,
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

    playJump()

    return () => {
      cancelled = true
      if (restTimerId !== null) {
        window.clearTimeout(restTimerId)
        restTimerId = null
      }
    }
  }, [state.phase])

  // After a real drag, the browser still fires a `click` event on
  // pointerup — handleClick would then mid-fall-cancel and snap the
  // mascot to its in-flight visual position (the "teleport to previous
  // position" bug). This ref lets handleClick recognize and skip that
  // post-drag click.
  const justDraggedRef = useRef(false)

  // ─── Click handler ──────────────────────────────────────────────────
  // Synchronous DOM work happens here (cancel anim, snap inline style)
  // rather than in a useEffect, so the body settles in the same frame
  // as the click event. The dispatch then notifies the FSM, which on
  // next render drives the reaction effect's timer.
  const handleClick = useCallback(() => {
    if (justDraggedRef.current) {
      // This click was spawned by the browser as a follow-on to the
      // pointerup that ended a drag. Swallow it so the drag's resting
      // state isn't overridden by a reaction.
      justDraggedRef.current = false
      return
    }
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

    // External click handler — pet panel uses this so clicking the
    // mascot also fires the "pet" WS message (mood bump).
    if (inputs.onClick) inputs.onClick()

    dispatch({ type: 'CLICK', currentVisualX: currentX })
  }, [state.phase, inputs])

  // ─── Pet-system: drag handling ───────────────────────────────────────
  // Drag-vs-click distinguishing:
  //   pointerdown sets up tracking but does NOT dispatch DRAG_START yet.
  //   pointermove (the FIRST one with any nonzero delta) commits to drag.
  //   pointerup with no movement → no drag; the browser's native click
  //     event fires and handleClick handles it normally.
  //   pointerup after a real drag → DRAG_RELEASE + sets justDraggedRef
  //     so handleClick swallows the spurious follow-on click event.
  //
  // No pixel threshold — any actual pointer movement counts as a drag.
  //
  // The pointermove/pointerup listeners attach to WINDOW synchronously
  // inside pointerdown (NOT via a useEffect keyed on phase) so they're
  // ready before the first move event, and they get torn down per-drag
  // so successive drags always work.
  //
  // No phase guard either — drag must be allowed from ANY phase including
  // 'reacting', or the user can't drag again during the 700ms reaction
  // window that follows every drag (the post-drag click puts the mascot
  // in reacting — without that window being interruptible the user gets
  // stuck after one drag).
  // ── Dangle physics — pendulum that swings the mascot while dragged.
  // The mascot tilts to a base angle (set by facing direction) and
  // oscillates around it based on cursor motion: each horizontal cursor
  // delta becomes an angular impulse, then a spring pulls it back to
  // the base angle with damping.
  const DANGLE_BASE_TILT_DEG = 65   // facing right → +tilt, left → −tilt
  const DANGLE_SPRING_K       = 80   // stiffness; higher = faster return
  const DANGLE_DAMPING        = 6    // friction; higher = less oscillation
  const DANGLE_IMPULSE_PER_PX = 1.2  // deg/s of angular vel per cursor-pixel
  // Rotation pivot expressed in SVG viewBox coordinates at Stage 5
  // (bodyScale = 1). At drag time we scale this point around the body's
  // feet pivot by the current bodyScale, so the rotation origin follows
  // the visible body as it shrinks at lower stages — otherwise the
  // pivot stays at a fixed wrapper-% and ends up way above the head
  // when the mascot is small.
  const DANGLE_PIVOT_X_VBX_STAGE5 = 0    // facing right → back-side of body
  const DANGLE_PIVOT_Y_VBX_STAGE5 = 50   // a bit above body top at Stage 5
  // Conversion from viewBox to wrapper-% for transform-origin. SVG
  // viewBox is 160×200 inside a SQUARE wrapper; preserveAspectRatio
  // "xMidYMid meet" fits by height → 10% letterbox on each horizontal
  // side, no vertical letterbox. So:
  //   pct_x = SVG_LETTERBOX_PCT + viewBoxX * VBX_TO_PCT
  //   pct_y = viewBoxY * VBX_TO_PCT
  const SVG_LETTERBOX_PCT = 10
  const VBX_TO_PCT        = 0.5   // 100 / 200

  interface DangleState {
    rafId: number
    angle: number
    angularVel: number
    baseAngle: number
    lastTime: number
    pendingImpulse: number
    lastCursorX: number
  }
  const dangleStateRef = useRef<DangleState>({
    rafId: 0,
    angle: 0,
    angularVel: 0,
    baseAngle: 0,
    lastTime: 0,
    pendingImpulse: 0,
    lastCursorX: 0,
  })
  const dangleRef = useRef<HTMLDivElement>(null)

  // facing is FSM state; we need the latest value when a drag commits,
  // so mirror it into a ref (handlePointerDown's closure can't depend
  // on state.facing without re-creating on every facing flip).
  const facingRef = useRef<'left' | 'right'>(state.facing)
  useEffect(() => { facingRef.current = state.facing }, [state.facing])

  const startDangle = useCallback((initialCursorX: number, baseAngle: number) => {
    const s = dangleStateRef.current
    s.angle = baseAngle  // snap to dangle pose immediately
    s.angularVel = 0
    s.baseAngle = baseAngle
    s.lastTime = performance.now()
    s.pendingImpulse = 0
    s.lastCursorX = initialCursorX

    const el = dangleRef.current
    if (el) {
      // Scale the stage-5 viewBox pivot around the body's feet by the
      // current bodyScale, so the rotation origin follows the visible
      // body as it shrinks. Then convert viewBox → wrapper-% for the
      // CSS transform-origin (the only unit transform-origin accepts).
      // Finally, mirror X by facing so the pivot is on the BACK side.
      const bs = bodyScaleRef.current
      const scaledVbxX = BODY_FEET_X + (DANGLE_PIVOT_X_VBX_STAGE5 - BODY_FEET_X) * bs
      const scaledVbxY = BODY_FEET_Y + (DANGLE_PIVOT_Y_VBX_STAGE5 - BODY_FEET_Y) * bs
      const pivotXPctRight = SVG_LETTERBOX_PCT + scaledVbxX * VBX_TO_PCT
      const pivotYPct      = scaledVbxY * VBX_TO_PCT
      const pivotXPct = facingRef.current === 'right'
        ? pivotXPctRight
        : 100 - pivotXPctRight
      el.style.transformOrigin = `${pivotXPct}% ${pivotYPct}%`
      el.style.transform = `rotate(${baseAngle}deg)`
    }

    if (s.rafId) cancelAnimationFrame(s.rafId)
    const tick = (now: number) => {
      const dt = Math.min((now - s.lastTime) / 1000, 0.05)
      s.lastTime = now

      // Consume any accumulated cursor impulse (added by pointermove).
      // SIGN MATTERS: cursor moving right (positive dx) accelerates the
      // pivot rightward; the body lags behind due to inertia, which means
      // it ends up MORE TO THE LEFT of the new pivot. With our rotation
      // pivot near the top of the mascot, "body further left of pivot"
      // is a MORE positive CSS angle. So we ADD pendingImpulse (which
      // carries the dx sign) directly to angularVel — that gives the
      // correct "swing opposite to pivot motion" inertia behavior.
      s.angularVel += s.pendingImpulse
      s.pendingImpulse = 0

      // Spring back to baseAngle with damping.
      const error = s.baseAngle - s.angle
      const angAccel = error * DANGLE_SPRING_K - s.angularVel * DANGLE_DAMPING
      s.angularVel += angAccel * dt
      s.angle += s.angularVel * dt

      const node = dangleRef.current
      if (node) node.style.transform = `rotate(${s.angle}deg)`

      s.rafId = requestAnimationFrame(tick)
    }
    s.rafId = requestAnimationFrame(tick)
  }, [])

  const updateDangleCursor = useCallback((clientX: number) => {
    const s = dangleStateRef.current
    if (!s.rafId) return
    const dx = clientX - s.lastCursorX
    s.pendingImpulse += dx * DANGLE_IMPULSE_PER_PX
    s.lastCursorX = clientX
  }, [])

  const stopDangle = useCallback(() => {
    const s = dangleStateRef.current
    if (s.rafId) {
      cancelAnimationFrame(s.rafId)
      s.rafId = 0
    }
    const el = dangleRef.current
    if (el) {
      el.style.transform = ''
      el.style.transformOrigin = ''
    }
  }, [])

  // Safety: cancel any in-flight rAF on unmount so the loop doesn't
  // leak past component teardown.
  useEffect(() => {
    return () => {
      if (dangleStateRef.current.rafId) {
        cancelAnimationFrame(dangleStateRef.current.rafId)
      }
    }
  }, [])

  interface DragState {
    pointerId: number
    startPointerX: number
    startPointerY: number
    startTranslateX: number
    lastDx: number
    lastDy: number
    maxAmp: number
    /** CSS zoom captured at pointerdown — used to divide screen-pixel
     *  deltas into local-pixel translations so the mascot tracks the
     *  cursor 1:1 visually at any zoom level. */
    zoom: number
    started: boolean
  }
  const dragStateRef = useRef<DragState | null>(null)

  const handlePointerDown = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (!inputs.draggable) return
    const el = wanderRef.current
    if (!el) return

    const currentX = readCurrentTranslateX(el)
    // lastDx defaults to currentX so a no-move release (a tap) leaves
    // position unchanged — but onMove will update it on the first real
    // movement anyway.
    const drag: DragState = {
      pointerId: e.pointerId,
      startPointerX: e.clientX,
      startPointerY: e.clientY,
      startTranslateX: currentX,
      lastDx: currentX,
      lastDy: 0,
      maxAmp: maxAmpRef.current,
      zoom: zoomRef.current,
      started: false,
    }
    dragStateRef.current = drag

    const onMove = (ev: PointerEvent) => {
      const d = dragStateRef.current
      if (!d || d.pointerId !== ev.pointerId) return
      // Convert screen-pixel deltas to LOCAL pixels by dividing by the
      // mascot layer's CSS zoom. Without this, the mascot moves
      // `cursorDelta × zoom` screen pixels instead of `cursorDelta`,
      // so at low zoom it lags the cursor badly.
      const dx = (ev.clientX - d.startPointerX) / d.zoom
      const dy = (ev.clientY - d.startPointerY) / d.zoom
      if (!d.started) {
        if (dx === 0 && dy === 0) return
        // First real movement — commit to drag.
        d.started = true
        // Cancel EVERY animation on the element (not just currentAnimRef).
        // Past animations with `fill: 'forwards'` keep their effect applied
        // even after onfinish nulls currentAnimRef — and animation effects
        // win over inline style. If we don't clear them, our inline
        // `el.style.transform` below is silently overridden and the mascot
        // doesn't follow the cursor visually (drag.lastDx still updates,
        // so the release lands correctly — that mismatch is the tell).
        el.getAnimations().forEach(anim => {
          try { anim.commitStyles() } catch { /* noop */ }
          anim.cancel()
        })
        currentAnimRef.current = null
        try { el.setPointerCapture(ev.pointerId) } catch { /* noop */ }
        // Force grabbing cursor for the whole document during drag, so it
        // stays consistent even when the pointer leaves the painted body
        // (which is now the only thing with a `grab` cursor by default).
        document.body.style.cursor = 'grabbing'
        // Kick off the dangle pendulum. Sign is set by facing direction
        // so the mascot tilts as if held by its back.
        const baseAngle = facingRef.current === 'right'
          ? DANGLE_BASE_TILT_DEG
          : -DANGLE_BASE_TILT_DEG
        startDangle(ev.clientX, baseAngle)
        dispatch({ type: 'DRAG_START', currentVisualX: d.startTranslateX })
      }
      const targetX = clamp(d.startTranslateX + dx, -d.maxAmp, d.maxAmp)
      const targetY = Math.min(0, dy)
      d.lastDx = targetX
      d.lastDy = targetY
      el.style.transform = `translate(${targetX}px, ${targetY}px) scale(1, 1)`
      // Feed the pendulum each cursor pixel of horizontal motion.
      updateDangleCursor(ev.clientX)
    }
    const onUp = (ev: PointerEvent) => {
      const d = dragStateRef.current
      if (!d || d.pointerId !== ev.pointerId) return
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      try { el.releasePointerCapture(ev.pointerId) } catch { /* noop */ }
      const wasStarted = d.started
      const dropX = d.lastDx
      const dropY = d.lastDy
      dragStateRef.current = null
      if (wasStarted) {
        // Tell handleClick to ignore the spurious click event the browser
        // is about to fire as a follow-on to this pointerup.
        justDraggedRef.current = true
        // Stop the pendulum loop and clear the rotation so the fall
        // animation plays with the mascot upright.
        stopDangle()
        // Restore body cursor (we forced it to grabbing on drag start).
        document.body.style.cursor = ''
        if (inputs.onDragRelease) inputs.onDragRelease(dropX, dropY)
        dispatch({ type: 'DRAG_RELEASE', dropX, dropY })
      }
      // If !wasStarted, this was a tap — the native click event fires and
      // handleClick handles it normally (justDraggedRef stays false).
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }, [inputs.draggable, inputs.onDragRelease])

  // ─── Pet-system: falling animation ───────────────────────────────────
  useEffect(() => {
    if (state.phase !== 'falling') return
    const el = wanderRef.current
    if (!el) return

    // Read the current Y from the inline transform we wrote during drag,
    // so the fall starts from the released position rather than 0.
    const computed = window.getComputedStyle(el).transform
    let fromY = 0
    const m = computed.match(/matrix\(([^)]+)\)/)
    if (m) {
      const v = m[1].split(',').map(s => parseFloat(s.trim()))
      if (Number.isFinite(v[5])) fromY = v[5]
    }
    // Snap X to dropX (already set by the FSM as state.position).
    const dropX = state.position
    el.style.transform = `translate(${dropX}px, ${fromY}px) scale(1, 1)`

    const anim = el.animate(
      buildFallKeyframes(fromY).map(kf => ({
        ...kf,
        // Re-emit each keyframe with the dropX baked in so the body lands
        // at the dropped X instead of returning to wherever the engine
        // thinks the rest position was.
        transform: (kf.transform as string).replace(
          /translate\(0px, /,
          `translate(${dropX}px, `,
        ),
      })),
      { duration: FALLING_DURATION_MS, easing: 'cubic-bezier(0.3, 0, 0.7, 1)', fill: 'forwards' },
    )
    currentAnimRef.current = anim
    anim.onfinish = () => {
      if (currentAnimRef.current === anim) currentAnimRef.current = null
      dispatch({ type: 'FALL_DONE' })
    }
    anim.oncancel = () => {
      if (currentAnimRef.current === anim) currentAnimRef.current = null
    }
  }, [state.phase, state.position])

  // ─── Pet-system: eating timer ────────────────────────────────────────
  useEffect(() => {
    if (state.phase !== 'eating') return
    const id = window.setTimeout(() => {
      dispatch({ type: 'EAT_DONE' })
    }, EATING_DURATION_MS)
    return () => window.clearTimeout(id)
  }, [state.phase])

  // ─── Pet-system: stage-up animation ──────────────────────────────────
  useEffect(() => {
    if (state.phase !== 'stageUp') return
    const el = wanderRef.current
    if (!el) return
    const anim = el.animate(buildStageUpKeyframes(), {
      duration: STAGE_UP_DURATION_MS,
      easing: 'ease-out',
      fill: 'forwards',
    })
    currentAnimRef.current = anim
    anim.onfinish = () => {
      if (currentAnimRef.current === anim) currentAnimRef.current = null
      dispatch({ type: 'STAGE_UP_DONE' })
    }
    anim.oncancel = () => {
      if (currentAnimRef.current === anim) currentAnimRef.current = null
    }
  }, [state.phase])

  // ─── Pet-system: petted timer ────────────────────────────────────────
  useEffect(() => {
    if (state.phase !== 'petted') return
    const id = window.setTimeout(() => {
      dispatch({ type: 'PETTED_DONE' })
    }, PETTED_DURATION_MS)
    return () => window.clearTimeout(id)
  }, [state.phase])

  // ─── Pet-system: external nonce triggers ─────────────────────────────
  // The backend can fire pet_stage_up / pet_fed / pet_petted; the slice
  // turns each event into a monotonically-rising nonce, and these effects
  // dispatch the corresponding FSM event when the nonce rises.
  useTriggerOnIncrease(inputs.stageUpNonce, () => dispatch({ type: 'STAGE_UP' }))
  useTriggerOnIncrease(inputs.fedNonce,     () => dispatch({ type: 'EAT_START' }))
  useTriggerOnIncrease(inputs.pettedNonce,  () => dispatch({ type: 'PET_STROKE' }))

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

  const idleVariant = pickIdleVariant(
    inputs.mood ?? 50,
    inputs.hunger ?? 0,
  )

  return {
    wanderRef,
    phase: state.phase,
    facing: (state as EngineState).facing,
    reaction: state.phase === 'reacting' ? state.reactionKind : null,
    bubbleSide,
    isEyeTracking: state.phase === 'resting' && state.idleMode === 'track',
    handleClick,
    handlePointerDown,
    dangleRef,
    idleVariant,
    isEating: state.phase === 'eating',
    isStageUp: state.phase === 'stageUp',
    isPetted: state.phase === 'petted',
    isDragging: state.phase === 'dragged',
  }
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value))
}

/** Fire `onIncrease` exactly when `nonce` ticks up. Used for backend-
 *  driven triggers (stage up, fed, petted) that the slice surfaces as
 *  monotonic counters. Same shape as useReactionOnIncrease. */
function useTriggerOnIncrease(nonce: number | undefined, onIncrease: () => void): void {
  const value = nonce ?? 0
  const prev = useRef(value)
  const cb = useRef(onIncrease)
  useEffect(() => { cb.current = onIncrease }, [onIncrease])
  useEffect(() => {
    if (value > prev.current) cb.current()
    prev.current = value
  }, [value])
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
