import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import { register } from '../socket/messageRegistry'

// A decision reply as the model writes it (backend ReplyStream, message type
// `agent_stream`): the reasoning so far, the actions being prepared, and the
// reply message so far. Never stored. Each part carries the id of the real
// item that replaces it: the reasoning row and the action rows come from the
// activity feed with the same ids, and the reply message arrives as a chat
// message whose clientId is the draft's id.

export interface StreamReasoning {
  id: string
  text: string
  done: boolean
}

export interface StreamAction {
  id: string
  name: string
  /** The parameters written so far, as JSON. */
  input: string
  done: boolean
  /** How its row shows it, as the real row will (see ActionItem). */
  displayParam?: string | null
  icon?: string
  integration?: string
}

export interface StreamMessage {
  id: string
  text: string
  continueWork: boolean
  done: boolean
}

export interface SessionStream {
  streamId: string
  attempt: number
  sender: string
  /** When the reply started (epoch ms). */
  startedAt: number
  /** The reply ended: only what runs is kept, until its real item arrives. */
  ended: boolean
  reasoning: StreamReasoning | null
  actions: StreamAction[]
  messages: StreamMessage[]
}

interface StreamPayload {
  sessionId: string
  streamId: string
  attempt: number
  sender: string
  startedAt: number
  phase: 'update' | 'end'
  reasoning?: StreamReasoning | null
  actions?: StreamAction[]
  messages?: StreamMessage[]
  /** On "end": ids of the actions and messages that run. */
  keep?: string[]
  /** The step's status line, once complete; on "end", null when the reply
   *  gave none. Absent: no change. */
  status?: string | null
}

interface StreamState {
  bySession: Record<string, SessionStream>
  /** What the run's current step is doing, shown in place of "Working". It
   *  stays until the next step's line replaces it, and goes with the run. */
  statusBySession: Record<string, string>
}

const initialState: StreamState = {
  bySession: {},
  statusBySession: {},
}

const streamSlice = createSlice({
  name: 'stream',
  initialState,
  reducers: {
    received(state, action: PayloadAction<StreamPayload>) {
      const p = action.payload
      if (!p.sessionId) return
      if (p.status !== undefined) {
        // Also for a reply that did not stream: its "end" alone carries it.
        if (p.status) state.statusBySession[p.sessionId] = p.status
        else if (p.phase === 'end') delete state.statusBySession[p.sessionId]
      }
      const current = state.bySession[p.sessionId]
      if (p.phase === 'end') {
        if (!current || current.streamId !== p.streamId) return
        const keep = new Set(p.keep || [])
        current.ended = true
        current.actions = current.actions.filter(a => keep.has(a.id))
        current.messages = current.messages.filter(m => keep.has(m.id))
        return
      }
      // A new reply, or a new request for the same one (a retry), starts over.
      if (!current || current.streamId !== p.streamId || current.attempt !== p.attempt) {
        state.bySession[p.sessionId] = {
          streamId: p.streamId,
          attempt: p.attempt,
          sender: p.sender,
          startedAt: p.startedAt,
          ended: false,
          reasoning: p.reasoning ?? null,
          actions: p.actions || [],
          messages: p.messages || [],
        }
        return
      }
      if (current.ended) return
      current.reasoning = p.reasoning ?? null
      current.actions = p.actions || []
      current.messages = p.messages || []
    },
    // A message that will not arrive (its action failed or was cancelled).
    dropMessage(state, action: PayloadAction<{ id: string }>) {
      for (const stream of Object.values(state.bySession)) {
        stream.messages = stream.messages.filter(m => m.id !== action.payload.id)
      }
    },
    cleared(state, action: PayloadAction<{ sessionId: string }>) {
      delete state.bySession[action.payload.sessionId]
      delete state.statusBySession[action.payload.sessionId]
    },
  },
})

export const { received, dropMessage, cleared } = streamSlice.actions

export default streamSlice.reducer

export const selectSessionStream = (state: RootState, sessionId: string): SessionStream | undefined =>
  state.stream.bySession[sessionId]

export const selectSessionStatus = (state: RootState, sessionId: string): string | undefined =>
  state.stream.statusBySession[sessionId]

// --- inbound message handlers --------------------------------------------

register('agent_stream', (data, dispatch) => {
  dispatch(received(data as StreamPayload))
})

register('action_update', (data, dispatch) => {
  const d = data as { id?: string; status?: string } | undefined
  if (d?.id && (d.status === 'error' || d.status === 'cancelled')) {
    dispatch(dropMessage({ id: d.id }))
  }
})

// The run ended: whatever is still shown of its replies is settled.
register('session_busy', (data, dispatch) => {
  const d = data as { sessionId?: string; busy?: boolean; state?: string } | undefined
  if (!d?.sessionId) return
  const state = d.state ?? (d.busy ? 'running' : 'idle')
  if (state === 'idle') dispatch(cleared({ sessionId: d.sessionId }))
})

register('chat_clear', (data, dispatch) => {
  const d = data as { sessionId?: string | null } | undefined
  if (d?.sessionId) dispatch(cleared({ sessionId: d.sessionId }))
})
