import { createSlice, createEntityAdapter, PayloadAction } from '@reduxjs/toolkit'
import type { ActionItem } from '../../types'
import { register } from '../socket/messageRegistry'

// Tasks + actions are normalized by id. We keep insertion order rather than
// re-sorting, since the backend pushes them in chronological order and the
// pagination cursor reads from the oldest entry's createdAt.
const adapter = createEntityAdapter<ActionItem, string>({
  selectId: (a) => a.id,
})

interface TasksExtraState {
  hasMore: boolean
  loadingOlder: boolean
  cancellingTaskId: string | null
  completingTaskId: string | null
  resumingTaskId: string | null
}

const initialState = adapter.getInitialState<TasksExtraState>({
  hasMore: true,
  loadingOlder: false,
  cancellingTaskId: null,
  completingTaskId: null,
  resumingTaskId: null,
})

const tasksSlice = createSlice({
  name: 'tasks',
  initialState,
  reducers: {
    setInitial(state, action: PayloadAction<{ actions: ActionItem[]; hasMore: boolean }>) {
      adapter.setAll(state, action.payload.actions)
      state.hasMore = action.payload.hasMore
      state.loadingOlder = false
    },
    addOrUpdate(state, action: PayloadAction<ActionItem>) {
      const incoming = action.payload
      const existing = state.entities[incoming.id]
      if (existing) {
        // Match legacy semantics: only the status field gets refreshed when
        // an existing item is re-added; everything else stays.
        if (existing.status !== incoming.status) {
          existing.status = incoming.status
        }
        return
      }
      adapter.addOne(state, incoming)
    },
    updateStatus(state, action: PayloadAction<{
      id: string
      status: ActionItem['status']
      duration?: number
      output?: string
      error?: string
    }>) {
      const entry = state.entities[action.payload.id]
      if (!entry) return
      entry.status = action.payload.status
      if (action.payload.duration !== undefined) entry.duration = action.payload.duration
      if (action.payload.output !== undefined) entry.output = action.payload.output
      if (action.payload.error !== undefined) entry.error = action.payload.error
    },
    updateTokens(state, action: PayloadAction<{
      id: string
      inputTokens: number
      outputTokens: number
      cacheTokens: number
    }>) {
      const entry = state.entities[action.payload.id]
      if (!entry) return
      entry.inputTokens = action.payload.inputTokens
      entry.outputTokens = action.payload.outputTokens
      entry.cacheTokens = action.payload.cacheTokens
    },
    removeAction(state, action: PayloadAction<{ id: string }>) {
      adapter.removeOne(state, action.payload.id)
    },
    clear(state) {
      adapter.removeAll(state)
      state.hasMore = false
      state.loadingOlder = false
    },
    prependMany(state, action: PayloadAction<{ actions: ActionItem[]; hasMore: boolean }>) {
      adapter.upsertMany(state, action.payload.actions)
      state.hasMore = action.payload.hasMore
      state.loadingOlder = false
    },
    setLoadingOlder(state, action: PayloadAction<boolean>) {
      state.loadingOlder = action.payload
    },
    setCancellingTaskId(state, action: PayloadAction<string | null>) {
      state.cancellingTaskId = action.payload
    },
    markCancelled(state, action: PayloadAction<{ taskId: string }>) {
      const entry = state.entities[action.payload.taskId]
      if (entry) entry.status = 'cancelled'
      state.cancellingTaskId = null
    },
    setCompletingTaskId(state, action: PayloadAction<string | null>) {
      state.completingTaskId = action.payload
    },
    markCompleted(state, action: PayloadAction<{ taskId: string }>) {
      const entry = state.entities[action.payload.taskId]
      if (entry) entry.status = 'completed'
      state.completingTaskId = null
    },
    setResumingTaskId(state, action: PayloadAction<string | null>) {
      state.resumingTaskId = action.payload
    },
    markResumed(state, action: PayloadAction<{ taskId: string }>) {
      const entry = state.entities[action.payload.taskId]
      if (entry) {
        entry.status = 'running'
        // Clear the completed-at duration so the row stops showing the
        // final elapsed time and ticks live again.
        entry.duration = undefined
        entry.error = undefined
      }
      state.resumingTaskId = null
    },
  },
})

export const {
  setInitial,
  addOrUpdate,
  updateStatus,
  updateTokens,
  removeAction,
  clear,
  prependMany,
  setLoadingOlder,
  setCancellingTaskId,
  markCancelled,
  setCompletingTaskId,
  markCompleted,
  setResumingTaskId,
  markResumed,
} = tasksSlice.actions

export const tasksAdapter = adapter
export default tasksSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { actions?: ActionItem[] } | undefined
  const actions = d?.actions || []
  const hasMore = actions.filter(a => a.itemType === 'task').length >= 15
  dispatch(setInitial({ actions, hasMore }))
})

register('action_add', (data, dispatch) => {
  dispatch(addOrUpdate(data as ActionItem))
})

register('action_update', (data, dispatch) => {
  const d = data as {
    id: string
    status: string
    duration?: number
    output?: string
    error?: string
  }
  dispatch(updateStatus({
    id: d.id,
    status: d.status as ActionItem['status'],
    duration: d.duration,
    output: d.output,
    error: d.error,
  }))
})

register('task_token_update', (data, dispatch) => {
  dispatch(updateTokens(data as { id: string; inputTokens: number; outputTokens: number; cacheTokens: number }))
})

register('action_remove', (data, dispatch) => {
  dispatch(removeAction(data as { id: string }))
})

register('action_clear', (_data, dispatch) => {
  dispatch(clear())
})

register('action_history', (data, dispatch) => {
  const d = data as { actions?: ActionItem[]; hasMore?: boolean }
  dispatch(prependMany({ actions: d.actions || [], hasMore: !!d.hasMore }))
})

register('task_cancel_response', (data, dispatch) => {
  const r = data as { taskId: string; success: boolean }
  if (r.success) {
    dispatch(markCancelled({ taskId: r.taskId }))
  } else {
    dispatch(setCancellingTaskId(null))
  }
})

register('task_complete_response', (data, dispatch) => {
  const r = data as { taskId: string; success: boolean }
  if (r.success) {
    dispatch(markCompleted({ taskId: r.taskId }))
  } else {
    dispatch(setCompletingTaskId(null))
  }
})

register('task_resume_response', (data, dispatch) => {
  const r = data as { taskId: string; success: boolean }
  if (r.success) {
    dispatch(markResumed({ taskId: r.taskId }))
  } else {
    dispatch(setResumingTaskId(null))
  }
})
