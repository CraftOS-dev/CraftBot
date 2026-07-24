import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { ChatMessage } from '../../types'
import { register } from '../socket/messageRegistry'

// Chat messages keyed per session. Each bucket keeps its messages in
// timestamp-ascending order. Optimistic ("pending") messages use
// `pending:<clientId>` as their messageId until the server echo arrives —
// then `addOrReconcile` swaps the temp entry for the real one in place.
interface SessionMessages {
  items: ChatMessage[]
  hasMore: boolean
  loadingOlder: boolean
  // Has an authoritative (session-scoped) page been fetched via
  // chat_history since the last init/reconnect? `init`'s message sample is
  // capped globally across every session, not per session — a bucket it
  // seeds must NOT be mistaken for a fully-loaded one just because it has
  // some items.
  initialLoaded: boolean
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
    bucket = { items: [], hasMore: false, loadingOlder: false, initialLoaded: false }
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
      state.bySession = {}
      for (const msg of action.payload.messages) {
        if (!msg.sessionId) continue
        bucketFor(state, msg.sessionId).items.push(msg)
      }
      for (const bucket of Object.values(state.bySession)) {
        sortBucket(bucket)
        // Heuristic: a full first page implies more history exists.
        bucket.hasMore = bucket.items.length >= 50
      }
    },
    addOrReconcile(state, action: PayloadAction<ChatMessage>) {
      const incoming = action.payload
      if (!incoming.sessionId) return
      const bucket = bucketFor(state, incoming.sessionId)
      // Use the server's authoritative timestamp (incoming.timestamp) —
      // it's what's actually persisted in chat.db, and what
      // get_messages_before's pagination cursor is compared against there.
      // Pinning this to the client's optimistic send-time instead (as a
      // past revision did, to dodge a virtualizer reorder-overlap bug)
      // would leave this message's in-store timestamp permanently
      // mismatched with its stored value — harmless for a message that
      // stays at the tail of a session, but if it's ever the oldest loaded
      // message it becomes the "before" cursor sent back to the server,
      // which can skip genuinely-older rows the mismatch excludes. The
      // reorder-overlap bug is now handled by the virtualizer's
      // content-keyed getItemKey instead, so this no longer needs pinning.
      if (incoming.clientId) {
        // Swap the pending optimistic entry (same clientId) for the
        // confirmed server message so no duplicate bubble appears.
        const tempIdx = bucket.items.findIndex(
          m => m.pending && m.clientId === incoming.clientId,
        )
        if (tempIdx !== -1) bucket.items.splice(tempIdx, 1)
      }
      upsertMessage(bucket, { ...incoming, pending: false })
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
      bucket.initialLoaded = true
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
