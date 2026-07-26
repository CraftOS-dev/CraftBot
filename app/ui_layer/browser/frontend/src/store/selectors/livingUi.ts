import type { RootState } from '../index'

export const selectLivingUiProjects = (state: RootState) =>
  state.livingUi.projects

export const selectLivingUiCreating = (state: RootState) =>
  state.livingUi.creating

export const selectLivingUiTodos = (state: RootState) =>
  state.livingUi.todos

export const selectLivingUiBuildEvents = (state: RootState) =>
  state.livingUi.buildEvents

export const selectActiveLivingUiId = (state: RootState) =>
  state.livingUi.activeId

export const selectLivingUiStates = (state: RootState) =>
  state.livingUi.states
