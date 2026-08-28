import type { RootState } from '../index'

export const selectLivingUiSettingsProjects = (state: RootState) =>
  state.livingUiSettings.projects
export const selectLivingUiSettingsHasLoadedProjects = (state: RootState) =>
  state.livingUiSettings.hasLoadedProjects
