import type { RootState } from '../index'
import { tasksAdapter } from '../slices/tasksSlice'

const adapterSelectors = tasksAdapter.getSelectors<RootState>((state) => state.tasks)

export const selectAllActions = adapterSelectors.selectAll
export const selectActionById = adapterSelectors.selectById
export const selectActionIds = adapterSelectors.selectIds

export const selectHasMoreActions = (state: RootState): boolean =>
  state.tasks.hasMore

export const selectLoadingOlderActions = (state: RootState): boolean =>
  state.tasks.loadingOlder

export const selectCancellingTaskId = (state: RootState): string | null =>
  state.tasks.cancellingTaskId

export const selectCompletingTaskId = (state: RootState): string | null =>
  state.tasks.completingTaskId

// For action_history pagination: cursor is the oldest task's createdAt
// (falling back to the oldest action of any kind if no tasks present).
export const selectOldestTaskCreatedAt = (state: RootState): number | undefined => {
  for (const id of state.tasks.ids) {
    const entry = state.tasks.entities[id]
    if (entry?.itemType === 'task' && entry.createdAt !== undefined) return entry.createdAt
  }
  // Fallback: first entry's createdAt.
  const firstId = state.tasks.ids[0]
  return firstId !== undefined ? state.tasks.entities[firstId]?.createdAt : undefined
}

export const selectHasAnyActions = (state: RootState): boolean =>
  state.tasks.ids.length > 0
