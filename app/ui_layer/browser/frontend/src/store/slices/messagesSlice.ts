import { createSlice, createEntityAdapter, PayloadAction } from '@reduxjs/toolkit'
import type { ChatMessage } from '../../types'
import { register } from '../socket/messageRegistry'

// Messages are normalized by messageId. Optimistic ("pending") messages use
// `pending:<clientId>` as their messageId until the server echo arrives —
// then `addOrReconcile` swaps the temp entry for the real one in place.
const adapter = createEntityAdapter<ChatMessage, string>({
  selectId: (m) => m.messageId,
  sortComparer: (a, b) => a.timestamp - b.timestamp,
})

interface MessagesExtraState {
  hasMore: boolean
  loadingOlder: boolean
}

const initialState = adapter.getInitialState<MessagesExtraState>({
  hasMore: false,
  loadingOlder: false,
})

const messagesSlice = createSlice({
  name: 'messages',
  initialState,
  reducers: {
    setInitial(state, action: PayloadAction<{ messages: ChatMessage[]; hasMore: boolean }>) {
      adapter.setAll(state, action.payload.messages)
      state.hasMore = action.payload.hasMore
      state.loadingOlder = false
    },
    addOrReconcile(state, action: PayloadAction<ChatMessage>) {
      const incoming = action.payload
      if (incoming.clientId) {
        // Find a pending entry with the same clientId and swap it for the
        // confirmed server message. Keeping it in place preserves scroll
        // position and avoids a duplicate bubble.
        const tempId = state.ids.find((id) => {
          const entry = state.entities[id]
          return entry?.pending && entry.clientId === incoming.clientId
        })
        if (tempId !== undefined) {
          adapter.removeOne(state, tempId)
        }
      }
      adapter.upsertOne(state, { ...incoming, pending: false })
    },
    addOptimistic(state, action: PayloadAction<ChatMessage>) {
      adapter.upsertOne(state, action.payload)
    },
    prependMany(state, action: PayloadAction<{ messages: ChatMessage[]; hasMore: boolean }>) {
      adapter.upsertMany(state, action.payload.messages)
      state.hasMore = action.payload.hasMore
      state.loadingOlder = false
    },
    clear(state) {
      adapter.removeAll(state)
      state.hasMore = false
      state.loadingOlder = false
    },
    setLoadingOlder(state, action: PayloadAction<boolean>) {
      state.loadingOlder = action.payload
    },
    markOptionSelected(state, action: PayloadAction<{ messageId: string; value: string }>) {
      const { messageId, value } = action.payload
      const entry = state.entities[messageId]
      if (entry && !entry.optionSelected) {
        entry.optionSelected = value
      }
    },
    markQuestionsAnswered(
      state,
      action: PayloadAction<{ messageId: string; answers?: Record<string, string>; declined?: boolean }>
    ) {
      const { messageId, answers, declined } = action.payload
      const entry = state.entities[messageId]
      if (entry && !entry.questionAnswers && !entry.questionsDeclined) {
        if (declined) {
          entry.questionsDeclined = true
        } else {
          entry.questionAnswers = answers
        }
      }
    },
  },
})

export const {
  setInitial,
  addOrReconcile,
  addOptimistic,
  prependMany,
  clear,
  setLoadingOlder,
  markOptionSelected,
  markQuestionsAnswered,
} = messagesSlice.actions

export const messagesAdapter = adapter
export default messagesSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { messages?: ChatMessage[] } | undefined
  const messages = d?.messages || []
  dispatch(setInitial({ messages, hasMore: messages.length >= 50 }))
})

register('chat_message', (data, dispatch) => {
  dispatch(addOrReconcile(data as ChatMessage))
})

register('chat_history', (data, dispatch) => {
  const d = data as { messages?: ChatMessage[]; hasMore?: boolean }
  dispatch(prependMany({ messages: d.messages || [], hasMore: !!d.hasMore }))
})

register('chat_clear', (_data, dispatch) => {
  dispatch(clear())
})
