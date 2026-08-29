import type { RootState } from '../index'

export const selectMemoryEnabled = (state: RootState) => state.memorySettings.enabled
export const selectMemoryItems = (state: RootState) => state.memorySettings.items
export const selectMemoryHasLoadedMode = (state: RootState) => state.memorySettings.hasLoadedMode
export const selectMemoryHasLoadedItems = (state: RootState) => state.memorySettings.hasLoadedItems
export const selectMemoryGraph = (state: RootState) => state.memorySettings.graph
export const selectMemoryGraphLoading = (state: RootState) => state.memorySettings.graphLoading
export const selectMemoryIndexedFiles = (state: RootState) => state.memorySettings.indexedFiles
export const selectMemoryIndexCandidates = (state: RootState) => state.memorySettings.indexCandidates
export const selectMemoryHasLoadedFiles = (state: RootState) => state.memorySettings.hasLoadedFiles
