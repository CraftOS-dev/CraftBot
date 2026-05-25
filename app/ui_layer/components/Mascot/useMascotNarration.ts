import { useEffect, useRef, useState } from 'react'
import { useWebSocket } from '../../browser/frontend/src/contexts/WebSocketContext'
import { parseDict } from '../../browser/frontend/src/pages/Tasks/actionRenderers/parse'
import {
  getMascotFormatter,
  toMascotResultStatus,
  type MascotActionFormat,
  type MascotActionStatus,
} from '../../browser/frontend/src/pages/Tasks/actionRenderers/mascotFormatters'
import type { ActionItem } from '../../browser/frontend/src/types'
import { MESSAGE_ACTIONS, normalizeActionName } from './mascotEngine'
import { formatMessage } from './narrationFormat'
import type { MascotState } from './types'

// How long each narration phase holds before transitioning. The spec was
// "after 5 seconds" for both the running-floor and the result-display
// windows, so the same constant feeds both.
const PHASE_DURATION_MS = 5000

// Parallel-batch dedupe window. When the agent's loop fires multiple
// actions roughly simultaneously, they all show up with createdAt
// timestamps within milliseconds of each other. Without this dedupe,
// every action goes through the full 5s + 5s narration cycle — so a
// 5-action parallel batch becomes ~50s of bubble backlog and the
// mascot falls badly out of sync with reality.
// When the FSM picks one action, any OTHER unnarrated action whose
// createdAt sits within this window of the picked one is treated as
// a sibling and marked as already-narrated (silently skipped). The
// window is wide enough to catch parallel batches but narrower than
// a typical LLM-loop-step gap, so genuinely sequential actions don't
// get folded together.
// TERRIBLE implementation but there is no easier way to detect
// parallel actions without revamping the agent base code.
const PARALLEL_BATCH_MS = 1500

// Action names that are never narrated as a normal running/result pair.
// task_end is signaled by a celebrate/frustrate body reaction instead.
const SKIP_ACTION_NAMES: ReadonlySet<string> = new Set(['task_end'])

/** Discriminated union describing what the speech bubble should render.
 *  `null` (returned alongside in the snapshot) means "no bubble at all".
 *
 *  The `action` kind carries a pre-formatted MascotActionFormat — the
 *  same POJO shape that mascotFormatters.ts (colocated with the Tasks
 *  panel renderers) produces. Keeping the formatting decisions over
 *  there means the bubble's per-action display stays in sync with the
 *  card-sized renderer for the same action. */
export type NarrationContent =
  | { kind: 'action'; format: MascotActionFormat }
  | { kind: 'message'; text: string }
  | { kind: 'thinking' }
  | { kind: 'waiting' }

interface NarrationSnapshot {
  bubble: NarrationContent | null
}

// ─────────────────────────────────────────────────────────────────────
// Internal state machine
// ─────────────────────────────────────────────────────────────────────
//
// Phases:
//   - idle:     no current action narrated; no bubble (unless task active
//               and we're between actions → 'thinking' is chosen instead).
//   - running:  showing "Running <name> with <params>". Held for at least
//               PHASE_DURATION_MS, AND until the action itself completes
//               (whichever is later). Then → result.
//   - result:   showing the action's output. Held for PHASE_DURATION_MS.
//   - message:  alternate "single bubble" lane for send_message family —
//               just the message text, held for PHASE_DURATION_MS.
//   - thinking: between actions while a task is still running. Stays until
//               a new narratable action appears or the task ends.
//
// Selection rule: when a phase ends, we pick the EARLIEST (smallest
// createdAt) action that hasn't been narrated yet AND isn't in
// SKIP_ACTION_NAMES. send_message family routes into the 'message' phase;
// everything else routes through 'running' → 'result'.

type InternalPhase = 'idle' | 'running' | 'result' | 'message' | 'thinking'

interface InternalState {
  phase: InternalPhase
  /** ID of the action being narrated (running/result/message); null otherwise. */
  actionId: string | null
  /** Wall-clock timestamp the phase was entered. Used for elapsed timing. */
  enteredAt: number
}

const INITIAL: InternalState = { phase: 'idle', actionId: null, enteredAt: 0 }

// ─────────────────────────────────────────────────────────────────────
// Pure helpers — operate on inputs, return next state or selection
// ─────────────────────────────────────────────────────────────────────

/** A task is "active" for narration purposes if it can still produce or
 *  hold actions — running/waiting/paused. Completed, cancelled, and
 *  errored tasks are terminal: their leftover actions should never be
 *  picked up by future narration cycles. */
const ACTIVE_TASK_STATUSES: ReadonlySet<string> = new Set([
  'running',
  'waiting',
  'paused',
])

/** Set of task IDs whose status is currently active. Used as the
 *  membership filter for action eligibility — an action is narratable
 *  only if its root task is in this set. */
function activeTaskIds(actions: ActionItem[]): Set<string> {
  const ids = new Set<string>()
  for (const a of actions) {
    if (a.itemType === 'task' && ACTIVE_TASK_STATUSES.has(a.status)) {
      ids.add(a.id)
    }
  }
  return ids
}

/** Walk parentId up to the root task. Actions are typically direct
 *  children of tasks (one hop), but the walk is bounded to handle any
 *  future nested-action structures defensively without risk of cycles. */
function findRootTaskId(
  itemMap: ReadonlyMap<string, ActionItem>,
  start: ActionItem,
): string | null {
  let cur: ActionItem | undefined = start
  for (let depth = 0; cur && depth < 16; depth++) {
    if (cur.itemType === 'task') return cur.id
    if (!cur.parentId) return null
    cur = itemMap.get(cur.parentId)
  }
  return null
}

function isTaskActive(actions: ActionItem[]): boolean {
  return activeTaskIds(actions).size > 0
}

/** Filter the action list down to narratable candidates and sort by
 *  ascending createdAt. The earliest unnarrated one wins selection.
 *
 *  Eligibility rules:
 *    1. Item type is 'action' (not 'task' or 'reasoning').
 *    2. Name isn't in the always-skip set (task_end → body reaction
 *       instead of narration).
 *    3. The action's root task is in the active set. THIS IS THE KEY
 *       guard against stale narration: when a previous task ends with
 *       actions that were never narrated (because they piled up faster
 *       than the FSM could play them), those actions stay in the list
 *       forever — but their root task is terminal, so they're excluded.
 *       Only the currently-running task's actions survive the filter. */
function listNarratableActions(actions: ActionItem[]): ActionItem[] {
  const activeIds = activeTaskIds(actions)
  if (activeIds.size === 0) return []

  const itemMap = new Map<string, ActionItem>()
  for (const a of actions) itemMap.set(a.id, a)

  return actions
    .filter(a => a.itemType === 'action')
    .filter(a => !SKIP_ACTION_NAMES.has(normalizeActionName(a.name)))
    .filter(a => {
      const rootId = findRootTaskId(itemMap, a)
      return rootId !== null && activeIds.has(rootId)
    })
    .sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0))
}

/** Pick the next action to narrate AND mark its parallel siblings as
 *  narrated (a side effect on `narratedRef`). The "siblings" are any
 *  other unnarrated narratable actions whose createdAt is within
 *  PARALLEL_BATCH_MS of the picked one — they're treated as part of
 *  the same agent-loop parallel batch and silently skipped, so the
 *  bubble doesn't fall behind by playing N × 10s for an N-wide batch.
 *
 *  send_message family is EXEMPT from sibling-skipping — they're
 *  user-facing utterances that must be preserved even when fired in
 *  the same batch as regular actions. The preemption check in the
 *  FSM effect routes them through the 'message' phase separately.
 *
 *  Takes a pre-filtered `narratable` list (from listNarratableActions)
 *  rather than the raw actions array, so the effect can compute that
 *  list once and pass it to both this and `findUrgentMessage`. */
function pickNextActionDeduped(
  narratable: ActionItem[],
  narratedRef: { current: Set<string> },
): ActionItem | null {
  let picked: ActionItem | null = null
  for (const a of narratable) {
    if (!narratedRef.current.has(a.id)) { picked = a; break }
  }
  if (!picked) return null

  const pickedT = picked.createdAt ?? 0
  for (const a of narratable) {
    if (a.id === picked.id) continue
    if (narratedRef.current.has(a.id)) continue
    // Never dedupe a message — those go through the real-time
    // preemption path and must remain selectable.
    if (MESSAGE_ACTIONS.has(normalizeActionName(a.name))) continue
    if ((a.createdAt ?? 0) <= pickedT + PARALLEL_BATCH_MS) {
      narratedRef.current.add(a.id)
    }
  }
  return picked
}

/** Look for an unnarrated send_message family action. Returns the
 *  EARLIEST one (so multiple messages play sequentially in order).
 *  Used by the FSM effect to preempt the current phase the moment a
 *  message becomes available — that's what makes message bubbles
 *  feel real-time instead of queued behind running/result phases. */
function findUrgentMessage(narratable: ActionItem[], narrated: ReadonlySet<string>): ActionItem | null {
  for (const a of narratable) {
    if (narrated.has(a.id)) continue
    if (MESSAGE_ACTIONS.has(normalizeActionName(a.name))) return a
  }
  return null
}

/** State factories — every transition lands on one of these, so wrapping
 *  them keeps `enteredAt: Date.now()` consistent and avoids the (3x)
 *  repetition of the same object literal across the FSM. */
function stateForAction(action: ActionItem): InternalState {
  const isMessage = MESSAGE_ACTIONS.has(normalizeActionName(action.name))
  return {
    phase: isMessage ? 'message' : 'running',
    actionId: action.id,
    enteredAt: Date.now(),
  }
}

function stateThinking(): InternalState {
  return { phase: 'thinking', actionId: null, enteredAt: Date.now() }
}

function stateIdle(): InternalState {
  return { phase: 'idle', actionId: null, enteredAt: 0 }
}

// ─────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────

interface NarrationOptions {
  /** Current mascot state — used to surface the 'waiting' override bubble. */
  mascotState: MascotState
}

export function useMascotNarration({ mascotState }: NarrationOptions): NarrationSnapshot {
  const { actions } = useWebSocket()
  const [internal, setInternal] = useState<InternalState>(INITIAL)
  const narratedRef = useRef<Set<string>>(new Set())
  // Mirror actions into a ref so timer callbacks see the latest list
  // without restarting the timer on every action update.
  const actionsRef = useRef(actions)
  useEffect(() => { actionsRef.current = actions }, [actions])

  // Prune the narrated set whenever the FSM lands in idle (= the task
  // wrapped up). Past task action IDs would otherwise accumulate in
  // narratedRef for the lifetime of the page — they're filtered out
  // by the terminal-task check in listNarratableActions anyway, so
  // keeping them around just costs memory.
  useEffect(() => {
    if (internal.phase === 'idle') narratedRef.current.clear()
  }, [internal.phase])

  // ── Transition engine ─────────────────────────────────────────────
  //
  // Re-evaluated whenever:
  //   - The current internal phase changes (transition just happened).
  //   - The action list changes (new action arrived, current action's
  //     status flipped).
  //
  // Decides whether to:
  //   - Transition immediately (e.g. idle → running because an action
  //     just arrived).
  //   - Schedule a timer for the next deadline (5s minimum on running;
  //     5s display on result/message).
  useEffect(() => {
    // Compute the narratable candidate list ONCE per effect run, reuse
    // for both the preemption check and the synchronous phase logic
    // below. listNarratableActions builds an item-id Map + filter +
    // sort, so paying for it once instead of three times per effect is
    // a worthwhile win on long action lists.
    const narratable = listNarratableActions(actions)

    // ── Real-time send_message preemption ────────────────────────
    // send_message family bubbles bypass the normal queue. The moment
    // an unnarrated message appears, the FSM jumps to its 'message'
    // phase regardless of what was previously being shown. This makes
    // the bubble behave the same way the 'waiting for your reply'
    // state override does — chat-style real-time delivery rather than
    // queued-behind-running/result.
    //
    // The in-flight action (if any) is marked as narrated to prevent
    // it from looping back as the "next" candidate when the message
    // phase later promotes — its narration is effectively cut short.
    const urgent = findUrgentMessage(narratable, narratedRef.current)
    if (urgent && (internal.phase !== 'message' || internal.actionId !== urgent.id)) {
      if (internal.actionId && internal.actionId !== urgent.id) {
        narratedRef.current.add(internal.actionId)
      }
      setInternal(stateForAction(urgent))
      return
    }

    // Shared "look for a queued action and either start it or fall back
    // to thinking/idle" helper. Used by every "phase ended, what now?"
    // codepath below. The `whenEmpty` argument decides what to do when
    // there's nothing queued — 'thinking' for between-action gaps,
    // 'idle' for after-task cleanup.
    //
    // Recomputes the narratable list from actionsRef because this fires
    // out of setTimeout callbacks where the closure's `narratable` is
    // stale; sync callers above can reuse the top-of-effect snapshot.
    const promoteOrFallback = (whenEmpty: 'thinking' | 'idle') => {
      const list = actionsRef.current
      if (!isTaskActive(list)) {
        setInternal(stateIdle())
        return
      }
      const next = pickNextActionDeduped(listNarratableActions(list), narratedRef)
      if (next) {
        setInternal(stateForAction(next))
        return
      }
      setInternal(whenEmpty === 'thinking' ? stateThinking() : stateIdle())
    }

    const finishCurrent = () => {
      if (internal.actionId) narratedRef.current.add(internal.actionId)
      promoteOrFallback('thinking')
    }

    switch (internal.phase) {
      case 'idle': {
        // Don't start narrating anything if there's no active task —
        // even if unnarrated actions linger (they're stale leftovers
        // from a previous task that already ended).
        if (!isTaskActive(actions)) return
        const next = pickNextActionDeduped(narratable, narratedRef)
        setInternal(next ? stateForAction(next) : stateThinking())
        return
      }

      case 'thinking': {
        // If task is done, drop the bubble — agent has nothing more to say.
        if (!isTaskActive(actions)) {
          setInternal(stateIdle())
          return
        }
        const next = pickNextActionDeduped(narratable, narratedRef)
        if (next) setInternal(stateForAction(next))
        return
      }

      case 'running': {
        // Held until BOTH (a) the 5s floor elapsed AND (b) the action is no
        // longer in 'running' status. Whichever comes second wins.
        const item = actions.find(a => a.id === internal.actionId)
        if (!item) {
          // Action vanished — defensive: skip to next.
          finishCurrent()
          return
        }
        const elapsed = Date.now() - internal.enteredAt
        const floorRemaining = Math.max(0, PHASE_DURATION_MS - elapsed)
        const stillRunning = item.status === 'running' || item.status === 'pending'

        if (!stillRunning && floorRemaining === 0) {
          // Both conditions met — transition to result now.
          setInternal({ phase: 'result', actionId: internal.actionId, enteredAt: Date.now() })
          return
        }
        if (!stillRunning) {
          // Action done but floor not yet elapsed — schedule the swap.
          const id = window.setTimeout(() => {
            setInternal({ phase: 'result', actionId: internal.actionId, enteredAt: Date.now() })
          }, floorRemaining)
          return () => window.clearTimeout(id)
        }
        // Still running. No timer needed — we'll be re-evaluated when the
        // action's status flips (actions effect dep).
        return
      }

      case 'result':
      case 'message': {
        // Held for a fixed PHASE_DURATION_MS, then move on.
        const elapsed = Date.now() - internal.enteredAt
        const remaining = Math.max(0, PHASE_DURATION_MS - elapsed)
        if (remaining === 0) {
          finishCurrent()
          return
        }
        const id = window.setTimeout(finishCurrent, remaining)
        return () => window.clearTimeout(id)
      }
    }
  }, [internal, actions])

  return { bubble: resolveBubble(internal, actions, mascotState) }
}

// ─────────────────────────────────────────────────────────────────────
// Render-side resolution
// ─────────────────────────────────────────────────────────────────────

/** Map the FSM state + current action list + mascot state to what the
 *  speech bubble should actually render. Pulled out of the hook body so
 *  the hook is just state-machine plumbing; this is all view logic.
 *
 *  The 'waiting' mascot-state is a hard override on top of the internal
 *  FSM — if the mascot reports waiting (agent paused on a user reply),
 *  that always takes precedence over whatever the FSM was saying. */
function resolveBubble(
  internal: InternalState,
  actions: ActionItem[],
  mascotState: MascotState,
): NarrationContent | null {
  if (mascotState === 'waiting') return { kind: 'waiting' }

  switch (internal.phase) {
    case 'idle':
      return null
    case 'thinking':
      return { kind: 'thinking' }
    case 'running': {
      const item = actions.find(a => a.id === internal.actionId)
      if (!item) return null
      const formatter = getMascotFormatter(item.name)
      return { kind: 'action', format: formatter.running(parseDict(item.input)) }
    }
    case 'result': {
      const item = actions.find(a => a.id === internal.actionId)
      if (!item) return null
      const formatter = getMascotFormatter(item.name)
      return {
        kind: 'action',
        format: formatter.result(parseDict(item.input), parseDict(item.output), toMascotResultStatus(item.status)),
      }
    }
    case 'message': {
      const item = actions.find(a => a.id === internal.actionId)
      if (!item) return null
      return {
        kind: 'message',
        text: formatMessage(parseDict(item.input)),
      }
    }
  }
}

// Re-export so consumers (SpeechBubble) can type their props against
// the POJO shape without reaching into the renderer package directly.
export type { MascotActionFormat, MascotActionStatus }
