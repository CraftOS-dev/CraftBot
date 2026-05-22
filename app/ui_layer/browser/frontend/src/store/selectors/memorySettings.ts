import type { RootState } from '../index'

export const selectMemoryEnabled = (state: RootState) => state.memorySettings.enabled
export const selectMemoryItems = (state: RootState) => state.memorySettings.items
export const selectMemoryHasLoadedMode = (state: RootState) => state.memorySettings.hasLoadedMode
export const selectMemoryHasLoadedItems = (state: RootState) => state.memorySettings.hasLoadedItems
