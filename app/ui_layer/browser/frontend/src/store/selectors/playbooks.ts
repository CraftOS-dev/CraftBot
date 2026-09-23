import type { RootState } from '../index'

export const selectPlaybooks = (state: RootState) => state.playbooks.items
export const selectPlaybooksHasLoaded = (state: RootState) => state.playbooks.hasLoaded
export const selectPlaybooksError = (state: RootState) => state.playbooks.error
