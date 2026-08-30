import type { RootState } from '../index'

export const selectAgentAppSettingsProjects = (state: RootState) =>
  state.agentAppSettings.projects
export const selectAgentAppSettingsHasLoadedProjects = (state: RootState) =>
  state.agentAppSettings.hasLoadedProjects
