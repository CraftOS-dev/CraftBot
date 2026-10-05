import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { PendingAgentAppSetup } from '../../types'
import { setupsAdapter } from '../slices/agentAppSetupSlice'

const adapterSelectors = setupsAdapter.getSelectors((state: RootState) => state.agentAppSetup.setups)

/** Every pending chat setup, oldest first. */
export const selectPendingSetups = adapterSelectors.selectAll

export const selectPendingSetupById = (state: RootState, wizardId: string): PendingAgentAppSetup | undefined =>
  adapterSelectors.selectById(state, wizardId)

/** Pending setups started from one chat, oldest first (its Resume card queue). */
export const selectSetupsForSession = createSelector(
  [selectPendingSetups, (_: RootState, sessionId: string) => sessionId],
  (setups, sessionId): PendingAgentAppSetup[] => setups.filter(s => s.originSessionId === sessionId),
)

/** The setup whose wizard popup is on screen, if any. */
export const selectShownSetup = (state: RootState): PendingAgentAppSetup | undefined => {
  const id = state.agentAppSetup.shownId
  return id ? adapterSelectors.selectById(state, id) : undefined
}

/** The setup awaiting cancel confirmation, if any. */
export const selectSetupPendingCancel = (state: RootState): PendingAgentAppSetup | undefined => {
  const id = state.agentAppSetup.confirmCancelId
  return id ? adapterSelectors.selectById(state, id) : undefined
}
