import type { RootState } from '../index'

export const selectPendingPrefill = (state: RootState) => state.chatInput.pendingPrefill
