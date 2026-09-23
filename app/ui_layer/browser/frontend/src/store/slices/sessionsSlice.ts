import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { SessionInfo } from '../../types'
import { register } from '../socket/messageRegistry'

// Chat sessions (main / chat / agent_app). The list is server-owned: the
// backend pushes the full list on init/session_list and incremental
// created/updated/deleted events afterwards.
interface SessionsState {
  sessions: SessionInfo[]
}

const initialState: SessionsState = {
  sessions: [],
}

const sessionsSlice = createSlice({
  name: 'sessions',
  initialState,
  reducers: {
    setSessions(state, action: PayloadAction<SessionInfo[]>) {
      state.sessions = action.payload
    },
    upsertSession(state, action: PayloadAction<SessionInfo>) {
      const incoming = action.payload
      const idx = state.sessions.findIndex(s => s.id === incoming.id)
      if (idx === -1) {
        state.sessions.push(incoming)
      } else {
        state.sessions[idx] = incoming
      }
    },
    removeSession(state, action: PayloadAction<{ sessionId: string }>) {
      state.sessions = state.sessions.filter(s => s.id !== action.payload.sessionId)
    },
  },
})

export const { setSessions, upsertSession, removeSession } = sessionsSlice.actions
export default sessionsSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { sessions?: SessionInfo[] } | undefined
  dispatch(setSessions(d?.sessions || []))
})

register('session_list', (data, dispatch) => {
  const d = data as { sessions?: SessionInfo[] } | undefined
  dispatch(setSessions(d?.sessions || []))
})

register('session_created', (data, dispatch) => {
  const d = data as { session?: SessionInfo } | undefined
  if (d?.session) dispatch(upsertSession(d.session))
})

register('session_updated', (data, dispatch) => {
  const d = data as { session?: SessionInfo } | undefined
  if (d?.session) dispatch(upsertSession(d.session))
})

register('session_deleted', (data, dispatch) => {
  const d = data as { sessionId?: string } | undefined
  if (d?.sessionId) dispatch(removeSession({ sessionId: d.sessionId }))
})

// session_cleared only affects the session's timeline (messages/activity
// slices listen for it); the session list itself is untouched.
