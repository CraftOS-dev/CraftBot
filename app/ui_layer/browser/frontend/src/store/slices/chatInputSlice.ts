import { createSlice, PayloadAction } from '@reduxjs/toolkit'

// Cross-component channel for the chat input, plus persisted draft text.
//
// `pendingPrefill` is a one-shot payload that Chat consumes via useEffect and
// clears immediately. Used by the Playbook modal (and any future feature
// that needs to drop text into the composer from elsewhere in the app).
//
// `drafts` persists each conversation's composer text, keyed by
// `livingUIId ?? 'main'` (Chat.tsx is shared between the main Chat page and
// every Living UI project's chat panel), so it survives the route unmount
// that happens when navigating to another tab (Settings, Tasks & Actions)
// and back.
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
    setDraftText(state, action: PayloadAction<{ key: string; text: string }>) {
      state.drafts[action.payload.key] = action.payload.text
    },
    clearDraftText(state, action: PayloadAction<string>) {
      delete state.drafts[action.payload]
    },
  },
})

export const { setPendingPrefill, clearPendingPrefill, setDraftText, clearDraftText } = chatInputSlice.actions
export default chatInputSlice.reducer
