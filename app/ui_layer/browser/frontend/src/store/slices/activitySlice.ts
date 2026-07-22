import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { ActionItem } from '../../types'
import { register } from '../socket/messageRegistry'

// Inline activity (action + reasoning items) keyed per session. Each bucket
// is kept in chronological (createdAt ascending) order — the backend pushes
// items as they happen, and init delivers them pre-sorted.
interface ActivityState {
  bySession: Record<string, ActionItem[]>
}

const initialState: ActivityState = {
  bySession: {},
}

function bucketFor(state: ActivityState, sessionId: string): ActionItem[] {
  let bucket = state.bySession[sessionId]
  if (!bucket) {
    bucket = []
    state.bySession[sessionId] = bucket
  }
  return bucket
}

const activitySlice = createSlice({
  name: 'activity',
  initialState,
  reducers: {
    setInitial(state, action: PayloadAction<{ items: ActionItem[] }>) {
      state.bySession = {}
      for (const item of action.payload.items) {
        if (!item.sessionId) continue
        bucketFor(state, item.sessionId).push(item)
      }
      for (const bucket of Object.values(state.bySession)) {
        bucket.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0))
      }
    },
    addOrUpdate(state, action: PayloadAction<ActionItem>) {
      const incoming = action.payload
      if (!incoming.sessionId) return
      const bucket = bucketFor(state, incoming.sessionId)
      const idx = bucket.findIndex(a => a.id === incoming.id)
      if (idx === -1) {
        bucket.push(incoming)
      } else {
        // Re-broadcast of a known item: refresh mutable fields, keep the rest.
        bucket[idx] = { ...bucket[idx], ...incoming }
      }
    },
    updateItem(state, action: PayloadAction<{
      id: string
      sessionId?: string
      status?: ActionItem['status']
      completedAt?: number
      duration?: number
      input?: string
      output?: string
      error?: string
    }>) {
      const { id, sessionId, ...fields } = action.payload
      const buckets = sessionId && state.bySession[sessionId]
        ? [state.bySession[sessionId]]
        : Object.values(state.bySession)
      for (const bucket of buckets) {
        const entry = bucket.find(a => a.id === id)
        if (!entry) continue
        if (fields.status !== undefined) entry.status = fields.status
        if (fields.completedAt != null) entry.completedAt = fields.completedAt
        if (fields.duration !== undefined) entry.duration = fields.duration
        if (fields.input !== undefined) entry.input = fields.input
        if (fields.output !== undefined) entry.output = fields.output
        if (fields.error !== undefined) entry.error = fields.error
        return
      }
    },
    removeItem(state, action: PayloadAction<{ id: string; sessionId?: string }>) {
      const { id, sessionId } = action.payload
      if (sessionId && state.bySession[sessionId]) {
        state.bySession[sessionId] = state.bySession[sessionId].filter(a => a.id !== id)
        return
      }
      for (const key of Object.keys(state.bySession)) {
        state.bySession[key] = state.bySession[key].filter(a => a.id !== id)
      }
    },
    clearSession(state, action: PayloadAction<{ sessionId: string | null }>) {
      const { sessionId } = action.payload
      if (sessionId === null) {
        state.bySession = {}
      } else {
        delete state.bySession[sessionId]
      }
    },
    dropSession(state, action: PayloadAction<{ sessionId: string }>) {
      delete state.bySession[action.payload.sessionId]
    },
  },
})

export const {
  setInitial,
  addOrUpdate,
  updateItem,
  removeItem,
  clearSession,
  dropSession,
} = activitySlice.actions

export default activitySlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { actions?: ActionItem[] } | undefined
  dispatch(setInitial({ items: d?.actions || [] }))
})

register('action_add', (data, dispatch) => {
  dispatch(addOrUpdate(data as ActionItem))
})

register('action_update', (data, dispatch) => {
  dispatch(updateItem(data as {
    id: string
    sessionId?: string
    status?: ActionItem['status']
    completedAt?: number
    duration?: number
    input?: string
    output?: string
    error?: string
  }))
})

register('action_remove', (data, dispatch) => {
  dispatch(removeItem(data as { id: string; sessionId?: string }))
})

register('chat_clear', (data, dispatch) => {
  const d = data as { sessionId?: string | null } | undefined
  dispatch(clearSession({ sessionId: d?.sessionId ?? null }))
})

register('session_cleared', (data, dispatch) => {
  const d = data as { sessionId?: string } | undefined
  if (d?.sessionId) dispatch(clearSession({ sessionId: d.sessionId }))
})

register('session_deleted', (data, dispatch) => {
  const d = data as { sessionId?: string } | undefined
  if (d?.sessionId) dispatch(dropSession({ sessionId: d.sessionId }))
})
