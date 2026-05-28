import type { RootState } from '../index'

export const selectMcpServers = (state: RootState) => state.mcpSettings.servers
export const selectMcpIsLoading = (state: RootState) => state.mcpSettings.isLoading
export const selectMcpHasLoaded = (state: RootState) => state.mcpSettings.hasLoaded
