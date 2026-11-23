import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

/** A header of an http server: its name and the env keys it references.
 * Header values never leave the backend. */
export interface MCPHeaderInfo {
  name: string
  uses: string[]
}

/** Live connection state from the running MCP client, if it knows the server. */
export interface MCPServerStatus {
  connected: boolean
  error: string | null
  tool_count: number
}

/** A server as `mcp_list` sends it: no env or header values. */
export interface MCPServerConfig {
  name: string
  description: string
  enabled: boolean
  transport: string
  command?: string | null
  /** Never sent (arguments can hold tokens): see args_count. */
  args?: string[] | null
  args_count?: number
  /** Redacted: user info and query string removed. */
  url?: string | null
  timeout?: number | null
  action_set: string | null
  /** Env key -> whether a value is set. */
  env: Record<string, boolean>
  headers?: MCPHeaderInfo[]
  missing_env?: string[]
  needs_config?: boolean
  platform_blocked?: boolean
  /** The entry failed validation; `error` says why. */
  invalid?: boolean
  error?: string | null
  status?: MCPServerStatus | null
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
