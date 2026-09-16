import { getSocketClient } from '../store/socket/socketInstance'

/**
 * Browser-side freeze diagnostics.
 *
 * Records main-thread long tasks (≥ LONG_TASK_MS) together with the socket
 * message types that arrived shortly before, so a stall points at the burst
 * that caused it (docs/plans/ui-data-freshness-plan.md, RS-0).
 *
 * Entries are kept on `window.__craftbotPerf` (bounded) for test harnesses,
 * and logged to the console in development builds.
 */

const LONG_TASK_MS = 100
// Messages arriving this long before a long task are attributed to it.
const ATTRIBUTION_WINDOW_MS = 2000
const MAX_ENTRIES = 200

export interface LongTaskEntry {
  /** performance.now() timestamp when the task started. */
  startedAt: number
  durationMs: number
  /** Inbound socket message counts by type within the attribution window. */
  recentMessages: Record<string, number>
}

declare global {
  interface Window {
    __craftbotPerf?: { longTasks: LongTaskEntry[] }
  }
}

export function startPerfMonitor(): void {
  const supported = typeof PerformanceObserver !== 'undefined'
    && PerformanceObserver.supportedEntryTypes?.includes('longtask')
  if (!supported || window.__craftbotPerf) return

  const buffer = { longTasks: [] as LongTaskEntry[] }
  window.__craftbotPerf = buffer

  const recent: { type: string; at: number }[] = []
  getSocketClient().onAnyMessage((msg) => {
    const now = performance.now()
    recent.push({ type: msg.type, at: now })
    while (recent.length > 0 && now - recent[0].at > ATTRIBUTION_WINDOW_MS) recent.shift()
  })

  new PerformanceObserver((list) => {
    for (const task of list.getEntries()) {
      if (task.duration < LONG_TASK_MS) continue
      const from = task.startTime - ATTRIBUTION_WINDOW_MS
      const to = task.startTime + task.duration
      const recentMessages: Record<string, number> = {}
      for (const message of recent) {
        if (message.at >= from && message.at <= to) {
          recentMessages[message.type] = (recentMessages[message.type] ?? 0) + 1
        }
      }
      const entry = { startedAt: task.startTime, durationMs: Math.round(task.duration), recentMessages }
      buffer.longTasks.push(entry)
      if (buffer.longTasks.length > MAX_ENTRIES) buffer.longTasks.shift()
      if (import.meta.env.DEV) {
        console.warn(`[LONG TASK] ${entry.durationMs}ms main-thread block`, recentMessages)
      }
    }
  }).observe({ type: 'longtask', buffered: true })
}
