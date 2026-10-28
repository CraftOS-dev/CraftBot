/**
 * The terminal client's Redux store.
 *
 * Built from the browser frontend's own slice reducers (imported read-only,
 * so both UIs share one protocol model) plus the terminal's `tui` slice.
 * Importing a slice also registers its inbound socket handlers, exactly as in
 * the browser. `installBrowserGlobals` must run before this module loads.
 */
import { configureStore } from '@reduxjs/toolkit'
import connectionReducer from '../../../browser/frontend/src/store/slices/connectionSlice'
import messagesReducer from '../../../browser/frontend/src/store/slices/messagesSlice'
import activityReducer from '../../../browser/frontend/src/store/slices/activitySlice'
import sessionsReducer from '../../../browser/frontend/src/store/slices/sessionsSlice'
import dashboardReducer from '../../../browser/frontend/src/store/slices/dashboardSlice'
import onboardingReducer from '../../../browser/frontend/src/store/slices/onboardingSlice'
import localLlmReducer from '../../../browser/frontend/src/store/slices/localLlmSlice'
import agentAppReducer from '../../../browser/frontend/src/store/slices/agentAppSlice'
import agentReducer from '../../../browser/frontend/src/store/slices/agentSlice'
import workspaceReducer from '../../../browser/frontend/src/store/slices/workspaceSlice'
import mcpSettingsReducer from '../../../browser/frontend/src/store/slices/mcpSettingsSlice'
import memorySettingsReducer from '../../../browser/frontend/src/store/slices/memorySettingsSlice'
import skillsSettingsReducer from '../../../browser/frontend/src/store/slices/skillsSettingsSlice'
import commandsSettingsReducer from '../../../browser/frontend/src/store/slices/commandsSettingsSlice'
import proactiveSettingsReducer from '../../../browser/frontend/src/store/slices/proactiveSettingsSlice'
import agentAppSettingsReducer from '../../../browser/frontend/src/store/slices/agentAppSettingsSlice'
import generalSettingsReducer from '../../../browser/frontend/src/store/slices/generalSettingsSlice'
import modelSettingsReducer from '../../../browser/frontend/src/store/slices/modelSettingsSlice'
import reasoningReducer from '../../../browser/frontend/src/store/slices/reasoningSlice'
import integrationsSettingsReducer from '../../../browser/frontend/src/store/slices/integrationsSettingsSlice'
import chatInputReducer from '../../../browser/frontend/src/store/slices/chatInputSlice'
import playbooksReducer from '../../../browser/frontend/src/store/slices/playbooksSlice'
import miniBrowserReducer from '../../../browser/frontend/src/store/slices/miniBrowserSlice'
import uiReducer from '../../../browser/frontend/src/store/slices/uiSlice'
import { socketMiddleware } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import '../../../browser/frontend/src/store/socket/versionWatch'
import '../../../browser/frontend/src/store/socket/readReceipts'
import {
  createUiPersistenceMiddleware,
  loadPersistedUiState,
} from '../../../browser/frontend/src/store/uiState'
import tuiReducer from './tuiSlice'

export const store = configureStore({
  reducer: {
    connection: connectionReducer,
    messages: messagesReducer,
    activity: activityReducer,
    sessions: sessionsReducer,
    dashboard: dashboardReducer,
    onboarding: onboardingReducer,
    localLlm: localLlmReducer,
    agentApp: agentAppReducer,
    agent: agentReducer,
    workspace: workspaceReducer,
    mcpSettings: mcpSettingsReducer,
    memorySettings: memorySettingsReducer,
    skillsSettings: skillsSettingsReducer,
    commandsSettings: commandsSettingsReducer,
    proactiveSettings: proactiveSettingsReducer,
    agentAppSettings: agentAppSettingsReducer,
    generalSettings: generalSettingsReducer,
    modelSettings: modelSettingsReducer,
    reasoning: reasoningReducer,
    integrationsSettings: integrationsSettingsReducer,
    chatInput: chatInputReducer,
    playbooks: playbooksReducer,
    miniBrowser: miniBrowserReducer,
    ui: uiReducer,
    tui: tuiReducer,
  },
  preloadedState: { ui: loadPersistedUiState() },
  // The development-only safety checks walk the whole state on every
  // dispatch; the transcript makes that the dominant cost. Off, as the
  // browser does for its large subtrees.
  middleware: getDefault =>
    getDefault({ immutableCheck: false, serializableCheck: false }).concat(
      socketMiddleware,
      createUiPersistenceMiddleware(),
    ),
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
