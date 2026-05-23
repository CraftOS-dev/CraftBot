import { useEffect, useRef, useState } from 'react'
import { useWebSocket } from '../../browser/frontend/src/contexts/WebSocketContext'
import type { ActionItem } from '../../browser/frontend/src/types'

// Minimum time (ms) any action is held in the slot before we'll swap to a
// newer one. Most actions complete almost instantly because we don't stream
// LLM output, so this floor is what makes the slot legible at all.
const MIN_DISPLAY_MS = 3000

interface Snapshot {
  /** The action whose renderer should currently be shown, or null when we're
   *  between actions (the slot should render its "thinking" placeholder). */
  displayed: ActionItem | null
}

// Picks the most recently created action across all tasks. Reasoning items
// are skipped — they're transcribed in the task panel but don't have their
// own renderer.
function findLatestAction(actions: ActionItem[]): ActionItem | null {
  let best: ActionItem | null = null
  for (const a of actions) {
    if (a.itemType !== 'action') continue
    if (!best || (a.createdAt ?? 0) > (best.createdAt ?? 0)) best = a
  }
  return best
}

// Drives the mascot's action slot.
//
// Lifecycle:
//   1. First action ever → shown immediately, timestamped.
//   2. Newer action arrives within the 3s window → stashed as `pending`
//      (only one ever queued; newer arrivals overwrite the queue).
//   3. Newer action arrives after the 3s window → swapped in immediately.
//   4. Same action's status updates → fields refreshed, timer not reset.
//   5. 3s timer fires:
//        - pending exists → promote it (resets the window).
//        - displayed action is no longer running → clear to null (slot
//          falls back to the thinking placeholder).
//        - displayed action still running → keep showing.
//   6. After the 3s window, when a displayed action's status flips off
//      "running" with no pending, the same effect re-arms and clears.
export function useDisplayedAction(): Snapshot {
  const { actions } = useWebSocket()
  const [displayed, setDisplayed] = useState<ActionItem | null>(null)
  const displayedSinceRef = useRef<number>(0)
  const pendingRef = useRef<ActionItem | null>(null)

  // React to incoming action updates — decide whether to swap, queue, or
  // just refresh the currently-shown item's fields.
  useEffect(() => {
    const latest = findLatestAction(actions)
    if (!latest) return

    setDisplayed(prev => {
      const now = Date.now()

      if (!prev) {
        displayedSinceRef.current = now
        pendingRef.current = null
        return latest
      }

      // Refresh current item's data in case its status flipped.
      const refreshed = actions.find(a => a.id === prev.id) ?? prev

      if (latest.id === prev.id) {
        return refreshed
      }

      const elapsed = now - displayedSinceRef.current
      if (elapsed >= MIN_DISPLAY_MS) {
        displayedSinceRef.current = now
        pendingRef.current = null
        return latest
      }

      // Within the 3s floor — queue the newcomer for promotion when the
      // timer fires. Refreshed current stays on screen until then.
      pendingRef.current = latest
      return refreshed
    })
  }, [actions])

  // Single timer that handles both the initial 3s expiry and any post-3s
  // re-evaluation triggered by `displayed` changing (status flips, swaps).
  useEffect(() => {
    if (!displayed) return

    const tick = () => {
      const now = Date.now()

      if (pendingRef.current) {
        // Promote the queued action.
        const next = pendingRef.current
        pendingRef.current = null
        displayedSinceRef.current = now
        setDisplayed(next)
        return
      }

      // No queue and the visible action is done — drop to the thinking
      // placeholder. Keep showing while it's still running.
      if (displayed.status !== 'running') {
        setDisplayed(null)
      }
    }

    const elapsed = Date.now() - displayedSinceRef.current
    const remaining = MIN_DISPLAY_MS - elapsed
    // Small buffer so timeouts always fire *after* the 3s mark, not on it.
    const delay = remaining > 0 ? remaining + 16 : 0
    const id = window.setTimeout(tick, delay)
    return () => window.clearTimeout(id)
  }, [displayed])

  return { displayed }
}
