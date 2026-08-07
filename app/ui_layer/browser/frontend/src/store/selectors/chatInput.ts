import type { RootState } from '../index'

export const selectPendingPrefill = (state: RootState) => state.chatInput.pendingPrefill

export const selectDraftText = (state: RootState, sessionId: string) =>
  state.chatInput.drafts[sessionId] ?? ''
