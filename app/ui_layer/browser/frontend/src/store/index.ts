import { configureStore } from '@reduxjs/toolkit'
import connectionReducer from './slices/connectionSlice'
import messagesReducer from './slices/messagesSlice'
import activityReducer from './slices/activitySlice'
import sessionsReducer from './slices/sessionsSlice'
import dashboardReducer from './slices/dashboardSlice'
import onboardingReducer from './slices/onboardingSlice'
import localLlmReducer from './slices/localLlmSlice'
import agentAppReducer from './slices/agentAppSlice'
import agentReducer from './slices/agentSlice'
import workspaceReducer from './slices/workspaceSlice'
import mcpSettingsReducer from './slices/mcpSettingsSlice'
import memorySettingsReducer from './slices/memorySettingsSlice'
import skillsSettingsReducer from './slices/skillsSettingsSlice'
import commandsSettingsReducer from './slices/commandsSettingsSlice'
import proactiveSettingsReducer from './slices/proactiveSettingsSlice'
import agentAppSettingsReducer from './slices/agentAppSettingsSlice'
import generalSettingsReducer from './slices/generalSettingsSlice'
import modelSettingsReducer from './slices/modelSettingsSlice'
import integrationsSettingsReducer from './slices/integrationsSettingsSlice'
import chatInputReducer from './slices/chatInputSlice'
import uiReducer from './slices/uiSlice'
import { socketMiddleware } from './socket/socketMiddleware'
import { createUiPersistenceMiddleware, loadPersistedUiState } from './uiState'

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
    integrationsSettings: integrationsSettingsReducer,
    chatInput: chatInputReducer,
    ui: uiReducer,
  },
  // Remembered UI state (panel sizes, filters, scroll…) is restored before
  // the first render, so nothing flashes from its default.
  preloadedState: { ui: loadPersistedUiState() },
  middleware: (getDefault) => getDefault().concat(socketMiddleware, createUiPersistenceMiddleware()),
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
