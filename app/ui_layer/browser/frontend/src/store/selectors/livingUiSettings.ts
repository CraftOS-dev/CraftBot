import type { RootState } from '../index'

export const selectLivingUiSettingsProjects = (state: RootState) =>
  state.livingUiSettings.projects
export const selectLivingUiSettingsHasLoadedProjects = (state: RootState) =>
  state.livingUiSettings.hasLoadedProjects
export const selectLivingUiGlobalConfig = (state: RootState) =>
  state.livingUiSettings.globalConfig
export const selectLivingUiHasLoadedGlobalConfig = (state: RootState) =>
  state.livingUiSettings.hasLoadedGlobalConfig
