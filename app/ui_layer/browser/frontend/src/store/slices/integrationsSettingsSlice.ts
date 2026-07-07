import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface IntegrationField {
  key: string
  label: string
  placeholder: string
  password: boolean
}

export interface IntegrationAccount {
  display: string
  id: string
  // Present only for integrations whose backend supports multiple accounts
  // (Gmail, Calendar, Drive, Docs, YouTube, Outlook, LinkedIn, Notion,
  // HubSpot, Slack) — see craftos_integrations/accounts.py. Absent/undefined
  // for single-account integrations.
  alias?: string | null
  is_primary?: boolean
}

// Schema for a single config input rendered by the Configure section in
// the Manage modal. Sourced from the backend handler's ``config_fields``.
export interface ConfigField {
  key: string
  label: string
  type: 'text' | 'textarea' | 'list' | 'checkbox' | 'select' | 'number'
  placeholder?: string
  help?: string
  options?: Array<{ value: string; label: string }>
}

export interface Integration {
  id: string
  name: string
  description: string
  auth_type: 'oauth' | 'token' | 'both' | 'interactive' | 'token_with_interactive'
  connected: boolean
  accounts: IntegrationAccount[]
  fields: IntegrationField[]
  icon?: string
  has_config?: boolean
  config_fields?: ConfigField[] | null
  connect_help?: string[] | null
}

interface IntegrationsSettingsState {
  integrations: Integration[]
  total: number
  connected: number
  hasLoaded: boolean
}

const initialState: IntegrationsSettingsState = {
  integrations: [],
  total: 0,
  connected: 0,
  hasLoaded: false,
}

const integrationsSettingsSlice = createSlice({
  name: 'integrationsSettings',
  initialState,
  reducers: {
    setIntegrations(
      state,
      action: PayloadAction<{ integrations: Integration[]; total?: number; connected?: number }>,
    ) {
      state.integrations = action.payload.integrations
      state.total = action.payload.total ?? action.payload.integrations.length
      state.connected =
        action.payload.connected ?? action.payload.integrations.filter(i => i.connected).length
      state.hasLoaded = true
    },
    // Optimistic disconnect — mark the integration disconnected and clear
    // its accounts so the UI flips immediately. The authoritative
    // ``integration_list`` broadcast will overwrite this when it arrives.
    setDisconnected(state, action: PayloadAction<string>) {
      const entry = state.integrations.find(i => i.id === action.payload)
      if (entry && entry.connected) {
        entry.connected = false
        entry.accounts = []
        state.connected = Math.max(0, state.connected - 1)
      }
    },
  },
})

export const { setIntegrations, setDisconnected } = integrationsSettingsSlice.actions
export default integrationsSettingsSlice.reducer

register('integration_list', (data, dispatch) => {
  const d = data as {
    success: boolean
    integrations?: Integration[]
    total?: number
    connected?: number
  }
  if (d.success && d.integrations) {
    dispatch(
      setIntegrations({
        integrations: d.integrations,
        total: d.total,
        connected: d.connected,
      }),
    )
  }
})
