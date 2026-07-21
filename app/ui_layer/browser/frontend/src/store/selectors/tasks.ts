import type { RootState } from '../index'
import { tasksAdapter } from '../slices/tasksSlice'
import { isEndedStatus } from '../../utils/taskStatus'

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

export const selectResumingTaskId = (state: RootState): string | null =>
  state.tasks.resumingTaskId

export const selectDeletingTaskId = (state: RootState): string | null =>
  state.tasks.deletingTaskId

// For action_history pagination: cursor is the oldest *ended* task's
// createdAt, since pagination only ever walks ended-task history — active
// tasks are always loaded in full up front (see tasksSlice.ts).
export const selectOldestTaskCreatedAt = (state: RootState): number | undefined => {
  for (const id of state.tasks.ids) {
    const entry = state.tasks.entities[id]
    if (entry?.itemType === 'task' && isEndedStatus(entry.status) && entry.createdAt !== undefined) {
      return entry.createdAt
    }
  }
  return undefined
}

export const selectHasAnyActions = (state: RootState): boolean =>
  state.tasks.ids.length > 0
