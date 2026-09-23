import { store } from '../store'
import { selectUiState } from '../store/selectors/ui'
import { setUiState } from '../store/slices/uiSlice'
import { UI_STATE } from '../store/uiState'
import type { TourId } from './types'

// Device-local record of which tours a user has already seen, kept as
// persisted UI state (see store/uiState/catalog.ts). A completed tour never
// auto-starts again, but can always be replayed on demand. Plain functions
// over the store because the tour controller runs outside React.

export function hasCompletedTour(id: TourId): boolean {
  return selectUiState(store.getState(), UI_STATE.tour.completed(id))
}

export function markTourCompleted(id: TourId): void {
  store.dispatch(setUiState(UI_STATE.tour.completed(id), true))
}

export function resetTourCompletion(id: TourId): void {
  store.dispatch(setUiState(UI_STATE.tour.completed(id), false))
}
