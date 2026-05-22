import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface MCPServerConfig {
  name: string
  description: string
  enabled: boolean
  transport: string
  command?: string
  action_set: string
  env: Record<string, string>
}

interface McpSettingsState {
  servers: MCPServerConfig[]
  isLoading: boolean
  hasLoaded: boolean
}

const initialState: McpSettingsState = {
  servers: [],
  isLoading: false,
  hasLoaded: false,
}

const mcpSettingsSlice = createSlice({
  name: 'mcpSettings',
  initialState,
  reducers: {
    setServers(state, action: PayloadAction<MCPServerConfig[]>) {
      state.servers = action.payload
      state.isLoading = false
      state.hasLoaded = true
    },
    setLoading(state, action: PayloadAction<boolean>) {
      state.isLoading = action.payload
    },
    // Optimistic toggle so the UI doesn't flicker waiting for mcp_list.
    setEnabled(state, action: PayloadAction<{ name: string; enabled: boolean }>) {
      const entry = state.servers.find(s => s.name === action.payload.name)
      if (entry) entry.enabled = action.payload.enabled
    },
    // Optimistic remove pending the mcp_list refresh.
    removeServer(state, action: PayloadAction<string>) {
      state.servers = state.servers.filter(s => s.name !== action.payload)
    },
  },
})

export const { setServers, setLoading, setEnabled, removeServer } = mcpSettingsSlice.actions
export default mcpSettingsSlice.reducer

register('mcp_list', (data, dispatch) => {
  const d = data as { success: boolean; servers?: MCPServerConfig[] }
  if (d.success && d.servers) dispatch(setServers(d.servers))
})
