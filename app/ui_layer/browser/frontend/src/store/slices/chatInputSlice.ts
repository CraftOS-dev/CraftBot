import { createSlice, PayloadAction } from '@reduxjs/toolkit'

// Cross-component prefill channel for the chat input.
//
// The chat input state itself stays local to Chat.tsx — this slice only
// carries a one-shot "pendingPrefill" payload that Chat consumes via
// useEffect and clears immediately. Used by the Playbook modal (and any
// future feature that needs to drop text into the composer from elsewhere
// in the app).
interface ChatInputState {
  pendingPrefill: string | null
}

const initialState: ChatInputState = {
  pendingPrefill: null,
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
  },
})

export const { setPendingPrefill, clearPendingPrefill } = chatInputSlice.actions
export default chatInputSlice.reducer
