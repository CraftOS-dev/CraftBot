import type { RootState } from '../index'

export const selectPendingPrefill = (state: RootState) => state.chatInput.pendingPrefill

export const selectDraftText = (key: string) => (state: RootState) => state.chatInput.drafts[key] ?? ''
