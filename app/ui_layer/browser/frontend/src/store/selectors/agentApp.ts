import type { RootState } from '../index'

export const selectAgentAppProjects = (state: RootState) =>
  state.agentApp.projects

export const selectAgentAppCreating = (state: RootState) =>
  state.agentApp.creating

export const selectAgentAppTodos = (state: RootState) =>
  state.agentApp.todos

export const selectAgentAppBuildEvents = (state: RootState) =>
  state.agentApp.buildEvents

export const selectAgentAppSnapshots = (state: RootState) =>
  state.agentApp.snapshots

export const selectActiveAgentAppId = (state: RootState) =>
  state.agentApp.activeId

export const selectAgentAppStates = (state: RootState) =>
  state.agentApp.states
