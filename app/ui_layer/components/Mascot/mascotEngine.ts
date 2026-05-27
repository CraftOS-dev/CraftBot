// Pure behavior layer for the mascot — no React, no DOM access except for
// readCurrentTranslateX (which is a tiny inspection helper). All the
// timing, geometry, randomization, and state-transition logic that the
// React hooks need lives here, so the React side is just plumbing.
//
// The mascot's behavior is modeled as a finite state machine. A single
// `transition(state, event)` function describes every move; the React
// hook in useMascotBehavior is responsible for firing the events at the
// right time (timers, animation onfinish callbacks, click handlers) and
// applying the side effects each phase implies (start an animation, snap
// inline style, etc.).

// ─────────────────────────────────────────────────────────────────────
// Timing constants (milliseconds)
// ─────────────────────────────────────────────────────────────────────

/** How long one hop animation runs (crouch → arc → land → settle). */
export const HOP_DURATION_MS = 850

/** How long the "settle back to center" animation runs when the mascot
 *  is being pinned / silenced (e.g. an action card arrives). */
export const SETTLE_DURATION_MS = 400

/** Rest between hops, sampled uniformly in this range. Tuned so the
 *  cumulative cycle (hop + rest) matches the original 1300–5500ms feel:
 *  hop is 850ms, so a 450–4650ms rest keeps total cycle 1300–5500ms. */
export const POST_HOP_REST_MIN_MS = 450
export const POST_HOP_REST_MAX_MS = 4650

/** Short delay between "mascot becomes active again" (waking from sleep,
 *  reaction ending) and the first new hop. Keeps the mascot from feeling
 *  sluggish on transitions but doesn't fire instantly. */
export const WANDER_WARMUP_MS = 300

/** How long the happy reaction holds — the body stays still at the
 *  click position, > < eyes show, rays burst (rays have their own
 *  shorter CSS animation, ~420ms). */
export const HAPPY_DURATION_MS = 700

/** A single vertical jump-in-place takes this long. Matched to the hop
 *  duration so the squash-and-stretch beats land on the same rhythm —
 *  the in-place jump should read as "same character, just vertical". */
export const JUMP_IN_PLACE_DURATION_MS = HOP_DURATION_MS

/** Rest between consecutive in-place jumps, sampled uniformly in this
 *  range. Shorter than the wander rest because the agent is "expectant"
 *  — repeated little hops feel more attentive than long pauses. */
export const JUMP_REST_MIN_MS = 250
export const JUMP_REST_MAX_MS = 500

/** Idle-mode cycle interval. The mascot switches between wandering
 *  (hopping around the stage) and tracking (standing still with eyes
 *  following the cursor) on this rhythm — randomized so it doesn't
 *  feel mechanical. */
export const IDLE_CYCLE_MIN_MS = 6_000
export const IDLE_CYCLE_MAX_MS = 10_000

// ─────────────────────────────────────────────────────────────────────
// Geometry constants
// ─────────────────────────────────────────────────────────────────────

/** Matches var(--space-3) in Mascot.module.css — used to compute the
 *  mascot's available wander range from the stage's outer width. */
export const STAGE_EDGE_PADDING_PX = 12

/** Per-hop step size limits. Caps the maximum DISTANCE of a single hop so
 *  the mascot never looks like it's teleporting — only the cumulative
 *  path covers the stage's full range. */
export const MIN_HOP_STEP_PX = 20
export const MAX_HOP_STEP_PX = 80

// ─────────────────────────────────────────────────────────────────────
// Action name handling
// ─────────────────────────────────────────────────────────────────────

/** Action names sometimes arrive with spaces or hyphens (skill metadata)
 *  instead of snake_case. Normalize before matching against the sets
 *  below — same transform getActionRenderer uses for its registry. */
export function normalizeActionName(name: string): string {
  return name.toLowerCase().replace(/[\s-]+/g, '_')
}

/** Action names that route through the narration FSM's 'message' phase
 *  (single-bubble display of the message body itself) rather than the
 *  default 'running' → 'result' lane. */
export const MESSAGE_ACTIONS: ReadonlySet<string> = new Set([
  'send_message',
  'send_message_with_attachment',
])

// ─────────────────────────────────────────────────────────────────────
// DOM-inspection helpers
// ─────────────────────────────────────────────────────────────────────

/** Reads the wander element's current *visual* X position — meaning the
 *  point on screen where the element's origin is right now.
 *
 *  This is more than just reading the matrix's translateX. The hop
 *  keyframes use `translate(...) scale(...)`, and the element has
 *  `transform-origin: 50% 95%` (anchored near the feet). A scale around
 *  a non-(0,0) origin visually shifts the element by
 *  `origin_x * (1 - scale_x)`. So a mid-hop matrix like
 *  `matrix(0.94, 0, 0, 1.06, 20, -18)` (peak of the arc) has tx=20 but
 *  the body is actually drawn at `20 + 60*(1-0.94) = 23.6px` in viewport
 *  X. Reading just `tx` and snapping the inline style to `translate(20,
 *  …)` would teleport the body by ~3.6px sideways. We need the effective
 *  visual position so the click handler can pin the body exactly where
 *  the user saw it.
 */
export function readCurrentTranslateX(el: HTMLElement): number {
  const style = window.getComputedStyle(el)
  const t = style.transform
  if (!t || t === 'none') return 0

  let scaleX = 1
  let translateX = 0

  const m2 = t.match(/matrix\(([^)]+)\)/)
  if (m2) {
    const v = m2[1].split(',').map(s => parseFloat(s.trim()))
    if (Number.isFinite(v[0])) scaleX = v[0]
    if (Number.isFinite(v[4])) translateX = v[4]
  } else {
    const m3 = t.match(/matrix3d\(([^)]+)\)/)
    if (m3) {
      const v = m3[1].split(',').map(s => parseFloat(s.trim()))
      if (Number.isFinite(v[0])) scaleX = v[0]
      if (Number.isFinite(v[12])) translateX = v[12]
    }
  }

  // transformOrigin's computed value is already resolved to pixels
  // ("60px 114px" for 50% 95% on a 120px-wide element).
  const ox = parseFloat(style.transformOrigin.split(/\s+/)[0] ?? '0') || 0

  return translateX + ox * (1 - scaleX)
}

// ─────────────────────────────────────────────────────────────────────
// Geometry helpers
// ─────────────────────────────────────────────────────────────────────

/** Maximum amount the mascot's center can drift left/right of the stage
 *  midpoint before its edge crosses the stage's content area. */
export function computeMaxAmplitude(stageContentWidth: number, effectiveSize: number): number {
  return Math.max(0, (stageContentWidth - effectiveSize) / 2)
}

/** Pick a uniform-random rest delay in [POST_HOP_REST_MIN_MS, POST_HOP_REST_MAX_MS]. */
export function pickPostHopRest(): number {
  return POST_HOP_REST_MIN_MS + Math.random() * (POST_HOP_REST_MAX_MS - POST_HOP_REST_MIN_MS)
}

/** Pick the next random hop target. Constrains the step DISTANCE (not
 *  position), so each hop is a believable little leap regardless of
 *  panel width. Retries with random direction so the mascot naturally
 *  drifts away from the stage edges without explicit edge logic. */
export function pickRandomHopTarget(prev: number, maxAmp: number): number {
  if (maxAmp <= 0) return 0

  const minStep = Math.min(MIN_HOP_STEP_PX, maxAmp)
  const maxStep = Math.min(MAX_HOP_STEP_PX, maxAmp * 2)
  if (maxStep <= minStep) {
    // Stage is too tight to randomize meaningfully — just bounce to the
    // other side of the current position, clamped to range.
    return -Math.sign(prev || 1) * Math.min(maxAmp, minStep)
  }

  for (let i = 0; i < 8; i++) {
    const step = minStep + Math.random() * (maxStep - minStep)
    const dir = Math.random() < 0.5 ? -1 : 1
    const candidate = prev + step * dir
    if (candidate >= -maxAmp && candidate <= maxAmp) return candidate
  }
  // After repeated misses (near an edge), force a step toward the center.
  return prev > 0
    ? Math.max(-maxAmp, prev - maxStep)
    : Math.min(maxAmp, prev + maxStep)
}

// ─────────────────────────────────────────────────────────────────────
// Animation keyframe builders
// ─────────────────────────────────────────────────────────────────────

/** Build the WAAPI keyframe sequence for a hop. Eight keyframes:
 *  rest → crouch → push off → peak → descent → land (heavy squash) →
 *  recover → settle. Arc height scales with hop distance so short hops
 *  have low arcs and tall hops have proper-looking ones. */
export function buildHopKeyframes(start: number, target: number): Keyframe[] {
  const distance = target - start
  const mid = start + distance / 2
  const arcH = Math.min(22, Math.max(8, Math.abs(distance) * 0.28))
  const arcMid = arcH * 0.65

  return [
    { transform: `translate(${start}px, 0) scale(1, 1)`, offset: 0 },
    // Crouch — wider + shorter, slight dip into the floor.
    { transform: `translate(${start}px, 4px) scale(1.15, 0.85)`, offset: 0.18 },
    // Push off — body stretches up as it leaves the ground.
    { transform: `translate(${start + distance * 0.25}px, -${arcMid}px) scale(0.92, 1.10)`, offset: 0.35 },
    // Peak — apex of the arc.
    { transform: `translate(${mid}px, -${arcH}px) scale(0.94, 1.06)`, offset: 0.5 },
    // Descent — still stretched, approaching landing spot.
    { transform: `translate(${start + distance * 0.75}px, -${arcMid}px) scale(0.95, 1.06)`, offset: 0.65 },
    // Landing — heaviest squash, absorbs the impact.
    { transform: `translate(${target}px, 4px) scale(1.18, 0.82)`, offset: 0.80 },
    // Recovery — half-squash on the way back to neutral.
    { transform: `translate(${target}px, 2px) scale(1.05, 0.96)`, offset: 0.90 },
    // Settle — back to rest at the new spot.
    { transform: `translate(${target}px, 0) scale(1, 1)`, offset: 1 },
  ]
}

/** Two-keyframe ease used for non-hop transitions (mascot being pinned
 *  to the center, or recovering from a mid-hop interruption). */
export function buildSettleKeyframes(start: number, target: number): Keyframe[] {
  return [
    { transform: `translate(${start}px, 0) scale(1, 1)` },
    { transform: `translate(${target}px, 0) scale(1, 1)` },
  ]
}

/** Vertical jump-in-place keyframes. Mirrors buildHopKeyframes' full
 *  eight-beat structure (rest → crouch → push off → peak → descent →
 *  land → recover → settle) with translateX locked to 0 throughout, so
 *  the animation reads as the same character motion as a hop — just
 *  vertical. Skipping the push-off / descent / recovery beats (as an
 *  earlier 5-keyframe version did) makes the jump feel stiff and
 *  un-Pixar; keeping them all preserves the squash-and-stretch arc. */
export function buildJumpInPlaceKeyframes(): Keyframe[] {
  const arcH = 18
  const arcMid = arcH * 0.65

  return [
    // Rest.
    { transform: 'translate(0px, 0) scale(1, 1)', offset: 0 },
    // Crouch — wider + shorter, slight dip into the floor.
    { transform: 'translate(0px, 4px) scale(1.15, 0.85)', offset: 0.18 },
    // Push off — body stretches up as feet leave the ground.
    { transform: `translate(0px, ${-arcMid}px) scale(0.92, 1.10)`, offset: 0.35 },
    // Peak — apex of the arc.
    { transform: `translate(0px, ${-arcH}px) scale(0.94, 1.06)`, offset: 0.5 },
    // Descent — still stretched on the way back down.
    { transform: `translate(0px, ${-arcMid}px) scale(0.95, 1.06)`, offset: 0.65 },
    // Landing — heaviest squash, absorbs the impact.
    { transform: 'translate(0px, 4px) scale(1.18, 0.82)', offset: 0.80 },
    // Recovery — half-squash on the way back to neutral.
    { transform: 'translate(0px, 2px) scale(1.05, 0.96)', offset: 0.90 },
    // Settle.
    { transform: 'translate(0px, 0) scale(1, 1)', offset: 1 },
  ]
}

/** Sample a uniform-random rest delay in [JUMP_REST_MIN_MS, JUMP_REST_MAX_MS]. */
export function pickJumpRest(): number {
  return JUMP_REST_MIN_MS + Math.random() * (JUMP_REST_MAX_MS - JUMP_REST_MIN_MS)
}

/** Sample a uniform-random idle-mode cycle interval. */
export function pickIdleCycleDelay(): number {
  return IDLE_CYCLE_MIN_MS + Math.random() * (IDLE_CYCLE_MAX_MS - IDLE_CYCLE_MIN_MS)
}

// ─────────────────────────────────────────────────────────────────────
// State machine
// ─────────────────────────────────────────────────────────────────────

/** What the mascot is currently doing.
 *
 *  - `inactive`: not wandering for any external reason (sleeping/pinned/
 *    collapsed). The mascot sits at center, body not animated.
 *  - `resting`: awake, between hops. Breathing animation only. The
 *    wander timer is counting down toward the next hop (wander mode
 *    only — track mode just sits and lets the eyes follow cursor).
 *  - `hopping`: a hop animation is in flight.
 *  - `reacting`: a click or external trigger pinned the body for a
 *    reaction (happy on click / task success; frustrated on task abort).
 *  - `waitingJump`: agent is waiting for a user reply — body is pinned
 *    at the stage center and loops vertical jumps in place.
 */
export type Phase = 'inactive' | 'resting' | 'hopping' | 'reacting' | 'waitingJump'

/** Which reaction visual to render while phase === 'reacting'.
 *  - `happy`: > < eyes + yellow ray burst (click + task success).
 *  - `frustrated`: flat eye dashes + sweat drop (task aborted/error). */
export type ReactionKind = 'happy' | 'frustrated'

/** Cycles within the `resting` phase to keep idle behavior varied.
 *  - `wander`: existing behavior — pick a random hop target periodically.
 *  - `track`:  stand still and let the eyes follow the cursor.
 *  Cycled on a randomized timer in useMascotBehavior. */
export type IdleMode = 'wander' | 'track'

export interface EngineState {
  phase: Phase
  /** Where the mascot's rest position is, in px translateX from center. */
  position: number
  /** Where the current hop is heading (only meaningful in 'hopping'). */
  hopTarget: number
  /** Visual orientation — set on hop start to match direction of travel. */
  facing: 'left' | 'right'
  /** Which reaction is being played. Only meaningful while phase === 'reacting'. */
  reactionKind: ReactionKind
  /** Current idle behavior. Determines whether 'resting' arms the wander
   *  timer or stays put for eye-tracking. */
  idleMode: IdleMode
}

export const INITIAL_STATE: EngineState = {
  phase: 'inactive',
  position: 0,
  hopTarget: 0,
  facing: 'right',
  reactionKind: 'happy',
  idleMode: 'wander',
}

export type EngineEvent =
  /** External world says "wander is/isn't allowed right now" (driven by
   *  the agent's sleeping/pinned/collapsed status). */
  | { type: 'SET_ACTIVE', active: boolean }
  /** Wander timer expired; pick a new target and start hopping. */
  | { type: 'WANDER_TICK', maxAmp: number }
  /** The hop's WAAPI animation reached offset 1. */
  | { type: 'HOP_DONE' }
  /** The reaction timer expired. */
  | { type: 'REACTION_DONE' }
  /** User clicked the mascot. Carries the visual X at click time so
   *  the reacting phase can pin the body to the right spot. */
  | { type: 'CLICK', currentVisualX: number }
  /** External trigger (task end success/aborted) — pins the body at the
   *  current rest position and plays the requested reaction kind. */
  | { type: 'EXTERNAL_REACT', kind: ReactionKind }
  /** Cycle timer fired — flip between wander and track idle modes.
   *  Only meaningful in the active idle phases (resting/hopping); other
   *  phases ignore it. */
  | { type: 'CYCLE_IDLE_MODE' }
  /** External signal that the agent has entered (active=true) or exited
   *  (active=false) the waiting-for-user-reply state. */
  | { type: 'SET_WAITING', active: boolean }

export function transition(state: EngineState, event: EngineEvent): EngineState {
  switch (event.type) {
    case 'SET_ACTIVE': {
      if (event.active) {
        // Become active. If we were stuck inactive, drop into resting
        // and let the wander loop start. Active phases pass through.
        return state.phase === 'inactive'
          ? { ...state, phase: 'resting' }
          : state
      }
      // Become inactive — cancel any current activity and reset position.
      // The React side animates the body back to center.
      return { ...state, phase: 'inactive', position: 0, hopTarget: 0 }
    }

    case 'WANDER_TICK': {
      // Only the resting phase honors wander ticks. The wander effect
      // already clears its timer on phase change, but the reducer guard
      // protects against any leftover dispatch from a race.
      if (state.phase !== 'resting') return state
      const target = pickRandomHopTarget(state.position, event.maxAmp)
      // Sub-pixel "movement" produces no animation but does flip facing;
      // skip to avoid a no-op hop cycle.
      if (Math.abs(target - state.position) < 1) return state
      return {
        ...state,
        phase: 'hopping',
        hopTarget: target,
        facing: target > state.position ? 'right' : 'left',
      }
    }

    case 'HOP_DONE': {
      if (state.phase !== 'hopping') return state
      // Hop reached its target — that's now the resting position.
      return { ...state, phase: 'resting', position: state.hopTarget }
    }

    case 'REACTION_DONE': {
      if (state.phase !== 'reacting') return state
      return { ...state, phase: 'resting' }
    }

    case 'CLICK': {
      // Already reacting? Ignore — don't restart mid-reaction.
      if (state.phase === 'reacting') return state
      // From any other phase (including 'inactive' for the wake-from-
      // sleep path), snap to the click X and react. Note: the external
      // click handler is responsible for rejecting clicks when the
      // mascot is pinned by an action card — the FSM accepts them here.
      return {
        ...state,
        phase: 'reacting',
        position: event.currentVisualX,
        hopTarget: event.currentVisualX,
        reactionKind: 'happy',
      }
    }

    case 'EXTERNAL_REACT': {
      // Already reacting? Ignore — don't stack/override an in-flight
      // reaction. Otherwise pin at the current rest position (no hop
      // interruption snap because external reactions usually arrive
      // outside of motion) and play the requested kind.
      if (state.phase === 'reacting') return state
      return {
        ...state,
        phase: 'reacting',
        hopTarget: state.position,
        reactionKind: event.kind,
      }
    }

    case 'CYCLE_IDLE_MODE': {
      // Only flips during the active idle phases. Reacting/inactive/
      // waitingJump explicitly ignore — those phases own their own
      // visuals and would look wrong if the eyes started tracking
      // mid-reaction or mid-jump. The cycle effect re-arms when phase
      // returns to resting, so a tick missed during e.g. a hop comes
      // back on the next cycle.
      if (state.phase !== 'resting' && state.phase !== 'hopping') return state
      return { ...state, idleMode: state.idleMode === 'wander' ? 'track' : 'wander' }
    }

    case 'SET_WAITING': {
      if (event.active) {
        // Enter waiting jump from anywhere except 'reacting' (don't
        // interrupt an in-flight reaction — REACTION_DONE will land us
        // back in 'resting' and the React-side re-sync effect will
        // promote into waitingJump on the next render). Snap position
        // to 0 because the jump animation runs in-place at the stage
        // center.
        if (state.phase === 'reacting') return state
        return { ...state, phase: 'waitingJump', position: 0, hopTarget: 0 }
      }
      // Leaving waiting — drop back into the normal idle loop. The
      // wander/track cycle picks up wherever idleMode left off.
      if (state.phase !== 'waitingJump') return state
      return { ...state, phase: 'resting' }
    }
  }
}
