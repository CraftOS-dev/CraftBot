import type { TourId } from './types'

// Device-local record of which tours a user has already seen. Follows the
// existing `craftbot.*` localStorage convention (see Layout.tsx). A completed
// tour never auto-starts again, but can always be replayed on demand.
const KEY_PREFIX = 'craftbot.tour.completed.'

export function hasCompletedTour(id: TourId): boolean {
  try {
    return window.localStorage.getItem(KEY_PREFIX + id) === '1'
  } catch {
    return false
  }
}

export function markTourCompleted(id: TourId): void {
  try {
    window.localStorage.setItem(KEY_PREFIX + id, '1')
  } catch {
    /* storage unavailable — the tour may simply reappear next session */
  }
}

export function resetTourCompletion(id: TourId): void {
  try {
    window.localStorage.removeItem(KEY_PREFIX + id)
  } catch {
    /* no-op */
  }
}
