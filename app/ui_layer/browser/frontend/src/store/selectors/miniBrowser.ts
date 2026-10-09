import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { MiniBrowserTab } from '../../types'
import { miniBrowserTabsAdapter, miniBrowserVaultAdapter } from '../slices/miniBrowserSlice'

const tabSelectors = miniBrowserTabsAdapter.getSelectors((state: RootState) => state.miniBrowser.tabs)
const vaultSelectors = miniBrowserVaultAdapter.getSelectors(
  (state: RootState) => state.miniBrowser.vault.entries,
)

/** True once the backend has reported the browser state at least once. */
export const selectMiniBrowserKnown = (state: RootState) => state.miniBrowser.known
export const selectMiniBrowserStatus = (state: RootState) => state.miniBrowser.status
export const selectMiniBrowserError = (state: RootState) => state.miniBrowser.error
/** The dedicated chat session behind the page (null until reported). */
export const selectMiniBrowserSessionId = (state: RootState) => state.miniBrowser.sessionId
export const selectMiniBrowserAdblock = (state: RootState) => state.miniBrowser.adblock
export const selectMiniBrowserFollow = (state: RootState) => state.miniBrowser.follow
export const selectMiniBrowserViewedTabId = (state: RootState) => state.miniBrowser.viewedTabId
export const selectMiniBrowserViewport = (state: RootState) => state.miniBrowser.viewport
export const selectMiniBrowserSettings = (state: RootState) => state.miniBrowser.settings

/** Tabs in strip order. */
export const selectMiniBrowserTabs = tabSelectors.selectAll

export const selectMiniBrowserViewedTab = (state: RootState): MiniBrowserTab | null => {
  const id = state.miniBrowser.viewedTabId
  return id ? tabSelectors.selectById(state, id) ?? null : null
}

/** Whether any agent is working in a tab right now. */
export const selectMiniBrowserAgentBusy = createSelector(
  selectMiniBrowserTabs,
  (tabs): boolean => tabs.some(tab => tab.busy && tab.ownerKind !== 'user'),
)

export const selectMiniBrowserInstall = (state: RootState) => state.miniBrowser.install
export const selectMiniBrowserNavResult = (state: RootState) => state.miniBrowser.navResult
export const selectMiniBrowserEvents = (state: RootState) => state.miniBrowser.events
export const selectMiniBrowserClipboard = (state: RootState) => state.miniBrowser.clipboard

export const selectMiniBrowserVaultLoaded = (state: RootState) => state.miniBrowser.vault.loaded
export const selectMiniBrowserVaultEntries = vaultSelectors.selectAll
export const selectMiniBrowserVaultStatus = (state: RootState) => state.miniBrowser.vault.status
export const selectMiniBrowserVaultError = (state: RootState) => state.miniBrowser.vault.error
export const selectMiniBrowserVaultResult = (state: RootState) => state.miniBrowser.vault.result
