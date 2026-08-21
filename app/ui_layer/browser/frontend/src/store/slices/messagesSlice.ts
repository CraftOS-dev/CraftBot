import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { ChatMessage } from '../../types'
import { register } from '../socket/messageRegistry'

// Chat messages keyed per session. Each bucket keeps its messages in
// timestamp-ascending order. Optimistic ("pending") messages use
// `pending:<clientId>` as their messageId until the server echo arrives —
// then `addOrReconcile` swaps the temp entry for the real one in place.
//
// `historyStatus` tracks the session's initial history load (chat_history
// round trip with no beforeTimestamp). The init payload only carries an
// in-memory snapshot, so every bucket starts 'unfetched' and the Chat view
// requests the session's real first page on mount. It is distinct from
// `loadingOlder`, which is scroll-up pagination only — the initial load
// must not render the "Loading older messages" row. `hasMore` is only
// ever set from a chat_history response.
export type HistoryStatus = 'unfetched' | 'loading' | 'fetched'

interface SessionMessages {
  items: ChatMessage[]
  hasMore: boolean
  loadingOlder: boolean
  historyStatus: HistoryStatus
}

interface MessagesState {
  bySession: Record<string, SessionMessages>
}

const initialState: MessagesState = {
  bySession: {},
}

function bucketFor(state: MessagesState, sessionId: string): SessionMessages {
  let bucket = state.bySession[sessionId]
  if (!bucket) {
    bucket = { items: [], hasMore: false, loadingOlder: false, historyStatus: 'unfetched' }
    state.bySession[sessionId] = bucket
  }
  return bucket
}

function sortBucket(bucket: SessionMessages) {
  bucket.items.sort((a, b) => a.timestamp - b.timestamp)
}

// Upsert by messageId, preserving timestamp order.
function upsertMessage(bucket: SessionMessages, message: ChatMessage) {
  const idx = bucket.items.findIndex(m => m.messageId === message.messageId)
  if (idx === -1) {
    bucket.items.push(message)
  } else {
    bucket.items[idx] = message
  }
  sortBucket(bucket)
}

const messagesSlice = createSlice({
  name: 'messages',
  initialState,
  reducers: {
    setInitial(state, action: PayloadAction<{ messages: ChatMessage[] }>) {
      // Replaces everything: init carries only the backend's in-memory
      // snapshot, so every bucket restarts unfetched and the per-session
      // chat_history fetch re-establishes the real page + hasMore.
      state.bySession = {}
      for (const msg of action.payload.messages) {
        if (!msg.sessionId) continue
        bucketFor(state, msg.sessionId).items.push(msg)
      }
      for (const bucket of Object.values(state.bySession)) {
        sortBucket(bucket)
      }
    },
    addOrReconcile(state, action: PayloadAction<ChatMessage>) {
      const incoming = action.payload
      if (!incoming.sessionId) return
      const bucket = bucketFor(state, incoming.sessionId)
      // Carry the optimistic bubble's own timestamp forward rather than
      // adopting the server's. The two are assigned by different clocks
      // (client send-click time vs. server receipt time), so swapping to
      // the server's value can shift this message's sort position past
      // activity items that streamed in during the round trip — a
      // mid-render reorder that the virtualizer renders as a transient
      // overlap between rows.
      let timestamp = incoming.timestamp
      if (incoming.clientId) {
        // Swap the pending optimistic entry (same clientId) for the
        // confirmed server message so no duplicate bubble appears.
        const tempIdx = bucket.items.findIndex(
          m => m.pending && m.clientId === incoming.clientId,
        )
        if (tempIdx !== -1) {
          timestamp = bucket.items[tempIdx].timestamp
          bucket.items.splice(tempIdx, 1)
        }
      }
      upsertMessage(bucket, { ...incoming, timestamp, pending: false })
    },
    addOptimistic(state, action: PayloadAction<ChatMessage>) {
      if (!action.payload.sessionId) return
      upsertMessage(bucketFor(state, action.payload.sessionId), action.payload)
    },
    // Draft handoff: move the 'new' bucket's messages (the optimistic user
    // bubble) into the real session's bucket the moment session_created
    // arrives, so the message never disappears while waiting for the
    // server echo (which later reconciles by clientId as usual).
    transferSession(state, action: PayloadAction<{ from: string; to: string }>) {
      const { from, to } = action.payload
      const src = state.bySession[from]
      if (!src || from === to) return
      delete state.bySession[from]
      const dst = bucketFor(state, to)
      for (const msg of src.items) {
        upsertMessage(dst, { ...msg, sessionId: to })
      }
    },
    prependMany(state, action: PayloadAction<{
      sessionId: string
      messages: ChatMessage[]
      hasMore: boolean
    }>) {
      const bucket = bucketFor(state, action.payload.sessionId)
      for (const msg of action.payload.messages) {
        upsertMessage(bucket, msg)
      }
      bucket.hasMore = action.payload.hasMore
      bucket.loadingOlder = false
      bucket.historyStatus = 'fetched'
    },
    // The initial (no-beforeTimestamp) history request is in flight.
    historyRequested(state, action: PayloadAction<{ sessionId: string }>) {
      bucketFor(state, action.payload.sessionId).historyStatus = 'loading'
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
    setLoadingOlder(state, action: PayloadAction<{ sessionId: string; loading: boolean }>) {
      bucketFor(state, action.payload.sessionId).loadingOlder = action.payload.loading
    },
    markOptionSelected(state, action: PayloadAction<{
      sessionId: string
      messageId: string
      value: string
    }>) {
      const bucket = state.bySession[action.payload.sessionId]
      const entry = bucket?.items.find(m => m.messageId === action.payload.messageId)
      if (entry && !entry.optionSelected) {
        entry.optionSelected = action.payload.value
      }
    },
  },
})

export const {
  setInitial,
  addOrReconcile,
  addOptimistic,
  transferSession,
  prependMany,
  historyRequested,
  clearSession,
  dropSession,
  setLoadingOlder,
  markOptionSelected,
} = messagesSlice.actions

export default messagesSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { messages?: ChatMessage[] } | undefined
  dispatch(setInitial({ messages: d?.messages || [] }))
})

register('chat_message', (data, dispatch) => {
  dispatch(addOrReconcile(data as ChatMessage))
})

register('chat_history', (data, dispatch) => {
  const d = data as { sessionId?: string; messages?: ChatMessage[]; hasMore?: boolean }
  if (!d.sessionId) return
  dispatch(prependMany({
    sessionId: d.sessionId,
    messages: d.messages || [],
    hasMore: !!d.hasMore,
  }))
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

// A pinned question was answered/dismissed (possibly on another client):
// recording the selection un-pins it and locks the bubble's chips.
register('question_answered', (data, dispatch) => {
  const d = data as { sessionId?: string; messageId?: string; value?: string } | undefined
  if (d?.sessionId && d.messageId && d.value) {
    dispatch(markOptionSelected({ sessionId: d.sessionId, messageId: d.messageId, value: d.value }))
  }
})
