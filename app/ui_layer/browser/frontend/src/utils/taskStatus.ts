import type { ActionStatus } from '../types'

const ENDED_STATUSES: ReadonlySet<ActionStatus> = new Set(['completed', 'error', 'cancelled'])

export function isEndedStatus(status: ActionStatus): boolean {
  return ENDED_STATUSES.has(status)
}
