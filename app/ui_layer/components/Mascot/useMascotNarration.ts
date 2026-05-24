import { useEffect, useRef, useState } from 'react'
import { useWebSocket } from '../../browser/frontend/src/contexts/WebSocketContext'
import { parseDict } from '../../browser/frontend/src/pages/Tasks/actionRenderers/parse'
import type { ActionItem } from '../../browser/frontend/src/types'
import { MESSAGE_ACTIONS, normalizeActionName } from './mascotEngine'
import type { MascotState } from './types'

// How long each narration phase holds before transitioning. The user-facing
// requirement was "after 5 seconds" for both the running-floor and the
// result-display windows, so the same constant feeds both.
const PHASE_DURATION_MS = 5000

// Action names that are never narrated as a normal running/result pair.
// task_end is signaled by a celebrate/frustrate body reaction instead.
const SKIP_ACTION_NAMES: ReadonlySet<string> = new Set(['task_end'])

/** Discriminated union describing what the speech bubble should render.
 *  `null` (returned alongside in the snapshot) means "no bubble at all". */
export type NarrationContent =
  | { kind: 'running'; actionName: string; params: string }
  | { kind: 'result'; actionName: string; result: string }
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
//               (whichever is later). Then → result (or message → done).
//   - result:   showing the action's output. Held for PHASE_DURATION_MS.
//   - message:  alternate "single bubble" lane for send_message family —
//               just the message text, held for PHASE_DURATION_MS.
//   - thinking: between actions while a task is still running. Stays until
//               a new narratable action appears.
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
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────

function trim(s: string, max: number): string {
  return s.length > max ? s.slice(0, max).trimEnd() + '…' : s
}

function stringifyValue(v: unknown, max = 100): string {
  if (v == null) return ''
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return trim(s, max)
}

/** Pick the most informative single value out of an action's parsed input.
 *  - Empty/no dict → empty string.
 *  - One entry → just that value.
 *  - Multiple → the longest string value (heuristic for "the prompt/query/
 *    main argument"), falling back to a compact key=value list. */
function formatParams(input: Record<string, unknown> | null): string {
  if (!input) return ''
  const entries = Object.entries(input)
  if (entries.length === 0) return ''
  if (entries.length === 1) return stringifyValue(entries[0][1])

  let primary: [string, string] | null = null
  for (const [k, v] of entries) {
    if (typeof v === 'string' && (!primary || v.length > primary[1].length)) {
      primary = [k, v]
    }
  }
  if (primary) return stringifyValue(primary[1])

  return trim(entries.map(([k, v]) => `${k}=${stringifyValue(v, 30)}`).join(', '), 140)
}

/** Pull a human-readable result string from an action. Prefers parsed-dict
 *  fields commonly carrying the "main" output (text/content/result/message),
 *  then falls back to the raw output string, then to a generic "Done". */
function formatResult(item: ActionItem, output: Record<string, unknown> | null): string {
  if (item.status === 'error' || item.error) {
    const err = item.error ?? String(output?.error ?? '')
    return err ? trim(`Error: ${err}`, 160) : 'Error'
  }
  if (item.status === 'cancelled') return 'Cancelled'
  if (output) {
    const text =
      output.text ??
      output.content ??
      output.result ??
      output.message ??
      output.output ??
      null
    if (typeof text === 'string' && text.length > 0) return trim(text, 160)
    return stringifyValue(output, 160)
  }
  if (item.output) return trim(item.output, 160)
  return 'Done'
}

/** Pull the message text out of a send_message action's input. Falls back
 *  to the whole input dump if no recognised field is present. */
function formatMessage(input: Record<string, unknown> | null): string {
  if (!input) return ''
  const msg = input.message ?? input.text ?? input.content
  if (typeof msg === 'string') return trim(msg, 220)
  return stringifyValue(input, 220)
}

// ─────────────────────────────────────────────────────────────────────
// Action selection
// ─────────────────────────────────────────────────────────────────────

/** Filter the action list down to candidates we'd narrate, then sort by
 *  ascending createdAt so the earliest unnarrated one is at the front. */
function listNarratableActions(actions: ActionItem[]): ActionItem[] {
  return actions
    .filter(a => a.itemType === 'action')
    .filter(a => !SKIP_ACTION_NAMES.has(normalizeActionName(a.name)))
    .sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0))
}

function findNextAction(actions: ActionItem[], narrated: ReadonlySet<string>): ActionItem | null {
  for (const a of listNarratableActions(actions)) {
    if (!narrated.has(a.id)) return a
  }
  return null
}

function isTaskActive(actions: ActionItem[]): boolean {
  return actions.some(
    a => a.itemType === 'task' && (a.status === 'running' || a.status === 'waiting' || a.status === 'paused'),
  )
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
    const startNextOrIdle = () => {
      const list = actionsRef.current
      // Only consider narrating new actions while a task is still
      // active. Once the task wraps up we don't want to keep chewing
      // through completed actions that piled up in the queue — the
      // mascot would look "still working" long after the task ended.
      if (!isTaskActive(list)) {
        setInternal({ phase: 'idle', actionId: null, enteredAt: Date.now() })
        return
      }
      const next = findNextAction(list, narratedRef.current)
      if (next) {
        const isMessage = MESSAGE_ACTIONS.has(normalizeActionName(next.name))
        setInternal({
          phase: isMessage ? 'message' : 'running',
          actionId: next.id,
          enteredAt: Date.now(),
        })
        return
      }
      // Task is still active but no unnarrated actions left — sit in
      // 'thinking' until a new action arrives or the task ends.
      setInternal({
        phase: 'thinking',
        actionId: null,
        enteredAt: Date.now(),
      })
    }

    const finishCurrent = () => {
      if (internal.actionId) narratedRef.current.add(internal.actionId)
      startNextOrIdle()
    }

    switch (internal.phase) {
      case 'idle': {
        // Don't start narrating anything if there's no active task —
        // even if there are unnarrated actions in the list (they're
        // stale leftovers from a previous task that already ended).
        if (!isTaskActive(actions)) return
        const next = findNextAction(actions, narratedRef.current)
        if (next) {
          const isMessage = MESSAGE_ACTIONS.has(normalizeActionName(next.name))
          setInternal({
            phase: isMessage ? 'message' : 'running',
            actionId: next.id,
            enteredAt: Date.now(),
          })
        } else {
          // Task started but no narratable action yet — show 'thinking'.
          setInternal({ phase: 'thinking', actionId: null, enteredAt: Date.now() })
        }
        return
      }

      case 'thinking': {
        // If task is done, drop the bubble immediately — agent has
        // nothing more to say.
        if (!isTaskActive(actions)) {
          setInternal({ phase: 'idle', actionId: null, enteredAt: Date.now() })
          return
        }
        const next = findNextAction(actions, narratedRef.current)
        if (next) {
          const isMessage = MESSAGE_ACTIONS.has(normalizeActionName(next.name))
          setInternal({
            phase: isMessage ? 'message' : 'running',
            actionId: next.id,
            enteredAt: Date.now(),
          })
        }
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

  // ── Resolve the rendered bubble ────────────────────────────────────
  //
  // 'waiting' is a hard override on top of the internal narration FSM —
  // if the mascot state itself reports waiting (agent paused on a user
  // reply), that always takes precedence over whatever the FSM was
  // saying. Other mascot states pass through and let the FSM speak.
  const bubble: NarrationContent | null = (() => {
    if (mascotState === 'waiting') return { kind: 'waiting' }

    switch (internal.phase) {
      case 'idle':
        return null
      case 'thinking':
        return { kind: 'thinking' }
      case 'running': {
        const item = actions.find(a => a.id === internal.actionId)
        if (!item) return null
        return {
          kind: 'running',
          actionName: item.name,
          params: formatParams(parseDict(item.input)),
        }
      }
      case 'result': {
        const item = actions.find(a => a.id === internal.actionId)
        if (!item) return null
        return {
          kind: 'result',
          actionName: item.name,
          result: formatResult(item, parseDict(item.output)),
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
  })()

  return { bubble }
}
