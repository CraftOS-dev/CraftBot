import type { RootState } from '../index'

export const selectUserMd = (state: RootState) => state.generalSettings.userMd
export const selectAgentMd = (state: RootState) => state.generalSettings.agentMd
export const selectSoulMd = (state: RootState) => state.generalSettings.soulMd
export const selectHasLoadedUserMd = (state: RootState) => state.generalSettings.hasLoadedUserMd
export const selectHasLoadedAgentMd = (state: RootState) => state.generalSettings.hasLoadedAgentMd
export const selectHasLoadedSoulMd = (state: RootState) => state.generalSettings.hasLoadedSoulMd
export const selectUpdateChecked = (state: RootState) => state.generalSettings.updateChecked
export const selectUpdateAvailable = (state: RootState) => state.generalSettings.updateAvailable
export const selectLatestVersion = (state: RootState) => state.generalSettings.latestVersion
