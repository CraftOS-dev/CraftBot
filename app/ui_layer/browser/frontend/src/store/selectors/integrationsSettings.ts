import type { RootState } from '../index'

export const selectIntegrations = (state: RootState) => state.integrationsSettings.integrations
export const selectIntegrationsTotal = (state: RootState) => state.integrationsSettings.total
export const selectIntegrationsConnected = (state: RootState) => state.integrationsSettings.connected
export const selectIntegrationsHasLoaded = (state: RootState) => state.integrationsSettings.hasLoaded
