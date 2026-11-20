import type { RootState } from '../index'

export const selectAgentAppProjects = (state: RootState) => state.agentApp.framework.apps
export const selectAgentAppCatalogLoaded = (state: RootState) => state.agentApp.framework.hasSnapshot
