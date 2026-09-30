import { createEntityAdapter, createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { PendingAgentAppSetup } from '../../types'
import type { AppDispatch } from '../index'
import { register } from '../socket/messageRegistry'
import { getSocketClient } from '../socket/socketInstance'
import { UI_STATE } from '../uiState'
import { setUiState } from './uiSlice'

// Pending chat-started Agent App setups (issue #448).
//
// agent_app_scaffold asks its setup questions in the Create Custom wizard and
// creates nothing until the user answers. The backend keeps each unfinished
// setup (app/agent_app/pending_setups.py) and pushes the list on connect; this
// slice mirrors it. Closing the popup only hides it (`shownId`), so the
// Resume card in the originating chat can bring it back. Only finalize or an
// explicit cancel ends a setup.

export const setupsAdapter = createEntityAdapter<PendingAgentAppSetup, string>({
  selectId: setup => setup.wizardId,
  sortComparer: (a, b) => a.createdAt - b.createdAt,
})

interface AgentAppSetupState {
  setups: ReturnType<typeof setupsAdapter.getInitialState>
  /** The setup whose wizard popup is on screen. */
  shownId: string | null
  /** The setup the user asked to cancel, awaiting confirmation. */
  confirmCancelId: string | null
}

const initialState: AgentAppSetupState = {
  setups: setupsAdapter.getInitialState(),
  shownId: null,
  confirmCancelId: null,
}

const agentAppSetupSlice = createSlice({
  name: 'agentAppSetup',
  initialState,
  reducers: {
    setSetups(state, action: PayloadAction<PendingAgentAppSetup[]>) {
      setupsAdapter.setAll(state.setups, action.payload)
      if (state.shownId && !state.setups.entities[state.shownId]) state.shownId = null
      if (state.confirmCancelId && !state.setups.entities[state.confirmCancelId]) state.confirmCancelId = null
    },
    /** A live summons from the agent: store it and pop it up. */
    setupOpened(state, action: PayloadAction<PendingAgentAppSetup>) {
      setupsAdapter.upsertOne(state.setups, action.payload)
      state.shownId = action.payload.wizardId
    },
    setupEnded(state, action: PayloadAction<string>) {
      setupsAdapter.removeOne(state.setups, action.payload)
      if (state.shownId === action.payload) state.shownId = null
      if (state.confirmCancelId === action.payload) state.confirmCancelId = null
    },
    sessionSetupsRemoved(state, action: PayloadAction<string>) {
      const ids = Object.values(state.setups.entities)
        .filter(s => s?.originSessionId === action.payload)
        .map(s => s!.wizardId)
      setupsAdapter.removeMany(state.setups, ids)
      if (state.shownId && ids.includes(state.shownId)) state.shownId = null
      if (state.confirmCancelId && ids.includes(state.confirmCancelId)) state.confirmCancelId = null
    },
    showSetup(state, action: PayloadAction<string>) {
      if (state.setups.entities[action.payload]) state.shownId = action.payload
    },
    /** Close the popup; the setup stays pending and resumable. */
    hideSetup(state) {
      state.shownId = null
    },
    requestCancelSetup(state, action: PayloadAction<string>) {
      state.confirmCancelId = action.payload
    },
    dismissCancelSetup(state) {
      state.confirmCancelId = null
    },
  },
})

export const {
  setSetups,
  setupOpened,
  setupEnded,
  sessionSetupsRemoved,
  showSetup,
  hideSetup,
  requestCancelSetup,
  dismissCancelSetup,
} = agentAppSetupSlice.actions
export default agentAppSetupSlice.reducer

/** End a setup's saved answers (this tab's draft of it). */
export function clearSetupProgress(wizardId: string) {
  return setUiState(UI_STATE.agentApp.setupProgress(wizardId), null)
}

/**
 * Cancel a setup for good: the backend drops it and tells the chat that
 * started it. Removed here right away; the broadcast reply removes it in
 * every other tab.
 */
export function cancelSetup(wizardId: string) {
  return (dispatch: AppDispatch) => {
    getSocketClient().send('agent_app_setup_cancel', { wizardId })
    dispatch(setupEnded(wizardId))
    dispatch(clearSetupProgress(wizardId))
  }
}

// --- inbound message handlers --------------------------------------------

register('agent_app_setup_list', (data, dispatch) => {
  const d = data as { setups?: PendingAgentAppSetup[] } | undefined
  dispatch(setSetups(d?.setups || []))
})

register('agent_app_wizard_open', (data, dispatch) => {
  const d = data as PendingAgentAppSetup | undefined
  if (d?.wizardId && Array.isArray(d.questions) && d.questions.length > 0) {
    dispatch(setupOpened(d))
  }
})

register('agent_app_setup_cancel', (data, dispatch) => {
  const d = data as { wizardId?: string } | undefined
  if (d?.wizardId) dispatch(setupEnded(d.wizardId))
})

// A successful finalize created the project; the setup is over everywhere.
// Follow-up rounds (followupQuestions) and failures keep it pending.
register('agent_app_wizard_finalize', (data, dispatch) => {
  const d = data as { success?: boolean; wizardId?: string; projectId?: string } | undefined
  if (d?.success && d.projectId && d.wizardId) dispatch(setupEnded(d.wizardId))
})

register('session_deleted', (data, dispatch) => {
  const d = data as { sessionId?: string } | undefined
  if (d?.sessionId) dispatch(sessionSetupsRemoved(d.sessionId))
})
