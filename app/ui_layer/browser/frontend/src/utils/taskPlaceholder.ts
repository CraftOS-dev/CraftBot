import type { ActionItem, ActionStatus } from '../types'

// Describes the trailing placeholder shown at the end of a transcript/list
// while the task is still active. Returns null for terminal task states
// (completed / error / cancelled / pending / idle).
export interface ActivePlaceholder {
  label: string
  status: ActionStatus
}

// `children` are the task's action/reasoning items. The "Thinking…"
// placeholder is suppressed when one of them is currently `running` — the
// running action itself already represents the agent's activity, so a
// separate placeholder would be redundant (and would dangle the timeline's
// dashed line below it with nothing to connect to). The waiting/paused
// placeholders are returned unconditionally because they convey a
// user-facing wait state and host the Reply button.
export function getActivePlaceholder(
  status: ActionStatus,
  children?: ActionItem[],
): ActivePlaceholder | null {
  switch (status) {
    case 'running': {
      const hasRunningChild = children?.some(c => c.status === 'running') ?? false
      if (hasRunningChild) return null
      return { label: 'Thinking…', status: 'running' }
    }
    case 'waiting':
      return { label: 'Waiting for your reply…', status: 'waiting' }
    case 'paused':
      return { label: 'Paused — awaiting confirmation…', status: 'paused' }
    default:
      return null
  }
}
