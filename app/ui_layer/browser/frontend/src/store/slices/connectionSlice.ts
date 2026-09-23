import { createSlice, PayloadAction } from '@reduxjs/toolkit'

export interface ConnectionState {
  connected: boolean
  version: string
  reconnectAttempt: number
  /** Connected, but the backend isn't answering liveness pings (busy event loop). */
  backendBusy: boolean
}

const initialState: ConnectionState = {
  connected: false,
  version: '',
  reconnectAttempt: 0,
  backendBusy: false,
}

const connectionSlice = createSlice({
  name: 'connection',
  initialState,
  reducers: {
    setConnected(state, action: PayloadAction<boolean>) {
      state.connected = action.payload
      if (action.payload) state.reconnectAttempt = 0
      else state.backendBusy = false
    },
    setVersion(state, action: PayloadAction<string>) {
      state.version = action.payload
    },
    setReconnectAttempt(state, action: PayloadAction<number>) {
      state.reconnectAttempt = action.payload
    },
    setBackendBusy(state, action: PayloadAction<boolean>) {
      state.backendBusy = action.payload
    },
  },
})

export const { setConnected, setVersion, setReconnectAttempt, setBackendBusy } = connectionSlice.actions
export default connectionSlice.reducer
