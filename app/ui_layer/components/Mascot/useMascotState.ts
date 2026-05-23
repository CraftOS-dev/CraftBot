import { useEffect, useMemo, useRef, useState } from 'react'
import { useWebSocket } from '../../browser/frontend/src/contexts/WebSocketContext'
import { useDerivedAgentStatus } from '../../browser/frontend/src/hooks/useDerivedAgentStatus'
import type { ActionItem } from '../../browser/frontend/src/types'
import type { MascotState } from './types'

export interface MascotStateSnapshot {
  state: MascotState
  /** The latest in-progress action, if any. Used later by the action slot. */
  currentAction: ActionItem | null
  /** Total completed actions+tasks. CraftBotMascot wiggles when this rises. */
  completedCount: number
  /** Human-readable label suitable for the display panel's status line. */
  label: string
}

// How long the agent must stay continuously idle before the mascot transitions
// from the "resting" pose (awake but quiet) into the full sleeping pose.
const IDLE_TO_SLEEP_MS = 30 * 60 * 1000

// Coarse re-render interval used to re-evaluate the idle threshold while
// the agent is idle. One minute is plenty — the 30-min gate doesn't need
// frame-accurate timing, and we don't want to wake React up every second.
const IDLE_TICK_MS = 60_000

// Bridges the browser-app's agent status signals into the mascot's
// vocabulary. Lives in the shared mascot folder so the React display panel
// is self-contained, but the imports above are intentionally one-way (mascot
// reads from the browser frontend, never the other direction) — when a CLI
// mascot lands it'll get its own equivalent hook reading from its own state.
export function useMascotState(): MascotStateSnapshot {
  const { actions, messages, connected } = useWebSocket()
  const status = useDerivedAgentStatus({ actions, messages, connected })

  // Compute the "raw" snapshot — the state the agent's signals point to,
  // before the sleep-delay rule kicks in. If raw state is 'idle', the
  // gating logic below decides whether to surface it as 'idle' (sleeping)
  // or 'resting' (awake-but-quiet).
  const raw = useMemo(() => {
    const running = actions
      .filter(a => a.itemType === 'action' && a.status === 'running')
      .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
    const currentAction = running[0] ?? null

    const completedCount = actions.filter(
      a => (a.itemType === 'action' || a.itemType === 'task') && a.status === 'completed'
    ).length

    const hasPausedTask = actions.some(
      a => a.itemType === 'task' && a.status === 'paused'
    )

    // Priority resolution: error > waiting > paused > working/thinking > idle.
    let rawState: MascotState
    if (status.state === 'error') {
      rawState = 'error'
    } else if (status.state === 'waiting') {
      rawState = 'waiting'
    } else if (hasPausedTask) {
      rawState = 'paused'
    } else if (status.state === 'working') {
      rawState = currentAction ? 'working' : 'thinking'
    } else if (status.state === 'thinking') {
      rawState = 'thinking'
    } else {
      rawState = 'idle'
    }

    return { rawState, currentAction, completedCount }
  }, [actions, messages, connected, status])

  // Timestamp of when the agent most recently became idle. Reset whenever
  // the raw state moves to anything non-idle. Kept in a ref so it survives
  // re-renders without forcing them.
  const idleStartRef = useRef<number | null>(null)

  // Tick counter — bumped on a coarse interval while idle so the memo
  // re-evaluates and can flip raw 'idle' → resolved 'idle' once the
  // 30-minute threshold passes.
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (raw.rawState === 'idle') {
      if (idleStartRef.current === null) {
        idleStartRef.current = Date.now()
      }
    } else {
      // Any non-idle state resets the timer so a brief flash of activity
      // restarts the 30-minute window from scratch.
      idleStartRef.current = null
    }
  }, [raw.rawState])

  useEffect(() => {
    if (raw.rawState !== 'idle') return
    const id = window.setInterval(() => setTick(t => t + 1), IDLE_TICK_MS)
    return () => window.clearInterval(id)
  }, [raw.rawState])

  // Resolve the public state: if raw is 'idle', gate it on the elapsed
  // idle duration. Non-idle states pass through unchanged.
  const state: MascotState = useMemo(() => {
    if (raw.rawState !== 'idle') return raw.rawState
    const startedAt = idleStartRef.current
    if (startedAt === null) return 'resting'
    const elapsed = Date.now() - startedAt
    return elapsed >= IDLE_TO_SLEEP_MS ? 'idle' : 'resting'
    // `tick` is intentionally in the dep list — it's the trigger that lets
    // this memo re-run when the 30-min mark passes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw.rawState, tick])

  return {
    state,
    currentAction: raw.currentAction,
    completedCount: raw.completedCount,
    label: status.message,
  }
}
