import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

// Cross-component prefill channel for the chat input, plus per-session
// composer drafts.
//
// `pendingPrefill` is a one-shot payload Chat consumes via useEffect and
// clears immediately. Used by the Playbook modal (and any future feature
// that needs to drop text into the composer from elsewhere in the app).
//
// `drafts` persists each session's unsent composer text, keyed by
// sessionId ('main', a real session id, or 'new' for the draft view). It
// lives in Redux (not component state) so it survives both switching
// between sessions and navigating away to another app tab and back —
// Chat.tsx unmounts/remounts in both cases, but the store doesn't.
interface ChatInputState {
  pendingPrefill: string | null
  drafts: Record<string, string>
}

const initialState: ChatInputState = {
  pendingPrefill: null,
  drafts: {},
}

const chatInputSlice = createSlice({
  name: 'chatInput',
  initialState,
  reducers: {
    setPendingPrefill(state, action: PayloadAction<string>) {
      state.pendingPrefill = action.payload
    },
    clearPendingPrefill(state) {
      state.pendingPrefill = null
    },
    setDraftText(state, action: PayloadAction<{ sessionId: string; text: string }>) {
      const { sessionId, text } = action.payload
      if (text === '') {
        delete state.drafts[sessionId]
      } else {
        state.drafts[sessionId] = text
      }
    },
    // Voice input: append a transcript chunk to the current draft, adding a
    // separating space unless the draft is empty or already ends with one.
    // Done in the reducer (reading current state directly) rather than via
    // a functional setState update, since the recognition callback's
    // closure can be stale by the time a result arrives.
    appendDraftText(state, action: PayloadAction<{ sessionId: string; text: string }>) {
      const { sessionId, text } = action.payload
      const prev = state.drafts[sessionId] ?? ''
      state.drafts[sessionId] = prev + (prev === '' || prev.endsWith(' ') ? '' : ' ') + text
    },
    clearDraftText(state, action: PayloadAction<{ sessionId: string }>) {
      delete state.drafts[action.payload.sessionId]
    },
    // Draft-view handoff: /session/new -> /session/{id}. Carries over any
    // text typed after the send that created the session but before the
    // session_created reply switched the route.
    transferDraft(state, action: PayloadAction<{ from: string; to: string }>) {
      const { from, to } = action.payload
      if (from === to) return
      const text = state.drafts[from]
      if (text === undefined) return
      delete state.drafts[from]
      state.drafts[to] = text
    },
  },
})

export const {
  setPendingPrefill,
  clearPendingPrefill,
  setDraftText,
  appendDraftText,
  clearDraftText,
  transferDraft,
} = chatInputSlice.actions
export default chatInputSlice.reducer

// A deleted session's draft is no longer reachable — drop it so `drafts`
// doesn't accumulate stale entries forever.
register('session_deleted', (data, dispatch) => {
  const d = data as { sessionId?: string } | undefined
  if (d?.sessionId) dispatch(clearDraftText({ sessionId: d.sessionId }))
})
