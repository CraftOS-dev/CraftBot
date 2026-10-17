import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { MiniBrowserActivity, MiniBrowserLastFrame, MiniBrowserTab } from '../../types'
import {
  miniBrowserVaultAdapter,
  type MiniBrowserSessionView,
} from '../slices/miniBrowserSlice'

// Every chat session has a browser of its own: the per-session selectors take
// the session id. createSelector memoizes per argument set (RTK's weakMap
// memoization), so two panels on two sessions never evict each other.

const vaultSelectors = miniBrowserVaultAdapter.getSelectors(
  (state: RootState) => state.miniBrowser.vault.entries,
)

const NO_TABS: MiniBrowserTab[] = []

/** A session's browser as its panel shows it; undefined until reported. */
export const selectMiniBrowserView = (
  state: RootState,
  sessionId: string,
): MiniBrowserSessionView | undefined => state.miniBrowser.views[sessionId]

/** A session's tabs, in strip order. */
export const selectMiniBrowserTabs = createSelector(
  [
    (state: RootState, sessionId: string) => state.miniBrowser.views[sessionId]?.tabIds,
    (state: RootState) => state.miniBrowser.tabs.entities,
  ],
  (ids, entities): MiniBrowserTab[] => {
    if (!ids || ids.length === 0) return NO_TABS
    const tabs: MiniBrowserTab[] = []
    for (const id of ids) {
      const tab = entities[id]
      if (tab) tabs.push(tab)
    }
    return tabs
  },
)

/** The tab on screen in a session's browser panel. */
export const selectMiniBrowserViewedTab = (
  state: RootState,
  sessionId: string,
): MiniBrowserTab | null => {
  const id = state.miniBrowser.views[sessionId]?.viewedTabId
  return id ? state.miniBrowser.tabs.entities[id] ?? null : null
}

/** Whether any agent is working in one of a session's tabs right now. */
export const selectMiniBrowserAgentBusy = createSelector(
  [selectMiniBrowserTabs],
  (tabs): boolean => tabs.some(tab => tab.busy && tab.ownerKind !== 'user'),
)

/** Where a session's browser left off: the picture shown while it starts
 *  or is off (null: none to show). */
export const selectMiniBrowserLastFrame = (
  state: RootState,
  sessionId: string,
): MiniBrowserLastFrame | null => state.miniBrowser.lastFrames[sessionId] ?? null

/** Whether a session's browser runs, and whether an agent browses in it. */
export const selectMiniBrowserActivity = (
  state: RootState,
  sessionId: string,
): MiniBrowserActivity | undefined => state.miniBrowser.activity[sessionId]

export const selectMiniBrowserInstall = (state: RootState) => state.miniBrowser.install
export const selectMiniBrowserEvents = (state: RootState) => state.miniBrowser.events
export const selectMiniBrowserClipboard = (state: RootState) => state.miniBrowser.clipboard

export const selectMiniBrowserVaultLoaded = (state: RootState) => state.miniBrowser.vault.loaded
export const selectMiniBrowserVaultEntries = vaultSelectors.selectAll
export const selectMiniBrowserVaultStatus = (state: RootState) => state.miniBrowser.vault.status
export const selectMiniBrowserVaultError = (state: RootState) => state.miniBrowser.vault.error
export const selectMiniBrowserVaultResult = (state: RootState) => state.miniBrowser.vault.result
